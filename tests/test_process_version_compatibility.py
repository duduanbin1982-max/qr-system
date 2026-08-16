import logging
import uuid

import pytest

from modules import config
from modules.db import get_db
from modules.domain.process_versioning import LegacyMasterDataWriteBlockedError
from modules.services.master_data_lifecycle_service import MasterDataLifecycleService
from modules.services.process_service import ProcessService
from modules.services.route_service import ProcessRouteService
from tests.test_process_management import _insert_order, _insert_process, _insert_route
from tests.test_process_version_workflow import _actors, _create_process, _publish
from tests.test_route_version_workflow import _create_route, _publish_route


def _set_flags(
    monkeypatch,
    *,
    query=False,
    audit=False,
    write=False,
    legacy_blocked=False,
):
    monkeypatch.setattr(config, "PROCESS_VERSIONED_QUERY_ENABLED", query)
    monkeypatch.setattr(config, "PROCESS_VERSION_COMPAT_AUDIT_ENABLED", audit)
    monkeypatch.setattr(config, "PROCESS_VERSIONED_WRITE_ENABLED", write)
    monkeypatch.setattr(config, "PROCESS_LEGACY_WRITE_BLOCKED", legacy_blocked)


def test_v2_query_disabled_preserves_legacy_process_and_route_contracts(
    client, monkeypatch
):
    _set_flags(monkeypatch)
    with client.application.app_context():
        db = get_db()
        process_id = _insert_process(db, "Legacy 查询工序")
        route_id = _insert_route(db, [process_id])
        db.commit()

        processes = ProcessService.list_processes(search="Legacy 查询工序")
        routes = ProcessRouteService.list_routes(search="Process Route")

    process = next(item for item in processes["processes"] if item["id"] == process_id)
    route = next(item for item in routes["routes"] if item["id"] == route_id)
    assert process["process_name"] == "Legacy 查询工序"
    assert "process_version_id" not in process
    assert route["processes"][0]["process_id"] == process_id
    assert "route_version_id" not in route


def test_v2_query_flattens_current_process_version_and_filters_retired_selection(
    client, monkeypatch
):
    _set_flags(monkeypatch, query=True)
    preparer, approver = _actors(client)
    created = _create_process(client, preparer, "V2 查询工序")
    published = _publish(client, created["version"]["id"], preparer, approver)

    with client.application.app_context():
        result = ProcessService.list_processes(search="V2 查询工序")
        process = result["processes"][0]
        retirement = MasterDataLifecycleService.request_process(
            created["root"]["id"],
            "retire",
            {
                "reason": "工艺停止使用",
                "idempotency_key": f"retire-{uuid.uuid4().hex}",
            },
            preparer,
        )
        MasterDataLifecycleService.approve_process(
            retirement["id"], {"row_version": 0}, approver
        )
        history = ProcessService.list_processes(search="V2 查询工序")
        selectable = ProcessService.list_processes(
            search="V2 查询工序", selectable=True
        )

    assert process["process_name"] == published["name"]
    assert process["process_version_id"] == published["id"]
    assert process["process_version"] == 1
    assert process["version_status"] == "published"
    assert process["lifecycle_status"] == "active"
    assert history["processes"][0]["lifecycle_status"] == "retired"
    assert selectable["processes"] == []


def test_v2_route_query_preserves_processes_and_exposes_node_versions(
    client, monkeypatch
):
    _set_flags(monkeypatch, query=True)
    preparer, approver = _actors(client)
    process = _create_process(client, preparer, "V2 路线节点")
    published_process = _publish(
        client, process["version"]["id"], preparer, approver
    )
    route = _create_route(client, preparer, [published_process])
    published_route = _publish_route(
        client, route["version"]["id"], preparer, approver
    )

    with client.application.app_context():
        result = ProcessRouteService.list_routes(search=route["root"]["name"])

    projected = result["routes"][0]
    assert projected["route_version_id"] == published_route["id"]
    assert projected["route_version"] == 1
    assert projected["version_status"] == "published"
    assert projected["processes"][0]["process_id"] == published_process["process_id"]
    assert projected["processes"][0]["process_version_id"] == published_process["id"]
    assert projected["processes"][0]["process_name"] == published_process["name"]


def test_compat_audit_logs_differences_without_changing_v2_response(
    client, monkeypatch, caplog
):
    _set_flags(monkeypatch, query=True, audit=True)
    preparer, approver = _actors(client)
    created = _create_process(client, preparer, "双读基线工序")
    published = _publish(client, created["version"]["id"], preparer, approver)

    with client.application.app_context():
        db = get_db()
        db.execute(
            "UPDATE processes SET name='故意制造的 Legacy 差异' WHERE id=?",
            (created["root"]["id"],),
        )
        db.commit()
        with caplog.at_level(logging.WARNING, logger="qr-system.compatibility"):
            result = ProcessService.list_processes()

    process = next(
        item
        for item in result["processes"]
        if item["id"] == created["root"]["id"]
    )
    assert process["process_name"] == published["name"]
    assert "master_data_compat_diff" in caplog.text
    assert "field_differences" in caplog.text


def test_legacy_crud_is_blocked_in_routes_and_services(
    client, auth_headers, monkeypatch
):
    _set_flags(
        monkeypatch, query=True, write=True, legacy_blocked=True
    )

    with pytest.raises(LegacyMasterDataWriteBlockedError):
        ProcessService.create_process({"name": "内部绕过尝试", "category": "结构件"})
    with pytest.raises(LegacyMasterDataWriteBlockedError):
        ProcessRouteService.delete_route(999999)

    requests = (
        client.post(
            "/api/processes",
            headers=auth_headers,
            json={"name": "Legacy 新增", "category": "结构件"},
        ),
        client.put(
            "/api/processes/999999",
            headers=auth_headers,
            json={"name": "Legacy 修改"},
        ),
        client.delete("/api/processes/999999", headers=auth_headers),
        client.post(
            "/api/process-routes",
            headers=auth_headers,
            json={
                "name": "Legacy 路线新增",
                "category": "结构件",
                "processes": [{"process_id": 1, "required_audit": 0}],
            },
        ),
        client.put(
            "/api/process-routes/999999",
            headers=auth_headers,
            json={
                "name": "Legacy 路线修改",
                "category": "结构件",
                "processes": [{"process_id": 1, "required_audit": 0}],
            },
        ),
        client.delete("/api/process-routes/999999", headers=auth_headers),
    )

    for response in requests:
        assert response.status_code == 409, response.get_json()
        assert response.get_json()["code"] == "LEGACY_MASTER_DATA_WRITE_BLOCKED"
        assert response.get_json()["action"] == "use_versioned_master_data_api"


def test_versioned_write_api_requires_write_flag(client, auth_headers, monkeypatch):
    preparer, _ = _actors(client)
    created = _create_process(client, preparer, "新版写入开关")
    version_id = created["version"]["id"]
    command = {
        "row_version": 0,
        "idempotency_key": f"submit-{uuid.uuid4().hex}",
    }

    _set_flags(monkeypatch)
    disabled = client.post(
        f"/api/process-versions/{version_id}/submit",
        headers=auth_headers,
        json=command,
    )
    assert disabled.status_code == 409
    assert disabled.get_json()["code"] == "PROCESS_VERSIONED_WRITE_DISABLED"

    _set_flags(monkeypatch, query=True, write=True)
    enabled = client.post(
        f"/api/process-versions/{version_id}/submit",
        headers=auth_headers,
        json=command,
    )
    assert enabled.status_code == 200, enabled.get_json()
    assert enabled.get_json()["status"] == "pending_approval"


def test_legacy_route_apply_uses_current_route_version_nodes(
    client, auth_headers, monkeypatch
):
    _set_flags(monkeypatch, query=True)
    preparer, approver = _actors(client)
    process = _create_process(client, preparer, "版本路线正确节点")
    published_process = _publish(
        client, process["version"]["id"], preparer, approver
    )
    route = _create_route(client, preparer, [published_process])
    _publish_route(client, route["version"]["id"], preparer, approver)

    with client.application.app_context():
        db = get_db()
        wrong_process_id = _insert_process(db, "Legacy 投影错误节点")
        db.execute(
            "UPDATE process_route_items SET process_id=? WHERE route_id=?",
            (wrong_process_id, route["root"]["id"]),
        )
        order_id = _insert_order(db, [])
        db.commit()

    response = client.post(
        f"/api/process-routes/{route['root']['id']}/apply",
        headers=auth_headers,
        json={"order_id": order_id},
    )
    assert response.status_code == 200, response.get_json()

    with client.application.app_context():
        process_ids = [
            row["process_id"]
            for row in get_db().execute(
                "SELECT process_id FROM order_processes WHERE order_id=? ORDER BY seq_order",
                (order_id,),
            ).fetchall()
        ]
    assert process_ids == [published_process["process_id"]]


@pytest.mark.parametrize(
    "flags",
    [
        {
            "PROCESS_VERSIONED_QUERY_ENABLED": False,
            "PROCESS_VERSION_COMPAT_AUDIT_ENABLED": True,
            "PROCESS_VERSIONED_WRITE_ENABLED": False,
            "PROCESS_LEGACY_WRITE_BLOCKED": False,
        },
        {
            "PROCESS_VERSIONED_QUERY_ENABLED": False,
            "PROCESS_VERSION_COMPAT_AUDIT_ENABLED": False,
            "PROCESS_VERSIONED_WRITE_ENABLED": True,
            "PROCESS_LEGACY_WRITE_BLOCKED": False,
        },
        {
            "PROCESS_VERSIONED_QUERY_ENABLED": True,
            "PROCESS_VERSION_COMPAT_AUDIT_ENABLED": False,
            "PROCESS_VERSIONED_WRITE_ENABLED": False,
            "PROCESS_LEGACY_WRITE_BLOCKED": True,
        },
    ],
)
def test_invalid_process_versioning_flag_combinations_fail_fast(flags):
    with pytest.raises(RuntimeError, match="工序版本化功能开关组合无效"):
        config.validate_process_versioning_flags(flags)
