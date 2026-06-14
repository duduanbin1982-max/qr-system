"""qr-system — 工资计算 + 日报 + 生产进度 Service 层"""
from datetime import datetime
from modules.services import BaseService


class WageService:
    """计件工资 + 日报 + 生产进度。"""

    
    # Latest active process prices via DB VIEW (product_price_latest)
    _PP_DEDUP_JOIN = (
        "LEFT JOIN product_price_latest pp_dedup "
        "ON o.product_code = pp_dedup.product_code "
        "AND wr.process_id = pp_dedup.process_id"
    )

    @staticmethod
    def calculate_wages(employee_id='', date_from='', date_to='', page=1, limit=200, include_pending=False, include_rework=False):
        db = BaseService.db()
        status_filter = "wr.status = 'approved'" if not include_pending else "wr.status IN ('approved','pending')"
        type_filter = "wr.type IN ('normal','rework')" if include_rework else "wr.type = 'normal'"
        wr_where_parts = [status_filter, type_filter]
        wr_params = []
        if employee_id:
            wr_where_parts.append('wr.user_id = ?'); wr_params.append(employee_id)
        if date_from:
            wr_where_parts.append('wr.created_at >= ?'); wr_params.append(date_from)
        if date_to:
            wr_where_parts.append('wr.created_at <= ?'); wr_params.append(date_to + ' 23:59:59')
        wr_where = ' AND '.join(wr_where_parts)
        user_where = "u.status = 'active' AND u.id IN (SELECT ur.user_id FROM user_roles ur JOIN roles r ON ur.role_id = r.id WHERE r.code = 'worker')"
        user_params = []
        if employee_id:
            user_where += ' AND u.id = ?'; user_params.append(employee_id)
        total = db.execute("SELECT COUNT(*) FROM users u WHERE " + user_where, user_params).fetchone()[0]
        offset = (page - 1) * limit
        p1_params = user_params + [limit, offset]
        user_rows = db.execute("SELECT u.id, u.name, u.employee_no, COALESCE(pos.name, '') as position_name FROM users u LEFT JOIN positions pos ON u.position_id = pos.id WHERE " + user_where + " ORDER BY u.id LIMIT ? OFFSET ?", p1_params).fetchall()
        user_map = {row['id']: {'employee_name': row['name'] or 'unknown', 'employee_no': row['employee_no'] or '', 'position_name': row['position_name'] or ''} for row in user_rows}
        user_ids = list(user_map.keys())
        if not user_ids:
            return {'wages': [], 'total': total, 'page': page, 'limit': limit}
        placeholders = ','.join(['?' for _ in user_ids])
        p2_params = wr_params + user_ids
        query = ('''SELECT u.id as user_id, u.name as employee_name, u.employee_no,
                   wr.quantity, wr.created_at, wr.id as wr_id,
                   p.name as process_name,
                   o.order_no, o.product_name, o.product_code as order_product_code,
                   COALESCE(pp_dedup.unit_price, rp.unit_price, 0) as unit_price
            FROM users u
            LEFT JOIN work_records wr ON u.id = wr.user_id AND ''' + wr_where + '''
            LEFT JOIN processes p ON wr.process_id = p.id
            LEFT JOIN orders o ON wr.order_id = o.id
            LEFT JOIN route_prices rp ON o.route_id = rp.route_id
                AND wr.process_id = rp.process_id AND rp.status = 'active'
                AND rp.effective_date <= date('now','localtime')
            ''' + WageService._PP_DEDUP_JOIN + '''
            WHERE u.id IN (''' + placeholders + ''')
            ORDER BY u.id''')
        rows = db.execute(query, p2_params).fetchall()
        wages = {}
        for uid, info in user_map.items():
            wages[uid] = {'employee_name': info['employee_name'], 'employee_no': info['employee_no'], 'position_name': info['position_name'], 'total_quantity': 0, 'total_wage': 0, 'details': []}
        for row in rows:
            emp_id = row['user_id']
            if row['wr_id'] is not None:
                qty = row['quantity'] or 0
                up = row['unit_price'] or 0
                wage = qty * up
                if emp_id not in wages:
                    wages[emp_id] = {'employee_name': row['employee_name'] or 'unknown', 'employee_no': row['employee_no'] or '', 'position_name': '', 'total_quantity': 0, 'total_wage': 0, 'details': []}
                wages[emp_id]['total_quantity'] += qty
                wages[emp_id]['total_wage'] += wage
                wages[emp_id]['details'].append({'date': row['created_at'], 'order_no': row['order_no'] or '', 'product_name': row['product_name'] or '', 'product_code': row['order_product_code'] or '', 'process_name': row['process_name'], 'quantity': qty, 'unit_price': up, 'wage': wage})
        return {'wages': list(wages.values()), 'total': total, 'page': page, 'limit': limit}

    @staticmethod
    def daily_report(date):
        """员工生产日报表（含工序工价和工资，仅统计已审批通过的正常报工）。"""
        db = BaseService.db()
        rows = db.execute('''
            SELECT wr.*, u.name as employee_name, u.employee_no, p.name as process_name,
                   COALESCE(pp_dedup.unit_price, rp.unit_price, 0) as unit_price
            FROM work_records wr
            LEFT JOIN users u ON wr.user_id = u.id
            LEFT JOIN processes p ON wr.process_id = p.id
            LEFT JOIN orders o ON wr.order_id = o.id
            LEFT JOIN route_prices rp ON o.route_id = rp.route_id
                AND wr.process_id = rp.process_id AND rp.status = 'active'
                AND rp.effective_date <= date('now','localtime')
            ''' + WageService._PP_DEDUP_JOIN + '''
            WHERE wr.status = 'approved' AND wr.type = 'normal'
            AND wr.created_at >= ? AND wr.created_at < ?
            ORDER BY wr.user_id, wr.process_id
        ''', (date, date + ' 23:59:59')).fetchall()
        report = {}
        for row in rows:
            emp_id = row['user_id']; proc_id = row['process_id']
            emp_name = row['employee_name'] or '未知'
            proc_name = row['process_name'] or '未知'
            up = row['unit_price'] or 0
            qty = row['quantity'] or 0
            if emp_id not in report:
                report[emp_id] = {'employee_name': emp_name, 'employee_no': row['employee_no'],
                                  'processes': {}, 'total_wage': 0}
            if proc_id not in report[emp_id]['processes']:
                report[emp_id]['processes'][proc_id] = {'process_name': proc_name, 'quantity': 0, 'unit_price': up, 'wage': 0}
            report[emp_id]['processes'][proc_id]['quantity'] += qty
            report[emp_id]['processes'][proc_id]['wage'] += qty * up
            report[emp_id]['total_wage'] += qty * up
        return {'date': date, 'report': list(report.values())}

    @staticmethod
    def production_progress(page=1, limit=50):
        """生产进度看板（分页）。"""
        db = BaseService.db()
        total = db.execute('''
            SELECT COUNT(*) FROM orders o
            WHERE o.deleted_at IS NULL
              AND o.status IN ('producing', 'pending')
        ''').fetchone()[0]
        offset = (page - 1) * limit
        rows = db.execute('''
            SELECT o.*, COALESCE(o.completed, 0) as done_qty,
                   COALESCE(o.scrapped, 0) as scrap_qty
            FROM orders o
            WHERE o.deleted_at IS NULL
              AND o.status IN ('producing', 'pending')
            ORDER BY o.plan_end, o.created_at DESC
            LIMIT ? OFFSET ?
        ''', (limit, offset)).fetchall()
        # 批量预取工序，避免 N+1
        order_ids = [r['id'] for r in rows]
        proc_by_order = {}
        if order_ids:
            # placeholders are all '?' chars from trusted integer list — safe for f-string
            placeholders = ",".join("?" for _ in order_ids)
            proc_rows = db.execute(f'''
                SELECT op.order_id, op.process_id, p.name as process_name, op.completed,
                       op.scrapped, op.required_audit
                FROM order_processes op
                LEFT JOIN processes p ON op.process_id = p.id
                WHERE op.order_id IN ({placeholders}) ORDER BY op.seq_order
            ''', order_ids).fetchall()
            for pr in proc_rows:
                proc_by_order.setdefault(pr['order_id'], []).append(pr)

        result = []
        for row in rows:
            o = dict(row)
            total = o['quantity'] or 1
            done = o.get('done_qty', 0); scrap = o.get('scrap_qty', 0)
            progress_pct = min(100, int((done + scrap) / total * 100))
            o['progress'] = progress_pct
            o['remaining'] = total - done - scrap
            proc_rows = proc_by_order.get(row['id'], [])
            processes = []
            for pr in proc_rows:
                pd = pr['completed'] or 0; ps = pr['scrapped'] or 0
                pp = min(100, int((pd + ps) / total * 100))
                processes.append({
                    'process_id': pr['process_id'], 'process_name': pr['process_name'],
                    'completed': pd, 'scrapped': ps, 'progress': pp,
                    'required_audit': pr['required_audit']
                })
            o['processes'] = processes
            result.append(o)
        return {'orders': result, 'total': total, 'page': page, 'limit': limit}

    @staticmethod
    def monthly_summary(year_month, page=1, limit=100):
        """月度工资汇总（按员工聚合，JOIN 优化取价）。"""
        db = BaseService.db()
        rows = db.execute('''
            SELECT wr.user_id, u.name as employee_name, u.employee_no,
                   SUM(wr.quantity) as total_quantity,
                   SUM(wr.quantity * COALESCE(pp_dedup.unit_price, rp.unit_price, 0)) as total_wage
            FROM work_records wr
            JOIN users u ON wr.user_id = u.id
            LEFT JOIN orders o ON wr.order_id = o.id
            LEFT JOIN route_prices rp ON o.route_id = rp.route_id
                AND wr.process_id = rp.process_id AND rp.status = 'active'
                AND rp.effective_date <= date('now','localtime')
            ''' + WageService._PP_DEDUP_JOIN + '''
            WHERE wr.status = 'approved' AND wr.type = 'normal'
              AND wr.created_at >= ? AND wr.created_at < date(?, 'start of month', '+1 month')
            GROUP BY wr.user_id
            ORDER BY total_wage DESC
            LIMIT ? OFFSET ?
        ''', (year_month + '-01', year_month + '-01', limit, (page - 1) * limit)).fetchall()

        total_count = db.execute('''
            SELECT COUNT(DISTINCT wr.user_id) FROM work_records wr
            WHERE wr.status = 'approved' AND wr.type = 'normal'
              AND wr.created_at >= ? AND wr.created_at < date(?, 'start of month', '+1 month')
        ''', (year_month + '-01', year_month + '-01')).fetchone()[0]

        return {
            'year_month': year_month,
            'summary': [dict(r) for r in rows],
            'grand_total_wage': sum(r['total_wage'] or 0 for r in rows),
            'grand_total_quantity': sum(r['total_quantity'] or 0 for r in rows),
            'total': total_count, 'page': page, 'limit': limit,
        }

    @staticmethod
    def process_wage_summary(year_month):
        """按工序维度的工资汇总（用于分析各工序工资支出）。"""
        db = BaseService.db()
        rows = db.execute('''
            SELECT wr.process_id, p.name as process_name, p.category,
                   SUM(wr.quantity) as total_quantity,
                   SUM(wr.quantity * COALESCE(pp_dedup.unit_price, rp.unit_price, 0)) as total_wage,
                   COUNT(DISTINCT wr.user_id) as worker_count
            FROM work_records wr
            JOIN processes p ON wr.process_id = p.id
            LEFT JOIN orders o ON wr.order_id = o.id
            LEFT JOIN route_prices rp ON o.route_id = rp.route_id
                AND wr.process_id = rp.process_id AND rp.status = 'active'
                AND rp.effective_date <= date('now','localtime')
            ''' + WageService._PP_DEDUP_JOIN + '''
            WHERE wr.status = 'approved' AND wr.type = 'normal'
              AND wr.created_at >= ? AND wr.created_at < date(?, 'start of month', '+1 month')
            GROUP BY wr.process_id
            ORDER BY total_wage DESC
        ''', (year_month + '-01', year_month + '-01')).fetchall()
        grand_total = sum(r['total_wage'] or 0 for r in rows)
        return {
            'year_month': year_month,
            'summary': [dict(r) for r in rows],
            'grand_total_wage': grand_total,
        }

