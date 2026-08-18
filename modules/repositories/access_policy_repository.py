"""Access policy repository."""
from modules.repositories.context import resolve_db


class AccessPolicyRepository:
    @staticmethod
    def get_permission_rows(user_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT r.permissions AS role_perms "
            "FROM user_roles ur "
            "JOIN roles r ON ur.role_id = r.id "
            "WHERE ur.user_id = ? AND r.status = 'active'",
            (user_id,),
        ).fetchall()

    @staticmethod
    def list_position_process_ids(position_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT process_id FROM position_processes WHERE position_id = ?",
            (position_id,)
        ).fetchall()

    @staticmethod
    def list_user_process_ids(user_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT p.id FROM user_processes up "
            "JOIN processes p ON p.id = up.process_id "
            "WHERE up.user_id = ?",
            (user_id,)
        ).fetchall()

    @staticmethod
    def list_existing_process_ids(process_ids, db=None):
        if not process_ids:
            return []
        db = resolve_db(db)
        placeholders = ",".join("?" for _ in process_ids)
        return db.execute(
            f"SELECT id FROM processes WHERE id IN ({placeholders})",
            process_ids
        ).fetchall()
