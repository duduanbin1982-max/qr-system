"""
qr-system — 工作台路由：Dashboard + 数据看板(Board)
"""
from datetime import datetime
from flask import request, jsonify

from modules.app import app
from modules.db import get_db, get_setting
from modules.middleware.auth import check_auth, check_permission


@app.route('/api/dashboard', methods=['GET'])
@check_auth
@check_permission('dashboard:view')
def dashboard():
    db = get_db()
    today = datetime.now().strftime('%Y-%m-%d')

    total_orders = db.execute('SELECT COUNT(*) FROM orders WHERE deleted_at IS NULL').fetchone()[0]
    pending = db.execute('SELECT COUNT(*) FROM orders WHERE status = "pending" AND deleted_at IS NULL').fetchone()[0]
    producing = db.execute('SELECT COUNT(*) FROM orders WHERE status = "producing" AND deleted_at IS NULL').fetchone()[0]
    completed = db.execute('SELECT COUNT(*) FROM orders WHERE status = "completed" AND deleted_at IS NULL').fetchone()[0]

    today_records = db.execute('SELECT COUNT(*) FROM work_records WHERE DATE(created_at) = ?', (today,)).fetchone()[0]
    today_scrap = db.execute('SELECT COALESCE(SUM(quantity),0) FROM scrap_records WHERE DATE(created_at) = ?', (today,)).fetchone()[0]
    today_rework = db.execute('SELECT COALESCE(SUM(quantity),0) FROM rework_records WHERE DATE(created_at) = ?', (today,)).fetchone()[0]
    today_output = db.execute('SELECT COALESCE(SUM(quantity),0) FROM work_records WHERE DATE(created_at) = ? AND type = "normal"', (today,)).fetchone()[0]

    # --- Security stats ---
    locked_users = db.execute(
        "SELECT COUNT(*) FROM users WHERE locked_until IS NOT NULL AND locked_until > datetime('now','localtime')"
    ).fetchone()[0]
    today_failed_logins = db.execute(
        'SELECT COUNT(*) FROM login_logs WHERE DATE(created_at) = ? AND success = 0', (today,)
    ).fetchone()[0]
    today_success_logins = db.execute(
        'SELECT COUNT(*) FROM login_logs WHERE DATE(created_at) = ? AND success = 1', (today,)
    ).fetchone()[0]
    # 异常IP：不同于最近7天常用IP的成功登录
    recent_ips = set(r[0] for r in db.execute(
        "SELECT DISTINCT ip_address FROM login_logs WHERE success = 1 AND created_at > datetime('now','-7 days')"
    ).fetchall())
    today_ips = set(r[0] for r in db.execute(
        "SELECT DISTINCT ip_address FROM login_logs WHERE success = 1 AND DATE(created_at) = ?", (today,)
    ).fetchall())
    suspicious_ips = list(today_ips - recent_ips) if recent_ips else []

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
    warning_days_str = get_setting('delivery_warning_days', '0')
    warning_days = int(warning_days_str) if warning_days_str else 0
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
            'total_orders': total_orders,
            'pending': pending,
            'producing': producing,
            'completed': completed,
            'today_records': today_records,
            'today_scrap': today_scrap,
            'today_rework': today_rework,
            'today_output': today_output,
        },
        'security': {
            'locked_users': locked_users,
            'today_failed_logins': today_failed_logins,
            'today_success_logins': today_success_logins,
            'suspicious_ips': suspicious_ips,
        },
        'recent_records': [dict(r) for r in recent],
        'quick_actions': [
            {'page': 'orders',    'icon': '📋', 'label': '订单管理',   'perm': 'orders:view'},
            {'page': 'scan',      'icon': '📱', 'label': '扫码报工',   'perm': 'scan:view'},
            {'page': 'products',  'icon': '🏭', 'label': '产品管理',   'perm': 'products:view'},
            {'page': 'prices',    'icon': '💰', 'label': '工价管理',   'perm': 'prices:view'},
            {'page': 'users',     'icon': '👥', 'label': '员工管理',   'perm': 'users:view'},
            {'page': 'stats',     'icon': '📈', 'label': '统计报表',   'perm': 'stats:view'},
            {'page': 'board',     'icon': '📺', 'label': '数据看板',   'perm': 'board:view'},
            {'page': 'settings',  'icon': '⚙️', 'label': '系统设置',   'perm': 'settings:manage'},
        ],
        'delivery_warnings': {
            'overdue': [dict(r) for r in overdue_rows],
            'approaching': [dict(r) for r in approaching_rows],
            'warning_days': warning_days,
        },
    })


# Board endpoint (production overview dashboard) — 公开端点，供车间大屏无需认证拉取数据
@app.route('/api/dashboard/board', methods=['GET'])
def dashboard_board():
    db = get_db()
    today = datetime.now().strftime('%Y-%m-%d')
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    category = request.args.get('category', '').strip()
    cat_filter = ''
    cat_params = []
    if category:
        cat_filter = ' AND p.category = ?'
        cat_params = [category]

    total_orders = db.execute(f'''
        SELECT COUNT(DISTINCT o.id) FROM orders o
        LEFT JOIN products p ON o.product_code = p.product_code
        WHERE o.deleted_at IS NULL{cat_filter}
    ''', cat_params).fetchone()[0]
    producing_orders = db.execute(f'''
        SELECT COUNT(DISTINCT o.id) FROM orders o
        LEFT JOIN products p ON o.product_code = p.product_code
        WHERE o.status = 'producing' AND o.deleted_at IS NULL{cat_filter}
    ''', cat_params).fetchone()[0]
    completed_orders = db.execute(f'''
        SELECT COUNT(DISTINCT o.id) FROM orders o
        LEFT JOIN products p ON o.product_code = p.product_code
        WHERE o.status = 'completed' AND o.deleted_at IS NULL{cat_filter}
    ''', cat_params).fetchone()[0]

    today_output = db.execute('''
        SELECT COALESCE(SUM(wr.quantity),0) FROM work_records wr
        JOIN orders o ON wr.order_id = o.id AND o.deleted_at IS NULL
        WHERE DATE(wr.created_at) = ? AND wr.type = 'normal'
    ''', (today,)).fetchone()[0]
    today_reports = db.execute('''
        SELECT COUNT(*) FROM work_records wr
        JOIN orders o ON wr.order_id = o.id AND o.deleted_at IS NULL
        WHERE DATE(wr.created_at) = ?
    ''', (today,)).fetchone()[0]
    today_rework = db.execute('''
        SELECT COALESCE(SUM(rr.quantity),0) FROM rework_records rr
        JOIN orders o ON rr.order_id = o.id AND o.deleted_at IS NULL
        WHERE DATE(rr.created_at) = ?
    ''', (today,)).fetchone()[0]
    today_scrap = db.execute('''
        SELECT COALESCE(SUM(sr.quantity),0) FROM scrap_records sr
        JOIN orders o ON sr.order_id = o.id AND o.deleted_at IS NULL
        WHERE DATE(sr.created_at) = ?
    ''', (today,)).fetchone()[0]

    order_rows = db.execute(f'''
        SELECT o.id, o.order_no, o.product_name, o.product_code,
               COALESCE(c.name, o.customer) as customer,
               o.quantity, o.completed, o.status, o.plan_start, o.plan_end,
               CASE WHEN o.quantity > 0 THEN CAST(CAST(o.completed AS FLOAT) / o.quantity * 100 AS INTEGER) ELSE 0 END as progress_percent,
               p.category as product_category
        FROM orders o
        LEFT JOIN customers c ON o.customer_id = c.id
        LEFT JOIN products p ON o.product_code = p.product_code
        WHERE o.status IN ('producing', 'pending') AND o.deleted_at IS NULL{cat_filter}
        ORDER BY o.status = 'producing' DESC, progress_percent, o.created_at DESC
        LIMIT 50
    ''', cat_params).fetchall()

    overdue_rows = db.execute(f'''
        SELECT o.id, o.order_no, o.product_name, o.plan_end,
               CAST(julianday(?) - julianday(o.plan_end) AS INTEGER) as overdue_days
        FROM orders o
        LEFT JOIN products p ON o.product_code = p.product_code
        WHERE o.plan_end < ? AND o.status != 'completed' AND o.deleted_at IS NULL{cat_filter}
        ORDER BY o.plan_end ASC
        LIMIT 20
    ''', [today] + [today] + cat_params).fetchall()

    process_rows = db.execute('''
        SELECT pr.id, pr.name, pr.category,
               COALESCE(SUM(wr.quantity), 0) as output
        FROM processes pr
        LEFT JOIN work_records wr ON pr.id = wr.process_id
            AND DATE(wr.created_at) = ?
            AND wr.order_id IN (SELECT id FROM orders WHERE deleted_at IS NULL)
        GROUP BY pr.id, pr.name, pr.category
        HAVING output > 0
        ORDER BY output DESC
        LIMIT 15
    ''', (today,)).fetchall()
    scrap_by_proc = {r['process_id']: r['s'] for r in
        db.execute('SELECT process_id, SUM(quantity) as s FROM scrap_records WHERE DATE(created_at)=? GROUP BY process_id', (today,)).fetchall()}
    rework_by_proc = {r['process_id']: r['r'] for r in
        db.execute('SELECT process_id, SUM(quantity) as r FROM rework_records WHERE DATE(created_at)=? GROUP BY process_id', (today,)).fetchall()}
    process_rows = [dict(r) for r in process_rows]
    for p in process_rows:
        p['scrap'] = scrap_by_proc.get(p['id'], 0)
        p['rework'] = rework_by_proc.get(p['id'], 0)

    worker_rows = db.execute('''
        SELECT u.id, u.name, u.employee_no,
               COALESCE(SUM(wr.quantity), 0) as output,
               COUNT(wr.id) as report_count
        FROM users u
        LEFT JOIN work_records wr ON u.id = wr.user_id AND DATE(wr.created_at) = ?
            AND wr.order_id IN (SELECT id FROM orders WHERE deleted_at IS NULL)
        WHERE u.status = 'active'
        GROUP BY u.id, u.name, u.employee_no
        HAVING output > 0
        ORDER BY output DESC
        LIMIT 10
    ''', (today,)).fetchall()
    scrap_by_user = {r['user_id']: r['s'] for r in
        db.execute('SELECT user_id, SUM(quantity) as s FROM scrap_records WHERE DATE(created_at)=? GROUP BY user_id', (today,)).fetchall()}
    rework_by_user = {r['user_id']: r['r'] for r in
        db.execute('SELECT user_id, SUM(quantity) as r FROM rework_records WHERE DATE(created_at)=? GROUP BY user_id', (today,)).fetchall()}
    worker_rows = [dict(r) for r in worker_rows]
    for w in worker_rows:
        w['scrap'] = scrap_by_user.get(w['id'], 0)
        w['rework'] = rework_by_user.get(w['id'], 0)

    recent_rows = db.execute('''
        SELECT wr.id, wr.type, wr.quantity, wr.created_at,
               u.name as worker_name,
               pr.name as process_name,
               o.order_no
        FROM work_records wr
        LEFT JOIN users u ON wr.user_id = u.id
        LEFT JOIN processes pr ON wr.process_id = pr.id
        LEFT JOIN orders o ON wr.order_id = o.id AND o.deleted_at IS NULL
        ORDER BY wr.created_at DESC
        LIMIT 20
    ''').fetchall()

    return jsonify({
        'stats': {
            'total_orders': total_orders,
            'producing_orders': producing_orders,
            'completed_orders': completed_orders,
        },
        'today': {
            'today_output': today_output,
            'today_reports': today_reports,
            'today_rework': today_rework,
            'today_scrap': today_scrap,
        },
        'orders': [dict(r) for r in order_rows],
        'overdue_orders': [dict(r) for r in overdue_rows],
        'process_stats': [dict(r) for r in process_rows],
        'worker_stats': [dict(r) for r in worker_rows],
        'recent_reports': [dict(r) for r in recent_rows],
        'update_time': now_str,
    })
