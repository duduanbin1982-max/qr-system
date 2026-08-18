import json
import sqlite3
import uuid

import pytest

from factories import TEST_HASH, TEST_PASS
from modules.db import get_db
from modules.domain.process_config import PROCESS_CONFIG_FIELDS
from modules.migration_process_config import m067_version_process_config


def _permission_headers(client, permissions):
    suffix = uuid.uuid4().hex[:8]
    username = f"process_config_{suffix}"
    role_code = f"process_config_{suffix}"
    with client.application.app_context():
        db = get_db()
        role_id = db.execute(
            "INSERT INTO roles (name, code, description, permissions, status, level) "
            "VALUES (?, ?, 'pytest process config role', ?, 'active', 1)",
            (
                f"Process Config {suffix}",
                role_code,
                json.dumps(permissions, ensure_ascii=False),
            ),
        ).lastrowid
        user_id = db.execute(
            "INSERT INTO users "
            "(username, password, name, role, status, password_version, employee_no) "
            "VALUES (?, ?, ?, ?, 'active', 2, ?)",
            (
                username,
                TEST_HASH,
                f"Process Config {suffix}",
                role_code,
                f"TEST-PROCESS-CONFIG-{suffix.upper()}",
            ),
        ).lastrowid
        db.execute(
            "INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)",
            (user_id, role_id),
        )
        db.commit()
    response = client.post(
        "/api/auth/login", json={"username": username, "password": TEST_PASS}
    )
    assert response.status_code == 200, response.get_json()
    return {
        "Authorization": f"Bearer {response.get_json()['user']['token']}"
    }


def _current(client, headers):
    response = client.get("/api/process-config", headers=headers)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _create_payload(current, suffix="create"):
    return {
        "row_version": current["config"]["row_version"],
        "process_order_mode": "out_of_order",
        "serial_process_report_mode": "controlled_backfill",
        "limit_by_prev_process": 0,
        "limit_by_order_qty": 0,
        "approval_enabled": 0,
        "revision_reason": "受控调整报工策略",
        "idempotency_key": f"process-config-{suffix}-{uuid.uuid4().hex}",
    }


def test_v067_preserves_zero_values_migrates_permissions_and_is_idempotent():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE system_settings (
            key TEXT PRIMARY KEY, value TEXT, updated_at TEXT
        );
        CREATE TABLE roles (
            id INTEGER PRIMARY KEY, permissions TEXT
        );
        INSERT INTO system_settings(key,value) VALUES
            ('process_order_mode','sequential'),
            ('serial_process_report_mode','strict'),
            ('limit_by_prev_process','0'),
            ('limit_by_order_qty','0'),
            ('approval_enabled','0');
        """
    )
    db.execute(
        "INSERT INTO roles(id,permissions) VALUES(1,?)",
        (json.dumps(["settings:manage"]),),
    )

    m067_version_process_config(db)
    m067_version_process_config(db)

    config = db.execute("SELECT * FROM process_configs WHERE id=1").fetchone()
    assert {config[field] for field in PROCESS_CONFIG_FIELDS[2:]} == {0}
    assert config["active_revision_id"]
    assert db.execute(
        "SELECT COUNT(*) FROM process_config_revisions"
    ).fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM process_config_events").fetchone()[0] == 1
    permissions = json.loads(
        db.execute("SELECT permissions FROM roles WHERE id=1").fetchone()[0]
    )
    assert {
        "process_config:view",
        "process_config:create",
        "process_config:submit",
        "process_config:approve",
        "process_config:reject",
        "process_config:history",
    }.issubset(permissions)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute(
            "UPDATE process_config_revisions SET revision_reason='篡改' WHERE version=1"
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute(
            "UPDATE process_config_revisions SET approved_by_name='篡改' WHERE version=1"
        )


def test_scoped_permissions_and_legacy_settings_write_are_blocked(
    client, auth_headers
):
    viewer = _permission_headers(
        client,
        ["page:settings", "page:settings.process-config", "process_config:view"],
    )
    worker = _permission_headers(client, ["page:scan", "scan:view"])

    assert client.get("/api/process-config", headers=viewer).status_code == 200
    assert client.post(
        "/api/process-config/revisions",
        headers=viewer,
        json=_create_payload(_current(client, viewer)),
    ).status_code == 403
    assert client.get("/api/process-config", headers=worker).status_code == 403

    blocked = client.post(
        "/api/settings",
        headers=auth_headers,
        json={"approval_enabled": "0"},
    )
    assert blocked.status_code == 409
    assert blocked.get_json()["code"] == "LEGACY_PROCESS_CONFIG_WRITE_BLOCKED"
    blocked_delete = client.post(
        "/api/settings",
        headers=auth_headers,
        json={"_deleted_keys": ["process_order_mode"]},
    )
    assert blocked_delete.status_code == 409

    settings = client.get("/api/settings", headers=auth_headers).get_json()["settings"]
    allowed = client.get(
        "/api/settings/allowed-keys", headers=auth_headers
    ).get_json()["allowed_keys"]
    assert not set(PROCESS_CONFIG_FIELDS).intersection(settings)
    assert not set(PROCESS_CONFIG_FIELDS).intersection(allowed)
    assert "default_password" not in settings
    assert client.post(
        "/api/settings", headers=auth_headers, json={"page_size": None}
    ).status_code == 400
    assert client.post(
        "/api/settings", headers=auth_headers, json=["not", "an", "object"]
    ).status_code == 400


def test_create_submit_dual_approve_publishes_and_updates_legacy_mirrors(
    client, auth_headers
):
    approver = _permission_headers(
        client,
        [
            "page:settings",
            "page:settings.process-config",
            "process_config:approve",
            "process_config:reject",
            "process_config:history",
        ],
    )
    current = _current(client, auth_headers)
    created = client.post(
        "/api/process-config/revisions",
        headers=auth_headers,
        json=_create_payload(current),
    )
    assert created.status_code == 201, created.get_json()
    draft = created.get_json()
    assert draft["status"] == "draft"
    assert draft["base_row_version"] == current["config"]["row_version"]

    submitted = client.post(
        f"/api/process-config/revisions/{draft['id']}/submit",
        headers=auth_headers,
        json={
            "row_version": draft["row_version"],
            "idempotency_key": f"process-config-submit-{uuid.uuid4().hex}",
        },
    )
    assert submitted.status_code == 200, submitted.get_json()
    pending = submitted.get_json()
    assert pending["status"] == "pending_approval"

    self_approval = client.post(
        f"/api/process-config/revisions/{draft['id']}/approve",
        headers=auth_headers,
        json={
            "row_version": pending["row_version"],
            "idempotency_key": f"process-config-self-{uuid.uuid4().hex}",
        },
    )
    assert self_approval.status_code == 409
    assert self_approval.get_json()["code"] == (
        "PROCESS_CONFIG_APPROVAL_SEPARATION_REQUIRED"
    )

    approved = client.post(
        f"/api/process-config/revisions/{draft['id']}/approve",
        headers=approver,
        json={
            "row_version": pending["row_version"],
            "idempotency_key": f"process-config-approve-{uuid.uuid4().hex}",
        },
    )
    assert approved.status_code == 200, approved.get_json()
    result = approved.get_json()
    assert result["revision"]["status"] == "published"
    assert result["config"]["version"] == draft["version"]
    assert result["config"]["process_order_mode"] == "out_of_order"
    assert result["config"]["approval_enabled"] == 0

    with client.application.app_context():
        db = get_db()
        mirrors = dict(
            db.execute(
                "SELECT key,value FROM system_settings WHERE key IN (?,?,?,?,?)",
                PROCESS_CONFIG_FIELDS,
            ).fetchall()
        )
        assert mirrors["process_order_mode"] == "out_of_order"
        assert mirrors["approval_enabled"] == "0"
        events = db.execute(
            "SELECT event_type FROM process_config_events WHERE revision_id=? ORDER BY id",
            (draft["id"],),
        ).fetchall()
        assert [event["event_type"] for event in events] == [
            "created",
            "submitted",
            "approved",
            "published",
        ]


def test_stale_open_revision_strict_schema_and_rejection(client, auth_headers):
    approver = _permission_headers(
        client,
        ["process_config:approve", "process_config:reject", "process_config:view"],
    )
    current = _current(client, auth_headers)
    stale_payload = _create_payload(current, "stale")
    stale_payload["row_version"] += 1
    stale = client.post(
        "/api/process-config/revisions", headers=auth_headers, json=stale_payload
    )
    assert stale.status_code == 409
    assert stale.get_json()["code"] == "PROCESS_CONFIG_STALE"

    invalid = _create_payload(current, "invalid")
    invalid["unknown"] = True
    assert client.post(
        "/api/process-config/revisions", headers=auth_headers, json=invalid
    ).status_code == 400

    created = client.post(
        "/api/process-config/revisions",
        headers=auth_headers,
        json=_create_payload(current, "valid"),
    ).get_json()
    duplicate = client.post(
        "/api/process-config/revisions",
        headers=auth_headers,
        json=_create_payload(current, "duplicate"),
    )
    assert duplicate.status_code == 409
    assert duplicate.get_json()["code"] == "PROCESS_CONFIG_OPEN_REVISION_EXISTS"

    stale_update = client.put(
        f"/api/process-config/revisions/{created['id']}",
        headers=auth_headers,
        json={
            "row_version": created["row_version"] + 1,
            "approval_enabled": 1,
            "idempotency_key": f"process-config-update-{uuid.uuid4().hex}",
        },
    )
    assert stale_update.status_code == 409
    assert stale_update.get_json()["code"] == "PROCESS_CONFIG_STALE"

    updated = client.put(
        f"/api/process-config/revisions/{created['id']}",
        headers=auth_headers,
        json={
            "row_version": created["row_version"],
            "approval_enabled": 1,
            "revision_reason": "补充审批策略依据",
            "idempotency_key": f"process-config-update-valid-{uuid.uuid4().hex}",
        },
    )
    assert updated.status_code == 200, updated.get_json()
    with client.application.app_context():
        db = get_db()
        assert db.execute(
            "SELECT 1 FROM audit_logs WHERE action='process_config_revision_update' "
            "AND target_id=?",
            (created["id"],),
        ).fetchone()

    submitted = client.post(
        f"/api/process-config/revisions/{created['id']}/submit",
        headers=auth_headers,
        json={
            "row_version": updated.get_json()["row_version"],
            "idempotency_key": f"process-config-submit-{uuid.uuid4().hex}",
        },
    ).get_json()
    rejected = client.post(
        f"/api/process-config/revisions/{created['id']}/reject",
        headers=approver,
        json={
            "row_version": submitted["row_version"],
            "reason": "保持现行报工顺序",
            "idempotency_key": f"process-config-reject-{uuid.uuid4().hex}",
        },
    )
    assert rejected.status_code == 200, rejected.get_json()
    assert rejected.get_json()["status"] == "rejected"
    assert _current(client, auth_headers)["config"]["version"] == current["config"]["version"]
