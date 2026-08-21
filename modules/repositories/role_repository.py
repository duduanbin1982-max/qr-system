"""角色组与角色管理的数据访问层。"""
from modules.repositories.context import resolve_db


class RoleGroupRepository:
    """角色组数据访问。"""

    @staticmethod
    def list_all(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id,name,description,parent_id,status,created_at,updated_at "
            "FROM role_groups ORDER BY id"
        ).fetchall()

    @staticmethod
    def find_by_name(name, db=None):
        db = resolve_db(db)
        return db.execute("SELECT id FROM role_groups WHERE name = ?", (name,)).fetchone()

    @staticmethod
    def find_by_id(gid, db=None):
        db = resolve_db(db)
        return db.execute("SELECT * FROM role_groups WHERE id = ?", (gid,)).fetchone()

    @staticmethod
    def insert_txn(name, description, parent_id, status, permissions, db):
        cur = db.execute(
            "INSERT INTO role_groups (name, description, parent_id, status, permissions) "
            "VALUES (?,?,?,?,?)",
            (name, description, parent_id, status, permissions)
        )
        return cur.lastrowid

    @staticmethod
    def update_txn(sets_clause, params, gid, db):
        db.execute(
            "UPDATE role_groups SET " + sets_clause + " WHERE id = ?",
            params + [gid]
        )

    @staticmethod
    def get_parent_id(gid, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT parent_id FROM role_groups WHERE id=? AND parent_id IS NOT NULL", (gid,)
        ).fetchone()
        return row["parent_id"] if row else None

    @staticmethod
    def count_children(gid, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) FROM role_groups WHERE parent_id = ?", (gid,)
        ).fetchone()[0]

    @staticmethod
    def count_roles_in_group(gid, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) FROM roles WHERE group_id = ?", (gid,)
        ).fetchone()[0]

    @staticmethod
    def delete_txn(gid, db):
        db.execute("DELETE FROM role_groups WHERE id = ?", (gid,))


class RoleRepository:
    """角色数据访问。"""

    @staticmethod
    def list_all(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT r.*, rg.name as group_name, "
            "COALESCE((SELECT json_group_array(a.role_code) FROM role_code_aliases a "
            "WHERE a.role_id = r.id ORDER BY a.id), '[]') AS alias_codes "
            "FROM roles r LEFT JOIN role_groups rg ON r.group_id = rg.id "
            "ORDER BY r.level, r.id"
        ).fetchall()

    @staticmethod
    def list_approval_roles(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id, name, code, group_id, level, status, is_builtin "
            "FROM roles "
            "WHERE status = 'active' AND code <> 'worker' "
            "AND (code = 'admin' OR permissions LIKE '%\"approvals:decision\"%' "
            "OR permissions LIKE '%\"approvals:edit\"%') "
            "ORDER BY CASE WHEN code = 'admin' THEN 0 ELSE 1 END, level, id"
        ).fetchall()

    @staticmethod
    def find_by_code(code, db=None):
        db = resolve_db(db)
        return db.execute("SELECT id FROM roles WHERE code = ?", (code,)).fetchone()

    @staticmethod
    def find_active_by_id(role_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id, name, code, status FROM roles "
            "WHERE id = ? AND status = 'active'",
            (role_id,),
        ).fetchone()

    @staticmethod
    def find_active_by_code(code, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id, name, code, status FROM roles "
            "WHERE code = ? AND status = 'active' "
            "UNION ALL "
            "SELECT r.id, r.name, r.code, r.status FROM role_code_aliases a "
            "JOIN roles r ON r.id = a.role_id "
            "WHERE a.role_code = ? AND r.status = 'active' "
            "ORDER BY id LIMIT 1",
            (code, code),
        ).fetchone()

    @staticmethod
    def find_by_code_or_alias(code, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id, name, code, status FROM roles WHERE code = ? "
            "UNION ALL "
            "SELECT r.id, r.name, r.code, r.status FROM role_code_aliases a "
            "JOIN roles r ON r.id = a.role_id WHERE a.role_code = ? "
            "ORDER BY id LIMIT 1",
            (code, code),
        ).fetchone()

    @staticmethod
    def find_by_id(rid, db=None):
        db = resolve_db(db)
        return db.execute("SELECT * FROM roles WHERE id = ?", (rid,)).fetchone()

    @staticmethod
    def find_by_name_exclude(name, rid, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id FROM roles WHERE name = ? COLLATE NOCASE AND id != ?",
            (name, rid),
        ).fetchone()

    @staticmethod
    def find_by_name(name, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id FROM roles WHERE name = ? COLLATE NOCASE", (name,)
        ).fetchone()

    @staticmethod
    def find_by_code_exclude(code, rid, db=None):
        db = resolve_db(db)
        return db.execute("SELECT id FROM roles WHERE code = ? AND id != ?", (code, rid)).fetchone()

    @staticmethod
    def insert_txn(name, code, description, group_id, parent_id, level, permissions, status, db):
        cur = db.execute(
            "INSERT INTO roles (name, code, description, group_id, parent_id, "
            "level, permissions, status) VALUES (?,?,?,?,?,?,?,?)",
            (name, code, description, group_id, parent_id, level, permissions, status)
        )
        return cur.lastrowid

    @staticmethod
    def update_txn(sets_clause, params, rid, db):
        db.execute(
            "UPDATE roles SET " + sets_clause + " WHERE id = ?",
            params + [rid]
        )

    @staticmethod
    def get_parent_chain(cur_id, db=None):
        """Get parent_id chain for circular reference check."""
        db = resolve_db(db)
        results = db.execute(
            "SELECT parent_id FROM roles WHERE id = ? AND parent_id IS NOT NULL", (cur_id,)
        ).fetchall()
        return [r["parent_id"] for r in results]

    @staticmethod
    def count_user_roles(rid, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) FROM user_roles WHERE role_id = ?", (rid,)
        ).fetchone()[0]

    @staticmethod
    def count_references(rid, old_code=None, db=None):
        """Count durable and legacy references before a role-code change."""
        db = resolve_db(db)
        user_count = db.execute(
            "SELECT COUNT(*) FROM user_roles WHERE role_id = ?", (rid,)
        ).fetchone()[0]
        approval_count = 0
        if db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='approval_config'"
        ).fetchone():
            approval_count = db.execute(
                "SELECT COUNT(*) FROM approval_config WHERE "
                "approver_role_id = ? OR approver_role_2_id = ? OR approver_role_3_id = ?"
                + (" OR approver_role = ? OR approver_role_2 = ? OR approver_role_3 = ?" if old_code else ""),
                (rid, rid, rid, old_code, old_code, old_code) if old_code else (rid, rid, rid),
            ).fetchone()[0]
        legacy_user_count = 0
        if old_code is not None:
            legacy_user_count = db.execute(
                "SELECT COUNT(*) FROM users WHERE role = ?", (old_code,)
            ).fetchone()[0]
        return {
            "user_roles": user_count,
            "approval_configs": approval_count,
            "legacy_users": legacy_user_count,
            "total": user_count + approval_count + legacy_user_count,
        }

    @staticmethod
    def insert_code_alias_txn(role_id, code, reason, changed_by, db):
        db.execute(
            "INSERT OR IGNORE INTO role_code_aliases "
            "(role_id, role_code, reason, changed_by) VALUES (?,?,?,?)",
            (role_id, code, reason, changed_by),
        )

    @staticmethod
    def close_code_alias_txn(role_id, code, db):
        db.execute(
            "UPDATE role_code_aliases SET valid_to = datetime('now','localtime') "
            "WHERE role_id = ? AND role_code = ? AND valid_to IS NULL",
            (role_id, code),
        )

    @staticmethod
    def delete_txn(rid, db):
        db.execute("DELETE FROM roles WHERE id = ?", (rid,))

    @staticmethod
    def group_exists(gid, db=None):
        db = resolve_db(db)
        return db.execute("SELECT id FROM role_groups WHERE id = ?", (gid,)).fetchone()

    @staticmethod
    def role_exists(rid, db=None):
        db = resolve_db(db)
        return db.execute("SELECT id FROM roles WHERE id = ?", (rid,)).fetchone()
