"""qr-system - UserRepository

All SQL for users, user_processes, user_roles, positions, roles, role_groups tables.
Extracted from user_service.py.
"""
import json
from modules.db_unit_of_work import BaseService
from modules.query_utils import paginate, build_sort_clause


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
        role_summary_cte = (
            "WITH role_summary AS ("
            "SELECT u.id AS user_id, "
            "COALESCE(MAX(CASE WHEN COALESCE(r.code, u.role) = 'worker' THEN 1 ELSE 0 END), 0) AS has_worker_role, "
            "COALESCE(MAX(CASE WHEN COALESCE(r.code, u.role) <> 'worker' THEN 1 ELSE 0 END), 0) AS has_non_worker_role, "
            "COALESCE(MAX(CASE WHEN COALESCE(r.code, u.role) = 'admin' THEN 1 ELSE 0 END), 0) AS has_admin_role, "
            "COUNT(ur.role_id) AS role_count, "
            "COALESCE((SELECT r2.code FROM user_roles ur2 JOIN roles r2 ON ur2.role_id = r2.id "
            "WHERE ur2.user_id = u.id "
            "ORDER BY CASE WHEN r2.code = 'admin' THEN 0 WHEN r2.code <> 'worker' THEN 1 ELSE 2 END, r2.level, r2.id "
            "LIMIT 1), u.role) AS role_code "
            "FROM users u "
            "LEFT JOIN user_roles ur ON ur.user_id = u.id "
            "LEFT JOIN roles r ON ur.role_id = r.id "
            "GROUP BY u.id"
            ") "
        )

        where = ["1=1"]
        params = []
        if role_filter:
            if role_filter == "worker":
                where.append("rs.has_worker_role = 1 AND rs.has_non_worker_role = 0")
            elif role_filter == "admin":
                where.append("rs.has_admin_role = 1")
            else:
                where.append("(rs.role_code = ? OR (rs.role_count = 0 AND u.role = ?))")
                params.extend([role_filter, role_filter])
        if role_not:
            if role_not == "worker":
                where.append("rs.has_non_worker_role = 1")
            else:
                where.append("(rs.role_code != ? AND NOT (rs.role_count = 0 AND u.role = ?))")
                params.extend([role_not, role_not])
        if status:
            where.append("u.status = ?")
            params.append(status)
        if keyword:
            where.append("(u.username LIKE ? OR u.name LIKE ? OR u.nickname LIKE ? OR u.employee_no LIKE ? OR u.phone LIKE ? OR u.marker LIKE ?)")
            kw = "%" + keyword + "%"
            params.extend([kw, kw, kw, kw, kw, kw])

        where_sql = " AND ".join(where)
        count_sql = (
            role_summary_cte
            + "SELECT COUNT(*) "
            + "FROM users u JOIN role_summary rs ON rs.user_id = u.id "
            + "WHERE "
            + where_sql
        )
        total = db.execute(count_sql, params).fetchone()[0]

        base_sql = (
            role_summary_cte
            + "SELECT u.id, u.username, u.name, u.nickname, u.email, u.group_name, u.role, u.employee_no, "
            "u.marker, u.phone, u.process_ids, u.status, u.created_at, "
            "(SELECT GROUP_CONCAT(up2.process_id) FROM user_processes up2 WHERE up2.user_id = u.id) as process_ids_junction, "
            "u.last_active, u.position_id, u.locked_until, "
            "rs.role_code, rs.has_admin_role, rs.has_worker_role, rs.has_non_worker_role, rs.role_count, "
            "COALESCE((SELECT json_group_array(json_object('id', r2.id, 'name', r2.name, 'code', r2.code, 'level', r2.level, 'group_name', rg2.name)) "
            "FROM user_roles ur2 JOIN roles r2 ON ur2.role_id = r2.id "
            "LEFT JOIN role_groups rg2 ON r2.group_id = rg2.id "
            "WHERE ur2.user_id = u.id), '[]') AS role_items "
            "FROM users u JOIN role_summary rs ON rs.user_id = u.id "
            "WHERE " + where_sql + " "
            + build_sort_clause("u.id", {"u.id": "u.id"}, default="u.id")
        )
        paginated_sql, all_params, size, offset = paginate(base_sql, params, page=page, page_size=limit)
        rows = db.execute(paginated_sql, all_params).fetchall()
        users = []
        for row in rows:
            user = dict(row)
            raw_role_items = user.pop("role_items", "[]")
            try:
                parsed_roles = json.loads(raw_role_items or "[]")
                user["roles"] = parsed_roles if isinstance(parsed_roles, list) else []
            except Exception:
                user["roles"] = []
            if "role_code" not in user or not user["role_code"]:
                user["role_code"] = user.get("role") or "worker"
            user["is_worker_user"] = bool(user.get("has_worker_role")) and not bool(user.get("has_non_worker_role"))
            user["is_admin_user"] = bool(user.get("has_admin_role"))
            if not user.get("roles"):
                fallback_role = user.get("role_code") or user.get("role")
                if fallback_role:
                    user["roles"] = [{
                        "code": fallback_role,
                        "name": fallback_role,
                        "id": None,
                    }]
            users.append(user)

        return {
            "users": users,
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
            "SELECT id, username, name, nickname, email, phone, role, employee_no, marker, group_name, position_id, status "
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
    def find_role_code_by_id(role_id, db=None):
        """Find role code by role ID. Returns string or None."""
        db = db or BaseService.db()
        row = db.execute("SELECT code FROM roles WHERE id = ? LIMIT 1", (role_id,)).fetchone()
        return row["code"] if row else None

    @staticmethod
    def check_admin_role(user_id, db=None):
        """Check if user has admin role. Returns row or None."""
        db = db or BaseService.db()
        return db.execute(
            "SELECT 1 FROM user_roles ur JOIN roles r ON ur.role_id = r.id "
            "WHERE ur.user_id = ? AND r.code = 'admin' LIMIT 1",
            (user_id,)
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
        return db.execute(
            "SELECT COUNT(DISTINCT ur.user_id) FROM user_roles ur JOIN roles r ON ur.role_id = r.id WHERE r.code = 'admin'"
        ).fetchone()[0]

    @staticmethod
    def count_admin_roles_excluding(user_id, db=None):
        """Count admin roles excluding a specific user."""
        db = db or BaseService.db()
        return db.execute(
            "SELECT COUNT(DISTINCT ur.user_id) FROM user_roles ur JOIN roles r ON ur.role_id = r.id "
            "WHERE r.code = 'admin' AND ur.user_id != ?",
            (user_id,)
        ).fetchone()[0]

    @staticmethod
    def count_admin_users_excluding(user_id, db=None):
        """Count admin users (by role column) excluding one."""
        db = db or BaseService.db()
        return db.execute(
            "SELECT COUNT(*) FROM users WHERE role = 'admin' AND id != ?",
            (user_id,)
        ).fetchone()[0]

    @staticmethod
    def count_admin_roles_in_ids(ids, db=None):
        """Count how many of the given user IDs have admin role."""
        db = db or BaseService.db()
        placeholders = ",".join("?" for _ in ids)
        return db.execute(
            "SELECT COUNT(DISTINCT ur.user_id) FROM user_roles ur JOIN roles r ON ur.role_id = r.id "
            "WHERE r.code = 'admin' AND ur.user_id IN (" + placeholders + ")",
            ids
        ).fetchone()[0]

    @staticmethod
    def find_role_id_by_code(code, db=None):
        """Find role ID by old role column value. Returns int or None."""
        db = db or BaseService.db()
        row = db.execute("SELECT id FROM roles WHERE code = ? LIMIT 1", (code,)).fetchone()
        return row[0] if row else None

    @staticmethod
    def get_primary_role_code(user_id, db=None):
        """Get the display/primary role code for a user."""
        db = db or BaseService.db()
        row = db.execute(
            "SELECT r.code FROM user_roles ur JOIN roles r ON ur.role_id = r.id "
            "WHERE ur.user_id = ? "
            "ORDER BY CASE WHEN r.code = 'admin' THEN 0 WHEN r.code <> 'worker' THEN 1 ELSE 2 END, r.level, r.id "
            "LIMIT 1",
            (user_id,)
        ).fetchone()
        if row:
            return row["code"]
        row = db.execute("SELECT role FROM users WHERE id = ? LIMIT 1", (user_id,)).fetchone()
        return row["role"] if row else None

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
    def insert_user_txn(username, pw_hash, name, nickname, email, group_name, role, employee_no, marker, phone, position_id, status, db):
        """Insert a new user. Returns lastrowid."""
        cur = db.execute(
            "INSERT INTO users (username, password, name, nickname, email, group_name, "
            "role, employee_no, marker, phone, process_ids, position_id, status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (username, pw_hash, name, nickname, email, group_name, role, employee_no, marker, phone, "", position_id or None, status)
        )
        return cur.lastrowid

    @staticmethod
    def insert_user_import_txn(username, pw_hash, name, nickname, email, role, employee_no, phone, position_id, db):
        """Insert user during bulk import (slightly different column set)."""
        cur = db.execute(
            "INSERT INTO users (username, password, name, nickname, email, group_name, role, employee_no, phone, position_id, status, department_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (username, pw_hash, name, nickname, email, "员工组", role, employee_no, phone, position_id, "active", None)
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
    # User Detail / Documents
    # ============================================================

    @staticmethod
    def get_user_role_names(user_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT r.name FROM user_roles ur JOIN roles r ON ur.role_id = r.id WHERE ur.user_id = ?",
            (user_id,)
        ).fetchall()

    @staticmethod
    def get_user_assigned_processes(user_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT p.id, p.name FROM user_processes up JOIN processes p ON up.process_id = p.id WHERE up.user_id = ?",
            (user_id,)
        ).fetchall()

    @staticmethod
    def get_user_work_stats(user_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT COUNT(*) as total_records, SUM(quantity) as total_quantity FROM work_records WHERE user_id = ? AND status = 'approved'",
            (user_id,)
        ).fetchone()

    @staticmethod
    def list_user_documents(user_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT id, user_id, doc_name, doc_type, file_size, uploaded_by, created_at "
            "FROM employee_documents WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()

    @staticmethod
    def find_user_document(user_id, doc_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT * FROM employee_documents WHERE id = ? AND user_id = ?",
            (doc_id, user_id)
        ).fetchone()

    @staticmethod
    def insert_user_document_txn(user_id, doc_name, doc_type, file_path, file_size, uploaded_by, db):
        db.execute(
            "INSERT INTO employee_documents (user_id, doc_name, doc_type, file_path, file_size, uploaded_by) VALUES (?,?,?,?,?,?)",
            (user_id, doc_name, doc_type, file_path, file_size, uploaded_by)
        )

    @staticmethod
    def delete_user_document_txn(doc_id, db):
        db.execute("DELETE FROM employee_documents WHERE id = ?", (doc_id,))

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
