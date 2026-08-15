import ast
import uuid
from pathlib import Path

import jsonschema
import pytest

from factories import TEST_HASH, ensure_user
from modules import config
from modules.app import app
from modules.db import get_db
from modules.schemas import SCHEMAS
from modules.services.master_data_lifecycle_service import MasterDataLifecycleService
from modules.services.master_data_release_service import MasterDataReleaseService
from modules.services.process_version_service import ProcessVersionService
from tests.test_process_version_workflow import _actors, _create_process, _publish
from tests.test_route_version_workflow import _create_route


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _enable_versioned_writes(monkeypatch):
    monkeypatch.setattr(config, "PROCESS_VERSIONED_QUERY_ENABLED", True)
    monkeypatch.setattr(config, "PROCESS_VERSIONED_WRITE_ENABLED", True)


def _login(client, username, password="Test@1234"):
    response = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.get_json()
    payload = response.get_json() or {}
    token = payload.get("token") or payload.get("user", {}).get("token")
    return {"Authorization": f"Bearer {token}"}


def test_process_versioning_schemas_are_strict_and_validate_concurrency_fields():
    valid_create = {
        "name": "精密车削",
        "category": "机加工",
        "revision_reason": "建立新工序主数据",
        "idempotency_key": "process-create-001",
        "description": "精加工工序",
        "seq_order": 20,
    }
    jsonschema.validate(valid_create, SCHEMAS["process_version_create"])
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {**valid_create, "unexpected": True},
            SCHEMAS["process_version_create"],
        )

    valid_revision = {
        "row_version": 0,
        "revision_reason": "调整工艺参数",
        "idempotency_key": "process-revision-001",
        "name": "精密车削",
    }
    jsonschema.validate(valid_revision, SCHEMAS["process_revision_create"])

    for invalid in (
        {**valid_revision, "unexpected": True},
        {key: value for key, value in valid_revision.items() if key != "row_version"},
        {**valid_revision, "idempotency_key": " "},
        {**valid_revision, "revision_reason": " "},
    ):
        try:
            jsonschema.validate(invalid, SCHEMAS["process_revision_create"])
        except jsonschema.ValidationError:
            pass
        else:
            raise AssertionError(f"schema accepted invalid payload: {invalid}")

    valid_route = {
        "row_version": 0,
        "revision_reason": "更新路线节点",
        "idempotency_key": "route-revision-001",
        "items": [
            {
                "process_id": 1,
                "process_version_id": 2,
                "seq_order": 10,
                "is_required": 1,
                "required_audit": 0,
            }
        ],
    }
    jsonschema.validate(valid_route, SCHEMAS["route_revision_create"])
    invalid_node = {
        **valid_route,
        "items": [{"process_id": 1, "process_version_id": 0, "seq_order": -1}],
    }
    try:
        jsonschema.validate(invalid_node, SCHEMAS["route_revision_create"])
    except jsonschema.ValidationError:
        pass
    else:
        raise AssertionError("route schema accepted an invalid node")


def test_create_versioned_process_api_creates_stable_root_and_v1_draft(
    client, auth_headers
):
    idempotency_key = f"process-create-{uuid.uuid4().hex}"
    response = client.post(
        "/api/process-versions",
        headers=auth_headers,
        json={
            "name": "API 新建精车",
            "category": "机加工",
            "description": "由版本化入口创建",
            "seq_order": 25,
            "revision_reason": "建立新工序主数据",
            "idempotency_key": idempotency_key,
        },
    )

    assert response.status_code == 201, response.get_json()
    payload = response.get_json()
    assert payload["root"]["process_code"].startswith("PROC-")
    assert payload["root"]["current_effective_version_id"] is None
    assert payload["root"]["lifecycle_status"] == "active"
    assert payload["version"]["process_id"] == payload["root"]["id"]
    assert payload["version"]["version"] == 1
    assert payload["version"]["status"] == "draft"
    assert payload["version"]["name"] == "API 新建精车"
    assert payload["version"]["idempotency_key"] == idempotency_key


def test_version_routes_are_thin_http_adapters():
    for filename in (
        "process_versions.py",
        "route_versions.py",
        "master_data_releases.py",
    ):
        path = PROJECT_ROOT / "modules" / "routes" / filename
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported_modules = {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        source = path.read_text(encoding="utf-8")

        assert not any(module.startswith("modules.repositories") for module in imported_modules)
        assert "modules.db" not in imported_modules
        assert ".execute(" not in source


def test_process_version_api_enforces_schema_permissions_and_separation(
    client, auth_headers
):
    preparer, approver = _actors(client)
    created = _create_process(client, preparer, "API 工序")
    process_id = created["root"]["id"]
    version_id = created["version"]["id"]

    listed = client.get(f"/api/processes/{process_id}/versions", headers=auth_headers)
    assert listed.status_code == 200, listed.get_json()
    assert listed.get_json()["versions"][0]["id"] == version_id

    invalid = client.post(
        f"/api/process-versions/{version_id}/submit",
        headers=auth_headers,
        json={"row_version": 0, "idempotency_key": "submit-api-001", "extra": 1},
    )
    assert invalid.status_code == 400

    submitted = client.post(
        f"/api/process-versions/{version_id}/submit",
        headers=auth_headers,
        json={"row_version": 0, "idempotency_key": f"submit-{uuid.uuid4().hex}"},
    )
    assert submitted.status_code == 200, submitted.get_json()
    assert submitted.get_json()["status"] == "pending_approval"

    with client.application.app_context():
        db = get_db()
        username = f"process-api-{uuid.uuid4().hex[:8]}"
        actor_id = ensure_user(
            db,
            username,
            TEST_HASH,
            "API 制单人",
            "admin",
            f"API-{uuid.uuid4().hex[:8]}",
        )
    same_actor_headers = _login(client, username)
    with client.application.app_context():
        get_db().execute(
            "UPDATE process_versions SET created_by=? WHERE id=?", (actor_id, version_id)
        )
        get_db().commit()

    denied = client.post(
        f"/api/process-versions/{version_id}/approve",
        headers=same_actor_headers,
        json={
            "row_version": submitted.get_json()["row_version"],
            "idempotency_key": f"approve-{uuid.uuid4().hex}",
        },
    )
    assert denied.status_code == 409
    assert denied.get_json()["code"] == "PROCESS_APPROVAL_SEPARATION_REQUIRED"
    assert denied.get_json()["action"] == "select_different_approver"


def test_worker_cannot_view_version_drafts_or_impact(client, worker_auth_headers):
    preparer, _ = _actors(client)
    created = _create_process(client, preparer, "无权访问工序")
    process_id = created["root"]["id"]
    version_id = created["version"]["id"]

    versions = client.get(
        f"/api/processes/{process_id}/versions", headers=worker_auth_headers
    )
    impact = client.get(
        f"/api/process-versions/{version_id}/impact", headers=worker_auth_headers
    )

    assert versions.status_code == 403
    assert impact.status_code == 403


def test_revision_api_rejects_stale_root_row_version(client, auth_headers):
    preparer, approver = _actors(client)
    process = _create_process(client, preparer, "API 并发工序")
    _publish(client, process["version"]["id"], preparer, approver)
    process_id = process["root"]["id"]

    stale = client.post(
        f"/api/processes/{process_id}/revisions",
        headers=auth_headers,
        json={
            "row_version": 0,
            "revision_reason": "基于过期数据修订",
            "idempotency_key": f"revision-{uuid.uuid4().hex}",
        },
    )

    assert stale.status_code == 409, stale.get_json()
    assert stale.get_json()["code"] == "PROCESS_VERSION_STALE"
    assert stale.get_json()["action"] == "refresh_process_version"


def test_route_version_and_release_batch_apis_expose_stable_workflow_states(
    client, auth_headers
):
    preparer, approver = _actors(client)
    process = _create_process(client, preparer, "API 路线工序")
    published_process = _publish(
        client, process["version"]["id"], preparer, approver
    )
    route = _create_route(client, preparer, [published_process])
    route_id = route["root"]["id"]
    route_version_id = route["version"]["id"]

    listed = client.get(
        f"/api/process-routes/{route_id}/versions", headers=auth_headers
    )
    assert listed.status_code == 200, listed.get_json()
    assert listed.get_json()["versions"][0]["items"][0][
        "process_version_id"
    ] == published_process["id"]

    impact = client.get(
        f"/api/process-route-versions/{route_version_id}/impact",
        headers=auth_headers,
    )
    assert impact.status_code == 200, impact.get_json()
    assert impact.get_json()["version"]["id"] == route_version_id

    submitted_route = client.post(
        f"/api/process-route-versions/{route_version_id}/submit",
        headers=auth_headers,
        json={"row_version": 0, "idempotency_key": f"submit-{uuid.uuid4().hex}"},
    )
    assert submitted_route.status_code == 200, submitted_route.get_json()
    rejected_route = client.post(
        f"/api/process-route-versions/{route_version_id}/reject",
        headers=auth_headers,
        json={
            "row_version": submitted_route.get_json()["row_version"],
            "reason": "节点审批要求不完整",
            "idempotency_key": f"reject-{uuid.uuid4().hex}",
        },
    )
    assert rejected_route.status_code == 200, rejected_route.get_json()
    assert rejected_route.get_json()["status"] == "rejected"

    with client.application.app_context():
        batch = MasterDataReleaseService.create_batch(
            {
                "release_no": f"API-MDR-{uuid.uuid4().hex[:12]}",
                "revision_reason": "API 批次驳回验证",
                "idempotency_key": f"batch-{uuid.uuid4().hex}",
            },
            preparer,
        )

    fetched_batch = client.get(
        f"/api/master-data-release-batches/{batch['id']}", headers=auth_headers
    )
    assert fetched_batch.status_code == 200, fetched_batch.get_json()
    submitted_batch = client.post(
        f"/api/master-data-release-batches/{batch['id']}/submit",
        headers=auth_headers,
        json={"row_version": 0, "idempotency_key": f"submit-{uuid.uuid4().hex}"},
    )
    assert submitted_batch.status_code == 200, submitted_batch.get_json()
    rejected_batch = client.post(
        f"/api/master-data-release-batches/{batch['id']}/reject",
        headers=auth_headers,
        json={
            "row_version": submitted_batch.get_json()["row_version"],
            "reason": "发布依据不完整",
            "idempotency_key": f"reject-{uuid.uuid4().hex}",
        },
    )
    assert rejected_batch.status_code == 200, rejected_batch.get_json()
    assert rejected_batch.get_json()["status"] == "rejected"


def test_process_lifecycle_approval_api_uses_two_person_service_constraint(
    client, auth_headers
):
    preparer, approver = _actors(client)
    process = _create_process(client, preparer, "API 退休工序")
    _publish(client, process["version"]["id"], preparer, approver)
    process_id = process["root"]["id"]
    with client.application.app_context():
        request_record = MasterDataLifecycleService.request_process(
            process_id,
            "retire",
            {
                "reason": "旧工艺停止使用",
                "idempotency_key": f"retire-{uuid.uuid4().hex}",
            },
            preparer,
        )

    approved = client.post(
        f"/api/process-retirement-requests/{request_record['id']}/approve",
        headers=auth_headers,
        json={"row_version": 0, "idempotency_key": f"approve-{uuid.uuid4().hex}"},
    )
    assert approved.status_code == 200, approved.get_json()
    assert approved.get_json()["status"] == "approved"
