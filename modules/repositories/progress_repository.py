"""qr-system - ProgressRepository"""
from modules.services import BaseService


class ProgressRepository:

    @staticmethod
    def find_order(order_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT * FROM orders WHERE id = ? AND deleted_at IS NULL", (order_id,)
        ).fetchone()

    @staticmethod
    def list_processes(order_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT op.*, p.name as process_name FROM order_processes op "
            "JOIN processes p ON p.id = op.process_id "
            "WHERE op.order_id = ? ORDER BY op.seq_order", (order_id,)
        ).fetchall()

    @staticmethod
    def count_overdue(db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT COUNT(*) FROM orders WHERE deadline < DATE('now') "
            "AND status NOT IN ('completed','cancelled') AND deleted_at IS NULL"
        ).fetchone()[0]

    @staticmethod
    def count_near_due(db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT COUNT(*) FROM orders WHERE deadline BETWEEN DATE('now') "
            "AND DATE('now','+3 days') AND status NOT IN ('completed','cancelled') "
            "AND deleted_at IS NULL"
        ).fetchone()[0]
