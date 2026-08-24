import uuid

import pytest

from modules import config
from modules.domain.errors import ConflictError
from modules.domain.price_versioning import (
    ActiveReleaseBatchConflictError,
    ProcessVersionNotFrozenError,
)
from modules.repositories.payroll_repository import PayrollRepository
from modules.repositories.process_version_repository import ProcessVersionRepository
from modules.repositories.route_version_repository import RouteVersionRepository
from modules.services.master_data_release_service import MasterDataReleaseService
from modules.services.process_version_service import ProcessVersionService
from modules.services.route_version_service import RouteVersionService
from tests.pending_route_price_helpers import (
    pending_route_with_prices,
    route_draft_using_process_status,
)
from tests.test_process_version_workflow import _actors


@pytest.fixture(autouse=True)
def enable_pending_price_write(monkeypatch):
    monkeypatch.setattr(config, "ROUTE_PRICE_PENDING_REFERENCE_ENABLED", True)
    monkeypatch.setattr(config, "ROUTE_PRICE_PENDING_COMPAT_AUDIT_ENABLED", True)
    monkeypatch.setattr(config, "ROUTE_PRICE_PENDING_WRITE_ENABLED", True)


def test_route_submit_rejects_draft_process_version(client):
    preparer, _ = _actors(client)
    route = route_draft_using_process_status(client, "draft", preparer)
    with client.application.app_context():
        with pytest.raises(ProcessVersionNotFrozenError):
            RouteVersionService.submit(
                route["id"],
                {
                    "row_version": route["row_version"],
                    "idempotency_key": "route-submit-draft-process",
                },
                preparer,
            )


def test_route_reject_voids_exact_price_drafts_atomically(client):
    preparer, approver = _actors(client)
    route, prices = pending_route_with_prices(client, preparer, price_count=2)
    with client.application.app_context():
        rejected = RouteVersionService.reject(
            route["id"],
            {
                "row_version": route["row_version"],
                "idempotency_key": "route-reject-with-prices",
                "reason": "节点需要调整",
            },
            approver,
        )
        loaded = [PayrollRepository.price_version(price["id"]) for price in prices]
        void_events = [
            PayrollRepository.event_by_idempotency_key(
                f"route-reject-with-prices:price:{price['id']}"
            )
            for price in prices
        ]
    assert rejected["status"] == "draft"
    assert [price["status"] for price in loaded] == ["voided", "voided"]
    assert all(price["void_reason"] == "节点需要调整" for price in loaded)
    assert len({price["voided_at"] for price in loaded}) == 1
    assert [event["event_type"] for event in void_events] == [
        "price_version_voided",
        "price_version_voided",
    ]


def test_route_reject_rolls_back_partial_price_void(client, monkeypatch):
    preparer, approver = _actors(client)
    route, prices = pending_route_with_prices(client, preparer, price_count=2)

    def fail_after_first(route_version_id, payload, db):
        first = db.execute(
            "SELECT id,row_version FROM route_price_versions "
            "WHERE route_version_id=? AND status='draft' ORDER BY id LIMIT 1",
            (route_version_id,),
        ).fetchone()
        PayrollRepository.void_price_version(
            first["id"], first["row_version"], payload, db
        )
        raise RuntimeError("injected price void failure")

    monkeypatch.setattr(
        PayrollRepository,
        "void_draft_prices_for_route",
        staticmethod(fail_after_first),
    )
    with client.application.app_context():
        with pytest.raises(RuntimeError, match="injected"):
            RouteVersionService.reject(
                route["id"],
                {
                    "row_version": route["row_version"],
                    "idempotency_key": "route-reject-rollback",
                    "reason": "验证原子回滚",
                },
                approver,
            )
        current_route = RouteVersionRepository.version(route["id"])
        loaded = [PayrollRepository.price_version(price["id"]) for price in prices]
    assert current_route["status"] == "pending_approval"
    assert [price["status"] for price in loaded] == ["draft", "draft"]


def test_pending_release_batch_blocks_route_rejection(client):
    preparer, approver = _actors(client)
    route, prices = pending_route_with_prices(client, preparer, price_count=1)
    with client.application.app_context():
        batch = MasterDataReleaseService.create_batch(
            {
                "release_no": f"REJECT-GUARD-{uuid.uuid4().hex[:10]}",
                "revision_reason": "验证待审批批次阻断",
                "process_version_ids": [item["process_version_id"] for item in route["items"]],
                "route_version_ids": [route["id"]],
                "price_version_ids": [price["id"] for price in prices],
                "idempotency_key": f"reject-guard-create-{uuid.uuid4().hex}",
            },
            preparer,
        )
        submitted = MasterDataReleaseService.submit(
            batch["id"],
            {
                "row_version": batch["row_version"],
                "idempotency_key": f"reject-guard-submit-{uuid.uuid4().hex}",
            },
            preparer,
        )
        with pytest.raises(ActiveReleaseBatchConflictError) as caught:
            RouteVersionService.reject(
                route["id"],
                {
                    "row_version": route["row_version"],
                    "idempotency_key": "route-reject-active-batch",
                    "reason": "不应允许单独驳回",
                },
                approver,
            )
    assert caught.value.details["batch_ids"] == [submitted["id"]]


def test_draft_release_batch_does_not_block_route_rejection(client):
    preparer, approver = _actors(client)
    route, prices = pending_route_with_prices(client, preparer, price_count=1)
    with client.application.app_context():
        MasterDataReleaseService.create_batch(
            {
                "release_no": f"DRAFT-REJECT-{uuid.uuid4().hex[:10]}",
                "revision_reason": "验证草稿批次不阻断路线驳回",
                "process_version_ids": [
                    item["process_version_id"] for item in route["items"]
                ],
                "route_version_ids": [route["id"]],
                "price_version_ids": [price["id"] for price in prices],
                "idempotency_key": f"draft-reject-create-{uuid.uuid4().hex}",
            },
            preparer,
        )
        rejected = RouteVersionService.reject(
            route["id"],
            {
                "row_version": route["row_version"],
                "idempotency_key": "route-reject-draft-batch",
                "reason": "退回修改路线",
            },
            approver,
        )
        voided = PayrollRepository.price_version(prices[0]["id"])
    assert rejected["status"] == "draft"
    assert voided["status"] == "voided"


def test_pending_route_dependency_blocks_process_rejection(client):
    preparer, approver = _actors(client)
    route = route_draft_using_process_status(client, "pending_approval", preparer)
    with client.application.app_context():
        pending_route = RouteVersionService.submit(
            route["id"],
            {
                "row_version": route["row_version"],
                "idempotency_key": "dependency-route-submit",
            },
            preparer,
        )
        process_version_id = pending_route["items"][0]["process_version_id"]
        process = ProcessVersionRepository.version(process_version_id)
        with pytest.raises(ConflictError) as caught:
            ProcessVersionService.reject(
                process_version_id,
                {
                    "row_version": process["row_version"],
                    "idempotency_key": "dependency-process-reject",
                    "reason": "不应级联驳回",
                },
                approver,
            )
    assert caught.value.details["route_version_ids"] == [pending_route["id"]]
