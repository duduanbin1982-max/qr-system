import uuid

import pytest

from tests.test_process_version_workflow import _actors, _create_process, _publish
from tests.test_route_version_workflow import _create_route, _publish_route
from modules.db import get_db
from modules.domain.errors import ConflictError
from modules.domain.process_versioning import ReleaseDependencyError
from modules.repositories.master_data_release_repository import MasterDataReleaseRepository
from modules.repositories.payroll_repository import PayrollRepository
from modules.repositories.process_version_repository import ProcessVersionRepository
from modules.repositories.route_version_repository import RouteVersionRepository
from modules.services.master_data_release_service import MasterDataReleaseService
from modules.services.price_version_service import PriceVersionService
from modules.services.process_version_service import ProcessVersionService
from modules.services.route_version_service import RouteVersionService


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
        price = PriceVersionService.create(
            {
                "route_id": route_v2["process_route_id"],
                "process_id": process_v2["process_id"],
                "normal_unit_price": "1.25",
                "valid_from": "2026-08-20 07:00:00",
                "remark": "成组发布工价",
            },
            preparer,
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

    assert replay["id"] == created["id"]
    assert [item["id"] for item in replay["process_versions"]] == [first["id"]]
