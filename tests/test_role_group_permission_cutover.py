import json
import sqlite3

import pytest

from modules.migration_role_group_permissions import m068_retire_role_group_permissions
from scripts.role_group_permissions_v68 import (
    apply_cutover,
    inspect_role_group_permissions,
)


def _database():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE role_groups (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            parent_id INTEGER,
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            permissions TEXT DEFAULT '',
            data_scope TEXT DEFAULT 'all'
        );
        CREATE TABLE roles (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            code TEXT NOT NULL,
            permissions TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'active',
            group_id INTEGER
        );
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
        );
        CREATE TABLE user_roles (user_id INTEGER NOT NULL, role_id INTEGER NOT NULL);
        CREATE TABLE audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL,
            user_id INTEGER,
            action TEXT NOT NULL,
            target_type TEXT DEFAULT '',
            target_id INTEGER DEFAULT 0,
            detail TEXT DEFAULT '',
            category TEXT DEFAULT 'legacy',
            severity TEXT DEFAULT 'info',
            mandatory INTEGER DEFAULT 0,
            schema_version INTEGER DEFAULT 1,
            redaction_version INTEGER DEFAULT 1,
            request_id TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    db.execute(
        "INSERT INTO role_groups(id,name,permissions) VALUES(1,'普通员工组',?)",
        (json.dumps(["orders:view"], ensure_ascii=False),),
    )
    db.execute(
        "INSERT INTO roles(id,name,code,permissions,group_id) VALUES"
        "(1,'系统管理员','admin','[\"*\"]',NULL),"
        "(2,'普通员工','worker','[]',1)"
    )
    db.executemany(
        "INSERT INTO users(id,username,name) VALUES(?,?,?)",
        [(10, "admin-a", "管理员甲"), (11, "admin-b", "管理员乙"), (20, "worker", "员工")],
    )
    db.executemany(
        "INSERT INTO user_roles(user_id,role_id) VALUES(?,?)",
        [(10, 1), (11, 1), (20, 2)],
    )
    db.commit()
    return db


def test_v068_archives_and_clears_legacy_permissions_idempotently():
    db = _database()
    m068_retire_role_group_permissions(db)
    db.execute("PRAGMA user_version=68")
    db.commit()

    report = inspect_role_group_permissions(db)
    assert report["status"] == "ready"
    assert report["summary"]["users_with_group_only_permissions"] == 1
    assert len(report["manifest_sha256"]) == 64

    result = apply_cutover(
        db,
        idempotency_key="role-group-v068-test",
        expected_manifest_sha256=report["manifest_sha256"],
        actor_user_id=10,
        actor_name="管理员甲",
        approved_by_user_id=11,
        approved_by_name="管理员乙",
    )
    assert result["status"] == "passed"
    assert result["idempotent"] is False
    assert db.execute("SELECT permissions FROM role_groups WHERE id=1").fetchone()[0] == "[]"
    archive = db.execute(
        "SELECT permissions_json,role_count,user_count "
        "FROM role_group_permission_archive"
    ).fetchone()
    assert json.loads(archive["permissions_json"]) == ["orders:view"]
    assert (archive["role_count"], archive["user_count"]) == (1, 1)

    repeated = apply_cutover(
        db,
        idempotency_key="role-group-v068-test",
        expected_manifest_sha256=report["manifest_sha256"],
        actor_user_id=10,
        actor_name="管理员甲",
        approved_by_user_id=11,
        approved_by_name="管理员乙",
    )
    assert repeated["status"] == "passed"
    assert repeated["idempotent"] is True
    assert db.execute(
        "SELECT COUNT(*) FROM role_group_permission_cutovers"
    ).fetchone()[0] == 1


def test_v068_guards_future_non_empty_role_group_permissions_and_evidence_mutation():
    db = _database()
    m068_retire_role_group_permissions(db)
    db.execute("PRAGMA user_version=68")
    db.commit()

    with pytest.raises(sqlite3.IntegrityError, match="cannot grant permissions"):
        db.execute(
            "INSERT INTO role_groups(id,name,permissions) VALUES(2,'新组','[\"orders:view\"]')"
        )
    with pytest.raises(sqlite3.IntegrityError, match="cannot grant permissions"):
        db.execute(
            "UPDATE role_groups SET permissions='[\"orders:view\"]' WHERE id=1"
        )
    db.rollback()

    report = inspect_role_group_permissions(db)
    apply_cutover(
        db,
        idempotency_key="role-group-v068-immutable-test",
        expected_manifest_sha256=report["manifest_sha256"],
        actor_user_id=10,
        actor_name="管理员甲",
        approved_by_user_id=11,
        approved_by_name="管理员乙",
    )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute(
            "UPDATE role_group_permission_archive SET group_name='篡改'"
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute("DELETE FROM role_group_permission_cutovers")
