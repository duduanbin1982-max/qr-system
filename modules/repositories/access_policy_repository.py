"""Access policy repository."""
from modules.db_unit_of_work import BaseService


class AccessPolicyRepository:
    @staticmethod
    def get_permission_rows(user_id, db=None):
        db = db or BaseService.db()
        return db.execute("\n            SELECT r.permissions as role_perms, rg.permissions as group_perms\n            FROM user_roles ur\n            JOIN roles r ON ur.role_id = r.id\n            LEFT JOIN role_groups rg ON r.group_id = rg.id\n            WHERE ur.user_id = ? AND r.status = 'active'\n        ", (user_id,)).fetchall()

    @staticmethod
    def list_position_process_ids(position_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT process_id FROM position_processes WHERE position_id = ?",
            (position_id,)
        ).fetchall()

    @staticmethod
    def list_existing_process_ids(process_ids, db=None):
        if not process_ids:
            return []
        db = db or BaseService.db()
        placeholders = ",".join("?" for _ in process_ids)
        return db.execute(
            f"SELECT id FROM processes WHERE id IN ({placeholders})",
            process_ids
        ).fetchall()
