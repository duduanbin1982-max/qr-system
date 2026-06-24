"""qr-system - ExportRepository"""
from modules.db_unit_of_work import BaseService


class ExportRepository:

    @staticmethod
    def get_orders_export(db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT o.id, o.order_no, c.name as customer, o.product_name, "
            "o.quantity, o.status, o.plan_start, o.plan_end, o.deadline, o.created_at "
            "FROM orders o LEFT JOIN customers c ON o.customer_id = c.id "
            "ORDER BY o.id DESC"
        ).fetchall()

    @staticmethod
    def get_work_records_export(order_id, date_from, date_to, db=None):
        db = db or BaseService.db()
        query = (
            "SELECT wr.id, o.order_no, p.name as process_name, u.name as worker_name, "
            "wr.serial_no, wr.quantity, wr.type, wr.remark, wr.created_at "
            "FROM work_records wr "
            "LEFT JOIN orders o ON wr.order_id = o.id "
            "LEFT JOIN processes p ON wr.process_id = p.id "
            "LEFT JOIN users u ON wr.user_id = u.id "
            "WHERE 1=1"
        )
        params = []
        if order_id:
            query += " AND wr.order_id = ?"
            params.append(order_id)
        if date_from:
            query += " AND wr.created_at >= ?"
            params.append(date_from)
        if date_to:
            query += " AND wr.created_at <= ?"
            params.append(date_to + " 23:59:59")
        query += " ORDER BY wr.id DESC LIMIT 10000"
        return db.execute(query, params).fetchall()
