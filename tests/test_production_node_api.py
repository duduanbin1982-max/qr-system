import json
import uuid

import pytest

from factories import TEST_HASH
from modules.db import get_db


def _login_with_permissions(client, permissions):
    suffix = uuid.uuid4().hex[:8]
    username = f"node-user-{suffix}"
    with client.application.app_context():
        db = get_db()
        role_id = db.execute(
            "INSERT INTO roles (name,code,description,permissions,status,level) "
            "VALUES (?,?, '',?,'active',1)",
            (
                f"Node Role {suffix}",
                f"node_role_{suffix}",
                json.dumps(permissions),
            ),
        ).lastrowid
        user_id = db.execute(
            "INSERT INTO users (username,password,name,role,employee_no,status,"
            "password_version,must_change_password) VALUES (?,?,?,'worker',?,'active',2,0)",
            (username, TEST_HASH, f"Node User {suffix}", f"NODE-{suffix}"),
        ).lastrowid
        db.execute(
            "INSERT INTO user_roles (user_id,role_id) VALUES (?,?)",
            (user_id, role_id),
        )
        db.commit()
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": "Test@1234"},
    )
    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    token = payload.get("token") or payload["user"]["token"]
    return {"Authorization": f"Bearer {token}"}


def _node_fixture(client):
    with client.application.app_context():
        db = get_db()
        node = db.execute(
            "SELECT n.*,p.name AS process_name FROM production_nodes n "
            "JOIN processes p ON p.id=n.process_id ORDER BY n.id LIMIT 1"
        ).fetchone()
        calendar_id = db.execute(
            "SELECT id FROM schedule_calendars WHERE status='active' ORDER BY id LIMIT 1"
        ).fetchone()[0]
        actor_id = db.execute(
            "SELECT id FROM users WHERE username='testrunner'"
        ).fetchone()[0]
        return dict(node), calendar_id, actor_id


def _create_payload(process_id, calendar_id, *, key=None, code=None):
    suffix = uuid.uuid4().hex[:8].upper()
    return {
        "process_id": process_id,
        "node_code": code or f"TEST-{suffix}",
        "node_name": f"Test Node {suffix}",
        "capacity_mode": "exclusive",
        "calendar_id": calendar_id,
        "row_version": 1,
        "reason": "API contract test",
        "idempotency_key": key or f"node-create-{uuid.uuid4().hex}",
    }


def test_node_routes_require_only_new_granular_permissions(client):
    legacy = _login_with_permissions(client, ["schedule:view", "schedule:edit"])
    for path in ("/api/production-nodes", "/api/production-nodes/1/audit-events"):
        response = client.get(path, headers=legacy)
        assert response.status_code == 403, response.get_json()

    view = _login_with_permissions(client, ["production_nodes:view"])
    assert client.get("/api/production-nodes", headers=view).status_code == 200
    node, calendar_id, _ = _node_fixture(client)
    denied = client.post(
        "/api/production-nodes",
        headers=view,
        json=_create_payload(node["process_id"], calendar_id),
    )
    assert denied.status_code == 403


@pytest.mark.parametrize(
    "query",
    ("?limit=0", "?limit=501", "?limit=bad", "?process_id=0", "?status=retired"),
)
def test_node_list_rejects_invalid_filters(client, auth_headers, query):
    response = client.get(f"/api/production-nodes{query}", headers=auth_headers)
    assert response.status_code == 400, response.get_json()


def test_node_create_update_replay_conflict_and_delete_rejection(client, auth_headers):
    existing, calendar_id, _ = _node_fixture(client)
    command = _create_payload(existing["process_id"], calendar_id)
    created = client.post("/api/production-nodes", headers=auth_headers, json=command)
    assert created.status_code == 201, created.get_json()
    node = created.get_json()
    assert node["row_version"] == 1
    assert node["legacy_process_line_id"] is None

    replay = client.post("/api/production-nodes", headers=auth_headers, json=command)
    assert replay.status_code == 201, replay.get_json()
    assert replay.get_json()["id"] == node["id"]

    reused = client.post(
        "/api/production-nodes",
        headers=auth_headers,
        json={**command, "node_name": "Different request"},
    )
    assert reused.status_code == 409, reused.get_json()
    with client.application.app_context():
        db = get_db()
        assert not db.execute(
            "SELECT 1 FROM production_nodes WHERE node_name='Different request'"
        ).fetchone()

    update = {
        **command,
        "node_name": "Renamed node",
        "status": "inactive",
        "row_version": node["row_version"],
        "idempotency_key": f"node-update-{uuid.uuid4().hex}",
    }
    updated = client.put(
        f"/api/production-nodes/{node['id']}", headers=auth_headers, json=update
    )
    assert updated.status_code == 200, updated.get_json()
    assert updated.get_json()["status"] == "inactive"
    assert updated.get_json()["row_version"] == 2

    stale = client.put(
        f"/api/production-nodes/{node['id']}",
        headers=auth_headers,
        json={**update, "idempotency_key": f"stale-{uuid.uuid4().hex}"},
    )
    assert stale.status_code == 409, stale.get_json()

    with client.application.app_context():
        db = get_db()
        other_process_id = db.execute(
            "SELECT id FROM processes WHERE id<>? AND status='active' ORDER BY id LIMIT 1",
            (node["process_id"],),
        ).fetchone()[0]
    reassigned = client.put(
        f"/api/production-nodes/{node['id']}",
        headers=auth_headers,
        json={
            **update,
            "process_id": other_process_id,
            "row_version": updated.get_json()["row_version"],
            "idempotency_key": f"node-process-change-{uuid.uuid4().hex}",
        },
    )
    assert reassigned.status_code == 409, reassigned.get_json()

    forbidden_mapping = client.put(
        f"/api/production-nodes/{node['id']}",
        headers=auth_headers,
        json={**update, "legacy_process_line_id": 999},
    )
    assert forbidden_mapping.status_code == 400
    assert client.delete(
        f"/api/production-nodes/{node['id']}", headers=auth_headers
    ).status_code == 405


def test_node_code_is_unique_inside_process(client, auth_headers):
    existing, calendar_id, _ = _node_fixture(client)
    response = client.post(
        "/api/production-nodes",
        headers=auth_headers,
        json=_create_payload(
            existing["process_id"], calendar_id, code=existing["node_code"]
        ),
    )
    assert response.status_code == 409, response.get_json()
    assert "节点编码" in response.get_json()["error"]


def test_capability_replacement_validates_scope_boundaries_and_audits(client, auth_headers):
    node, _, _ = _node_fixture(client)
    with client.application.app_context():
        db = get_db()
        process_version_id = db.execute(
            "SELECT id FROM process_versions WHERE process_id=? ORDER BY id DESC LIMIT 1",
            (node["process_id"],),
        ).fetchone()[0]

    command = {
        "capabilities": [
            {
                "product_family": "steel-shell",
                "process_version_id": process_version_id,
                "status": "active",
                "max_batch_quantity": None,
                "batch_minutes": None,
                "changeover_minutes": 0,
                "allow_mixed_orders": False,
            }
        ],
        "reason": "configure exclusive node capability",
        "idempotency_key": f"node-cap-{uuid.uuid4().hex}",
    }
    response = client.put(
        f"/api/production-nodes/{node['id']}/capabilities",
        headers=auth_headers,
        json=command,
    )
    assert response.status_code == 200, response.get_json()
    assert response.get_json()[0]["product_family"] == "steel-shell"

    duplicate = client.put(
        f"/api/production-nodes/{node['id']}/capabilities",
        headers=auth_headers,
        json={
            **command,
            "capabilities": command["capabilities"] * 2,
            "idempotency_key": f"node-cap-dup-{uuid.uuid4().hex}",
        },
    )
    assert duplicate.status_code == 400, duplicate.get_json()

    batch_fields = client.put(
        f"/api/production-nodes/{node['id']}/capabilities",
        headers=auth_headers,
        json={
            **command,
            "capabilities": [
                {**command["capabilities"][0], "max_batch_quantity": 10, "batch_minutes": 30}
            ],
            "idempotency_key": f"node-cap-batch-{uuid.uuid4().hex}",
        },
    )
    assert batch_fields.status_code == 400, batch_fields.get_json()

    bad_process_version = client.put(
        f"/api/production-nodes/{node['id']}/capabilities",
        headers=auth_headers,
        json={
            **command,
            "capabilities": [
                {**command["capabilities"][0], "process_version_id": 999999999}
            ],
            "idempotency_key": f"node-cap-fk-{uuid.uuid4().hex}",
        },
    )
    assert bad_process_version.status_code == 400, bad_process_version.get_json()


def test_capability_query_uses_view_permission_and_does_not_mutate_facts(client):
    node, _, _ = _node_fixture(client)
    view_headers = _login_with_permissions(client, ["production_nodes:view"])
    legacy_headers = _login_with_permissions(client, ["schedule:view", "schedule:edit"])
    with client.application.app_context():
        db = get_db()
        before = [
            dict(row)
            for row in db.execute(
                "SELECT * FROM production_node_capabilities "
                "WHERE production_node_id=? ORDER BY id",
                (node["id"],),
            ).fetchall()
        ]

    response = client.get(
        f"/api/production-nodes/{node['id']}/capabilities",
        headers=view_headers,
    )
    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    assert payload["node"]["id"] == node["id"]
    assert isinstance(payload["capabilities"], list)
    assert client.get(
        f"/api/production-nodes/{node['id']}/capabilities",
        headers=legacy_headers,
    ).status_code == 403
    assert client.get(
        "/api/production-nodes/999999999/capabilities",
        headers=view_headers,
    ).status_code == 404

    with client.application.app_context():
        db = get_db()
        after = [
            dict(row)
            for row in db.execute(
                "SELECT * FROM production_node_capabilities "
                "WHERE production_node_id=? ORDER BY id",
                (node["id"],),
            ).fetchall()
        ]
    assert after == before


def test_calendar_override_create_cancel_and_audit_are_strict(client, auth_headers):
    node, _, _ = _node_fixture(client)
    command = {
        "start_at": "2026-09-20 08:00:00",
        "end_at": "2026-09-20 10:00:00",
        "override_type": "maintenance",
        "reason": "planned maintenance",
        "idempotency_key": f"node-calendar-{uuid.uuid4().hex}",
    }
    created = client.post(
        f"/api/production-nodes/{node['id']}/calendar-overrides",
        headers=auth_headers,
        json=command,
    )
    assert created.status_code == 201, created.get_json()
    override = created.get_json()
    assert override["status"] == "active"

    invalid = client.post(
        f"/api/production-nodes/{node['id']}/calendar-overrides",
        headers=auth_headers,
        json={**command, "start_at": command["end_at"], "idempotency_key": "bad-time-key"},
    )
    assert invalid.status_code == 400, invalid.get_json()

    cancelled = client.post(
        f"/api/production-node-calendar-overrides/{override['id']}/cancel",
        headers=auth_headers,
        json={
            "reason": "maintenance no longer required",
            "idempotency_key": f"node-calendar-cancel-{uuid.uuid4().hex}",
        },
    )
    assert cancelled.status_code == 200, cancelled.get_json()
    assert cancelled.get_json()["status"] == "cancelled"

    second_cancel = client.post(
        f"/api/production-node-calendar-overrides/{override['id']}/cancel",
        headers=auth_headers,
        json={
            "reason": "duplicate cancellation",
            "idempotency_key": f"node-calendar-cancel-{uuid.uuid4().hex}",
        },
    )
    assert second_cancel.status_code == 409, second_cancel.get_json()

    audits = client.get(
        f"/api/production-nodes/{node['id']}/audit-events?limit=20",
        headers=auth_headers,
    )
    assert audits.status_code == 200, audits.get_json()
    assert {item["event_type"] for item in audits.get_json()} >= {
        "calendar_override_created",
        "calendar_override_cancelled",
    }
    with client.application.app_context():
        db = get_db()
        event_id = db.execute(
            "SELECT id FROM production_node_audit_events "
            "WHERE production_node_id=? ORDER BY id DESC LIMIT 1",
            (node["id"],),
        ).fetchone()[0]
        with pytest.raises(Exception, match="immutable"):
            db.execute(
                "UPDATE production_node_audit_events SET reason='tampered' WHERE id=?",
                (event_id,),
            )
