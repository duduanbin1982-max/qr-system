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

    @staticmethod
    def list_active_existing_process_ids(process_ids, db=None):
        if not process_ids:
            return []
        db = resolve_db(db)
        normalized = list(dict.fromkeys(int(value) for value in process_ids))
        placeholders = ",".join("?" for _ in normalized)
        return db.execute(
            "SELECT DISTINCT process.id FROM processes process "
            "LEFT JOIN process_versions version "
            "ON version.id=process.current_effective_version_id "
            f"WHERE process.id IN ({placeholders}) AND process.status='active' "
            "AND COALESCE(process.lifecycle_status,'active')='active' "
            "AND (process.current_effective_version_id IS NULL "
            "OR version.status='published') ORDER BY process.id",
            normalized,
        ).fetchall()

    @staticmethod
    def list_historical_position_order_process_ids(position_id, order_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT DISTINCT order_process.process_id FROM orders order_row "
            "JOIN order_processes order_process ON order_process.order_id=order_row.id "
            "JOIN process_versions bound_version "
            "ON bound_version.id=order_process.process_version_id "
            "AND bound_version.process_id=order_process.process_id "
            "WHERE order_row.id=? AND order_row.deleted_at IS NULL "
            "AND order_row.status NOT IN ('completed','cancelled') "
            "AND order_process.process_version_id IS NOT NULL AND ("
            "EXISTS (SELECT 1 FROM position_versions position_version "
            "JOIN position_version_processes version_process "
            "ON version_process.position_version_id=position_version.id "
            "WHERE position_version.position_id=? "
            "AND position_version.status IN ('published','superseded','retired') "
            "AND version_process.process_id=order_process.process_id) OR ("
            "NOT EXISTS (SELECT 1 FROM position_versions existing_version "
            "WHERE existing_version.position_id=?) AND EXISTS ("
            "SELECT 1 FROM position_processes legacy_process "
            "WHERE legacy_process.position_id=? "
            "AND legacy_process.process_id=order_process.process_id))) "
            "ORDER BY order_process.process_id",
            (order_id, position_id, position_id, position_id),
        ).fetchall()
