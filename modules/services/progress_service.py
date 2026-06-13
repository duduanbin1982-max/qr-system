"""
qr-system — ProgressService
"""
from modules.services import BaseService


class ProgressService:
    @staticmethod
    def get_order_progress(order_id):
        db = BaseService.db()
        order = db.execute(
            "SELECT * FROM orders WHERE id = ? AND deleted_at IS NULL", (order_id,)
        ).fetchone()
        if not order:
            raise ValueError("订单不存在")
        processes = db.execute(
            "SELECT op.*, p.name as process_name FROM order_processes op "
            "JOIN processes p ON p.id = op.process_id "
            "WHERE op.order_id = ? ORDER BY op.seq_order", (order_id,)
        ).fetchall()
        return {"order": dict(order), "processes": [dict(p) for p in processes]}

    @staticmethod
    def get_delivery_alerts():
        db = BaseService.db()
        overdue = db.execute(
            "SELECT COUNT(*) FROM orders WHERE deadline < DATE('now') "
            "AND status NOT IN ('completed','cancelled') AND deleted_at IS NULL"
        ).fetchone()[0]
        near_due = db.execute(
            "SELECT COUNT(*) FROM orders WHERE deadline BETWEEN DATE('now') "
            "AND DATE('now','+3 days') AND status NOT IN ('completed','cancelled') "
            "AND deleted_at IS NULL"
        ).fetchone()[0]
        return {"overdue": overdue, "near_due": near_due}
