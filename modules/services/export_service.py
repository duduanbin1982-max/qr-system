"""
qr-system — ExportService
"""
from modules.services import BaseService


class ExportService:

    @staticmethod
    def get_orders_export():
        db = BaseService.db()
        rows = db.execute(
            "SELECT o.id, o.order_no, c.name as customer, o.product_name, "
            "o.quantity, o.status, o.plan_start, o.plan_end, o.deadline, o.created_at "
            "FROM orders o LEFT JOIN customers c ON o.customer_id = c.id "
            "ORDER BY o.id DESC"
        ).fetchall()
        return [{
            "id": r[0], "order_no": r[1], "customer": r[2], "product_name": r[3],
            "quantity": r[4], "status": r[5], "plan_start": r[6], "plan_end": r[7],
            "deadline": r[8], "created_at": r[9],
        } for r in rows]

    @staticmethod
    def get_work_records_export(order_id=None, date_from=None, date_to=None):
        db = BaseService.db()
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
        rows = db.execute(query, params).fetchall()
        return [{
            "id": r[0], "order_no": r[1], "process_name": r[2], "worker_name": r[3],
            "serial_no": r[4], "quantity": r[5], "type": r[6], "remark": r[7], "created_at": r[8],
        } for r in rows]

