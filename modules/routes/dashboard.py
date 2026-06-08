"""
qr-system - Dashboard route (workbench)
Security stats split to /api/dashboard/security
"""
from datetime import datetime
from flask import request, jsonify, g

from modules.app import app
from modules.cache_utils import ttl_cache
from modules.db import get_db, get_setting
from modules.middleware.auth import check_auth, check_permission


@app.route('/api/dashboard', methods=['GET'])
@ttl_cache(30)
@check_auth
@check_permission('dashboard:view')
def dashboard():
    db = get_db()
    today = datetime.now().strftime('%Y-%m-%d')

    # Combined order stats (1 query for 4 counts)
    order_stats = db.execute('''
        SELECT COUNT(*) as total,
               SUM(CASE WHEN status="pending" THEN 1 ELSE 0 END) as pending,
               SUM(CASE WHEN status="producing" THEN 1 ELSE 0 END) as producing,
               SUM(CASE WHEN status="completed" THEN 1 ELSE 0 END) as completed
        FROM orders WHERE deleted_at IS NULL
    ''').fetchone()

    # Combined today stats (UNION ALL single scan)
    today_stats = db.execute('''
        SELECT
          COALESCE(SUM(CASE WHEN t.source='work_records' THEN 1 ELSE 0 END),0) as today_records,
          COALESCE(SUM(CASE WHEN t.source='scrap_records' THEN t.qty ELSE 0 END),0) as today_scrap,
          COALESCE(SUM(CASE WHEN t.source='rework_records' THEN t.qty ELSE 0 END),0) as today_rework,
          COALESCE(SUM(CASE WHEN t.source='work_records' AND t.is_normal=1 THEN t.qty ELSE 0 END),0) as today_output
        FROM (
          SELECT 'work_records' as source, quantity as qty, (type='normal') as is_normal FROM work_records wr
            WHERE DATE(wr.created_at)=? AND wr.status='approved' AND wr.order_id IN (SELECT id FROM orders WHERE deleted_at IS NULL)
          UNION ALL
          SELECT 'scrap_records', quantity, 0 FROM scrap_records sr
            WHERE DATE(sr.created_at)=? AND sr.order_id IN (SELECT id FROM orders WHERE deleted_at IS NULL)
          UNION ALL
          SELECT 'rework_records', quantity, 0 FROM rework_records rr
            WHERE DATE(rr.created_at)=? AND rr.order_id IN (SELECT id FROM orders WHERE deleted_at IS NULL)
        ) t
    ''', (today, today, today)).fetchone()

    # Recent records
    recent = db.execute('''
        SELECT wr.*, u.name as worker_name, p.name as process_name, o.order_no
        FROM work_records wr
        LEFT JOIN users u ON wr.user_id = u.id
        LEFT JOIN processes p ON wr.process_id = p.id
        LEFT JOIN orders o ON wr.order_id = o.id AND o.deleted_at IS NULL
        ORDER BY wr.created_at DESC LIMIT 20
    ''').fetchall()

    # Delivery warnings
    warning_days_str = get_setting('delivery_warning_days', '3')
    try:
        warning_days = int(warning_days_str) if warning_days_str else 0
    except (ValueError, TypeError):
        warning_days = 0
    overdue_rows = []
    approaching_rows = []
    if warning_days > 0:
        overdue_rows = db.execute('''
            SELECT o.id, o.order_no, o.product_name, o.plan_end,
                   CAST(julianday(?) - julianday(o.plan_end) AS INTEGER) as overdue_days
            FROM orders o
            WHERE o.plan_end != '' AND o.plan_end < ?
              AND o.status != 'completed' AND o.deleted_at IS NULL
            ORDER BY o.plan_end ASC LIMIT 20
        ''', (today, today)).fetchall()
        approaching_rows = db.execute('''
            SELECT o.id, o.order_no, o.product_name, o.plan_end,
                   CAST(julianday(o.plan_end) - julianday(?) AS INTEGER) as days_left
            FROM orders o
            WHERE o.plan_end != '' AND o.plan_end >= ? AND o.plan_end <= date(?, '+' || ? || ' days')
              AND o.status != 'completed' AND o.deleted_at IS NULL
            ORDER BY o.plan_end ASC LIMIT 20
        ''', (today, today, today, warning_days)).fetchall()

    return jsonify({
        'company_name': get_setting('company_name', ''),
        'stats': {
            'total_orders': order_stats['total'],
            'pending': order_stats['pending'],
            'producing': order_stats['producing'],
            'completed': order_stats['completed'],
            'today_records': today_stats['today_records'],
            'today_scrap': today_stats['today_scrap'],
            'today_rework': today_stats['today_rework'],
            'today_output': today_stats['today_output'],
        },
        'recent_records': [dict(r) for r in recent],
        'quick_actions': [
            {'page': 'orders',    'icon': '\U0001f4cb', 'label': '订单管理',   'desc': '创建和管理生产订单'},
            {'page': 'scan',      'icon': '\U0001f4f1', 'label': '扫码报工',   'desc': '扫码记录工序产量'},
            {'page': 'products',  'icon': '\U0001f3ed', 'label': '产品管理',   'desc': '维护产品信息和BOM'},
            {'page': 'prices',    'icon': '\U0001f4b0', 'label': '工价管理',   'desc': '管理工序工价路线'},
            {'page': 'users',     'icon': '\U0001f465', 'label': '员工管理',   'desc': '管理用户和权限'},
            {'page': 'stats',     'icon': '\U0001f4c8', 'label': '统计报表',   'desc': '查看生产和质量报表'},
            {'page': 'board',     'icon': '\U0001f4fa', 'label': '数据看板',   'desc': '车间实时生产大屏'},
            {'page': 'settings',  'icon': '\u2699\ufe0f', 'label': '系统设置',   'desc': '系统配置与权限管理'},
        ],
        'delivery_warnings': {
            'overdue': [dict(r) for r in overdue_rows],
            'approaching': [dict(r) for r in approaching_rows],
            'warning_days': warning_days,
        },
    })


@app.route('/api/dashboard/security', methods=['GET'])
@check_auth
@check_permission('settings:manage')
def dashboard_security():
    """Security stats - admin only."""
    db = get_db()
    today = datetime.now().strftime('%Y-%m-%d')

    # Combined security stats (single query)
    sec_stats = db.execute('''
        SELECT
          (SELECT COUNT(*) FROM users WHERE locked_until IS NOT NULL AND locked_until > datetime('now','localtime')) as locked_users,
          (SELECT COUNT(*) FROM login_logs WHERE DATE(created_at)=? AND success=0) as today_failed_logins,
          (SELECT COUNT(*) FROM login_logs WHERE DATE(created_at)=? AND success=1) as today_success_logins
    ''', (today, today)).fetchone()

    suspicious_ips = db.execute('''
        SELECT COUNT(*) FROM (
          SELECT DISTINCT ip_address FROM login_logs
          WHERE success = 1 AND DATE(created_at) = ?
          EXCEPT
          SELECT DISTINCT ip_address FROM login_logs
          WHERE success = 1 AND DATE(created_at) < ? AND created_at > datetime('now','-7 days')
        )
    ''', (today, today)).fetchone()[0]

    return jsonify({
        'locked_users': sec_stats['locked_users'],
        'today_failed_logins': sec_stats['today_failed_logins'],
        'today_success_logins': sec_stats['today_success_logins'],
        'suspicious_ips': suspicious_ips,
    })