"""Department repository."""
from modules.db_unit_of_work import BaseService


class DepartmentRepository:
    @staticmethod
    def list_active(db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT id, name, description, parent_id, sort_order, status, created_at "
            "FROM departments WHERE status='active' ORDER BY sort_order"
        ).fetchall()

    @staticmethod
    def find_by_id(dep_id, db=None):
        db = db or BaseService.db()
        return db.execute("SELECT id FROM departments WHERE id = ?", (dep_id,)).fetchone()

    @staticmethod
    def find_active_by_id(dep_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT id FROM departments WHERE id = ? AND status='active'", (dep_id,)
        ).fetchone()

    @staticmethod
    def find_by_name(name, db=None):
        db = db or BaseService.db()
        return db.execute("SELECT id FROM departments WHERE name = ?", (name,)).fetchone()

    @staticmethod
    def insert_txn(name, description, parent_id, sort_order, db):
        db.execute(
            "INSERT INTO departments (name, description, parent_id, sort_order) VALUES (?,?,?,?)",
            (name, description, parent_id, sort_order),
        )

    @staticmethod
    def update_txn(dep_id, fields, db):
        sets = []
        params = []
        for field in ["name", "description", "parent_id", "sort_order", "status"]:
            if field in fields:
                sets.append(field + " = ?")
                params.append(fields[field])
        if not sets:
            return False
        db.execute("UPDATE departments SET " + ", ".join(sets) + " WHERE id = ?", params + [dep_id])
        return True

    @staticmethod
    def soft_delete_txn(dep_id, db):
        db.execute("UPDATE departments SET status = 'inactive' WHERE id = ?", (dep_id,))
