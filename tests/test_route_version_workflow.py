import uuid

import pytest

from tests.test_process_version_workflow import _actors, _create_process, _publish
from modules.domain.errors import ConflictError
from modules.domain.process_versioning import (
    ReleaseDependencyError,
    RouteProcessCategoryMismatchError,
)
from modules.domain.price_versioning import ProcessVersionNotFrozenError
from modules.repositories.route_version_repository import RouteVersionRepository
from modules.services.master_data_lifecycle_service import MasterDataLifecycleService
from modules.services.process_version_service import ProcessVersionService
from modules.services.route_version_service import RouteVersionService


def _published_process(client, preparer, approver, name, category="机加工"):
    created = _create_process(client, preparer, name)
    if category != "机加工":
        with client.application.app_context():
            ProcessVersionService.update_draft(
                created["version"]["id"],
                {"category": category, "row_version": 0},
                preparer,
            )
    with client.application.app_context():
        version = ProcessVersionService.get_version(created["version"]["id"])
    return created, _publish(client, version["id"], preparer, approver)


def _create_route(client, actor, process_versions):
    with client.application.app_context():
        return RouteVersionService.create_route(
            {
                "name": f"版本化路线-{uuid.uuid4().hex[:6]}",
                "category": "机加工",
                "description": "V1 路线草稿",
                "items": [
                    {
                        "process_id": version["process_id"],
                        "process_version_id": version["id"],
                        "seq_order": index * 10,
                        "is_required": 1,
                        "required_audit": index % 2,
                    }
                    for index, version in enumerate(process_versions, start=1)
                ],
                "idempotency_key": f"create-route-{uuid.uuid4().hex}",
            },
            actor,
        )


def _publish_route(client, version_id, preparer, approver, **approval_fields):
    with client.application.app_context():
        submitted = RouteVersionService.submit(
            version_id,
            {"row_version": 0, "idempotency_key": f"submit-route-{uuid.uuid4().hex}"},
            preparer,
        )
        return RouteVersionService.approve(
            version_id,
            {
                "row_version": submitted["row_version"],
                "idempotency_key": f"approve-route-{uuid.uuid4().hex}",
                **approval_fields,
            },
            approver,
        )


def test_new_route_is_draft_unavailable_and_publishes_stable_projection(client):
    preparer, approver = _actors(client)
    _, process = _published_process(client, preparer, approver, "路线车削")
    created = _create_route(client, preparer, [process])

    assert created["version"]["status"] == "draft"
    assert created["root"]["current_effective_version_id"] is None
    with client.application.app_context():
        with pytest.raises(ConflictError, match="尚无已发布版本"):
            RouteVersionService.resolve_current_for_business(created["root"]["id"])

    published = _publish_route(client, created["version"]["id"], preparer, approver)
    with client.application.app_context():
        root = RouteVersionRepository.root(created["root"]["id"])
        legacy_items = RouteVersionRepository.find_legacy_items(root["id"])
    assert published["status"] == "published"
    assert root["current_effective_version_id"] == published["id"]
    assert [item["process_id"] for item in legacy_items] == [process["process_id"]]


def test_route_revision_copies_nodes_and_validates_binding_category_and_sequence(client):
    preparer, approver = _actors(client)
    _, process = _published_process(client, preparer, approver, "路线铣削")
    created = _create_route(client, preparer, [process])
    _publish_route(client, created["version"]["id"], preparer, approver)

    with client.application.app_context():
        revision = RouteVersionService.create_revision(
            created["root"]["id"],
            {
                "name": "路线 V2",
                "revision_reason": "补充审批要求",
                "idempotency_key": f"route-revision-{uuid.uuid4().hex}",
            },
            preparer,
        )
        with pytest.raises(ConflictError, match="已有草稿或待审批修订版"):
            RouteVersionService.create_revision(
                created["root"]["id"],
                {
                    "revision_reason": "重复路线草稿",
                    "idempotency_key": f"route-revision-{uuid.uuid4().hex}",
                },
                preparer,
            )
    assert revision["version"] == 2
    assert revision["items"][0]["process_version_id"] == process["id"]

    _, other_category = _published_process(
        client, preparer, approver, "异类工序", category="结构件"
    )
    with client.application.app_context():
        with pytest.raises(RouteProcessCategoryMismatchError):
            RouteVersionService.update_draft(
                revision["id"],
                {
                    "row_version": revision["row_version"],
                    "items": [
                        {
                            "process_id": other_category["process_id"],
                            "process_version_id": other_category["id"],
                            "seq_order": 10,
                        }
                    ],
                },
                preparer,
            )


def test_route_publish_requires_published_process_versions_and_price_disposition(client):
    preparer, approver = _actors(client)
    draft_process = _create_process(client, preparer, "路线草稿依赖")["version"]
    created = _create_route(client, preparer, [draft_process])
    with client.application.app_context():
        with pytest.raises(ProcessVersionNotFrozenError) as process_error:
            RouteVersionService.submit(
                created["version"]["id"],
                {
                    "row_version": 0,
                    "idempotency_key": f"submit-route-{uuid.uuid4().hex}",
                },
                preparer,
            )
        assert process_error.value.details["process_version_ids"] == [draft_process["id"]]

    _, process = _published_process(client, preparer, approver, "计件路线工序")
    route = _create_route(client, preparer, [process])
    with client.application.app_context():
        submitted = RouteVersionService.submit(
            route["version"]["id"],
            {"row_version": 0, "idempotency_key": f"submit-route-{uuid.uuid4().hex}"},
            preparer,
        )
        with pytest.raises(ReleaseDependencyError) as price_error:
            RouteVersionService.approve(
                submitted["id"],
                {
                    "row_version": submitted["row_version"],
                    "idempotency_key": f"approve-route-{uuid.uuid4().hex}",
                    "required_price_process_ids": [process["process_id"]],
                    "price_dispositions": [],
                },
                approver,
            )
        assert price_error.value.details["reason_code"] == "PRICE_VERSION_BINDING_REQUIRED"
        published = RouteVersionService.approve(
            submitted["id"],
            {
                "row_version": submitted["row_version"],
                "idempotency_key": f"approve-route-{uuid.uuid4().hex}",
                "required_price_process_ids": [process["process_id"]],
                "price_dispositions": [
                    {
                        "process_id": process["process_id"],
                        "disposition": "not_applicable",
                        "reason": "该节点不采用计件工资",
                    }
                ],
            },
            approver,
        )
    assert published["status"] == "published"


def test_route_rejection_and_lifecycle_are_audited(client):
    preparer, approver = _actors(client)
    _, process = _published_process(client, preparer, approver, "路线生命周期工序")
    rejected_route = _create_route(client, preparer, [process])
    with client.application.app_context():
        submitted = RouteVersionService.submit(
            rejected_route["version"]["id"],
            {"row_version": 0, "idempotency_key": f"submit-route-{uuid.uuid4().hex}"},
            preparer,
        )
        rejected = RouteVersionService.reject(
            submitted["id"],
            {
                "row_version": submitted["row_version"],
                "reason": "节点审批要求不完整",
                "idempotency_key": f"reject-route-{uuid.uuid4().hex}",
            },
            approver,
        )
        rejection_events = RouteVersionRepository.list_events(
            rejected_route["root"]["id"]
        )
    assert rejected["status"] == "draft"
    assert rejection_events[-1]["event_type"] == "rejected"
    assert rejection_events[-1]["from_status"] == "pending_approval"
    assert rejection_events[-1]["to_status"] == "draft"

    route = _create_route(client, preparer, [process])
    published = _publish_route(client, route["version"]["id"], preparer, approver)
    request_key = f"retire-route-{uuid.uuid4().hex}"
    with client.application.app_context():
        request = MasterDataLifecycleService.request_route(
            route["root"]["id"],
            "retire",
            {"reason": "路线停止使用", "idempotency_key": request_key},
            preparer,
        )
        retired = MasterDataLifecycleService.approve_route(
            request["id"], {"row_version": 0}, approver
        )
        replay = MasterDataLifecycleService.request_route(
            route["root"]["id"],
            "retire",
            {"reason": "路线停止使用", "idempotency_key": request_key},
            preparer,
        )
        root = RouteVersionRepository.root(route["root"]["id"])
        version = RouteVersionRepository.version(published["id"])
        events = RouteVersionRepository.list_events(route["root"]["id"])

    assert retired["status"] == "approved"
    assert replay["id"] == request["id"]
    assert root["lifecycle_status"] == "retired"
    assert version["status"] == "retired"
    assert events[-1]["event_type"] == "retired"


def test_rejected_route_revision_is_edited_and_resubmitted_in_place(client):
    preparer, approver = _actors(client)
    _, process = _published_process(client, preparer, approver, "路线版本分配工序")
    route = _create_route(client, preparer, [process])
    _publish_route(client, route["version"]["id"], preparer, approver)

    with client.application.app_context():
        first_revision = RouteVersionService.create_revision(
            route["root"]["id"],
            {
                "revision_reason": "第一次修订后驳回",
                "idempotency_key": f"route-revision-{uuid.uuid4().hex}",
            },
            preparer,
        )
        submitted = RouteVersionService.submit(
            first_revision["id"],
            {
                "row_version": first_revision["row_version"],
                "idempotency_key": f"submit-route-{uuid.uuid4().hex}",
            },
            preparer,
        )
        rejected = RouteVersionService.reject(
            submitted["id"],
            {
                "row_version": submitted["row_version"],
                "reason": "保留历史后重新制单",
                "idempotency_key": f"reject-route-{uuid.uuid4().hex}",
            },
            approver,
        )
        updated = RouteVersionService.update_draft(
            rejected["id"],
            {
                "row_version": rejected["row_version"],
                "description": "驳回后修改节点说明",
            },
            preparer,
        )
        resubmitted = RouteVersionService.submit(
            updated["id"],
            {
                "row_version": updated["row_version"],
                "idempotency_key": f"resubmit-route-{uuid.uuid4().hex}",
            },
            preparer,
        )

    assert rejected["version"] == 2
    assert rejected["status"] == "draft"
    assert updated["id"] == rejected["id"]
    assert resubmitted["id"] == rejected["id"]
    assert resubmitted["version"] == 2
    assert resubmitted["status"] == "pending_approval"
    assert resubmitted["content_digest"] == RouteVersionService._content_digest(
        resubmitted
    )
