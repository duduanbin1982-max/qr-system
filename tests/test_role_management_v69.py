import sqlite3
import uuid

import pytest

from factories import ensure_process
from modules.db import get_db
from modules.domain.errors import ConflictError
from modules.repositories.role_repository import RoleRepository
from modules.services.approval_service import ApprovalService
from modules.services.role_service import RoleService


def _admin_id(db):
    return db.execute(
        "SELECT u.id FROM users u JOIN user_roles ur ON ur.user_id=u.id "
        "JOIN roles r ON r.id=ur.role_id "
        "WHERE r.code='admin' AND r.status='active' LIMIT 1"
    ).fetchone()["id"]


def test_role_code_alias_repository_insert_contract():
    db = sqlite3.connect(":memory:")
    db.execute(
        "CREATE TABLE role_code_aliases ("
        "role_id INTEGER, role_code TEXT, reason TEXT, changed_by INTEGER, "
        "UNIQUE(role_id, role_code))"
    )

    RoleRepository.insert_code_alias_txn(
        17, "quality_reviewer", "role created", 1000, db=db
    )

    assert db.execute(
        "SELECT role_id, role_code, reason, changed_by FROM role_code_aliases"
    ).fetchone() == (17, "quality_reviewer", "role created", 1000)


def test_role_code_alias_and_reference_guard(client):
    with client.application.app_context():
        db = get_db()
        actor_id = _admin_id(db)
        role_id = RoleService.create_role(
            {"name": "v069 alias " + uuid.uuid4().hex[:8], "code": "v069_alias_role"},
            actor_id,
        )
        RoleService.update_role(role_id, {"code": "v069_alias_role_v2"}, actor_id)
        aliases = db.execute(
            "SELECT role_code, valid_to FROM role_code_aliases "
            "WHERE role_id=? ORDER BY id", (role_id,)
        ).fetchall()
        assert [row["role_code"] for row in aliases] == [
            "v069_alias_role", "v069_alias_role_v2"
        ]
        user_id = db.execute(
            "INSERT INTO users(username,password,name,role,status) "
            "VALUES (?,?,?,?,?)",
            ("v069-user-" + uuid.uuid4().hex[:8], "hash", "v069 user", "worker", "active"),
        ).lastrowid
        db.execute("INSERT INTO user_roles(user_id,role_id) VALUES (?,?)", (user_id, role_id))
        db.commit()
        with pytest.raises(ConflictError, match="已被用户或审批配置引用"):
            RoleService.update_role(role_id, {"code": "v069_alias_role_v3"}, actor_id)


def test_approval_config_persists_stable_role_ids(client):
    with client.application.app_context():
        db = get_db()
        process_id = ensure_process(db, "v069 approval " + uuid.uuid4().hex[:8], 998)
        admin_role = db.execute(
            "SELECT id, code FROM roles WHERE code='admin' AND status='active'"
        ).fetchone()
        ApprovalService.save_configs([{
            "process_id": process_id,
            "require_approval": 1,
            "approver_role_id": admin_role["id"],
            "approval_level": 1,
        }])
        row = db.execute(
            "SELECT approver_role_id, approver_role FROM approval_config WHERE process_id=?",
            (process_id,),
        ).fetchone()
        assert row["approver_role_id"] == admin_role["id"]
        assert row["approver_role"] == admin_role["code"]
