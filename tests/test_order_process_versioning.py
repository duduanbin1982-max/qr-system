import uuid

import pytest

from modules.db import get_db
from modules.domain.errors import ConflictError
from modules.domain.work_report import WorkReportCommand
from modules.repositories.scan_repository import ScanRepository
from modules.services.master_data_lifecycle_service import MasterDataLifecycleService
from modules.services.order_service import OrderService
from modules.services.process_version_service import ProcessVersionService
from modules.services.route_service import ProcessRouteService
from modules.services.route_version_service import RouteVersionService
from modules.services.scan_helper_service import ScanHelperService
from modules.services.work_report_writer import WorkReportWriter
from tests.test_process_version_workflow import _actors, _create_process, _publish
from tests.test_route_version_workflow import _create_route, _publish_route


def _published_processes(client, preparer, approver, count=1):
    published = []
    for index in range(count):
        created = _create_process(client, preparer, f"订单版本工序-{index + 1}")
        published.append(
            _publish(client, created["version"]["id"], preparer, approver)
        )
    return published


def _published_route(client, preparer, approver, process_versions):
    created = _create_route(client, preparer, process_versions)
    published = _publish_route(
        client, created["version"]["id"], preparer, approver
    )
    return created, published


def _create_order(client, *, route_id=None, process_ids=None):
    with client.application.app_context():
        order_id, _ = OrderService.create_order(
            {
                "order_no": f"ORDER-VERSION-{uuid.uuid4().hex[:10].upper()}",
                "product_name": "版本化订单产品",
                "product_code": f"PV-{uuid.uuid4().hex[:8].upper()}",
                "quantity": 10,
                "route_id": route_id,
                "process_ids": list(process_ids or []),
            }
        )
        return order_id


def _order_binding(client, order_id):
    with client.application.app_context():
        db = get_db()
        order = dict(
            db.execute(
                "SELECT route_id,route_version_id,route_name_snapshot "
                "FROM orders WHERE id=?",
                (order_id,),
            ).fetchone()
        )
        processes = [
            dict(row)
            for row in db.execute(
                "SELECT process_id,process_version_id,process_code_snapshot,"
                "process_name_snapshot,process_category_snapshot,seq_order,required_audit "
                "FROM order_processes WHERE order_id=? ORDER BY seq_order,id",
                (order_id,),
            ).fetchall()
        ]
        return order, processes


def test_order_creation_freezes_published_route_and_node_versions(client):
    preparer, approver = _actors(client)
    processes = _published_processes(client, preparer, approver, count=2)
    route, published_route = _published_route(client, preparer, approver, processes)

    order_id = _create_order(client, route_id=route["root"]["id"])
    order, order_processes = _order_binding(client, order_id)

    assert order == {
        "route_id": route["root"]["id"],
        "route_version_id": published_route["id"],
        "route_name_snapshot": published_route["name"],
    }
    assert [row["process_version_id"] for row in order_processes] == [
        process["id"] for process in processes
    ]
    assert [row["process_name_snapshot"] for row in order_processes] == [
        process["name"] for process in processes
    ]
    assert all(row["process_code_snapshot"] for row in order_processes)
    assert all(row["process_category_snapshot"] == "机加工" for row in order_processes)


def test_new_route_revision_only_affects_new_orders(client):
    preparer, approver = _actors(client)
    processes = _published_processes(client, preparer, approver)
    route, route_v1 = _published_route(client, preparer, approver, processes)
    first_order_id = _create_order(client, route_id=route["root"]["id"])

    with client.application.app_context():
        revision = RouteVersionService.create_revision(
            route["root"]["id"],
            {
                "name": "订单使用的路线 V2",
                "revision_reason": "调整路线名称和审批要求",
                "idempotency_key": f"order-route-revision-{uuid.uuid4().hex}",
            },
            preparer,
        )
        submitted = RouteVersionService.submit(
            revision["id"],
            {
                "row_version": revision["row_version"],
                "idempotency_key": f"order-route-submit-{uuid.uuid4().hex}",
            },
            preparer,
        )
        route_v2 = RouteVersionService.approve(
            revision["id"],
            {
                "row_version": submitted["row_version"],
                "idempotency_key": f"order-route-approve-{uuid.uuid4().hex}",
            },
            approver,
        )

    second_order_id = _create_order(client, route_id=route["root"]["id"])
    first_order, _ = _order_binding(client, first_order_id)
    second_order, _ = _order_binding(client, second_order_id)

    assert first_order["route_version_id"] == route_v1["id"]
    assert first_order["route_name_snapshot"] == route_v1["name"]
    assert second_order["route_version_id"] == route_v2["id"]
    assert second_order["route_name_snapshot"] == route_v2["name"]


def test_custom_process_orders_freeze_each_current_process_revision(client):
    preparer, approver = _actors(client)
    created = _create_process(client, preparer, "自定义订单工序")
    process_v1 = _publish(client, created["version"]["id"], preparer, approver)
    first_order_id = _create_order(
        client, process_ids=[created["root"]["id"]]
    )

    with client.application.app_context():
        revision = ProcessVersionService.create_revision(
            created["root"]["id"],
            {
                "name": "自定义订单工序 V2",
                "revision_reason": "调整工序作业语义",
                "idempotency_key": f"order-process-revision-{uuid.uuid4().hex}",
            },
            preparer,
        )
        submitted = ProcessVersionService.submit(
            revision["id"],
            {
                "row_version": revision["row_version"],
                "idempotency_key": f"order-process-submit-{uuid.uuid4().hex}",
            },
            preparer,
        )
        process_v2 = ProcessVersionService.approve(
            revision["id"],
            {
                "row_version": submitted["row_version"],
                "idempotency_key": f"order-process-approve-{uuid.uuid4().hex}",
            },
            approver,
        )

    second_order_id = _create_order(
        client, process_ids=[created["root"]["id"]]
    )
    _, first_processes = _order_binding(client, first_order_id)
    _, second_processes = _order_binding(client, second_order_id)

    assert first_processes[0]["process_version_id"] == process_v1["id"]
    assert first_processes[0]["process_name_snapshot"] == process_v1["name"]
    assert second_processes[0]["process_version_id"] == process_v2["id"]
    assert second_processes[0]["process_name_snapshot"] == process_v2["name"]


def test_orders_reject_routes_without_current_version_or_after_retirement(client):
    preparer, approver = _actors(client)
    process = _published_processes(client, preparer, approver)[0]
    draft_route = _create_route(client, preparer, [process])

    with pytest.raises(ConflictError, match="尚无已发布版本"):
        _create_order(client, route_id=draft_route["root"]["id"])

    published = _publish_route(
        client, draft_route["version"]["id"], preparer, approver
    )
    with client.application.app_context():
        request = MasterDataLifecycleService.request_route(
            draft_route["root"]["id"],
            "retire",
            {
                "reason": "路线已不再接单",
                "idempotency_key": f"order-route-retire-{uuid.uuid4().hex}",
            },
            preparer,
        )
        MasterDataLifecycleService.approve_route(
            request["id"], {"row_version": request["row_version"]}, approver
        )

    assert published["id"]
    with pytest.raises(ConflictError, match="已退休"):
        _create_order(client, route_id=draft_route["root"]["id"])


def test_route_reapplication_writes_exact_binding_and_stays_blocked_after_reporting(client):
    preparer, approver = _actors(client)
    process = _published_processes(client, preparer, approver)[0]
    route, published_route = _published_route(client, preparer, approver, [process])
    order_id = _create_order(client, process_ids=[process["process_id"]])

    with client.application.app_context():
        applied_count = ProcessRouteService.apply_route(route["root"]["id"], order_id)
    order, processes = _order_binding(client, order_id)
    assert applied_count == 1
    assert order["route_version_id"] == published_route["id"]
    assert processes[0]["process_version_id"] == process["id"]

    with client.application.app_context():
        ScanHelperService.insert_work_record(
            order_id,
            process["process_id"],
            preparer["id"],
            "normal",
            1,
            "",
            "approved",
            None,
        )
        get_db().commit()
        with pytest.raises(ValueError, match="不能重新应用工艺路线"):
            ProcessRouteService.apply_route(route["root"]["id"], order_id)


def test_scan_display_and_work_fact_inherit_order_snapshots_and_retry_stays_unique(client):
    preparer, approver = _actors(client)
    processes = _published_processes(client, preparer, approver, count=2)
    route, published_route = _published_route(client, preparer, approver, processes)
    order_id = _create_order(client, route_id=route["root"]["id"])
    process = processes[0]

    with client.application.app_context():
        db = get_db()
        db.execute(
            "UPDATE processes SET name='当前根已改名' WHERE id=?",
            (process["process_id"],),
        )
        db.commit()

        displayed = [dict(row) for row in ScanHelperService.get_order_processes(order_id)]
        assert displayed[0]["process_name"] == process["name"]
        assert displayed[0]["process_version_id"] == process["id"]

        command = WorkReportCommand(
            report_type="normal",
            order_id=order_id,
            process_id=process["process_id"],
            user_id=preparer["id"],
            user_name=preparer["name"],
            quantity=1,
        )
        WorkReportWriter.execute_report_write(command)
        with pytest.raises(ValueError, match="此工序已报工"):
            WorkReportWriter.execute_report_write(command)

        work = dict(
            db.execute(
                "SELECT process_id,process_version_id,process_code_snapshot,"
                "process_name_snapshot,process_category_snapshot,route_id,"
                "route_version_id,route_name_snapshot FROM work_records "
                "WHERE order_id=? AND process_id=?",
                (order_id, process["process_id"]),
            ).fetchone()
        )
        count = db.execute(
            "SELECT COUNT(*) FROM work_records WHERE order_id=? AND process_id=?",
            (order_id, process["process_id"]),
        ).fetchone()[0]

        assert work == {
            "process_id": process["process_id"],
            "process_version_id": process["id"],
            "process_code_snapshot": process["process_code_snapshot"],
            "process_name_snapshot": process["name"],
            "process_category_snapshot": process["category"],
            "route_id": route["root"]["id"],
            "route_version_id": published_route["id"],
            "route_name_snapshot": published_route["name"],
        }
        assert count == 1
        assert ScanRepository.order_has_process_in_scope(
            order_id, [process["process_id"]], db=db
        )
        assert not ScanRepository.order_has_process_in_scope(
            order_id, [999999], db=db
        )
