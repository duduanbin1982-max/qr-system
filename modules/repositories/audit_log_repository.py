"""qr-system - AuditLogRepository

All SQL for audit_logs, user_roles, menu_permissions tables.
"""
from modules.db_unit_of_work import BaseService


class AuditLogRepository:
    """Audit log + user roles + menu permissions data access."""

    # ============================================================
    # Operation Logs
    # ============================================================
    @staticmethod
    def list_logs(page=1, limit=50, action="", keyword="", user_id=None, category="", date_from="", date_to="", db=None):
        db = db or BaseService.db()
        where = ["1=1"]
        params = []
        if action:
            where.append("al.action = ?"); params.append(action)
        if keyword:
            where.append("(al.detail LIKE ? OR al.target_type LIKE ?)")
            params.extend(["%" + keyword + "%", "%" + keyword + "%"])
        if user_id:
            where.append("al.user_id = ?"); params.append(user_id)
        if category == "permission":
            where.append("al.action IN ('set_user_roles','create_role','update_role','delete_role',"
                "'create_menu_permission','update_menu_permission','delete_menu_permission',"
                "'batch_set_roles','save_permissions','batch_update_menu_permissions',"
                "'reset_password','unlock_user','save_settings')")
        if date_from:
            where.append("al.created_at >= ?"); params.append(date_from)
        if date_to:
            where.append("al.created_at <= ?"); params.append(date_to + " 23:59:59")
        where_sql = " AND ".join(where)

        total = db.execute(
            "SELECT COUNT(*) FROM audit_logs al WHERE " + where_sql, params
        ).fetchone()[0]
        rows = db.execute(
            "SELECT al.*, u.name as user_name "
            "FROM audit_logs al LEFT JOIN users u ON al.user_id = u.id "
            "WHERE " + where_sql + " "
            "ORDER BY al.created_at DESC LIMIT ? OFFSET ?",
            params + [limit, (page - 1) * limit]
        ).fetchall()
        return {"logs": [dict(r) for r in rows], "total": total}

    # ============================================================
    # User Roles
    # ============================================================
    @staticmethod
    def get_user_roles(uid, db=None):
        db = db or BaseService.db()
        rows = db.execute(
            "SELECT r.*, rg.name as group_name "
            "FROM user_roles ur "
            "JOIN roles r ON ur.role_id = r.id "
            "LEFT JOIN role_groups rg ON r.group_id = rg.id "
            "WHERE ur.user_id = ? "
            "ORDER BY r.level, r.id",
            (uid,)
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def set_user_roles_txn(uid, role_ids, db):
        db.execute("DELETE FROM user_roles WHERE user_id = ?", (uid,))
        for rid in role_ids:
            db.execute("INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)", (uid, rid))

    @staticmethod
    def validate_role_ids(role_ids, db=None):
        db = db or BaseService.db()
        placeholders = ",".join("?" for _ in role_ids)
        valid = {r[0] for r in db.execute(
            "SELECT id FROM roles WHERE id IN (" + placeholders + ")", role_ids
        ).fetchall()}
        invalid = [str(rid) for rid in role_ids if rid not in valid]
        return valid, invalid

    @staticmethod
    def batch_set_roles_txn(user_ids, role_ids, action, db):
        for uid in user_ids:
            if action == "set":
                db.execute("DELETE FROM user_roles WHERE user_id = ?", (uid,))
                for rid in role_ids:
                    db.execute("INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)", (uid, rid))
            elif action == "add":
                for rid in role_ids:
                    db.execute("INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)", (uid, rid))
            elif action == "remove":
                for rid in role_ids:
                    db.execute("DELETE FROM user_roles WHERE user_id = ? AND role_id = ?", (uid, rid))

    # ============================================================
    # Permission Matrix
    # ============================================================
    @staticmethod
    def get_active_users(db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT id, username, name, nickname, role, status FROM users WHERE status='active' ORDER BY id"
        ).fetchall()

    @staticmethod
    def get_user_role_mappings(db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT ur.user_id, ur.role_id, r.name as role_name, r.code as role_code, "
            "r.permissions, r.status as role_status "
            "FROM user_roles ur JOIN roles r ON ur.role_id = r.id ORDER BY r.level"
        ).fetchall()

    @staticmethod
    def get_all_roles(db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT id, name, code, permissions, status, level FROM roles ORDER BY level"
        ).fetchall()

    # ============================================================
    # Menu Permissions CRUD
    # ============================================================
    @staticmethod
    def list_menu_permissions(db=None):
        db = db or BaseService.db()
        rows = db.execute(
            "SELECT * FROM menu_permissions ORDER BY sort_order ASC, id ASC"
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def find_menu_by_page(page, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT id FROM menu_permissions WHERE page = ?", (page,)
        ).fetchone()

    @staticmethod
    def insert_menu_permission_txn(page, permission, label, icon, sort_order, db):
        db.execute(
            "INSERT INTO menu_permissions (page, permission, label, icon, sort_order) VALUES (?,?,?,?,?)",
            (page, permission, label, (icon or "")[:20], sort_order)
        )

    @staticmethod
    def update_menu_permission_txn(page, set_clause, values, db):
        db.execute("UPDATE menu_permissions SET " + set_clause + " WHERE page = ?", values)

    @staticmethod
    def delete_menu_permission_txn(page, db):
        db.execute("DELETE FROM menu_permissions WHERE page = ?", (page,))

    @staticmethod
    def batch_update_menu_permissions_txn(items, db):
        for item in items:
            page = item.get("page", "").strip()
            if not page:
                continue
            permission = item.get("permission", "")
            label = item.get("label", "")
            icon = (item.get("icon", "") or "")[:20]
            sort_order = item.get("sort_order")
            if sort_order is not None:
                db.execute(
                    "UPDATE menu_permissions SET permission=?, label=?, icon=?, sort_order=? WHERE page=?",
                    (permission, label, icon, int(sort_order), page))
            else:
                db.execute(
                    "UPDATE menu_permissions SET permission=?, label=?, icon=? WHERE page=?",
                    (permission, label, icon, page))

    # ============================================================
    # Cleanup
    # ============================================================
    @staticmethod
    def clear_logs_txn(before_days, db):
        cur = db.execute(
            "DELETE FROM audit_logs WHERE created_at < datetime('now','localtime','-' || ? || ' days')",
            (str(before_days),)
        )
        return cur.rowcount
