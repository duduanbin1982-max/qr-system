"""
qr-system — 统计报表路由
提供：日报表、员工统计、报废记录、订单进度
"""
from flask import request, jsonify
from modules.app import app
from modules.db import get_db
from modules.middleware.auth import check_auth, check_permission


@app.route('/api/stats/daily', methods=['GET'])
@check_auth
@check_permission('stats:view')
def stats_daily():
    """日报表：某日报工明细 + 工序汇总"""
    date = request.args.get('date', '')
    try:
        db = get_db()
        # 报工明细（含软删除过滤）
        records = db.execute('''
            SELECT wr.id, wr.created_at, wr.quantity, wr.type, wr.status,
                   o.order_no, o.product_name,
                   p.name as process_name,
                   u.name as worker_name
            FROM work_records wr
            JOIN orders o ON wr.order_id = o.id AND o.deleted_at IS NULL
            JOIN processes p ON wr.process_id = p.id
            JOIN users u ON wr.user_id = u.id
            WHERE DATE(wr.created_at) = ?
            ORDER BY wr.created_at DESC
        ''', (date,)).fetchall()

        # 工序汇总
        summary = db.execute('''
            SELECT p.id, p.name,
                   COUNT(*) as record_count,
                   COALESCE(SUM(CASE WHEN wr.type = 'normal' THEN wr.quantity ELSE 0 END), 0) as total_output,
                   COALESCE(SUM(CASE WHEN wr.type = 'scrap' THEN wr.quantity ELSE 0 END), 0) as total_scrap,
                   COALESCE(SUM(CASE WHEN wr.type = 'rework' THEN wr.quantity ELSE 0 END), 0) as total_rework
            FROM work_records wr
            JOIN orders o ON wr.order_id = o.id AND o.deleted_at IS NULL
            JOIN processes p ON wr.process_id = p.id
            WHERE DATE(wr.created_at) = ?
            GROUP BY p.id
            ORDER BY record_count DESC
        ''', (date,)).fetchall()

        return jsonify({
            'records': [dict(r) for r in records],
            'summary': [dict(s) for s in summary],
        })
    except Exception as e:
        return jsonify({'error': f'查询失败: {str(e)}'}), 500


@app.route('/api/stats/worker', methods=['GET'])
@check_auth
@check_permission('stats:view')
def stats_worker():
    """员工计件统计"""
    start = request.args.get('start', '')
    end = request.args.get('end', '')
    try:
        db = get_db()
        where = ['wr.status = \'approved\'', 'o.deleted_at IS NULL']
        params = []
        if start:
            where.append('DATE(wr.created_at) >= ?')
            params.append(start)
        if end:
            where.append('DATE(wr.created_at) <= ?')
            params.append(end)
        where_clause = ' AND '.join(where)

        workers = db.execute(f'''
            SELECT u.id, u.name, u.employee_no,
                   COUNT(DISTINCT DATE(wr.created_at)) as work_days,
                   COALESCE(SUM(CASE WHEN wr.type = 'normal' THEN wr.quantity ELSE 0 END), 0) as total_output,
                   COALESCE(SUM(CASE WHEN wr.type = 'scrap' THEN wr.quantity ELSE 0 END), 0) as total_scrap,
                   COALESCE(SUM(CASE WHEN wr.type = 'rework' THEN wr.quantity ELSE 0 END), 0) as total_rework
            FROM users u
            JOIN work_records wr ON wr.user_id = u.id
            JOIN orders o ON wr.order_id = o.id
            WHERE {where_clause}
            GROUP BY u.id
            ORDER BY total_output DESC
        ''', params).fetchall()

        return jsonify({'workers': [dict(w) for w in workers]})
    except Exception as e:
        return jsonify({'error': f'查询失败: {str(e)}'}), 500


@app.route('/api/stats/scrap', methods=['GET'])
@check_auth
@check_permission('stats:view')
def stats_scrap():
    """报废记录查询"""
    start = request.args.get('start', '')
    end = request.args.get('end', '')
    try:
        db = get_db()
        where = ['o.deleted_at IS NULL']
        params = []
        if start:
            where.append('DATE(sr.created_at) >= ?')
            params.append(start)
        if end:
            where.append('DATE(sr.created_at) <= ?')
            params.append(end)
        where_clause = ' AND '.join(where)

        records = db.execute(f'''
            SELECT sr.id, sr.created_at, sr.quantity, sr.reason,
                   o.order_no, o.product_name,
                   p.name as process_name,
                   u.name as worker_name
            FROM scrap_records sr
            JOIN orders o ON sr.order_id = o.id
            JOIN processes p ON sr.process_id = p.id
            JOIN users u ON sr.user_id = u.id
            WHERE {where_clause}
            ORDER BY sr.created_at DESC
            LIMIT 500
        ''', params).fetchall()

        return jsonify({'records': [dict(r) for r in records]})
    except Exception as e:
        return jsonify({'error': f'查询失败: {str(e)}'}), 500


@app.route('/api/stats/order-progress', methods=['GET'])
@check_auth
@check_permission('stats:view')
def stats_order_progress():
    """订单进度总览：未删除订单 + 完成数量 + 进度"""
    try:
        db = get_db()
        orders = db.execute('''
            SELECT o.id, o.order_no, o.product_name,
                   COALESCE(c.name, o.customer) as customer,
                   o.quantity, COALESCE(o.completed, 0) as completed,
                   o.plan_end, o.status
            FROM orders o
            LEFT JOIN customers c ON o.customer_id = c.id
            WHERE o.deleted_at IS NULL
            ORDER BY o.status DESC, o.created_at DESC
        ''').fetchall()

        return jsonify({'orders': [dict(o) for o in orders]})
    except Exception as e:
        return jsonify({'error': f'查询失败: {str(e)}'}), 500
