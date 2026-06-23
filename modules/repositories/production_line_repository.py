"""
qr-system - ProductionLineRepository

All SQL for production_lines table.
"""
import sqlite3
from modules.db_unit_of_work import BaseService


class ProductionLineRepository:
    """Production line data access."""

    @staticmethod
    def find_all(db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT * FROM production_lines ORDER BY name"
        ).fetchall()

    @staticmethod
    def find_by_id(line_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT * FROM production_lines WHERE id = ?", (line_id,)
        ).fetchone()

    @staticmethod
    def insert(name, capacity_per_day, remark, db=None):
        db = db or BaseService.db()
        try:
            cur = db.execute(
                "INSERT INTO production_lines (name, capacity_per_day, remark) VALUES (?, ?, ?)",
                (name, capacity_per_day, remark)
            )
            return cur.lastrowid
        except sqlite3.IntegrityError:
            raise ValueError("production line name already exists")

    @staticmethod
    def update(line_id, name, capacity_per_day, remark, status, db=None):
        db = db or BaseService.db()
        existing = db.execute(
            "SELECT id FROM production_lines WHERE id = ?", (line_id,)
        ).fetchone()
        if not existing:
            raise ValueError("production line not found")
        db.execute(
            "UPDATE production_lines SET name=?, capacity_per_day=?, remark=?, status=? WHERE id=?",
            (name, capacity_per_day, remark, status, line_id)
        )

    @staticmethod
    def delete(line_id, db=None):
        db = db or BaseService.db()
        used = db.execute(
            "SELECT COUNT(*) FROM orders WHERE production_line_id = ? AND deleted_at IS NULL",
            (line_id,)
        ).fetchone()[0]
        if used:
            raise ValueError(f"production line in use by {used} orders")
        db.execute("DELETE FROM production_lines WHERE id = ?", (line_id,))
