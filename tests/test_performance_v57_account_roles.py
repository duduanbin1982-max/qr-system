import json

from modules.db import get_db
from scripts.provision_performance_v57_production import (
    _ensure_account as ensure_production_account,
    _ensure_role as ensure_production_role,
)
from scripts.repair_performance_v57_account_base_roles import (
    _account_snapshot,
    _repair_account_base_roles,
)
from scripts.validate_performance_v57_replica import (
    DEDICATED_ACCOUNT_BASE_ROLE,
    DEDICATED_ACCOUNTS,
    _create_dedicated_account,
)


def _definition(suffix):
    definition = dict(DEDICATED_ACCOUNTS["reviewer"])
    definition.update(
        username=f"1000_perf_{suffix}",
        employee_no=f"PERF-REVIEW-{suffix}",
        role_code=f"performance_reviewer_v57_{suffix}",
    )
    definition["permissions"] = list(definition["permissions"])
    return definition


def _assert_split_role(db, user_id, role_id, definition):
    user = db.execute(
        "SELECT role,status FROM users WHERE id=?", (user_id,)
    ).fetchone()
    mapping = db.execute(
        "SELECT r.id,r.code,r.permissions FROM user_roles ur "
        "JOIN roles r ON r.id=ur.role_id WHERE ur.user_id=?",
        (user_id,),
    ).fetchall()

    assert user["role"] == DEDICATED_ACCOUNT_BASE_ROLE
    assert user["status"] == "inactive"
    assert len(mapping) == 1
    assert mapping[0]["id"] == role_id
    assert mapping[0]["code"] == definition["role_code"]
    assert json.loads(mapping[0]["permissions"]) == definition["permissions"]


def test_replica_provisioning_splits_base_role_from_permission_role(client):
    with client.application.app_context():
        db = get_db()
        definition = _definition("replica")

        user_id, role_id = _create_dedicated_account(db, definition)
        db.commit()

        _assert_split_role(db, user_id, role_id, definition)


def test_production_provisioning_splits_base_role_from_permission_role(client):
    with client.application.app_context():
        db = get_db()
        definition = _definition("production")

        role_id, created = ensure_production_role(db, definition)
        assert created is True
        user_id, created = ensure_production_account(db, definition, role_id)
        assert created is True
        db.commit()

        _assert_split_role(db, user_id, role_id, definition)


def test_account_role_repair_preserves_permission_roles_and_department_scopes(client):
    with client.application.app_context():
        db = get_db()
        for department_id in range(1, 9):
            db.execute(
                "INSERT INTO departments (id,name,status) VALUES (?,?, 'active')",
                (department_id, f"生产范围-{department_id}"),
            )
        db.execute(
            "INSERT INTO departments (id,name,status) VALUES (11,'机加工班组','active')"
        )

        for index, (key, definition) in enumerate(DEDICATED_ACCOUNTS.items()):
            user_id = 10336 + index
            role_id = db.execute(
                "INSERT INTO roles (name,code,permissions,status) VALUES (?,?,?,'active')",
                (
                    definition["role_name"],
                    definition["role_code"],
                    json.dumps(
                        definition["permissions"],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                ),
            ).lastrowid
            db.execute(
                "INSERT INTO users "
                "(id,username,password,name,role,employee_no,status,password_version) "
                "VALUES (?,?,?,?,?,?,'inactive',2)",
                (
                    user_id,
                    definition["username"],
                    "unused-test-hash",
                    definition["name"],
                    definition["role_code"],
                    definition["employee_no"],
                ),
            )
            db.execute(
                "INSERT INTO user_roles (user_id,role_id) VALUES (?,?)",
                (user_id, role_id),
            )
            for department_id in list(range(1, 9)) + [11]:
                db.execute(
                    "INSERT INTO performance_department_scopes "
                    "(user_id,department_id,granted_by_name) VALUES (?,?,'pytest')",
                    (user_id, department_id),
                )
        db.commit()

        db.execute("BEGIN IMMEDIATE")
        changed = _repair_account_base_roles(db)
        db.commit()

        assert changed == 3
        accounts = _account_snapshot(db, allowed_base_roles={"worker"})
        assert set(accounts) == set(DEDICATED_ACCOUNTS)
        assert all(account["role"] == "worker" for account in accounts.values())
        assert all(len(account["department_ids"]) == 9 for account in accounts.values())
        assert db.execute(
            "SELECT COUNT(*) FROM audit_logs "
            "WHERE action='performance_v57_account_base_role_repair'"
        ).fetchone()[0] == 3
