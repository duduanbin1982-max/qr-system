"""qr-system - UserRepository

All SQL for users, user_processes, user_roles, positions, roles, role_groups tables.
Extracted from user_service.py.
"""
import json
from modules.repositories.context import resolve_db
from modules.query_utils import paginate, build_sort_clause


class UserRepository:
    """User data access layer. All methods are static."""

    # ============================================================
    # Process Validation
    # ============================================================
    @staticmethod
    def validate_process_ids(process_ids, db=None):
        """Return set of valid process IDs from the given list."""
        db = resolve_db(db)
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
        db = resolve_db(db)
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
        summary_where_sql = " AND ".join(where)
        summary_params = list(params)
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
        summary_row = db.execute(
            role_summary_cte
            + "SELECT COUNT(*) AS total, "
            + "SUM(CASE WHEN u.status = 'active' THEN 1 ELSE 0 END) AS active, "
            + "SUM(CASE WHEN u.status = 'inactive' THEN 1 ELSE 0 END) AS inactive, "
            + "SUM(CASE WHEN u.status = 'deleted' THEN 1 ELSE 0 END) AS deleted "
            + "FROM users u JOIN role_summary rs ON rs.user_id = u.id WHERE "
            + summary_where_sql,
            summary_params,
        ).fetchone()

        base_sql = (
            role_summary_cte
            + "SELECT u.id, u.username, u.name, u.nickname, u.email, u.group_name, u.role, u.employee_no, "
            "u.marker, u.phone, u.process_ids, u.status, u.created_at, u.purged_at, "
            "(SELECT GROUP_CONCAT(up2.process_id) FROM user_processes up2 WHERE up2.user_id = u.id) as process_ids_junction, "
            "COALESCE((SELECT json_group_array(json_object('id', p2.id, 'name', p2.name, 'source', '员工')) "
            "FROM user_processes up3 JOIN processes p2 ON up3.process_id = p2.id "
            "WHERE up3.user_id = u.id ORDER BY p2.seq_order, p2.id), '[]') AS explicit_process_items, "
            "COALESCE((SELECT json_group_array(json_object('id', p3.id, 'name', p3.name, 'source', '岗位')) "
            "FROM position_processes pp3 JOIN processes p3 ON pp3.process_id = p3.id "
            "WHERE pp3.position_id = u.position_id ORDER BY p3.seq_order, p3.id), '[]') AS position_process_items, "
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
            raw_explicit_process_items = user.pop("explicit_process_items", "[]")
            raw_position_process_items = user.pop("position_process_items", "[]")
            try:
                parsed_roles = json.loads(raw_role_items or "[]")
                user["roles"] = parsed_roles if isinstance(parsed_roles, list) else []
            except Exception:
                user["roles"] = []
            try:
                explicit_process_items = json.loads(raw_explicit_process_items or "[]")
            except Exception:
                explicit_process_items = []
            try:
                position_process_items = json.loads(raw_position_process_items or "[]")
            except Exception:
                position_process_items = []
            process_ids = user.get("process_ids_junction") or user.get("process_ids") or ""
            user["process_ids"] = process_ids or ""
            user["explicit_processes"] = explicit_process_items if isinstance(explicit_process_items, list) else []
            user["position_processes"] = position_process_items if isinstance(position_process_items, list) else []
            merged_processes = []
            seen_process_ids = set()
            for process in user["position_processes"] + user["explicit_processes"]:
                process_id = process.get("id") if isinstance(process, dict) else None
                if process_id in seen_process_ids:
                    continue
                seen_process_ids.add(process_id)
                merged_processes.append(process)
            user["work_processes"] = merged_processes
            user["work_process_names"] = "、".join(
                process.get("name", "") for process in merged_processes if isinstance(process, dict) and process.get("name")
            )
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
            "limit": size,
            "summary": {
                "total": summary_row["total"] or 0,
                "active": summary_row["active"] or 0,
                "inactive": summary_row["inactive"] or 0,
                "deleted": summary_row["deleted"] or 0,
            },
        }

    @staticmethod
    def find_user_by_username(username, db=None):
        """Find user by username. Returns row or None."""
        db = resolve_db(db)
        return db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()

    @staticmethod
    def find_user_by_id_basic(uid, db=None):
        """Find user by ID, returns row with id + username only."""
        db = resolve_db(db)
        return db.execute("SELECT id, username FROM users WHERE id = ?", (uid,)).fetchone()

    @staticmethod
    def find_user_by_id_full(uid, db=None):
        """Find user by ID, returns full row (includes password)."""
        db = resolve_db(db)
        return db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()

    @staticmethod
    def find_user_by_id_for_update(uid, db=None):
        """Find user by ID with selected fields for update comparison."""
        db = resolve_db(db)
        return db.execute(
            "SELECT id, username, name, nickname, email, phone, role, employee_no, marker, group_name, "
            "position_id, department_id, status, purged_at "
            "FROM users WHERE id = ?", (uid,)
        ).fetchone()

    @staticmethod
    def find_users_by_ids_for_update(ids, db=None):
        db = resolve_db(db)
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        return db.execute(
            "SELECT id, username, name, nickname, email, phone, role, employee_no, marker, group_name, "
            "position_id, department_id, status, purged_at FROM users WHERE id IN ("
            + placeholders
            + ") ORDER BY id",
            ids,
        ).fetchall()

    @staticmethod
    def find_user_status(uid, db=None):
        """Find user id + status only."""
        db = resolve_db(db)
        return db.execute("SELECT id, status FROM users WHERE id = ?", (uid,)).fetchone()

    @staticmethod
    def find_deleted_user(uid, db=None):
        """Find soft-deleted user. Returns row or None."""
        db = resolve_db(db)
        return db.execute(
            "SELECT id, username, purged_at FROM users WHERE id = ? AND status = 'deleted'",
            (uid,),
        ).fetchone()

    # ============================================================
    # Role Queries
    # ============================================================

    @staticmethod
    def find_role_by_code(code, db=None):
        """Find role row by code. Returns row or None."""
        db = resolve_db(db)
        return db.execute("SELECT id FROM roles WHERE code = ? LIMIT 1", (code,)).fetchone()

    @staticmethod
    def find_active_role_by_code(code, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id, code FROM roles WHERE code = ? AND status = 'active' LIMIT 1",
            (code,),
        ).fetchone()

    @staticmethod
    def find_active_roles_by_ids(role_ids, db=None):
        db = resolve_db(db)
        if not role_ids:
            return []
        placeholders = ",".join("?" for _ in role_ids)
        return db.execute(
            "SELECT id, code FROM roles WHERE status = 'active' AND id IN ("
            + placeholders
            + ") ORDER BY id",
            role_ids,
        ).fetchall()

    @staticmethod
    def get_user_role_rows(user_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT r.id, r.code FROM user_roles ur "
            "JOIN roles r ON r.id = ur.role_id WHERE ur.user_id = ? ORDER BY r.id",
            (user_id,),
        ).fetchall()

    @staticmethod
    def find_role_code_by_id(role_id, db=None):
        """Find role code by role ID. Returns string or None."""
        db = resolve_db(db)
        row = db.execute("SELECT code FROM roles WHERE id = ? LIMIT 1", (role_id,)).fetchone()
        return row["code"] if row else None

    @staticmethod
    def check_admin_role(user_id, db=None):
        """Check if user has admin role. Returns row or None."""
        db = resolve_db(db)
        return db.execute(
            "SELECT 1 FROM user_roles ur JOIN roles r ON ur.role_id = r.id "
            "JOIN users u ON u.id = ur.user_id "
            "WHERE ur.user_id = ? AND r.code = 'admin' "
            "AND r.status = 'active' AND u.status = 'active' LIMIT 1",
            (user_id,)
        ).fetchone()

    @staticmethod
    def has_admin_assignment(user_id, db=None):
        """Return whether a user is an administrator, including inactive/deleted users."""
        db = resolve_db(db)
        return db.execute(
            "SELECT 1 FROM users u WHERE u.id = ? AND (u.role = 'admin' OR EXISTS ("
            "SELECT 1 FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
            "WHERE ur.user_id = u.id AND r.code = 'admin')) LIMIT 1",
            (user_id,),
        ).fetchone()

    @staticmethod
    def admin_assignment_ids(user_ids, db=None):
        """Return administrator IDs from a target set regardless of account status."""
        db = resolve_db(db)
        if not user_ids:
            return set()
        placeholders = ",".join("?" for _ in user_ids)
        rows = db.execute(
            "SELECT u.id FROM users u WHERE u.id IN (" + placeholders + ") "
            "AND (u.role = 'admin' OR EXISTS ("
            "SELECT 1 FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
            "WHERE ur.user_id = u.id AND r.code = 'admin'))",
            list(user_ids),
        ).fetchall()
        return {row["id"] for row in rows}

    @staticmethod
    def get_role_group_name(role_id, db=None):
        """Get role group name for a role. Returns row or None."""
        db = resolve_db(db)
        return db.execute(
            "SELECT rg.name FROM roles r JOIN role_groups rg ON r.group_id = rg.id WHERE r.id = ?",
            (role_id,)
        ).fetchone()

    @staticmethod
    def count_admin_roles(db=None):
        """Count active users with the administrator role."""
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(DISTINCT ur.user_id) FROM user_roles ur "
            "JOIN roles r ON ur.role_id = r.id "
            "JOIN users u ON u.id = ur.user_id "
            "WHERE r.code = 'admin' AND u.status = 'active'"
        ).fetchone()[0]

    @staticmethod
    def count_admin_roles_excluding(user_id, db=None):
        """Count admin roles excluding a specific user."""
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(DISTINCT ur.user_id) FROM user_roles ur "
            "JOIN roles r ON ur.role_id = r.id "
            "JOIN users u ON u.id = ur.user_id "
            "WHERE r.code = 'admin' AND u.status = 'active' AND ur.user_id != ?",
            (user_id,)
        ).fetchone()[0]

    @staticmethod
    def count_admin_users_excluding(user_id, db=None):
        """Count admin users (by role column) excluding one."""
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) FROM users "
            "WHERE role = 'admin' AND status = 'active' AND id != ?",
            (user_id,)
        ).fetchone()[0]

    @staticmethod
    def count_admin_roles_in_ids(ids, db=None):
        """Count how many of the given user IDs have admin role."""
        db = resolve_db(db)
        placeholders = ",".join("?" for _ in ids)
        return db.execute(
            "SELECT COUNT(DISTINCT ur.user_id) FROM user_roles ur "
            "JOIN roles r ON ur.role_id = r.id "
            "JOIN users u ON u.id = ur.user_id "
            "WHERE r.code = 'admin' AND u.status = 'active' "
            "AND ur.user_id IN (" + placeholders + ")",
            ids
        ).fetchone()[0]

    @staticmethod
    def find_role_id_by_code(code, db=None):
        """Find role ID by old role column value. Returns int or None."""
        db = resolve_db(db)
        row = db.execute("SELECT id FROM roles WHERE code = ? LIMIT 1", (code,)).fetchone()
        return row[0] if row else None

    @staticmethod
    def get_primary_role_code(user_id, db=None):
        """Get the display/primary role code for a user."""
        db = resolve_db(db)
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
        db = resolve_db(db)
        return db.execute("SELECT id FROM positions WHERE id = ?", (position_id,)).fetchone()

    @staticmethod
    def find_department_by_id(department_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id FROM departments WHERE id = ?", (department_id,)
        ).fetchone()

    @staticmethod
    def get_active_positions(db=None):
        """Get all active positions (id, name)."""
        db = resolve_db(db)
        return db.execute("SELECT id, name FROM positions WHERE status='active'").fetchall()

    # ============================================================
    # Employee Number Helpers
    # ============================================================

    @staticmethod
    def get_next_employee_no(db=None):
        """Get next auto-generated employee number."""
        db = resolve_db(db)
        last = db.execute(
            "SELECT MAX(CAST(employee_no AS INTEGER)) as max_no FROM users WHERE employee_no GLOB '[0-9]*'"
        ).fetchone()
        return (last["max_no"] or 0) + 1

    @staticmethod
    def check_employee_no_exists(employee_no, db=None):
        """Check if an employee_no already exists."""
        db = resolve_db(db)
        return UserRepository.find_user_by_employee_no(employee_no, db=db) is not None

    @staticmethod
    def find_user_by_employee_no(employee_no, exclude_user_id=None, db=None):
        db = resolve_db(db)
        normalized = str(employee_no or "").strip()
        if not normalized:
            return None
        sql = (
            "SELECT id, username, employee_no FROM users "
            "WHERE lower(trim(employee_no)) = lower(?)"
        )
        params = [normalized]
        if exclude_user_id is not None:
            sql += " AND id != ?"
            params.append(exclude_user_id)
        sql += " LIMIT 1"
        return db.execute(sql, params).fetchone()

    # ============================================================
    # Transaction: User CRUD
    # ============================================================

    @staticmethod
    def insert_user_txn(username, pw_hash, name, nickname, email, group_name, role, employee_no, marker, phone, position_id, department_id, status, db):
        """Insert a new user. Returns lastrowid."""
        cur = db.execute(
            "INSERT INTO users (username, password, name, nickname, email, group_name, "
            "role, employee_no, marker, phone, process_ids, position_id, department_id, status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (username, pw_hash, name, nickname, email, group_name, role, employee_no, marker, phone, "", position_id or None, department_id or None, status)
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
    def replace_user_roles_txn(user_id, role_ids, db):
        db.execute("DELETE FROM user_roles WHERE user_id = ?", (user_id,))
        for role_id in role_ids:
            db.execute(
                "INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)",
                (user_id, role_id),
            )

    @staticmethod
    def add_user_roles_txn(user_id, role_ids, db):
        for role_id in role_ids:
            db.execute(
                "INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)",
                (user_id, role_id),
            )

    @staticmethod
    def remove_user_roles_txn(user_id, role_ids, db):
        if not role_ids:
            return
        placeholders = ",".join("?" for _ in role_ids)
        db.execute(
            "DELETE FROM user_roles WHERE user_id = ? AND role_id IN ("
            + placeholders
            + ")",
            [user_id] + list(role_ids),
        )

    @staticmethod
    def update_user_base_role_txn(user_id, role_code, db):
        db.execute("UPDATE users SET role = ? WHERE id = ?", (role_code, user_id))

    @staticmethod
    def soft_delete_user_txn(uid, db):
        """Soft-delete a user: set status='deleted' with timestamp."""
        db.execute(
            "UPDATE users SET status = 'deleted', token = NULL, "
            "deleted_at = datetime('now','localtime') WHERE id = ?",
            (uid,)
        )
        db.execute("DELETE FROM user_sessions WHERE user_id = ?", (uid,))

    @staticmethod
    def restore_user_txn(uid, db):
        """Restore a soft-deleted user."""
        db.execute("UPDATE users SET status = 'active', deleted_at = NULL WHERE id = ?", (uid,))

    @staticmethod
    def batch_soft_delete_users_txn(ids, db):
        """Soft-delete multiple users. Returns rowcount."""
        placeholders = ",".join("?" for _ in ids)
        cur = db.execute(
            "UPDATE users SET status = 'deleted', token = NULL, "
            "deleted_at = datetime('now','localtime') WHERE id IN (" + placeholders + ")",
            ids
        )
        db.execute(
            "DELETE FROM user_sessions WHERE user_id IN (" + placeholders + ")",
            ids,
        )
        return cur.rowcount

    @staticmethod
    def batch_update_status_txn(ids, status, db):
        """Batch update user status (active/inactive). Returns rowcount."""
        placeholders = ",".join("?" for _ in ids)
        cur = db.execute(
            "UPDATE users SET status = ?, "
            "token = CASE WHEN ? = 'inactive' THEN NULL ELSE token END "
            "WHERE id IN (" + placeholders + ") AND status IN ('active','inactive')",
            [status, status] + ids
        )
        if status == "inactive":
            db.execute(
                "DELETE FROM user_sessions WHERE user_id IN (" + placeholders + ")",
                ids,
            )
        return cur.rowcount

    # ============================================================
    # Transaction: Identity Purge
    # ============================================================

    @staticmethod
    def anonymize_deleted_user_txn(uid, actor_id, reason, password_hash, db):
        """Revoke access and redact identity while preserving ledger and audit history."""
        db.execute("DELETE FROM user_sessions WHERE user_id = ?", (uid,))
        db.execute("DELETE FROM user_processes WHERE user_id = ?", (uid,))
        db.execute("DELETE FROM user_roles WHERE user_id = ?", (uid,))
        db.execute(
            "UPDATE users SET username = ?, password = ?, name = ?, nickname = '', "
            "email = '', phone = '', employee_no = NULL, marker = '', group_name = '', "
            "process_ids = '', role = 'worker', token = NULL, failed_login_count = 0, "
            "locked_until = NULL, purged_at = datetime('now','localtime'), "
            "purged_by = ?, purge_reason = ? WHERE id = ?",
            (
                "purged_user_" + str(uid),
                password_hash,
                "已删除员工#" + str(uid),
                actor_id,
                reason,
                uid,
            ),
        )


    # ============================================================
    # User Detail / Documents
    # ============================================================

    @staticmethod
    def get_user_role_names(user_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT r.name FROM user_roles ur JOIN roles r ON ur.role_id = r.id WHERE ur.user_id = ?",
            (user_id,)
        ).fetchall()

    @staticmethod
    def get_user_assigned_processes(user_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT p.id, p.name FROM user_processes up JOIN processes p ON up.process_id = p.id WHERE up.user_id = ?",
            (user_id,)
        ).fetchall()

    @staticmethod
    def get_user_work_stats(user_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) as total_records, SUM(quantity) as total_quantity FROM work_records WHERE user_id = ? AND status = 'approved'",
            (user_id,)
        ).fetchone()

    @staticmethod
    def list_user_documents(user_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id, user_id, doc_name, doc_type, file_size, uploaded_by, created_at "
            "FROM employee_documents WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()

    @staticmethod
    def find_user_document(user_id, doc_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM employee_documents WHERE id = ? AND user_id = ?",
            (doc_id, user_id)
        ).fetchone()

    @staticmethod
    def insert_user_document_txn(user_id, doc_name, doc_type, file_path, file_size, uploaded_by, db):
        cursor = db.execute(
            "INSERT INTO employee_documents (user_id, doc_name, doc_type, file_path, file_size, uploaded_by) VALUES (?,?,?,?,?,?)",
            (user_id, doc_name, doc_type, file_path, file_size, uploaded_by)
        )
        return cursor.lastrowid

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
