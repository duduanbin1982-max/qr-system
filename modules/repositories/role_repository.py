"""qr-system — RoleRepository（角色组 + 角色管理数据访问层）"""
from modules.db_unit_of_work import BaseService


class RoleGroupRepository:
    """角色组数据访问。"""

    @staticmethod
    def list_all(db=None):
        db = db or BaseService.db()
        return db.execute("SELECT * FROM role_groups ORDER BY id").fetchall()

    @staticmethod
    def find_by_name(name, db=None):
        db = db or BaseService.db()
        return db.execute("SELECT id FROM role_groups WHERE name = ?", (name,)).fetchone()

    @staticmethod
    def find_by_id(gid, db=None):
        db = db or BaseService.db()
        return db.execute("SELECT id, name FROM role_groups WHERE id = ?", (gid,)).fetchone()

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
        db = db or BaseService.db()
        row = db.execute(
            "SELECT parent_id FROM role_groups WHERE id=? AND parent_id IS NOT NULL", (gid,)
        ).fetchone()
        return row["parent_id"] if row else None

    @staticmethod
    def count_children(gid, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT COUNT(*) FROM role_groups WHERE parent_id = ?", (gid,)
        ).fetchone()[0]

    @staticmethod
    def count_roles_in_group(gid, db=None):
        db = db or BaseService.db()
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
        db = db or BaseService.db()
        return db.execute(
            "SELECT r.*, rg.name as group_name "
            "FROM roles r LEFT JOIN role_groups rg ON r.group_id = rg.id "
            "ORDER BY r.level, r.id"
        ).fetchall()

    @staticmethod
    def find_by_code(code, db=None):
        db = db or BaseService.db()
        return db.execute("SELECT id FROM roles WHERE code = ?", (code,)).fetchone()

    @staticmethod
    def find_by_id(rid, db=None):
        db = db or BaseService.db()
        return db.execute("SELECT id, name, is_builtin FROM roles WHERE id = ?", (rid,)).fetchone()

    @staticmethod
    def find_by_name_exclude(name, rid, db=None):
        db = db or BaseService.db()
        return db.execute("SELECT id FROM roles WHERE name = ? AND id != ?", (name, rid)).fetchone()

    @staticmethod
    def find_by_code_exclude(code, rid, db=None):
        db = db or BaseService.db()
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
        db = db or BaseService.db()
        results = db.execute(
            "SELECT parent_id FROM roles WHERE id = ? AND parent_id IS NOT NULL", (cur_id,)
        ).fetchall()
        return [r["parent_id"] for r in results]

    @staticmethod
    def count_user_roles(rid, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT COUNT(*) FROM user_roles WHERE role_id = ?", (rid,)
        ).fetchone()[0]

    @staticmethod
    def delete_txn(rid, db):
        db.execute("DELETE FROM roles WHERE id = ?", (rid,))

    @staticmethod
    def group_exists(gid, db=None):
        db = db or BaseService.db()
        return db.execute("SELECT id FROM role_groups WHERE id = ?", (gid,)).fetchone()

    @staticmethod
    def role_exists(rid, db=None):
        db = db or BaseService.db()
        return db.execute("SELECT id FROM roles WHERE id = ?", (rid,)).fetchone()
