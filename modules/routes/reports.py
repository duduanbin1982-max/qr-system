"""
qr-system — 数据分析报表路由

注：全读端点，Swagger docstring 仅供文档参考。
"""
from datetime import datetime, timedelta
from flask import request, jsonify
from modules.app import app
from modules.db import get_db
from modules.middleware.auth import check_auth, check_permission
from modules.middleware.error_handler import handle_unexpected_error


@app.route('/api/reports/production-trend', methods=['GET'])
@check_auth
@check_permission('reports:view')
def reports_production_trend():
    """生产趋势：最近 N 天每日产出/报废/返工"""
    days = request.args.get('days', 30, type=int)
    if days <= 0:
        return jsonify({'trend': [], 'summary': {'total_output': 0, 'total_scrap': 0, 'total_rework': 0, 'scrap_rate': 0, 'rework_rate': 0, 'days': days}})
    try:
        db = get_db()
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=days - 1)).strftime('%Y-%m-%d')

        trend = db.execute('''
            SELECT dates.d as date,
                   COALESCE(SUM(CASE WHEN wr.type = 'normal' THEN wr.quantity ELSE 0 END), 0) as output,
                   COALESCE(SUM(CASE WHEN wr.type = 'scrap' THEN wr.quantity ELSE 0 END), 0) as scrap,
                   COALESCE(SUM(CASE WHEN wr.type = 'rework' THEN wr.quantity ELSE 0 END), 0) as rework,
                   COUNT(wr.id) as report_count
            FROM (
                WITH RECURSIVE dates(d) AS (
                    SELECT ? UNION ALL SELECT date(d, '+1 day') FROM dates WHERE d < ?
                )
                SELECT d FROM dates
            ) dates
            LEFT JOIN work_records wr ON DATE(wr.created_at) = dates.d
                AND wr.order_id IN (SELECT id FROM orders WHERE deleted_at IS NULL)
            GROUP BY dates.d
            ORDER BY dates.d ASC
        ''', (start_date, end_date)).fetchall()

        trend_data = [dict(r) for r in trend]
        total_output = sum(r['output'] for r in trend_data)
        total_scrap = sum(r['scrap'] for r in trend_data)
        total_rework = sum(r['rework'] for r in trend_data)

        return jsonify({
            'trend': trend_data,
            'summary': {
                'total_output': total_output,
                'total_scrap': total_scrap,
                'total_rework': total_rework,
                'scrap_rate': round(total_scrap / total_output * 100, 1) if total_output else 0,
                'rework_rate': round(total_rework / total_output * 100, 1) if total_output else 0,
                'days': days,
            },
        })
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/reports/worker-efficiency', methods=['GET'])
@check_auth
@check_permission('reports:view')
def reports_worker_efficiency():
    """工人效率：按工人汇总产出/报废/返工/工作天数"""
    start = request.args.get('start', '')
    end = request.args.get('end', '')
    try:
        db = get_db()
        where = ['wr.order_id IN (SELECT id FROM orders WHERE deleted_at IS NULL)']
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
                   COALESCE(SUM(CASE WHEN wr.type = 'normal' THEN wr.quantity ELSE 0 END), 0) as output,
                   COALESCE(SUM(CASE WHEN wr.type = 'scrap' THEN wr.quantity ELSE 0 END), 0) as scrap,
                   COALESCE(SUM(CASE WHEN wr.type = 'rework' THEN wr.quantity ELSE 0 END), 0) as rework,
                   COUNT(DISTINCT DATE(wr.created_at)) as work_days,
                   COUNT(wr.id) as report_count
            FROM users u
            LEFT JOIN work_records wr ON wr.user_id = u.id AND {where_clause}
            WHERE u.role = 'worker' AND u.status = 'active'
            GROUP BY u.id
            ORDER BY output DESC
        ''', params).fetchall()

        result = []
        for w in workers:
            wd = dict(w)
            wd['daily_avg'] = round(wd['output'] / wd['work_days'], 1) if wd['work_days'] else 0
            wd['scrap_rate'] = round(wd['scrap'] / wd['output'] * 100, 1) if wd['output'] else 0
            wd['rework_rate'] = round(wd['rework'] / wd['output'] * 100, 1) if wd['output'] else 0
            result.append(wd)

        return jsonify({'workers': result})
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/reports/quality-analysis', methods=['GET'])
@check_auth
@check_permission('reports:view')
def reports_quality_analysis():
    """品质分析：按工序 + 工人统计不良率"""
    start = request.args.get('start', '')
    end = request.args.get('end', '')
    try:
        db = get_db()
        where = ['wr.order_id IN (SELECT id FROM orders WHERE deleted_at IS NULL)']
        params = []
        if start:
            where.append('DATE(wr.created_at) >= ?')
            params.append(start)
        if end:
            where.append('DATE(wr.created_at) <= ?')
            params.append(end)
        where_clause = ' AND '.join(where)

        by_process = db.execute(f'''
            SELECT p.id, p.name, p.category,
                   COALESCE(SUM(CASE WHEN wr.type = 'normal' THEN wr.quantity ELSE 0 END), 0) as output,
                   COALESCE(SUM(CASE WHEN wr.type = 'scrap' THEN wr.quantity ELSE 0 END), 0) as scrap,
                   COALESCE(SUM(CASE WHEN wr.type = 'rework' THEN wr.quantity ELSE 0 END), 0) as rework
            FROM processes p
            JOIN work_records wr ON wr.process_id = p.id
            WHERE {where_clause}
            GROUP BY p.id
            ORDER BY output DESC
            LIMIT 20
        ''', params).fetchall()

        by_worker = db.execute(f'''
            SELECT u.id, u.name, u.employee_no,
                   COALESCE(SUM(CASE WHEN wr.type = 'normal' THEN wr.quantity ELSE 0 END), 0) as output,
                   COALESCE(SUM(CASE WHEN wr.type = 'scrap' THEN wr.quantity ELSE 0 END), 0) as scrap,
                   COALESCE(SUM(CASE WHEN wr.type = 'rework' THEN wr.quantity ELSE 0 END), 0) as rework
            FROM users u
            LEFT JOIN work_records wr ON wr.user_id = u.id AND {where_clause}
            WHERE u.role = 'worker' AND u.status = 'active'
            GROUP BY u.id
            ORDER BY output DESC
            LIMIT 20
        ''', params).fetchall()

        # Compute defect rates server-side for consistency
        process_list = []
        for r in by_process:
            d = dict(r)
            total = (d['output'] or 0) + (d['scrap'] or 0) + (d['rework'] or 0)
            d['defect_rate'] = round((d['scrap'] + d['rework']) / total * 100, 1) if total else 0
            process_list.append(d)
        worker_list = []
        for r in by_worker:
            d = dict(r)
            total = (d['output'] or 0) + (d['scrap'] or 0) + (d['rework'] or 0)
            d['defect_rate'] = round((d['scrap'] + d['rework']) / total * 100, 1) if total else 0
            worker_list.append(d)

        return jsonify({
            'by_process': process_list,
            'by_worker': worker_list,
        })
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/reports/order-analysis', methods=['GET'])
@check_auth
@check_permission('reports:view')
def reports_order_analysis():
    """订单分析：状态分布 + 月度趋势"""
    try:
        db = get_db()

        # 状态分布
        status_dist = db.execute('''
            SELECT o.status,
                   COUNT(*) as count,
                   COALESCE(SUM(o.quantity), 0) as qty,
                   COALESCE(SUM(o.completed), 0) as done
            FROM orders o
            WHERE o.deleted_at IS NULL
            GROUP BY o.status
            ORDER BY COUNT(*) DESC
        ''').fetchall()

        # 月度趋势（最近12个月）
        monthly = db.execute('''
            SELECT substr(o.created_at, 1, 7) as month,
                   COUNT(*) as count,
                   COALESCE(SUM(o.quantity), 0) as total_qty,
                   COALESCE(SUM(o.completed), 0) as total_done
            FROM orders o
            WHERE o.deleted_at IS NULL
              AND o.created_at >= date('now', '-12 months')
            GROUP BY substr(o.created_at, 1, 7)
            ORDER BY month ASC
        ''').fetchall()

        return jsonify({
            'status_distribution': [dict(r) for r in status_dist],
            'monthly_trend': [dict(r) for r in monthly],
        })
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')
