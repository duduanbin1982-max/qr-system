"""
qr-system — WageRepository（工资核算数据访问层）
"""
from modules.db_unit_of_work import BaseService


class WageRepository:
    """工资核算数据访问 — 集中管理报工记录、工序汇总、工资计算相关查询。"""

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
            user_params + [100, 0]
        ).fetchall()
        return rows, total

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

