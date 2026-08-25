import pytest

from modules.db import get_db
from modules.domain.price_versioning import (
    PriceBindingMismatchError,
    PriceBindingStaleError,
    PriceVersionVoidedError,
    ProcessVersionNotFrozenError,
    RouteVersionNotPricableError,
    StaleRowVersionError,
    assert_exact_price_binding,
    assert_expected_digest,
    assert_price_snapshot_current,
    price_reference_key,
    pricing_mode,
)
from modules.repositories.master_data_release_repository import (
    MasterDataReleaseRepository,
)
from modules.repositories.payroll_repository import PayrollRepository
from modules.repositories.process_version_repository import ProcessVersionRepository


def _seed_versioned_reference(db):
    process_id = db.execute(
        "INSERT INTO processes(name,category,status,process_code,lifecycle_status) "
        "VALUES ('Task2 工序','机加工','active','PROC-TASK2','active')"
    ).lastrowid
    process_v1 = db.execute(
        "INSERT INTO process_versions(process_id,version,process_code_snapshot,name,"
        "category,status,content_digest,idempotency_key) "
        "VALUES (?,1,'PROC-TASK2','Task2 工序 V1','机加工','published',"
        "'process-v1','task2-process-v1')",
        (process_id,),
    ).lastrowid
    process_v2 = db.execute(
        "INSERT INTO process_versions(process_id,version,process_code_snapshot,name,"
        "category,status,content_digest,idempotency_key) "
        "VALUES (?,2,'PROC-TASK2','Task2 工序 V2','机加工','pending_approval',"
        "'process-v2','task2-process-v2')",
        (process_id,),
    ).lastrowid
    db.execute(
        "UPDATE processes SET current_effective_version_id=? WHERE id=?",
        (process_v1, process_id),
    )

    route_id = db.execute(
        "INSERT INTO process_routes(name,category,status,route_code,lifecycle_status) "
        "VALUES ('Task2 路线','机加工','active','ROUTE-TASK2','active')"
    ).lastrowid
    route_v1 = db.execute(
        "INSERT INTO process_route_versions(process_route_id,version,route_code_snapshot,"
        "name,category,status,content_digest,idempotency_key) "
        "VALUES (?,1,'ROUTE-TASK2','Task2 路线 V1','机加工','draft',"
        "'route-v1','task2-route-v1')",
        (route_id,),
    ).lastrowid
    db.execute(
        "INSERT INTO process_route_version_items(route_version_id,process_id,"
        "process_version_id,seq_order) VALUES (?,?,?,10)",
        (route_v1, process_id, process_v1),
    )
    db.execute(
        "UPDATE process_route_versions SET status='published' WHERE id=?", (route_v1,)
    )
    route_v2 = db.execute(
        "INSERT INTO process_route_versions(process_route_id,version,route_code_snapshot,"
        "name,category,status,content_digest,idempotency_key) "
        "VALUES (?,2,'ROUTE-TASK2','Task2 路线 V2','机加工','draft',"
        "'route-v2','task2-route-v2')",
        (route_id,),
    ).lastrowid
    db.execute(
        "INSERT INTO process_route_version_items(route_version_id,process_id,"
        "process_version_id,seq_order) VALUES (?,?,?,10)",
        (route_v2, process_id, process_v2),
    )
    db.execute(
        "UPDATE process_route_versions SET status='pending_approval' WHERE id=?",
        (route_v2,),
    )
    db.execute(
        "UPDATE process_routes SET current_effective_version_id=? WHERE id=?",
        (route_v1, route_id),
    )
    db.commit()
    return {
        "process_id": process_id,
        "process_v1": process_v1,
        "process_v2": process_v2,
        "route_id": route_id,
        "route_v1": route_v1,
        "route_v2": route_v2,
    }


def test_reference_key_uses_both_exact_version_ids():
    assert price_reference_key(82, 72) == "82:72"
    assert price_reference_key(83, 72) != price_reference_key(82, 72)


@pytest.mark.parametrize(
    ("status", "expected"),
    [("published", "published_adjustment"), ("pending_approval", "pending_group_release")],
)
def test_pricing_mode_accepts_only_frozen_states(status, expected):
    assert pricing_mode(status) == expected


def test_pricing_mode_rejects_draft_with_stable_code():
    with pytest.raises(RouteVersionNotPricableError) as caught:
        pricing_mode("draft")
    assert caught.value.to_payload()["code"] == "ROUTE_VERSION_NOT_PRICABLE"


def test_binding_and_digest_guards_use_stable_conflicts():
    binding = {
        "route_id": 8,
        "process_id": 7,
        "route_content_digest": "route-v2",
        "process_content_digest": "process-v2",
    }
    assert_exact_price_binding(binding, 8, 7)
    with pytest.raises(PriceBindingMismatchError):
        assert_exact_price_binding(binding, 9, 7)
    with pytest.raises(PriceBindingStaleError):
        assert_expected_digest("route-v1", "route-v2")
    with pytest.raises(PriceBindingStaleError):
        assert_price_snapshot_current(
            {
                "status": "draft",
                "route_content_digest_snapshot": "route-v1",
                "process_content_digest_snapshot": "process-v2",
            },
            binding,
        )
    with pytest.raises(PriceVersionVoidedError):
        assert_price_snapshot_current({"id": 31, "status": "voided"}, binding)


def test_stable_conflicts_support_default_messages_and_details():
    error = ProcessVersionNotFrozenError(details={"process_version_ids": [72]})
    assert error.to_payload() == {
        "error": "路线节点引用的工序版本尚未冻结",
        "code": "PROCESS_VERSION_NOT_FROZEN",
        "details": {"process_version_ids": [72]},
    }


def test_reference_catalog_keeps_published_and_pending_versions_distinct(client):
    with client.application.app_context():
        ids = _seed_versioned_reference(get_db())
        published = PayrollRepository.list_route_process_references()
        expanded = PayrollRepository.list_route_process_references(include_pending=True)

    published_rows = [row for row in published if row["route_id"] == ids["route_id"]]
    expanded_rows = [row for row in expanded if row["route_id"] == ids["route_id"]]
    assert [row["route_version_id"] for row in published_rows] == [ids["route_v1"]]
    assert [row["route_version_id"] for row in expanded_rows] == [
        ids["route_v1"],
        ids["route_v2"],
    ]
    assert [row["reference_key"] for row in expanded_rows] == [
        price_reference_key(ids["route_v1"], ids["process_v1"]),
        price_reference_key(ids["route_v2"], ids["process_v2"]),
    ]
    assert expanded_rows[0]["pricing_mode"] == "published_adjustment"
    assert expanded_rows[1]["pricing_mode"] == "pending_group_release"
    assert expanded_rows[1]["route_content_digest"] == "route-v2"
    assert expanded_rows[1]["process_content_digest"] == "process-v2"


def test_exact_price_repository_contracts_are_optimistic_and_auditable(client):
    with client.application.app_context():
        db = get_db()
        ids = _seed_versioned_reference(db)
        price_id = PayrollRepository.create_price_version(
            {
                "route_id": ids["route_id"],
                "route_version_id": ids["route_v2"],
                "process_id": ids["process_id"],
                "process_version_id": ids["process_v2"],
                "normal_unit_price_micros": 1250000,
                "valid_from": "2026-08-24 07:00:00",
                "idempotency_key": "task2-price-create",
                "request_digest": "request-digest",
                "route_content_digest_snapshot": "route-v2",
                "process_content_digest_snapshot": "process-v2",
            },
            db,
        )
        created = PayrollRepository.price_version_by_idempotency_key(
            "task2-price-create", db=db
        )
        assert created["id"] == price_id
        binding = PayrollRepository.exact_price_binding(
            ids["route_v2"], ids["process_v2"], db=db
        )
        assert binding["route_content_digest"] == "route-v2"
        assert binding["process_content_digest"] == "process-v2"
        assert PayrollRepository.draft_price_for_binding(
            ids["route_v2"], ids["process_v2"], db=db
        )["id"] == price_id
        voided = PayrollRepository.void_price_version(
            price_id,
            created["row_version"],
            {
                "voided_at": "2026-08-24 12:00:00",
                "voided_by_name": "制单人",
                "void_reason": "录入错误",
            },
            db,
        )
        assert voided["status"] == "voided"
        with pytest.raises(StaleRowVersionError):
            PayrollRepository.void_price_version(
                price_id,
                created["row_version"],
                {"void_reason": "重复作废"},
                db,
            )

        pending_routes = ProcessVersionRepository.pending_routes_for_process_version(
            ids["process_v2"], db=db
        )
        assert [row["id"] for row in pending_routes] == [ids["route_v2"]]

        batch = MasterDataReleaseRepository.create_batch(
            {
                "release_no": "REL-TASK2",
                "revision_reason": "Task2 repository contract",
                "idempotency_key": "task2-release",
            },
            db,
        )
        MasterDataReleaseRepository.add_route_version(batch["id"], ids["route_v2"], db)
        assert [row["id"] for row in MasterDataReleaseRepository.active_batches_for_route_version(
            ids["route_v2"], db=db
        )] == [batch["id"]]
        event = MasterDataReleaseRepository.insert_release_member_event(
            {
                "batch_id": batch["id"],
                "action": "added",
                "member_type": "route_version",
                "member_id": ids["route_v2"],
                "actor_name": "制单人",
                "reason": "初始成员",
                "idempotency_key": "task2-member-added",
            },
            db,
        )
        replay = MasterDataReleaseRepository.insert_release_member_event(
            {
                "batch_id": batch["id"],
                "action": "removed",
                "member_type": "route_version",
                "member_id": 999,
                "actor_name": "不应覆盖",
                "reason": "不应覆盖",
                "idempotency_key": "task2-member-added",
            },
            db,
        )
        assert replay == event
        assert MasterDataReleaseRepository.list_release_member_events(
            batch["id"], db=db
        ) == [event]
