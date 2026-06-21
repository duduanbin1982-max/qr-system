"""qr-system - UserRepository

All SQL for users, user_processes, user_roles, positions, roles, role_groups tables.
Extracted from user_service.py.
"""
from modules.services import BaseService
from modules.services.query_utils import paginate, build_sort_clause


class UserRepository:
    """User data access layer. All methods are static."""

    # ============================================================
    # Process Validation
    # ============================================================
    @staticmethod
    def validate_process_ids(process_ids, db=None):
        """Return set of valid process IDs from the given list."""
        db = db or BaseService.db()
        if not process_ids:
            return set()
        placeholders = ",".join("?" for _ in process_ids)
        rows = db.execute(
            "SELECT id FROM processes WHERE id IN (" + placeholders + ")",
            process_ids
        ).fetchall()
        return set(row["id"] for row in rows)

    # ============================================================
    # User Queries
    # ============================================================

    @staticmethod
    def list_users(page=1, limit=20, role_filter="", role_not="", keyword="", status="", db=None):
        """Paginated user list with filters. Returns {users, total, page, limit}."""
        db = db or BaseService.db()
        where = ["1=1"]
        params = []
        if role_filter:
            where.append("u.role = ?")
            params.append(role_filter)
        if role_not:
            where.append("u.role != ?")
            params.append(role_not)
        if role_filter != 'admin' and not role_not:
            where.append("u.username != 'admin'")
        if status:
            where.append("u.status = ?")
            params.append(status)
        if keyword:
            where.append("(u.username LIKE ? OR u.name LIKE ? OR u.nickname LIKE ? OR u.employee_no LIKE ? OR u.phone LIKE ?)")
            kw = "%" + keyword + "%"
            params.extend([kw, kw, kw, kw, kw])

        where_sql = " AND ".join(where)
        total = db.execute(
            "SELECT COUNT(*) FROM users u WHERE " + where_sql, params
        ).fetchone()[0]

        base_sql = (
            "SELECT u.id, u.username, u.name, u.nickname, u.email, u.group_name, u.role, u.employee_no, "
            "u.phone, u.process_ids, u.status, u.created_at, "
            "(SELECT GROUP_CONCAT(up2.process_id) FROM user_processes up2 WHERE up2.user_id = u.id) as process_ids_junction, "
            "u.last_active, u.position_id, u.locked_until, "
            "(SELECT r.code FROM user_roles ur2 JOIN roles r ON ur2.role_id = r.id WHERE ur2.user_id = u.id ORDER BY r.level LIMIT 1) as role_code, "
            "(SELECT COUNT(*) FROM user_roles ur2 WHERE ur2.user_id = u.id AND ur2.role_id = 1) > 0 as has_admin_role "
            "FROM users u WHERE " + where_sql + " "
            + build_sort_clause("u.id", {"u.id": "u.id"}, default="u.id")
        )
        paginated_sql, all_params, size, offset = paginate(base_sql, params, page=page, page_size=limit)
        rows = db.execute(paginated_sql, all_params).fetchall()

        return {
            "users": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "limit": size
        }

    @staticmethod
    def find_user_by_username(username, db=None):
        """Find user by username. Returns row or None."""
        db = db or BaseService.db()
        return db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()

    @staticmethod
    def find_user_by_id_basic(uid, db=None):
        """Find user by ID, returns row with id + username only."""
        db = db or BaseService.db()
        return db.execute("SELECT id, username FROM users WHERE id = ?", (uid,)).fetchone()

    @staticmethod
    def find_user_by_id_full(uid, db=None):
        """Find user by ID, returns full row (includes password)."""
        db = db or BaseService.db()
        return db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()

    @staticmethod
    def find_user_by_id_for_update(uid, db=None):
        """Find user by ID with selected fields for update comparison."""
        db = db or BaseService.db()
        return db.execute(
            "SELECT id, username, name, nickname, email, phone, role, employee_no, group_name, position_id, status "
            "FROM users WHERE id = ?", (uid,)
        ).fetchone()

    @staticmethod
    def find_user_status(uid, db=None):
        """Find user id + status only."""
        db = db or BaseService.db()
        return db.execute("SELECT id, status FROM users WHERE id = ?", (uid,)).fetchone()

    @staticmethod
    def find_deleted_user(uid, db=None):
        """Find soft-deleted user. Returns row or None."""
        db = db or BaseService.db()
        return db.execute(
            "SELECT id, username FROM users WHERE id = ? AND status = 'deleted'", (uid,)
        ).fetchone()

    # ============================================================
    # Role Queries
    # ============================================================

    @staticmethod
    def find_role_by_code(code, db=None):
        """Find role row by code. Returns row or None."""
        db = db or BaseService.db()
        return db.execute("SELECT id FROM roles WHERE code = ? LIMIT 1", (code,)).fetchone()

    @staticmethod
    def check_admin_role(user_id, db=None):
        """Check if user has admin role (role_id=1). Returns row or None."""
        db = db or BaseService.db()
        return db.execute(
            "SELECT 1 FROM user_roles WHERE user_id = ? AND role_id = 1", (user_id,)
        ).fetchone()

    @staticmethod
    def get_role_group_name(role_id, db=None):
        """Get role group name for a role. Returns row or None."""
        db = db or BaseService.db()
        return db.execute(
            "SELECT rg.name FROM roles r JOIN role_groups rg ON r.group_id = rg.id WHERE r.id = ?",
            (role_id,)
        ).fetchone()

    @staticmethod
    def count_admin_roles(db=None):
        """Count total users with admin role."""
        db = db or BaseService.db()
        return db.execute("SELECT COUNT(*) FROM user_roles WHERE role_id = 1").fetchone()[0]

    @staticmethod
    def count_admin_roles_excluding(user_id, db=None):
        """Count admin roles excluding a specific user."""
        db = db or BaseService.db()
        return db.execute(
            "SELECT COUNT(*) FROM user_roles WHERE role_id = 1 AND user_id != ?", (user_id,)
        ).fetchone()[0]

    @staticmethod
    def count_admin_users_excluding(user_id, db=None):
        """Count admin users (by role column) excluding one."""
        db = db or BaseService.db()
        return db.execute(
            "SELECT COUNT(*) FROM users WHERE role = 'admin' AND id != ?", (user_id,)
        ).fetchone()[0]

    @staticmethod
    def count_admin_roles_in_ids(ids, db=None):
        """Count how many of the given user IDs have admin role."""
        db = db or BaseService.db()
        placeholders = ",".join("?" for _ in ids)
        return db.execute(
            "SELECT COUNT(*) FROM user_roles WHERE role_id = 1 AND user_id IN (" + placeholders + ")",
            ids
        ).fetchone()[0]

    @staticmethod
    def find_role_id_by_code(code, db=None):
        """Find role ID by old role column value. Returns int or None."""
        db = db or BaseService.db()
        row = db.execute("SELECT id FROM roles WHERE code = ? LIMIT 1", (code,)).fetchone()
        return row[0] if row else None

    # ============================================================
    # Position Queries
    # ============================================================

    @staticmethod
    def find_position_by_id(position_id, db=None):
        """Find position by ID. Returns row or None."""
        db = db or BaseService.db()
        return db.execute("SELECT id FROM positions WHERE id = ?", (position_id,)).fetchone()

    @staticmethod
    def get_active_positions(db=None):
        """Get all active positions (id, name)."""
        db = db or BaseService.db()
        return db.execute("SELECT id, name FROM positions WHERE status='active'").fetchall()

    # ============================================================
    # Employee Number Helpers
    # ============================================================

    @staticmethod
    def get_next_employee_no(db=None):
        """Get next auto-generated employee number."""
        db = db or BaseService.db()
        last = db.execute(
            "SELECT MAX(CAST(employee_no AS INTEGER)) as max_no FROM users WHERE employee_no GLOB '[0-9]*'"
        ).fetchone()
        return (last["max_no"] or 0) + 1

    @staticmethod
    def check_employee_no_exists(employee_no, db=None):
        """Check if an employee_no already exists."""
        db = db or BaseService.db()
        return db.execute("SELECT 1 FROM users WHERE employee_no = ?", (employee_no,)).fetchone() is not None

    # ============================================================
    # Transaction: User CRUD
    # ============================================================

    @staticmethod
    def insert_user_txn(username, pw_hash, name, nickname, email, group_name, role, employee_no, phone, position_id, status, db):
        """Insert a new user. Returns lastrowid."""
        cur = db.execute(
            "INSERT INTO users (username, password, name, nickname, email, group_name, "
            "role, employee_no, phone, process_ids, position_id, status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (username, pw_hash, name, nickname, email, group_name, role, employee_no, phone, "", position_id or None, status)
        )
        return cur.lastrowid

    @staticmethod
    def insert_user_import_txn(username, pw_hash, name, nickname, email, role, employee_no, phone, position_id, db):
        """Insert user during bulk import (slightly different column set)."""
        cur = db.execute(
            "INSERT INTO users (username, password, name, nickname, email, group_name, role, employee_no, phone, position_id, status, department_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (username, pw_hash, name, nickname, email, "???", role, employee_no, phone, position_id, "active")
        )
        return cur.lastrowid

    @staticmethod
    def insert_user_role_txn(user_id, role_id, db):
        """Insert or ignore a user-role mapping."""
        db.execute("INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)", (user_id, role_id))

    @staticmethod
    def insert_user_process_txn(user_id, process_id, db):
        """Insert or ignore a user-process mapping."""
        db.execute("INSERT OR IGNORE INTO user_processes (user_id, process_id) VALUES (?, ?)", (user_id, process_id))

    @staticmethod
    def delete_user_processes_txn(user_id, db):
        """Delete all process assignments for a user."""
        db.execute("DELETE FROM user_processes WHERE user_id = ?", (user_id,))

    @staticmethod
    def update_user_txn(uid, set_clause, params, db):
        """Update user fields dynamically. set_clause is comma-separated 'field = ?, ...'."""
        db.execute("UPDATE users SET " + set_clause + " WHERE id = ?", params + [uid])

    @staticmethod
    def delete_user_role_txn(user_id, role_id, db):
        """Delete a specific user-role mapping."""
        db.execute("DELETE FROM user_roles WHERE user_id = ? AND role_id = ?", (user_id, role_id))

    @staticmethod
    def soft_delete_user_txn(uid, db):
        """Soft-delete a user: set status='deleted' with timestamp."""
        db.execute(
            "UPDATE users SET status = 'deleted', deleted_at = datetime('now','localtime') WHERE id = ?",
            (uid,)
        )

    @staticmethod
    def restore_user_txn(uid, db):
        """Restore a soft-deleted user."""
        db.execute("UPDATE users SET status = 'active', deleted_at = NULL WHERE id = ?", (uid,))

    @staticmethod
    def batch_soft_delete_users_txn(ids, db):
        """Soft-delete multiple users. Returns rowcount."""
        placeholders = ",".join("?" for _ in ids)
        cur = db.execute(
            "UPDATE users SET status = 'deleted', deleted_at = datetime('now','localtime') WHERE id IN (" + placeholders + ")",
            ids
        )
        return cur.rowcount

    @staticmethod
    def batch_update_status_txn(ids, status, db):
        """Batch update user status (active/inactive). Returns rowcount."""
        placeholders = ",".join("?" for _ in ids)
        cur = db.execute(
            "UPDATE users SET status = ? WHERE id IN (" + placeholders + ") AND status IN ('active','inactive')",
            [status] + ids
        )
        return cur.rowcount

    # ============================================================
    # Transaction: Permanent Delete Cascade
    # ============================================================

    @staticmethod
    def permanent_delete_cascade_txn(uid, db):
        """Delete all user data across all related tables, then the user."""
        db.execute("DELETE FROM user_sessions WHERE user_id = ?", (uid,))
        db.execute("DELETE FROM login_logs WHERE user_id = ?", (uid,))
        db.execute("DELETE FROM user_processes WHERE user_id = ?", (uid,))
        db.execute("DELETE FROM user_roles WHERE user_id = ?", (uid,))
        db.execute("DELETE FROM audit_logs WHERE user_id = ?", (uid,))
        db.execute("DELETE FROM audit_logs WHERE target_id = ? AND target_type = ?", (uid, "user"))
        db.execute("DELETE FROM order_remark_history WHERE user_id = ?", (uid,))
        db.execute("DELETE FROM wage_snapshots WHERE employee_id = ?", (uid,))
        db.execute("DELETE FROM wage_adjustments WHERE user_id = ?", (uid,))
        db.execute("DELETE FROM users WHERE id = ?", (uid,))

    # ============================================================
    # Transaction: Password & Account
    # ============================================================

    @staticmethod
    def reset_password_txn(uid, hashed_pw, db):
        """Reset password, clear lockout and force change flag."""
        db.execute(
            "UPDATE users SET password = ?, password_version = 2, "
            "must_change_password = 1, locked_until = NULL, "
            "failed_login_count = 0 WHERE id = ?",
            (hashed_pw, uid)
        )

    @staticmethod
    def unlock_user_txn(uid, db):
        """Clear brute-force lockout counters."""
        db.execute("UPDATE users SET failed_login_count = 0, locked_until = NULL WHERE id = ?", (uid,))

    # ============================================================
    # Transaction: Audit Log
    # ============================================================

    @staticmethod
    def insert_audit_log_txn(user_id, action, target_type, target_id, detail, db):
        """Insert an audit log entry."""
        db.execute(
            "INSERT INTO audit_logs (user_id, action, target_type, target_id, detail) VALUES (?,?,?,?,?)",
            (user_id, action, target_type, target_id, detail)
        )
