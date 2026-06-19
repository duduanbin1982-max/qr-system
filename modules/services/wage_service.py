"""qr-system — 工资计算 + 日报 + 生产进度 Service 层"""
from datetime import datetime
from modules.services import BaseService
from modules.repositories.wage_repository import WageRepository


class WageService:
    """计件工资 + 日报 + 生产进度。"""

    # Shared price-join fragment used across multiple queries
    _PRICE_JOIN = (
        "LEFT JOIN route_prices rp ON o.route_id = rp.route_id "
        "AND wr.process_id = rp.process_id AND rp.status = 'active' "
        "AND rp.effective_date <= DATE(wr.created_at)"
    )

    _PRICE_SELECT = (
        "COALESCE(rp.unit_price, 0) as unit_price"
    )

    @classmethod
    def _price_joins(cls):
        """Return (price_join_sql, price_select_sql)."""
        return cls._PRICE_JOIN, cls._PRICE_SELECT

    @staticmethod
    def calculate_wages(employee_id='', date_from='', date_to='', page=1, limit=200, include_pending=False, include_rework=False, hide_zero=False):
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

        # Use WageRepository for user pagination
        user_where = "u.status = 'active' AND u.id IN (SELECT ur.user_id FROM user_roles ur JOIN roles r ON ur.role_id = r.id WHERE r.code = 'worker')"
        user_params = []
        if employee_id:
            user_where += ' AND u.id = ?'; user_params.append(employee_id)
        user_rows, total = WageRepository.get_worker_paged(user_where, user_params, db, page, limit)
        user_map = {row['id']: {'employee_name': row['name'] or 'unknown', 'employee_no': row['employee_no'] or '', 'position_name': row['position_name'] or ''} for row in user_rows}
        user_ids = list(user_map.keys())
        if not user_ids:
            return {'wages': [], 'total': total, 'page': page, 'limit': limit}

        placeholders = ','.join(['?' for _ in user_ids])
        price_join, price_select = WageService._price_joins()
        query = ('''SELECT u.id as user_id, u.name as employee_name, u.employee_no,
                   wr.quantity, wr.created_at, wr.id as wr_id,
                   p.name as process_name,
                   o.order_no, o.product_name, o.product_code as order_product_code,
                   ''' + price_select + '''
            FROM users u
            LEFT JOIN work_records wr ON u.id = wr.user_id AND ''' + wr_where + '''
            LEFT JOIN processes p ON wr.process_id = p.id
            LEFT JOIN orders o ON wr.order_id = o.id
            ''' + price_join + '''
            ''' '''
            WHERE u.id IN (''' + placeholders + ''')
            ORDER BY u.id''')
        rows = db.execute(query, wr_params + user_ids).fetchall()
        wages = {}
        for uid, info in user_map.items():
            wages[uid] = {'employee_id': uid, 'employee_name': info['employee_name'], 'employee_no': info['employee_no'], 'position_name': info['position_name'], 'total_quantity': 0, 'total_wage': 0, 'details': []}
        for row in rows:
            emp_id = row['user_id']
            if row['wr_id'] is not None:
                qty = row['quantity'] or 0
                up = row['unit_price'] or 0
                wage = qty * up
                if emp_id not in wages:
                    wages[emp_id] = {'employee_id': emp_id, 'employee_name': row['employee_name'] or 'unknown', 'employee_no': row['employee_no'] or '', 'position_name': '', 'total_quantity': 0, 'total_wage': 0, 'details': []}
                wages[emp_id]['total_quantity'] += qty
                wages[emp_id]['total_wage'] += wage
                wages[emp_id]['details'].append({'date': row['created_at'], 'order_no': row['order_no'] or '', 'product_name': row['product_name'] or '', 'product_code': row['order_product_code'] or '', 'process_name': row['process_name'], 'quantity': qty, 'unit_price': up, 'wage': wage})
        if hide_zero:
            wages = {uid: w for uid, w in wages.items() if w['total_quantity'] > 0}
            total = len(wages)
        return {'wages': list(wages.values()), 'total': total, 'page': page, 'limit': limit}

    @staticmethod
    def daily_report(date):
        """员工生产日报表（含工序工价和工资，仅统计已审批通过的正常报工）。"""
        db = BaseService.db()
        price_join, price_select = WageService._price_joins()
        rows = db.execute('''
            SELECT wr.*, u.name as employee_name, u.employee_no, p.name as process_name,
                   ''' + price_select + '''
            FROM work_records wr
            LEFT JOIN users u ON wr.user_id = u.id
            LEFT JOIN processes p ON wr.process_id = p.id
            LEFT JOIN orders o ON wr.order_id = o.id
            ''' + price_join + '''
            ''' '''
            WHERE wr.status = 'approved' AND wr.type = 'normal'
            AND wr.created_at >= ? AND wr.created_at < ?
            ORDER BY wr.user_id, wr.process_id
        ''', (date, date + ' 23:59:59')).fetchall()
        report = {}
        for row in rows:
            emp_id = row['user_id']
            if emp_id not in report:
                report[emp_id] = {'employee_name': row['employee_name'] or 'unknown', 'employee_no': row['employee_no'] or '', 'processes': {}}
            pid = row['process_id']
            if pid not in report[emp_id]['processes']:
                report[emp_id]['processes'][pid] = {'process_name': row['process_name'], 'quantity': 0, 'unit_price': row['unit_price'] or 0}
            report[emp_id]['processes'][pid]['quantity'] += row['quantity'] or 0
        return {'date': date, 'report': list(report.values())}

    @staticmethod
    def production_progress(page=1, limit=50):
        db = BaseService.db()
        total = db.execute("SELECT COUNT(*) FROM orders WHERE deleted_at IS NULL AND status != 'cancelled'").fetchone()[0]
        rows = db.execute('''
            SELECT o.*, COALESCE(o.completed, 0) as done_qty,
                   (SELECT COUNT(*) FROM product_items pi WHERE pi.order_id = o.id AND pi.status = 'completed') as actual_completed
            FROM orders o
            WHERE o.deleted_at IS NULL AND o.status != 'cancelled'
            ORDER BY o.created_at DESC LIMIT ? OFFSET ?
        ''', (limit, (page - 1) * limit)).fetchall()
        result = []
        for o in rows:
            o = dict(o)
            processes = db.execute('''
                SELECT op.order_id, op.process_id, p.name as process_name, op.completed,
                       (SELECT COUNT(*) FROM product_items pi WHERE pi.order_id = op.order_id) as total_items,
                       op.required_audit
                FROM order_processes op
                JOIN processes p ON op.process_id = p.id
                WHERE op.order_id = ? ORDER BY op.seq_order
            ''', (o['id'],)).fetchall()
            processes_list = []
            for pr in processes:
                total = pr['total_items'] or o['quantity'] or 1
                pd = pr['completed'] or 0
                ps = 0
                ps_row = db.execute("SELECT COALESCE(SUM(quantity), 0) FROM work_records WHERE order_id=? AND process_id=? AND type='scrap' AND status='approved'", (o['id'], pr['process_id'])).fetchone()
                if ps_row: ps = ps_row[0]
                pp = min(100, int((pd + ps) / total * 100))
                processes_list.append({
                    'process_id': pr['process_id'], 'process_name': pr['process_name'],
                    'completed': pd, 'scrapped': ps, 'progress': pp,
                    'required_audit': pr['required_audit']
                })
            o['processes'] = processes_list
            result.append(o)
        return {'orders': result, 'total': total, 'page': page, 'limit': limit}

    @staticmethod
    def monthly_summary(year_month, page=1, limit=100):
        """月度工资汇总（按员工聚合）。"""
        db = BaseService.db()
        price_join, price_select = WageService._price_joins()
        rows = db.execute('''
            SELECT wr.user_id, u.name as employee_name, u.employee_no,
                   SUM(wr.quantity) as total_quantity,
                   SUM(wr.quantity * ''' + price_select.replace('as unit_price', '') + ''') as total_wage
            FROM work_records wr
            JOIN users u ON wr.user_id = u.id
            LEFT JOIN orders o ON wr.order_id = o.id
            ''' + price_join + '''
            ''' '''
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
        # Grand totals for ALL workers (not just current page)
        gt = db.execute('''
            SELECT COALESCE(SUM(wr.quantity),0) as total_qty,
                   COALESCE(SUM(wr.quantity * ''' + price_select.replace('as unit_price', '') + '''),0) as total_wage
            FROM work_records wr
            LEFT JOIN orders o ON wr.order_id = o.id
            ''' + price_join + '''
            WHERE wr.status = 'approved' AND wr.type = 'normal'
              AND wr.created_at >= ? AND wr.created_at < date(?, 'start of month', '+1 month')
        ''', (year_month + '-01', year_month + '-01')).fetchone()
        return {
            'year_month': year_month,
            'summary': [dict(r) for r in rows],
            'grand_total_wage': round(gt['total_wage'] or 0, 2),
            'grand_total_quantity': gt['total_qty'] or 0,
            'total': total_count, 'page': page, 'limit': limit,
        }

    @staticmethod
    def process_wage_summary(year_month):
        """按工序维度的工资汇总（用于分析各工序工资支出）。"""
        db = BaseService.db()
        price_join, price_select = WageService._price_joins()
        rows = db.execute('''
            SELECT wr.process_id, p.name as process_name, p.category,
                   SUM(wr.quantity) as total_quantity,
                   SUM(wr.quantity * ''' + price_select.replace('as unit_price', '') + ''') as total_wage,
                   COUNT(DISTINCT wr.user_id) as worker_count
            FROM work_records wr
            JOIN processes p ON wr.process_id = p.id
            LEFT JOIN orders o ON wr.order_id = o.id
            ''' + price_join + '''
            ''' '''
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

    # -- P0: snapshots --
    @staticmethod
    def save_snapshot(year_month, employee_id=None):
        db = BaseService.db()
        result = WageService.calculate_wages(
            employee_id=str(employee_id) if employee_id else "",
            date_from=year_month + "-01", date_to="", page=1, limit=99999
        )
        saved = 0
        with BaseService.transaction() as txn:
            for emp in result.get("wages", []):
                txn.execute(
                    "INSERT INTO wage_snapshots (employee_id,employee_name,employee_no,year_month,total_quantity,total_wage,rework_wage,details_json,status,updated_at) VALUES (?,?,?,?,?,?,?,?,'draft',datetime('now','localtime')) ON CONFLICT(employee_id,year_month) DO UPDATE SET total_quantity=excluded.total_quantity,total_wage=excluded.total_wage,rework_wage=excluded.rework_wage,details_json=excluded.details_json,updated_at=datetime('now','localtime')",
                    (emp.get("employee_id",0), emp.get("employee_name",""), emp.get("employee_no",""),
                     year_month, emp.get("total_quantity",0), emp.get("total_wage",0),
                     emp.get("rework_wage",0), __import__("json").dumps(emp.get("details",[]), ensure_ascii=False))
                )
                saved += 1
        return {"saved": saved, "year_month": year_month}

    @staticmethod
    def lock_snapshot(year_month, locked_by="system", notes=""):
        db = BaseService.db()
        with BaseService.transaction() as txn:
            txn.execute(
                "UPDATE wage_snapshots SET status='locked',locked_at=datetime('now','localtime'),locked_by=?,notes=? WHERE year_month=? AND status='draft'",
                (locked_by, notes, year_month)
            )
            count = txn.execute("SELECT changes()").fetchone()[0]
        return {"locked": count, "year_month": year_month, "notes": notes}

    @staticmethod
    def list_snapshots(year_month):
        db = BaseService.db()
        rows = db.execute(
            "SELECT * FROM wage_snapshots WHERE year_month=? ORDER BY total_wage DESC", (year_month,)
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def confirm_snapshot(year_month, confirmed_by="system"):
        db = BaseService.db()
        with BaseService.transaction() as txn:
            txn.execute(
                "UPDATE wage_snapshots SET status='confirmed',confirmed_at=datetime('now','localtime'),confirmed_by=? WHERE year_month=? AND status IN ('draft','locked')",
                (confirmed_by, year_month)
            )
            count = txn.execute("SELECT changes()").fetchone()[0]
        return {"confirmed": count, "year_month": year_month, "confirmed_by": confirmed_by}

    @staticmethod
    def get_snapshot_status(year_month):
        db = BaseService.db()
        rows = db.execute(
            "SELECT status, COUNT(*) as cnt, SUM(total_wage) as total_wage FROM wage_snapshots WHERE year_month=? GROUP BY status",
            (year_month,)
        ).fetchall()
        result = {"draft": 0, "locked": 0, "confirmed": 0, "total_wage": 0}
        for r in rows:
            result[r["status"]] = r["cnt"]
            result["total_wage"] += r["total_wage"] or 0
        result["total_employees"] = sum(v for k,v in result.items() if k != "total_wage")
        return result

    # -- P2-P3: adjustments, trends, positions, prediction --
    @staticmethod
    def list_adjustments(user_id=None, year_month=None):
        db = BaseService.db()
        where = []
        params = []
        if user_id:
            where.append("user_id=?"); params.append(user_id)
        if year_month:
            where.append("year_month=?"); params.append(year_month)
        sql = "SELECT a.*, u.name as employee_name FROM wage_adjustments a LEFT JOIN users u ON a.user_id=u.id"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY a.created_at DESC"
        return [dict(r) for r in db.execute(sql, params).fetchall()]

    @staticmethod
    def save_adjustment(user_id, year_month, adj_type, amount, reason, created_by):
        db = BaseService.db()
        existing = db.execute(
            "SELECT id FROM wage_adjustments WHERE user_id=? AND year_month=? AND type=?",
            (user_id, year_month, adj_type)
        ).fetchone()
        if existing:
            db.execute(
                "UPDATE wage_adjustments SET amount=?, reason=?, created_by=? WHERE id=?",
                (amount, reason or "", created_by, existing["id"])
            )
            adj_id = existing["id"]
        else:
            db.execute(
                "INSERT INTO wage_adjustments (user_id, year_month, type, amount, reason, created_by) VALUES (?,?,?,?,?,?)",
                (user_id, year_month, adj_type, amount, reason or "", created_by)
            )
            adj_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        return {"success": True, "id": adj_id}

    @staticmethod
    def delete_adjustment(adj_id):
        db = BaseService.db()
        db.execute("DELETE FROM wage_adjustments WHERE id=?", (adj_id,))
        db.commit()
        return {"deleted": db.total_changes}

    @staticmethod
    def get_adjustments_total(user_id, year_month):
        db = BaseService.db()
        rows = db.execute(
            "SELECT type, SUM(amount) as total FROM wage_adjustments WHERE user_id=? AND year_month=? GROUP BY type",
            (user_id, year_month)
        ).fetchall()
        result = {"bonus": 0, "deduction": 0, "allowance": 0, "net": 0}
        for r in rows:
            result[r["type"]] = r["total"] or 0
        result["net"] = result["bonus"] + result["allowance"] - result["deduction"]
        return result

    @staticmethod
    def wage_trends(months=12):
        db = BaseService.db()
        rows = db.execute(
            "SELECT year_month, SUM(total_wage) as total_wage, SUM(total_quantity) as total_quantity, COUNT(DISTINCT employee_id) as employee_count FROM wage_snapshots WHERE status IN ('draft','locked','confirmed') GROUP BY year_month ORDER BY year_month DESC LIMIT ?",
            (months,)
        ).fetchall()
        if rows:
            result = []
            for r in reversed(rows):
                result.append({
                    "year_month": r["year_month"],
                    "total_wage": round(r["total_wage"] or 0, 2),
                    "total_quantity": r["total_quantity"] or 0,
                    "employee_count": r["employee_count"] or 0,
                })
            return result
        # Fallback: live data from work_records when no snapshots saved
        price_join, price_select = WageService._price_joins()
        rows2 = db.execute(
            "SELECT strftime('%Y-%m', wr.created_at) as year_month, "
            "COALESCE(SUM(wr.quantity),0) as total_quantity, "
            "COALESCE(SUM(wr.quantity * " + price_select.replace('as unit_price', '') + "),0) as total_wage, "
            "COUNT(DISTINCT wr.user_id) as employee_count "
            "FROM work_records wr "
            "LEFT JOIN orders o ON wr.order_id = o.id " + price_join + " "
            "WHERE wr.status = 'approved' AND wr.type = 'normal' "
            "AND wr.created_at >= date('now','-" + str(months) + " months') "
            "GROUP BY strftime('%Y-%m', wr.created_at) "
            "ORDER BY year_month ASC LIMIT ?",
            (months,)
        ).fetchall()
        result = []
        for r in rows2:
            result.append({
                "year_month": r["year_month"],
                "total_wage": round(r["total_wage"] or 0, 2),
                "total_quantity": r["total_quantity"] or 0,
                "employee_count": r["employee_count"] or 0,
            })
        return result

    @staticmethod
    def position_summary(year_month):
        db = BaseService.db()
        price_join, price_select = WageService._price_joins()
        rows = db.execute(
            "SELECT COALESCE(pos.name, '未分配') as position_name, COUNT(DISTINCT wr.user_id) as employee_count, SUM(wr.quantity) as total_quantity, SUM(wr.quantity * " + price_select.replace('as unit_price', '') + ") as total_wage FROM work_records wr JOIN users u ON wr.user_id = u.id LEFT JOIN positions pos ON u.position_id = pos.id LEFT JOIN orders o ON wr.order_id = o.id AND o.deleted_at IS NULL " + price_join + " " " WHERE wr.status = 'approved' AND wr.type = 'normal' AND wr.created_at >= ? AND wr.created_at < date(?, 'start of month', '+1 month') GROUP BY pos.name ORDER BY total_wage DESC",
            (year_month + "-01", year_month + "-01")
        ).fetchall()
        grand_total = sum(r["total_wage"] or 0 for r in rows)
        return {"year_month": year_month, "summary": [dict(r) for r in rows], "grand_total_wage": grand_total}

    @staticmethod
    def wage_prediction(months=6):
        db = BaseService.db()
        rows = db.execute(
            "SELECT year_month, SUM(total_wage) as total_wage, SUM(total_quantity) as total_quantity FROM wage_snapshots WHERE status IN ('draft','locked','confirmed') GROUP BY year_month ORDER BY year_month DESC LIMIT ?",
            (months,)
        ).fetchall()
        if len(rows) < 2:
            return {"predicted_wage": 0, "predicted_quantity": 0, "confidence": 0, "months_data": len(rows)}
        wages = [r["total_wage"] or 0 for r in reversed(rows)]
        n = len(wages)
        x_mean = (n - 1) / 2
        y_mean = sum(wages) / n
        denom = max(sum((i - x_mean)**2 for i in range(n)), 1)
        slope = sum((i - x_mean) * (wages[i] - y_mean) for i in range(n)) / denom
        predicted_wage = y_mean + slope * n
        ss_res = sum((wages[i] - (y_mean + slope * (i - x_mean)))**2 for i in range(n))
        ss_tot = sum((w - y_mean)**2 for w in wages)
        r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
        quantities = [r["total_quantity"] or 0 for r in reversed(rows)]
        predicted_quantity = round(sum(quantities) / n)
        return {
            "predicted_wage": round(max(0, predicted_wage), 2),
            "predicted_quantity": predicted_quantity,
            "confidence": round(min(100, max(0, r2 * 100))),
            "months_data": n, "trend": "up" if slope > 0 else "down" if slope < 0 else "stable",
            "avg_wage": round(y_mean, 2),
        }
