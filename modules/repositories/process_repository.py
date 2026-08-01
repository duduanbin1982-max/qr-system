"""qr-system - ProcessRepository"""
import sqlite3

from modules.repositories.context import resolve_db
from modules.process_references import PROCESS_REFERENCES


class ProcessRepository:

    @staticmethod
    def list_all(conditions, params, sort_by, sort_dir, limit, offset, db=None):
        db = resolve_db(db)
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
        db = resolve_db(db)
        sql = "SELECT COUNT(*) FROM processes"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        return db.execute(sql, params).fetchone()[0]

    @staticmethod
    def get_category_counts(db=None):
        db = resolve_db(db)
        return {r["category"]: r["cnt"] for r in db.execute(
            "SELECT category, COUNT(*) as cnt FROM processes GROUP BY category"
        ).fetchall()}

    @staticmethod
    def find_by_name(name, db=None):
        db = resolve_db(db)
        return db.execute("SELECT id FROM processes WHERE name = ?", (name,)).fetchone()

    @staticmethod
    def find_by_id(pid, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id, name, category, status FROM processes WHERE id = ?", (pid,)
        ).fetchone()

    @staticmethod
    def find_by_ids(process_ids, db=None):
        db = resolve_db(db)
        normalized_ids = list(dict.fromkeys(int(pid) for pid in process_ids))
        if not normalized_ids:
            return []
        placeholders = ",".join("?" for _ in normalized_ids)
        return db.execute(
            "SELECT id, name, category, status FROM processes WHERE id IN ("
            + placeholders + ")",
            normalized_ids,
        ).fetchall()

    @staticmethod
    def get_max_seq(category, db=None):
        db = resolve_db(db)
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
        db = resolve_db(db)
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
        try:
            db.execute("DELETE FROM processes WHERE id = ?", (pid,))
            return True
        except sqlite3.IntegrityError:
            return False

    @staticmethod
    def count_route_category_conflicts(pid, category, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) FROM process_route_items pri "
            "JOIN process_routes pr ON pr.id = pri.route_id "
            "WHERE pri.process_id = ? AND pr.category != ?",
            (pid, category),
        ).fetchone()[0]

    @staticmethod
    def check_impact(pid, db=None):
        db = resolve_db(db)
        impact = {}
        for reference in PROCESS_REFERENCES:
            table_exists = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (reference.table,),
            ).fetchone()
            if not table_exists:
                continue
            available_columns = {
                row[1] for row in db.execute(f'PRAGMA table_info("{reference.table}")')
            }
            predicates = [
                f'"{column}" = ?'
                for column in reference.columns
                if column in available_columns
            ]
            params = [pid] * len(predicates)
            for column in reference.csv_columns:
                if column not in available_columns:
                    continue
                predicates.append(
                    f"(',' || REPLACE(COALESCE(\"{column}\", ''), ' ', '') || ',') "
                    "LIKE ('%,' || ? || ',%')"
                )
                params.append(pid)
            if not predicates:
                continue
            count = db.execute(
                f'SELECT COUNT(*) FROM "{reference.table}" WHERE '
                + " OR ".join(predicates),
                params,
            ).fetchone()[0]
            if count:
                impact[reference.table] = count
        return impact
