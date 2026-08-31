import uuid

import jsonschema
import pytest

from modules import config
from tests.test_process_version_workflow import _actors, _create_process, _publish
from tests.test_route_version_workflow import _create_route, _publish_route
from modules.db import get_db
from modules.domain.errors import ConflictError
from modules.domain.price_versioning import (
    PriceBindingMismatchError,
    PriceBindingStaleError,
    PriceVersionVoidedError,
)
from modules.domain.process_versioning import ReleaseDependencyError
from modules.repositories.master_data_release_repository import MasterDataReleaseRepository
from modules.repositories.payroll_repository import PayrollRepository
from modules.repositories.process_version_repository import ProcessVersionRepository
from modules.repositories.route_version_repository import RouteVersionRepository
from modules.schemas import SCHEMAS
from modules.services.master_data_release_service import MasterDataReleaseService
from modules.services.price_version_service import PriceVersionService
from modules.services.process_version_service import ProcessVersionService
from modules.services.route_version_service import RouteVersionService
from tests.pending_route_price_helpers import create_exact_price_for_route_item


@pytest.fixture(autouse=True)
def enable_pending_price_write(monkeypatch):
    monkeypatch.setattr(config, "PROCESS_VERSIONED_WRITE_ENABLED", True)
    monkeypatch.setattr(config, "ROUTE_PRICE_PENDING_REFERENCE_ENABLED", True)
    monkeypatch.setattr(config, "ROUTE_PRICE_PENDING_COMPAT_AUDIT_ENABLED", True)
    monkeypatch.setattr(config, "ROUTE_PRICE_PENDING_WRITE_ENABLED", True)


def _submitted_process_revision(client, root_id, preparer, **changes):
    with client.application.app_context():
        revision = ProcessVersionService.create_revision(
            root_id,
            {
                "revision_reason": "成组发布工序修订",
                "idempotency_key": f"batch-process-revision-{uuid.uuid4().hex}",
                **changes,
            },
            preparer,
        )
        return ProcessVersionService.submit(
            revision["id"],
            {"row_version": 0, "idempotency_key": f"batch-process-submit-{uuid.uuid4().hex}"},
            preparer,
        )


def _submitted_route_revision(client, root_id, preparer, items):
    with client.application.app_context():
        revision = RouteVersionService.create_revision(
            root_id,
            {
                "items": items,
                "revision_reason": "同步工序修订",
                "idempotency_key": f"batch-route-revision-{uuid.uuid4().hex}",
            },
            preparer,
        )
        return RouteVersionService.submit(
            revision["id"],
            {"row_version": 0, "idempotency_key": f"batch-route-submit-{uuid.uuid4().hex}"},
            preparer,
        )


def _create_batch(client, preparer, process_ids=(), route_ids=(), price_ids=()):
    with client.application.app_context():
        return MasterDataReleaseService.create_batch(
            {
                "release_no": f"MDR-{uuid.uuid4().hex[:12].upper()}",
                "revision_reason": "工序路线成组发布",
                "process_version_ids": list(process_ids),
                "route_version_ids": list(route_ids),
                "price_version_ids": list(price_ids),
                "idempotency_key": f"release-batch-{uuid.uuid4().hex}",
            },
            preparer,
        )


def _pending_release_fixture(
    client,
    preparer,
    approver,
    *,
    process_creator=None,
    route_creator=None,
    price_creator=None,
    batch_creator=None,
):
    process_creator = process_creator or preparer
    route_creator = route_creator or preparer
    price_creator = price_creator or preparer
    batch_creator = batch_creator or preparer
    created = _create_process(
        client, process_creator, f"成组发布职责工序-{uuid.uuid4().hex[:6]}"
    )
    with client.application.app_context():
        process = ProcessVersionService.submit(
            created["version"]["id"],
            {
                "row_version": created["version"]["row_version"],
                "idempotency_key": f"duty-process-submit-{uuid.uuid4().hex}",
            },
            process_creator,
        )
    route_created = _create_route(client, route_creator, [process])
    with client.application.app_context():
        route = RouteVersionService.submit(
            route_created["version"]["id"],
            {
                "row_version": route_created["version"]["row_version"],
                "idempotency_key": f"duty-route-submit-{uuid.uuid4().hex}",
            },
            route_creator,
        )
        price = create_exact_price_for_route_item(
            route, route["items"][0], price_creator, "1.25"
        )
    batch = _create_batch(
        client,
        batch_creator,
        [process["id"]],
        [route["id"]],
        [price["id"]],
    )
    return process, route, price, batch


def test_release_batch_members_include_route_nodes_for_dependency_display(client):
    preparer, approver = _actors(client)
    process_created = _create_process(client, preparer, "发布批次节点工序")
    process = _publish(
        client, process_created["version"]["id"], preparer, approver
    )
    route = _create_route(client, preparer, [process])
    batch = _create_batch(client, preparer, route_ids=[route["version"]["id"]])

    with client.application.app_context():
        loaded = MasterDataReleaseRepository.batch(batch["id"])

    assert len(loaded["route_versions"]) == 1
    assert loaded["route_versions"][0]["items"] == route["version"]["items"]
    assert loaded["route_versions"][0]["items"][0]["process_version_id"] == process["id"]


def test_process_change_affecting_current_route_requires_revision_or_approved_exception(client):
    preparer, approver = _actors(client)
    process_created = _create_process(client, preparer, "受影响路线工序")
    process_v1 = _publish(client, process_created["version"]["id"], preparer, approver)
    route_created = _create_route(client, preparer, [process_v1])
    route_v1 = _publish_route(client, route_created["version"]["id"], preparer, approver)
    process_v2 = _submitted_process_revision(
        client, process_created["root"]["id"], preparer, name="受影响路线工序 V2"
    )
    batch = _create_batch(client, preparer, [process_v2["id"]])

    with client.application.app_context():
        with pytest.raises(ReleaseDependencyError) as missing:
            MasterDataReleaseService.submit(
                batch["id"],
                {"row_version": 0, "idempotency_key": f"submit-batch-{uuid.uuid4().hex}"},
                preparer,
            )
        assert missing.value.details["reason_code"] == (
            "AFFECTED_ROUTE_REVISION_OR_EXCEPTION_REQUIRED"
        )

        exception = {
            "route_version_id": route_v1["id"],
            "retained_process_version_id": process_v1["id"],
            "replacement_process_version_id": process_v2["id"],
            "reason": "该路线在批准有效期内继续使用旧工序",
            "approved_by": approver["id"],
            "approved_by_name": approver["name"],
            "valid_from": "2026-08-12 07:00:00",
            "valid_to": "2026-09-01 07:00:00",
        }
        submitted = MasterDataReleaseService.submit(
            batch["id"],
            {
                "row_version": 0,
                "approved_exceptions": [exception],
                "idempotency_key": f"submit-batch-{uuid.uuid4().hex}",
            },
            preparer,
        )
        persisted = MasterDataReleaseRepository.batch(batch["id"])[
            "approved_exceptions"
        ]
    assert submitted["status"] == "pending_approval"
    assert len(persisted) == 1
    assert persisted[0]["reason"] == exception["reason"]


def test_atomic_batch_publishes_process_then_route_and_is_idempotent(client):
    preparer, approver = _actors(client)
    process_created = _create_process(client, preparer, "成组切换工序")
    process_v1 = _publish(client, process_created["version"]["id"], preparer, approver)
    route_created = _create_route(client, preparer, [process_v1])
    _publish_route(client, route_created["version"]["id"], preparer, approver)
    process_v2 = _submitted_process_revision(
        client, process_created["root"]["id"], preparer, name="成组切换工序 V2"
    )
    route_v2 = _submitted_route_revision(
        client,
        route_created["root"]["id"],
        preparer,
        [
            {
                "process_id": process_v2["process_id"],
                "process_version_id": process_v2["id"],
                "seq_order": 10,
                "is_required": 1,
                "required_audit": 1,
            }
        ],
    )
    with client.application.app_context():
        price = create_exact_price_for_route_item(
            route_v2, route_v2["items"][0], preparer, "1.25"
        )
    batch = _create_batch(
        client,
        preparer,
        [process_v2["id"]],
        [route_v2["id"]],
        [price["id"]],
    )

    with client.application.app_context():
        submitted = MasterDataReleaseService.submit(
            batch["id"],
            {"row_version": 0, "idempotency_key": f"submit-batch-{uuid.uuid4().hex}"},
            preparer,
        )
        command = {
            "row_version": submitted["row_version"],
            "idempotency_key": f"approve-batch-{uuid.uuid4().hex}",
            "required_price_process_ids": [process_v2["process_id"]],
            "price_dispositions": [
                {
                    "process_id": process_v2["process_id"],
                    "disposition": "price_version",
                    "price_version_id": price["id"],
                }
            ],
        }
        published = MasterDataReleaseService.approve(batch["id"], command, approver)
        replay = MasterDataReleaseService.approve(batch["id"], command, approver)
        process_root = ProcessVersionRepository.root(process_v2["process_id"])
        route_root = RouteVersionRepository.root(route_v2["process_route_id"])
        approved_price = PayrollRepository.price_version(price["id"])

    assert published["status"] == "published"
    assert replay == published
    assert process_root["current_effective_version_id"] == process_v2["id"]
    assert route_root["current_effective_version_id"] == route_v2["id"]
    assert approved_price["status"] == "approved"
    assert approved_price["route_version_id"] == route_v2["id"]
    assert approved_price["process_version_id"] == process_v2["id"]


def test_price_approval_failure_rolls_back_process_and_route_switches(
    client, monkeypatch
):
    preparer, approver = _actors(client)
    process_created = _create_process(client, preparer, "工价失败回滚工序")
    process_v1 = _publish(
        client, process_created["version"]["id"], preparer, approver
    )
    route_created = _create_route(client, preparer, [process_v1])
    route_v1 = _publish_route(
        client, route_created["version"]["id"], preparer, approver
    )
    process_v2 = _submitted_process_revision(
        client, process_v1["process_id"], preparer, name="工价失败回滚工序 V2"
    )
    route_v2 = _submitted_route_revision(
        client,
        route_v1["process_route_id"],
        preparer,
        [
            {
                "process_id": process_v2["process_id"],
                "process_version_id": process_v2["id"],
                "seq_order": 10,
                "is_required": 1,
                "required_audit": 0,
            }
        ],
    )
    with client.application.app_context():
        price = create_exact_price_for_route_item(
            route_v2, route_v2["items"][0], preparer, "1.50"
        )
    batch = _create_batch(
        client,
        preparer,
        [process_v2["id"]],
        [route_v2["id"]],
        [price["id"]],
    )

    with client.application.app_context():
        submitted = MasterDataReleaseService.submit(
            batch["id"],
            {
                "row_version": 0,
                "idempotency_key": f"submit-batch-{uuid.uuid4().hex}",
            },
            preparer,
        )

        def fail_price_approval(*args, **kwargs):
            raise RuntimeError("simulated price approval failure")

        monkeypatch.setattr(
            PayrollRepository, "approve_price_version", fail_price_approval
        )
        with pytest.raises(RuntimeError, match="simulated price approval failure"):
            MasterDataReleaseService.approve(
                batch["id"],
                {
                    "row_version": submitted["row_version"],
                    "idempotency_key": f"approve-batch-{uuid.uuid4().hex}",
                    "required_price_process_ids": [process_v2["process_id"]],
                    "price_dispositions": [
                        {
                            "process_id": process_v2["process_id"],
                            "disposition": "price_version",
                            "price_version_id": price["id"],
                        }
                    ],
                },
                approver,
            )

        assert ProcessVersionRepository.version(process_v2["id"])["status"] == "pending_approval"
        assert RouteVersionRepository.version(route_v2["id"])["status"] == "pending_approval"
        assert PayrollRepository.price_version(price["id"])["status"] == "draft"
        assert ProcessVersionRepository.root(process_v1["process_id"])[
            "current_effective_version_id"
        ] == process_v1["id"]
        assert RouteVersionRepository.root(route_v1["process_route_id"])[
            "current_effective_version_id"
        ] == route_v1["id"]


def test_batch_failure_rolls_back_all_member_statuses_and_pointers(client, monkeypatch):
    preparer, approver = _actors(client)
    process_created = _create_process(client, preparer, "原子回滚工序")
    process_v1 = _publish(client, process_created["version"]["id"], preparer, approver)
    route_created = _create_route(client, preparer, [process_v1])
    route_v1 = _publish_route(client, route_created["version"]["id"], preparer, approver)
    process_v2 = _submitted_process_revision(client, process_v1["process_id"], preparer)
    route_v2 = _submitted_route_revision(
        client,
        route_v1["process_route_id"],
        preparer,
        [{
            "process_id": process_v2["process_id"],
            "process_version_id": process_v2["id"],
            "seq_order": 10,
            "is_required": 1,
            "required_audit": 0,
        }],
    )
    batch = _create_batch(client, preparer, [process_v2["id"]], [route_v2["id"]])
    with client.application.app_context():
        submitted = MasterDataReleaseService.submit(
            batch["id"],
            {"row_version": 0, "idempotency_key": f"submit-batch-{uuid.uuid4().hex}"},
            preparer,
        )

        def fail_projection(*args, **kwargs):
            raise RuntimeError("simulated route projection failure")

        monkeypatch.setattr(
            RouteVersionRepository, "update_compatibility_projection", fail_projection
        )
        with pytest.raises(RuntimeError, match="simulated route projection failure"):
            MasterDataReleaseService.approve(
                batch["id"],
                {
                    "row_version": submitted["row_version"],
                    "idempotency_key": f"approve-batch-{uuid.uuid4().hex}",
                },
                approver,
            )
        assert ProcessVersionRepository.version(process_v2["id"])["status"] == "pending_approval"
        assert RouteVersionRepository.version(route_v2["id"])["status"] == "pending_approval"
        assert ProcessVersionRepository.root(process_v1["process_id"])[
            "current_effective_version_id"
        ] == process_v1["id"]
        assert RouteVersionRepository.root(route_v1["process_route_id"])[
            "current_effective_version_id"
        ] == route_v1["id"]
        assert MasterDataReleaseRepository.batch(batch["id"])["status"] == "pending_approval"


def test_batch_approval_rejects_impact_drift(client):
    preparer, approver = _actors(client)
    created = _create_process(client, preparer, "批次影响漂移")
    process_v1 = _publish(client, created["version"]["id"], preparer, approver)
    process_v2 = _submitted_process_revision(client, process_v1["process_id"], preparer)
    batch = _create_batch(client, preparer, [process_v2["id"]])
    with client.application.app_context():
        submitted = MasterDataReleaseService.submit(
            batch["id"],
            {"row_version": 0, "idempotency_key": f"submit-batch-{uuid.uuid4().hex}"},
            preparer,
        )
        db = get_db()
        db.execute(
            "INSERT INTO approval_config "
            "(process_id,require_approval,approver_role,approval_level) "
            "VALUES (?,1,'admin',1)",
            (process_v1["process_id"],),
        )
        db.commit()
        with pytest.raises(ConflictError, match="影响范围已变化"):
            MasterDataReleaseService.approve(
                batch["id"],
                {
                    "row_version": submitted["row_version"],
                    "idempotency_key": f"approve-batch-{uuid.uuid4().hex}",
                },
                approver,
            )


def test_batch_creation_idempotency_does_not_append_members(client):
    preparer, _ = _actors(client)
    first = _create_process(client, preparer, "幂等批次工序一")["version"]
    second = _create_process(client, preparer, "幂等批次工序二")["version"]
    key = f"release-batch-{uuid.uuid4().hex}"
    with client.application.app_context():
        created = MasterDataReleaseService.create_batch(
            {
                "release_no": f"MDR-{uuid.uuid4().hex[:12].upper()}",
                "revision_reason": "批次幂等验证",
                "process_version_ids": [first["id"]],
                "idempotency_key": key,
            },
            preparer,
        )
        replay = MasterDataReleaseService.create_batch(
            {
                "release_no": "MDR-REPLAY-SHOULD-NOT-APPLY",
                "revision_reason": "重放不得追加成员",
                "process_version_ids": [second["id"]],
                "idempotency_key": key,
            },
            preparer,
        )
        member_events = MasterDataReleaseRepository.list_release_member_events(
            created["id"]
        )

    assert replay["id"] == created["id"]
    assert [item["id"] for item in replay["process_versions"]] == [first["id"]]
    assert [(event["action"], event["member_id"]) for event in member_events] == [
        ("added", first["id"])
    ]


def test_draft_batch_can_auditably_replace_voided_price(client):
    preparer, approver = _actors(client)
    _, route, price, _ = _pending_release_fixture(client, preparer, approver)
    with client.application.app_context():
        voided_price = PriceVersionService.void(
            price["id"],
            {
                "row_version": price["row_version"],
                "reason": "金额录入错误",
                "idempotency_key": f"void-price-{uuid.uuid4().hex}",
            },
            preparer,
        )
        replacement = create_exact_price_for_route_item(
            route, route["items"][0], preparer, "1.50"
        )
    batch = _create_batch(
        client,
        preparer,
        route_ids=[route["id"]],
        price_ids=[voided_price["id"]],
    )
    command = {
        "member_type": "price_version",
        "member_id": voided_price["id"],
        "replacement_member_id": replacement["id"],
        "row_version": batch["row_version"],
        "reason": "替换已作废工价",
        "idempotency_key": f"replace-voided-price-{uuid.uuid4().hex}",
    }
    with client.application.app_context():
        result = MasterDataReleaseService.replace_member(
            batch["id"], command, preparer
        )
        replay = MasterDataReleaseService.replace_member(
            batch["id"], command, preparer
        )
        event = MasterDataReleaseRepository.list_release_member_events(batch["id"])[-1]
    assert [row["id"] for row in result["price_versions"]] == [replacement["id"]]
    assert replay == result
    assert result["row_version"] == batch["row_version"] + 1
    assert result["impact_digest"]
    assert event["action"] == "replaced"
    assert event["member_id"] == voided_price["id"]
    assert event["replacement_member_id"] == replacement["id"]


def test_draft_batch_member_remove_is_audited_and_submitted_batch_is_immutable(client):
    preparer, approver = _actors(client)
    process, route, price, batch = _pending_release_fixture(
        client, preparer, approver
    )
    with client.application.app_context():
        removed = MasterDataReleaseService.remove_member(
            batch["id"],
            {
                "member_type": "price_version",
                "member_id": price["id"],
                "row_version": batch["row_version"],
                "reason": "调整发布范围",
                "idempotency_key": f"remove-price-{uuid.uuid4().hex}",
            },
            preparer,
        )
        event = MasterDataReleaseRepository.list_release_member_events(batch["id"])[-1]
    assert removed["price_versions"] == []
    assert event["action"] == "removed"

    complete = _create_batch(
        client,
        preparer,
        [process["id"]],
        [route["id"]],
        [price["id"]],
    )
    with client.application.app_context():
        submitted = MasterDataReleaseService.submit(
            complete["id"],
            {
                "row_version": complete["row_version"],
                "idempotency_key": f"submit-before-mutation-{uuid.uuid4().hex}",
            },
            preparer,
        )
        with pytest.raises(ConflictError, match="只有草稿"):
            MasterDataReleaseService.remove_member(
                submitted["id"],
                {
                    "member_type": "price_version",
                    "member_id": price["id"],
                    "row_version": submitted["row_version"],
                    "reason": "不允许修改",
                    "idempotency_key": f"remove-submitted-{uuid.uuid4().hex}",
                },
                preparer,
            )


def test_voided_price_blocks_batch_submit(client):
    preparer, approver = _actors(client)
    _, _, price, batch = _pending_release_fixture(client, preparer, approver)
    with client.application.app_context():
        PriceVersionService.void(
            price["id"],
            {
                "row_version": price["row_version"],
                "reason": "提交前作废",
                "idempotency_key": f"void-before-submit-{uuid.uuid4().hex}",
            },
            preparer,
        )
        with pytest.raises(PriceVersionVoidedError):
            MasterDataReleaseService.submit(
                batch["id"],
                {
                    "row_version": batch["row_version"],
                    "idempotency_key": f"submit-voided-{uuid.uuid4().hex}",
                },
                preparer,
            )


def test_stale_price_snapshot_blocks_batch_submit(client, monkeypatch):
    preparer, approver = _actors(client)
    _, _, _, batch = _pending_release_fixture(client, preparer, approver)
    original = PayrollRepository.exact_price_binding

    def stale_binding(*args, **kwargs):
        binding = original(*args, **kwargs)
        return {**binding, "process_content_digest": "changed-after-price-create"}

    monkeypatch.setattr(PayrollRepository, "exact_price_binding", stale_binding)
    with client.application.app_context():
        with pytest.raises(PriceBindingStaleError):
            MasterDataReleaseService.submit(
                batch["id"],
                {
                    "row_version": batch["row_version"],
                    "idempotency_key": f"submit-stale-{uuid.uuid4().hex}",
                },
                preparer,
            )


def test_price_not_matching_any_batch_route_node_blocks_submit(client):
    preparer, approver = _actors(client)
    _, _, foreign_price, _ = _pending_release_fixture(client, preparer, approver)
    process, route, _, _ = _pending_release_fixture(client, preparer, approver)
    batch = _create_batch(
        client,
        preparer,
        [process["id"]],
        [route["id"]],
        [foreign_price["id"]],
    )
    with client.application.app_context():
        with pytest.raises(PriceBindingMismatchError):
            MasterDataReleaseService.submit(
                batch["id"],
                {
                    "row_version": batch["row_version"],
                    "idempotency_key": f"submit-mismatch-{uuid.uuid4().hex}",
                },
                preparer,
            )


@pytest.mark.parametrize(
    "matching_creator",
    ["batch_creator", "process_creator", "route_creator", "price_creator"],
)
def test_batch_approver_must_differ_from_every_member_creator(
    client, matching_creator
):
    preparer, approver = _actors(client)
    creators = {matching_creator: approver}
    _, _, _, batch = _pending_release_fixture(
        client, preparer, approver, **creators
    )
    submit_actor = approver if matching_creator == "batch_creator" else preparer
    with client.application.app_context():
        submitted = MasterDataReleaseService.submit(
            batch["id"],
            {
                "row_version": batch["row_version"],
                "idempotency_key": f"duty-submit-{uuid.uuid4().hex}",
            },
            submit_actor,
        )
        with pytest.raises(ConflictError, match="制单人与批准人必须不同"):
            MasterDataReleaseService.approve(
                batch["id"],
                {
                    "row_version": submitted["row_version"],
                    "idempotency_key": f"duty-approve-{uuid.uuid4().hex}",
                },
                approver,
            )


def test_release_member_mutation_schemas_are_strict():
    remove = {
        "member_type": "price_version",
        "member_id": 11,
        "row_version": 0,
        "reason": "移除失效工价",
        "idempotency_key": "remove-member-001",
    }
    replace = {**remove, "replacement_member_id": 12}
    jsonschema.validate(remove, SCHEMAS["master_data_release_member_remove"])
    jsonschema.validate(replace, SCHEMAS["master_data_release_member_replace"])
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {**remove, "member_type": "unsupported"},
            SCHEMAS["master_data_release_member_remove"],
        )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {**replace, "unexpected": True},
            SCHEMAS["master_data_release_member_replace"],
        )


def test_release_member_remove_api_uses_strict_schema(client, auth_headers):
    preparer, _ = _actors(client)
    process = _create_process(client, preparer, "成员 API 工序")["version"]
    created = client.post(
        "/api/master-data-release-batches",
        headers=auth_headers,
        json={
            "release_no": f"API-MEMBER-{uuid.uuid4().hex[:10]}",
            "revision_reason": "验证成员移除接口",
            "process_version_ids": [process["id"]],
            "idempotency_key": f"api-member-create-{uuid.uuid4().hex}",
        },
    )
    assert created.status_code == 201, created.get_json()
    batch = created.get_json()
    removed = client.post(
        f"/api/master-data-release-batches/{batch['id']}/members/remove",
        headers=auth_headers,
        json={
            "member_type": "process_version",
            "member_id": process["id"],
            "row_version": batch["row_version"],
            "reason": "调整发布范围",
            "idempotency_key": f"api-member-remove-{uuid.uuid4().hex}",
        },
    )
    assert removed.status_code == 200, removed.get_json()
    assert removed.get_json()["process_versions"] == []

    invalid = client.post(
        f"/api/master-data-release-batches/{batch['id']}/members/remove",
        headers=auth_headers,
        json={
            "member_type": "process_version",
            "member_id": process["id"],
            "row_version": removed.get_json()["row_version"],
            "reason": "字段错误",
            "idempotency_key": f"api-member-invalid-{uuid.uuid4().hex}",
            "unexpected": True,
        },
    )
    assert invalid.status_code == 400
