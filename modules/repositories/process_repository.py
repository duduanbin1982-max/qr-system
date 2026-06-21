"""qr-system - ProcessRepository"""
from modules.services import BaseService


class ProcessRepository:

    @staticmethod
    def list_all(conditions, params, sort_by, sort_dir, limit, offset, db=None):
        db = db or BaseService.db()
        sql = ("SELECT id, name AS process_name, description, category, "
               "seq_order, status, created_at FROM processes")
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY " + sort_by + " " + sort_dir + ", id " + sort_dir
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params = params + [limit, offset]
        return db.execute(sql, params).fetchall()

    @staticmethod
    def count_all(conditions, params, db=None):
        db = db or BaseService.db()
        sql = "SELECT COUNT(*) FROM processes"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        return db.execute(sql, params).fetchone()[0]

    @staticmethod
    def get_category_counts(db=None):
        db = db or BaseService.db()
        return {r["category"]: r["cnt"] for r in db.execute(
            "SELECT category, COUNT(*) as cnt FROM processes GROUP BY category"
        ).fetchall()}

    @staticmethod
    def find_by_name(name, db=None):
        db = db or BaseService.db()
        return db.execute("SELECT id FROM processes WHERE name = ?", (name,)).fetchone()

    @staticmethod
    def find_by_id(pid, db=None):
        db = db or BaseService.db()
        return db.execute("SELECT id, name FROM processes WHERE id = ?", (pid,)).fetchone()

    @staticmethod
    def get_max_seq(category, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT COALESCE(MAX(seq_order),0) FROM processes WHERE category = ?",
            (category,)
        ).fetchone()[0]

    @staticmethod
    def insert_txn(name, description, category, seq_order, status, db):
        cur = db.execute(
            "INSERT INTO processes (name, description, category, seq_order, status, updated_at) "
            "VALUES (?,?,?,?,?, datetime('now','localtime'))",
            (name, description, category, seq_order, status)
        )
        return cur.lastrowid

    @staticmethod
    def find_duplicate_name(name, exclude_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT id FROM processes WHERE name = ? AND id != ?", (name, exclude_id)
        ).fetchone()

    @staticmethod
    def update_txn(set_clause, params, pid, db):
        db.execute(
            "UPDATE processes SET " + set_clause + " WHERE id = ?",
            params + [pid]
        )

    @staticmethod
    def delete_txn(pid, db):
        db.execute("DELETE FROM processes WHERE id = ?", (pid,))

    @staticmethod
    def check_impact(pid, tables, db=None):
        db = db or BaseService.db()
        parts = [
            "SELECT '" + t + "' as tbl, COUNT(*) as cnt FROM " + t + " WHERE process_id = ?"
            for t in tables
        ]
        union_sql = " UNION ALL ".join(parts)
        rows = db.execute(union_sql, [pid] * len(tables)).fetchall()
        return {r["tbl"]: r["cnt"] for r in rows if r["cnt"] > 0}
