"""
qr-system — WageRepository（工资核算数据访问层）
"""
from modules.db_unit_of_work import BaseService


class WageRepository:
    """工资核算数据访问 — 集中管理报工记录、工序汇总、工资计算相关查询。"""

    _PRICE_JOIN = (
        "LEFT JOIN route_prices rp ON o.route_id = rp.route_id "
        "AND wr.process_id = rp.process_id AND rp.status = 'active' "
        "AND rp.effective_date <= DATE(wr.created_at)"
    )
    _PRICE_SELECT = "COALESCE(rp.unit_price, 0) as unit_price"

    @classmethod
    def _unit_price_expr(cls):
        return cls._PRICE_SELECT.replace("as unit_price", "")

    @staticmethod
    def get_worker_role_code(db=None):
        db = db or BaseService.db()
        row = db.execute(
            "SELECT COALESCE((SELECT value FROM system_settings WHERE key='worker_role_code'), 'worker')"
        ).fetchone()
        return row[0] if row else "worker"

    @staticmethod
    def get_worker_wage_summary(user_where, user_params, p1_params, p2_params, db=None):
        """按工人统计报工汇总（含工资估算）。"""
        db = db or BaseService.db()
        query = ("""SELECT u.id as user_id, u.name as employee_name, u.employee_no,
            COUNT(DISTINCT DATE(wr.created_at)) as work_days,
            COUNT(wr.id) as record_count,
            COALESCE(SUM(CASE WHEN wr.type='normal' THEN wr.quantity ELSE 0 END),0) as total_output,
            COALESCE(SUM(CASE WHEN wr.type='scrap' THEN wr.quantity ELSE 0 END),0) as total_scrap,
            COALESCE(SUM(CASE WHEN wr.type='rework' THEN wr.quantity ELSE 0 END),0) as total_rework
            FROM work_records wr
            JOIN users u ON wr.user_id=u.id
            JOIN orders o ON wr.order_id=o.id
            WHERE o.deleted_at IS NULL AND o.status != 'cancelled'
        """ + user_where + """
            GROUP BY u.id
            ORDER BY total_output DESC
            LIMIT ? OFFSET ?""")
        return db.execute(query, p2_params).fetchall()

    @staticmethod
    def get_worker_paged(user_where, user_params, db=None, page=1, limit=50):
        """分页查询工人列表（含岗位名）。"""
        db = db or BaseService.db()
        total = db.execute(
            "SELECT COUNT(*) FROM users u WHERE " + user_where, user_params
        ).fetchone()[0]
        rows = db.execute(
            "SELECT u.id, u.name, u.employee_no, COALESCE(pos.name, '') as position_name "
            "FROM users u LEFT JOIN positions pos ON u.position_id = pos.id "
            "WHERE " + user_where + " ORDER BY u.id LIMIT ? OFFSET ?",
            user_params + [limit, (page - 1) * limit]
        ).fetchall()
        return rows, total

    @classmethod
    def get_worker_paged_by_role(cls, employee_id="", db=None, page=1, limit=50):
        db = db or BaseService.db()
        user_where = (
            "u.status = 'active' "
            "AND u.id IN ("
            "SELECT ur.user_id FROM user_roles ur "
            "JOIN roles r ON ur.role_id = r.id "
            "WHERE r.code = ?)"
        )
        user_params = [cls.get_worker_role_code(db)]
        if employee_id:
            user_where += " AND u.id = ?"
            user_params.append(employee_id)
        return cls.get_worker_paged(user_where, user_params, db, page, limit)

    @classmethod
    def get_wage_rows_for_workers(cls, wr_where, wr_params, user_ids, db=None):
        db = db or BaseService.db()
        if not user_ids:
            return []
        placeholders = ",".join(["?" for _ in user_ids])
        query = (
            """SELECT u.id as user_id, u.name as employee_name, u.employee_no,
                   wr.quantity, wr.created_at, wr.id as wr_id,
                   p.name as process_name,
                   o.order_no, o.product_name, o.product_code as order_product_code,
                   """
            + cls._PRICE_SELECT
            + """
            FROM users u
            LEFT JOIN work_records wr ON u.id = wr.user_id AND """
            + wr_where
            + """
            LEFT JOIN processes p ON wr.process_id = p.id
            LEFT JOIN orders o ON wr.order_id = o.id
            """
            + cls._PRICE_JOIN
            + """
            WHERE u.id IN ("""
            + placeholders
            + """)
            ORDER BY u.id"""
        )
        return db.execute(query, wr_params + user_ids).fetchall()

    @classmethod
    def get_daily_report_rows(cls, date, db=None):
        db = db or BaseService.db()
        query = (
            """
            SELECT wr.*, u.name as employee_name, u.employee_no, p.name as process_name,
                   """
            + cls._PRICE_SELECT
            + """
            FROM work_records wr
            LEFT JOIN users u ON wr.user_id = u.id
            LEFT JOIN processes p ON wr.process_id = p.id
            LEFT JOIN orders o ON wr.order_id = o.id
            """
            + cls._PRICE_JOIN
            + """
            WHERE wr.status = 'approved' AND wr.type = 'normal'
            AND wr.created_at >= ? AND wr.created_at < ?
            ORDER BY wr.user_id, wr.process_id
            """
        )
        return db.execute(query, (date, date + " 23:59:59")).fetchall()

    @staticmethod
    def count_active_orders(db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT COUNT(*) FROM orders WHERE deleted_at IS NULL AND status != 'cancelled'"
        ).fetchone()[0]

    @staticmethod
    def get_production_orders(page=1, limit=50, db=None):
        db = db or BaseService.db()
        return db.execute(
            """
            SELECT o.*, COALESCE(o.completed, 0) as done_qty,
                   (SELECT COUNT(*) FROM product_items pi WHERE pi.order_id = o.id AND pi.status = 'completed') as actual_completed
            FROM orders o
            WHERE o.deleted_at IS NULL AND o.status != 'cancelled'
            ORDER BY o.created_at DESC LIMIT ? OFFSET ?
            """,
            (limit, (page - 1) * limit),
        ).fetchall()

    @staticmethod
    def get_production_processes(order_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            """
            SELECT op.order_id, op.process_id, p.name as process_name, op.completed,
                   (SELECT COUNT(*) FROM product_items pi WHERE pi.order_id = op.order_id) as total_items,
                   op.required_audit,
                   COALESCE((
                       SELECT SUM(wr.quantity)
                       FROM work_records wr
                       WHERE wr.order_id = op.order_id
                         AND wr.process_id = op.process_id
                         AND wr.type = 'scrap'
                         AND wr.status = 'approved'
                   ), 0) as scrapped
            FROM order_processes op
            JOIN processes p ON op.process_id = p.id
            WHERE op.order_id = ? ORDER BY op.seq_order
            """,
            (order_id,),
        ).fetchall()

    @classmethod
    def get_monthly_summary(cls, year_month, page=1, limit=100, db=None):
        db = db or BaseService.db()
        month_start = year_month + "-01"
        unit_price = cls._unit_price_expr()
        rows = db.execute(
            """
            SELECT wr.user_id, u.name as employee_name, u.employee_no,
                   SUM(wr.quantity) as total_quantity,
                   SUM(wr.quantity * """
            + unit_price
            + """) as total_wage
            FROM work_records wr
            JOIN users u ON wr.user_id = u.id
            LEFT JOIN orders o ON wr.order_id = o.id
            """
            + cls._PRICE_JOIN
            + """
            WHERE wr.status = 'approved' AND wr.type = 'normal'
              AND wr.created_at >= ? AND wr.created_at < date(?, 'start of month', '+1 month')
            GROUP BY wr.user_id
            ORDER BY total_wage DESC
            LIMIT ? OFFSET ?
            """,
            (month_start, month_start, limit, (page - 1) * limit),
        ).fetchall()
        total_count = db.execute(
            """
            SELECT COUNT(DISTINCT wr.user_id) FROM work_records wr
            WHERE wr.status = 'approved' AND wr.type = 'normal'
              AND wr.created_at >= ? AND wr.created_at < date(?, 'start of month', '+1 month')
            """,
            (month_start, month_start),
        ).fetchone()[0]
        grand_total = db.execute(
            """
            SELECT COALESCE(SUM(wr.quantity),0) as total_qty,
                   COALESCE(SUM(wr.quantity * """
            + unit_price
            + """),0) as total_wage
            FROM work_records wr
            LEFT JOIN orders o ON wr.order_id = o.id
            """
            + cls._PRICE_JOIN
            + """
            WHERE wr.status = 'approved' AND wr.type = 'normal'
              AND wr.created_at >= ? AND wr.created_at < date(?, 'start of month', '+1 month')
            """,
            (month_start, month_start),
        ).fetchone()
        return rows, total_count, grand_total

    @classmethod
    def get_process_wage_summary(cls, year_month, db=None):
        db = db or BaseService.db()
        month_start = year_month + "-01"
        return db.execute(
            """
            SELECT wr.process_id, p.name as process_name, p.category,
                   SUM(wr.quantity) as total_quantity,
                   SUM(wr.quantity * """
            + cls._unit_price_expr()
            + """) as total_wage,
                   COUNT(DISTINCT wr.user_id) as worker_count
            FROM work_records wr
            JOIN processes p ON wr.process_id = p.id
            LEFT JOIN orders o ON wr.order_id = o.id
            """
            + cls._PRICE_JOIN
            + """
            WHERE wr.status = 'approved' AND wr.type = 'normal'
              AND wr.created_at >= ? AND wr.created_at < date(?, 'start of month', '+1 month')
            GROUP BY wr.process_id
            ORDER BY total_wage DESC
            """,
            (month_start, month_start),
        ).fetchall()

    @staticmethod
    def upsert_snapshot(employee, year_month, details_json, db=None):
        db = db or BaseService.db()
        db.execute(
            "INSERT INTO wage_snapshots (employee_id,employee_name,employee_no,year_month,total_quantity,total_wage,rework_wage,details_json,status,updated_at) VALUES (?,?,?,?,?,?,?,?,'draft',datetime('now','localtime')) ON CONFLICT(employee_id,year_month) DO UPDATE SET total_quantity=excluded.total_quantity,total_wage=excluded.total_wage,rework_wage=excluded.rework_wage,details_json=excluded.details_json,updated_at=datetime('now','localtime')",
            (
                employee.get("employee_id", 0),
                employee.get("employee_name", ""),
                employee.get("employee_no", ""),
                year_month,
                employee.get("total_quantity", 0),
                employee.get("total_wage", 0),
                employee.get("rework_wage", 0),
                details_json,
            ),
        )

    @staticmethod
    def lock_snapshots(year_month, locked_by="system", notes="", db=None):
        db = db or BaseService.db()
        db.execute(
            "UPDATE wage_snapshots SET status='locked',locked_at=datetime('now','localtime'),locked_by=?,notes=? WHERE year_month=? AND status='draft'",
            (locked_by, notes, year_month),
        )
        return db.execute("SELECT changes()").fetchone()[0]

    @staticmethod
    def list_snapshots(year_month, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT * FROM wage_snapshots WHERE year_month=? ORDER BY total_wage DESC",
            (year_month,),
        ).fetchall()

    @staticmethod
    def confirm_snapshots(year_month, confirmed_by="system", db=None):
        db = db or BaseService.db()
        db.execute(
            "UPDATE wage_snapshots SET status='confirmed',confirmed_at=datetime('now','localtime'),confirmed_by=? WHERE year_month=? AND status IN ('draft','locked')",
            (confirmed_by, year_month),
        )
        return db.execute("SELECT changes()").fetchone()[0]

    @staticmethod
    def get_snapshot_status_rows(year_month, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT status, COUNT(*) as cnt, SUM(total_wage) as total_wage FROM wage_snapshots WHERE year_month=? GROUP BY status",
            (year_month,),
        ).fetchall()

    @staticmethod
    def list_adjustments(user_id=None, year_month=None, db=None):
        db = db or BaseService.db()
        where = []
        params = []
        if user_id:
            where.append("user_id=?")
            params.append(user_id)
        if year_month:
            where.append("year_month=?")
            params.append(year_month)
        sql = "SELECT a.*, u.name as employee_name FROM wage_adjustments a LEFT JOIN users u ON a.user_id=u.id"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY a.created_at DESC"
        return db.execute(sql, params).fetchall()

    @staticmethod
    def find_adjustment_id(user_id, year_month, adj_type, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT id FROM wage_adjustments WHERE user_id=? AND year_month=? AND type=?",
            (user_id, year_month, adj_type),
        ).fetchone()

    @staticmethod
    def update_adjustment(adj_id, amount, reason, created_by, db=None):
        db = db or BaseService.db()
        db.execute(
            "UPDATE wage_adjustments SET amount=?, reason=?, created_by=? WHERE id=?",
            (amount, reason or "", created_by, adj_id),
        )

    @staticmethod
    def insert_adjustment(user_id, year_month, adj_type, amount, reason, created_by, db=None):
        db = db or BaseService.db()
        db.execute(
            "INSERT INTO wage_adjustments (user_id, year_month, type, amount, reason, created_by) VALUES (?,?,?,?,?,?)",
            (user_id, year_month, adj_type, amount, reason or "", created_by),
        )
        return db.execute("SELECT last_insert_rowid()").fetchone()[0]

    @staticmethod
    def delete_adjustment(adj_id, db=None):
        db = db or BaseService.db()
        db.execute("DELETE FROM wage_adjustments WHERE id=?", (adj_id,))
        return db.total_changes

    @staticmethod
    def get_adjustments_total_rows(user_id, year_month, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT type, SUM(amount) as total FROM wage_adjustments WHERE user_id=? AND year_month=? GROUP BY type",
            (user_id, year_month),
        ).fetchall()

    @staticmethod
    def get_wage_trend_snapshots(months=12, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT year_month, SUM(total_wage) as total_wage, SUM(total_quantity) as total_quantity, COUNT(DISTINCT employee_id) as employee_count FROM wage_snapshots WHERE status IN ('draft','locked','confirmed') GROUP BY year_month ORDER BY year_month DESC LIMIT ?",
            (months,),
        ).fetchall()

    @classmethod
    def get_live_wage_trends(cls, months=12, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT strftime('%Y-%m', wr.created_at) as year_month, "
            "COALESCE(SUM(wr.quantity),0) as total_quantity, "
            "COALESCE(SUM(wr.quantity * " + cls._unit_price_expr() + "),0) as total_wage, "
            "COUNT(DISTINCT wr.user_id) as employee_count "
            "FROM work_records wr "
            "LEFT JOIN orders o ON wr.order_id = o.id "
            + cls._PRICE_JOIN
            + " "
            "WHERE wr.status = 'approved' AND wr.type = 'normal' "
            "AND wr.created_at >= date('now','-" + str(months) + " months') "
            "GROUP BY strftime('%Y-%m', wr.created_at) "
            "ORDER BY year_month ASC LIMIT ?",
            (months,),
        ).fetchall()

    @classmethod
    def get_position_summary(cls, year_month, db=None):
        db = db or BaseService.db()
        month_start = year_month + "-01"
        return db.execute(
            "SELECT COALESCE(pos.name, '未分配') as position_name, COUNT(DISTINCT wr.user_id) as employee_count, "
            "SUM(wr.quantity) as total_quantity, SUM(wr.quantity * "
            + cls._unit_price_expr()
            + ") as total_wage FROM work_records wr "
            "JOIN users u ON wr.user_id = u.id "
            "LEFT JOIN positions pos ON u.position_id = pos.id "
            "LEFT JOIN orders o ON wr.order_id = o.id AND o.deleted_at IS NULL "
            + cls._PRICE_JOIN
            + " WHERE wr.status = 'approved' AND wr.type = 'normal' "
            "AND wr.created_at >= ? AND wr.created_at < date(?, 'start of month', '+1 month') "
            "GROUP BY pos.name ORDER BY total_wage DESC",
            (month_start, month_start),
        ).fetchall()

    @staticmethod
    def get_order_wages(start, end, db=None):
        """按订单统计工资汇总。"""
        db = db or BaseService.db()
        date_filter = ""
        params = []
        if start:
            date_filter += " AND DATE(o.created_at) >= ?"
            params.append(start)
        if end:
            date_filter += " AND DATE(o.created_at) <= ?"
            params.append(end)
        rows = db.execute(
            """SELECT o.*, COALESCE(o.completed, 0) as done_qty,
               (SELECT COUNT(*) FROM product_items pi WHERE pi.order_id=o.id AND pi.status='completed') as actual_completed
               FROM orders o
               WHERE o.deleted_at IS NULL AND o.status != 'cancelled'""" + date_filter + """
               ORDER BY o.created_at DESC LIMIT 100""",
            params
        ).fetchall()
        return rows

    @staticmethod
    def get_process_breakdown(order_id, db=None):
        """获取订单工序完成情况。"""
        db = db or BaseService.db()
        return db.execute(
            """SELECT op.order_id, op.process_id, p.name as process_name, op.completed,
               (SELECT COUNT(*) FROM product_items pi WHERE pi.order_id=op.order_id) as total_items
               FROM order_processes op
               JOIN processes p ON op.process_id=p.id
               WHERE op.order_id = ? ORDER BY op.seq_order""",
            (order_id,)
        ).fetchall()

    @staticmethod
    def get_daily_summary(start, end, db=None):
        """日报工汇总。"""
        db = db or BaseService.db()
        date_filter = ""
        params = []
        if start:
            date_filter += " AND DATE(wr.created_at) >= ?"
            params.append(start)
        if end:
            date_filter += " AND DATE(wr.created_at) <= ?"
            params.append(end)
        return db.execute(
            """SELECT wr.user_id, u.name as employee_name, u.employee_no,
               COALESCE(SUM(CASE WHEN wr.type='normal' THEN wr.quantity ELSE 0 END),0) as total_output
               FROM work_records wr
               JOIN users u ON wr.user_id=u.id
               JOIN orders o ON wr.order_id=o.id
               WHERE o.deleted_at IS NULL""" + date_filter + """
               GROUP BY wr.user_id ORDER BY total_output DESC""",
            params
        ).fetchall()

    @staticmethod
    def get_process_summary(start, end, db=None):
        """按工序统计报工汇总。"""
        db = db or BaseService.db()
        date_filter = ""
        params = []
        if start:
            date_filter += " AND DATE(wr.created_at) >= ?"
            params.append(start)
        if end:
            date_filter += " AND DATE(wr.created_at) <= ?"
            params.append(end)
        return db.execute(
            """SELECT wr.process_id, p.name as process_name, p.category,
               COALESCE(SUM(CASE WHEN wr.type='normal' THEN wr.quantity ELSE 0 END),0) as total_output,
               COUNT(DISTINCT wr.user_id) as worker_count
               FROM work_records wr
               JOIN processes p ON wr.process_id=p.id
               JOIN orders o ON wr.order_id=o.id
               WHERE o.deleted_at IS NULL""" + date_filter + """
               GROUP BY wr.process_id ORDER BY total_output DESC""",
            params
        ).fetchall()
