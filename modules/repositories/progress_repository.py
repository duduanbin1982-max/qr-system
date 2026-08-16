"""qr-system - ProgressRepository"""
from modules.repositories.context import resolve_db
from modules.process_fact_projection import (
    process_value_sql,
    process_version_join,
    warn_legacy_fact_rows,
)


class ProgressRepository:

    @staticmethod
    def find_order(order_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM orders WHERE id = ? AND deleted_at IS NULL", (order_id,)
        ).fetchone()

    @staticmethod
    def list_processes(order_id, db=None):
        db = resolve_db(db)
        process_name = process_value_sql("op", "process_version", "p")
        rows = db.execute(
            "SELECT op.*," + process_name + " AS process_name FROM order_processes op "
            "JOIN processes p ON p.id = op.process_id "
            + process_version_join("op", "process_version")
            +
            "WHERE op.order_id = ? ORDER BY op.seq_order", (order_id,)
        ).fetchall()
        warn_legacy_fact_rows("order_processes", rows)
        return rows

    @staticmethod
    def count_overdue(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) FROM orders WHERE deadline < DATE('now') "
            "AND status NOT IN ('completed','cancelled') AND deleted_at IS NULL"
        ).fetchone()[0]

    @staticmethod
    def count_near_due(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) FROM orders WHERE deadline BETWEEN DATE('now') "
            "AND DATE('now','+3 days') AND status NOT IN ('completed','cancelled') "
            "AND deleted_at IS NULL"
        ).fetchone()[0]
