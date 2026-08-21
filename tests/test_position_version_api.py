import ast
import uuid
from pathlib import Path

import jsonschema
import pytest

from factories import TEST_HASH, ensure_user
from modules import config
from modules.db import get_db
from modules.schemas import SCHEMAS
from modules.services.position_version_service import PositionVersionService
from tests.test_position_version_workflow import (
    _actors,
    _create_position,
    _publish_position,
    _published_process,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _enable_position_versioned_writes(monkeypatch):
    monkeypatch.setattr(config, "POSITION_VERSIONED_QUERY_ENABLED", True)
    monkeypatch.setattr(config, "POSITION_VERSIONED_WRITE_ENABLED", True)
    monkeypatch.setattr(config, "POSITION_LEGACY_WRITE_BLOCKED", False)


def _login(client, username, password="Test@1234"):
    response = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.get_json()
    payload = response.get_json() or {}
    token = payload.get("token") or payload.get("user", {}).get("token")
    return {"Authorization": f"Bearer {token}"}


def _second_admin_headers(client):
    with client.application.app_context():
        db = get_db()
        suffix = uuid.uuid4().hex[:8]
        username = f"position-api-admin-{suffix}"
        ensure_user(
            db,
            username,
            TEST_HASH,
            "岗位 API 独立制单人",
            "admin",
            f"POSITION-API-{suffix}",
        )
    return _login(client, username)


def test_position_versioning_schemas_are_strict():
    valid_create = {
        "name": "精密车工",
        "description": "负责精密车削",
        "process_ids": [1, 2],
        "revision_reason": "建立岗位主数据",
        "idempotency_key": "position-create-001",
    }
    jsonschema.validate(valid_create, SCHEMAS["position_version_create"])
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {**valid_create, "unexpected": True},
            SCHEMAS["position_version_create"],
        )

    valid_revision = {
        "row_version": 1,
        "revision_reason": "补充岗位说明",
        "idempotency_key": "position-revision-001",
        "description": "新说明",
    }
    jsonschema.validate(valid_revision, SCHEMAS["position_revision_create"])
    for invalid in (
        {**valid_revision, "unexpected": True},
        {key: value for key, value in valid_revision.items() if key != "row_version"},
        {**valid_revision, "idempotency_key": "short"},
        {**valid_revision, "revision_reason": " "},
    ):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid, SCHEMAS["position_revision_create"])

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {"row_version": 0, "idempotency_key": "position-update-001"},
            SCHEMAS["position_version_update"],
        )
    jsonschema.validate(
        {
            "row_version": 0,
            "idempotency_key": "position-update-001",
            "process_ids": [],
        },
        SCHEMAS["position_version_update"],
    )


def test_create_position_api_builds_inactive_root_and_v1_draft(
    client, auth_headers
):
    preparer, approver = _actors(client)
    _, process = _published_process(client, preparer, approver, "API 岗位工序")
    key = f"position-api-create-{uuid.uuid4().hex}"
    response = client.post(
        "/api/positions",
        headers={**auth_headers, "X-Request-ID": "position-api-create-request"},
        json={
            "name": f"API 新建岗位-{uuid.uuid4().hex[:8]}",
            "description": "由岗位版本化入口创建",
            "process_ids": [process["process_id"]],
            "revision_reason": "建立岗位主数据",
            "idempotency_key": key,
        },
    )

    assert response.status_code == 201, response.get_json()
    payload = response.get_json()
    assert payload["root"]["position_code"].startswith("POS-")
    assert payload["root"]["status"] == "inactive"
    assert payload["root"]["current_effective_version_id"] is None
    assert payload["version"]["version"] == 1
    assert payload["version"]["status"] == "draft"
    assert payload["version"]["process_ids"] == [process["process_id"]]
    assert payload["version"]["idempotency_key"] == key
    with client.application.app_context():
        db = get_db()
        db.execute(
            "UPDATE users SET position_id=? WHERE id=?",
            (payload["root"]["id"], payload["version"]["created_by"]),
        )
        db.commit()

    listed = client.get("/api/positions", headers=auth_headers)
    listed_position = next(
        item
        for item in listed.get_json()["positions"]
        if item["id"] == payload["root"]["id"]
    )
    assert listed_position["open_version"]["id"] == payload["version"]["id"]
    assert listed_position["pending_lifecycle_request"] is None
    assert listed_position["employee_count"] == 1


def test_position_version_api_exposes_workflow_history_impact_and_projection(
    client, auth_headers
):
    preparer, approver = _actors(client)
    _, process = _published_process(client, preparer, approver, "API 工作流工序")
    created = _create_position(client, preparer, [process["process_id"]])
    version_id = created["version"]["id"]
    position_id = created["root"]["id"]

    invalid = client.post(
        f"/api/position-versions/{version_id}/submit",
        headers=auth_headers,
        json={
            "row_version": created["version"]["row_version"],
            "idempotency_key": "position-api-invalid",
            "extra": True,
        },
    )
    assert invalid.status_code == 400

    submitted = client.post(
        f"/api/position-versions/{version_id}/submit",
        headers=auth_headers,
        json={
            "row_version": created["version"]["row_version"],
            "idempotency_key": f"position-api-submit-{uuid.uuid4().hex}",
        },
    )
    assert submitted.status_code == 200, submitted.get_json()
    approved = client.post(
        f"/api/position-versions/{version_id}/approve",
        headers=auth_headers,
        json={
            "row_version": submitted.get_json()["row_version"],
            "idempotency_key": f"position-api-approve-{uuid.uuid4().hex}",
        },
    )
    assert approved.status_code == 200, approved.get_json()
    assert approved.get_json()["status"] == "published"

    versions = client.get(
        f"/api/positions/{position_id}/versions", headers=auth_headers
    )
    fetched = client.get(
        f"/api/position-versions/{version_id}", headers=auth_headers
    )
    impact = client.get(
        f"/api/position-versions/{version_id}/impact", headers=auth_headers
    )
    positions = client.get("/api/positions", headers=auth_headers)

    assert versions.status_code == fetched.status_code == impact.status_code == 200
    assert versions.get_json()["versions"][0]["id"] == version_id
    assert fetched.get_json()["id"] == version_id
    assert impact.get_json()["version"]["id"] == version_id
    projected = next(
        row
        for row in positions.get_json()["positions"]
        if row["id"] == position_id
    )
    assert projected["process_ids"] == [process["process_id"]]
    assert projected["current_effective_version_id"] == version_id
    assert projected["current_version"]["id"] == version_id


def test_position_lifecycle_api_uses_two_person_service_and_mandatory_audit(
    client, auth_headers
):
    preparer, approver = _actors(client)
    created = _create_position(client, preparer, [], "API 退休岗位")
    published = _publish_position(
        client, created["version"]["id"], preparer, approver
    )
    requester_headers = _second_admin_headers(client)
    with client.application.app_context():
        root = get_db().execute(
            "SELECT row_version FROM positions WHERE id=?",
            (created["root"]["id"],),
        ).fetchone()

    requested = client.post(
        f"/api/positions/{created['root']['id']}/retirement-requests",
        headers=requester_headers,
        json={
            "row_version": root["row_version"],
            "lifecycle_reason": "API 申请退休",
            "idempotency_key": f"position-api-retire-{uuid.uuid4().hex}",
        },
    )
    assert requested.status_code == 201, requested.get_json()
    approved = client.post(
        f"/api/position-lifecycle-requests/{requested.get_json()['id']}/approve",
        headers=auth_headers,
        json={
            "row_version": requested.get_json()["row_version"],
            "idempotency_key": f"position-api-retire-approve-{uuid.uuid4().hex}",
        },
    )

    assert approved.status_code == 200, approved.get_json()
    assert approved.get_json()["status"] == "approved"
    assert approved.get_json()["position"]["lifecycle_status"] == "retired"
    assert approved.get_json()["position_version"]["id"] == published["id"]
    with client.application.app_context():
        audit = get_db().execute(
            "SELECT mandatory FROM audit_logs WHERE action='position_retired' "
            "AND target_id=?",
            (created["root"]["id"],),
        ).fetchone()
    assert audit["mandatory"] == 1


def test_worker_cannot_view_position_history_or_impact(
    client, worker_auth_headers
):
    preparer, approver = _actors(client)
    created, _ = _published_process(client, preparer, approver, "无权岗位工序")
    position = _create_position(
        client, preparer, [created["root"]["id"]], "无权岗位"
    )

    versions = client.get(
        f"/api/positions/{position['root']['id']}/versions",
        headers=worker_auth_headers,
    )
    impact = client.get(
        f"/api/position-versions/{position['version']['id']}/impact",
        headers=worker_auth_headers,
    )

    assert versions.status_code == 403
    assert impact.status_code == 403


def test_position_version_routes_are_thin_and_do_not_duplicate_safe_audit():
    path = PROJECT_ROOT / "modules" / "routes" / "position_versions.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }

    assert not any(
        module.startswith("modules.repositories") for module in imported_modules
    )
    assert "modules.db" not in imported_modules
    assert ".execute(" not in source
    assert "safe_audit_log" not in source
