"""
qr-system — 数据看板路由 (Board)
供车间大屏公开拉取生产数据（无需认证）
从 dashboard.py 拆分，独立模块
"""
from datetime import datetime
from flask import request, jsonify

from modules.app import app
from modules.db import get_db, get_setting

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
    # Scrap/rework totals by process (pre-fetch to avoid N+1)
    _scrap_rows = db.execute(
        'SELECT sr.process_id, SUM(sr.quantity) as s FROM scrap_records sr '
        'JOIN orders o ON sr.order_id = o.id AND o.deleted_at IS NULL '
        'WHERE DATE(sr.created_at)=? GROUP BY sr.process_id', (today,)
    ).fetchall()
    scrap_by_proc = {r['process_id']: r['s'] for r in _scrap_rows}
    _rework_rows = db.execute(
        'SELECT rr.process_id, SUM(rr.quantity) as r FROM rework_records rr '
        'JOIN orders o ON rr.order_id = o.id AND o.deleted_at IS NULL '
        'WHERE DATE(rr.created_at)=? GROUP BY rr.process_id', (today,)
    ).fetchall()
    rework_by_proc = {r['process_id']: r['r'] for r in _rework_rows}
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
    _scrap_user_rows = db.execute(
        'SELECT sr.user_id, SUM(sr.quantity) as s FROM scrap_records sr '
        'JOIN orders o ON sr.order_id = o.id AND o.deleted_at IS NULL '
        'WHERE DATE(sr.created_at)=? GROUP BY sr.user_id', (today,)
    ).fetchall()
    scrap_by_user = {r['user_id']: r['s'] for r in _scrap_user_rows}
    _rework_user_rows = db.execute(
        'SELECT rr.user_id, SUM(rr.quantity) as r FROM rework_records rr '
        'JOIN orders o ON rr.order_id = o.id AND o.deleted_at IS NULL '
        'WHERE DATE(rr.created_at)=? GROUP BY rr.user_id', (today,)
    ).fetchall()
    rework_by_user = {r['user_id']: r['r'] for r in _rework_user_rows}
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
