import json
import sqlite3

import pytest

from factories import (
    WORKER_HASH,
    bind_order_process_versions,
    create_order,
    create_process_route,
    ensure_process,
    ensure_user,
)
from modules.db import get_db
from modules.middleware.auth import AuthSessionService
from modules.services.payroll_service import (
    PayrollAuditService,
    PayrollCalculationService,
    PayrollWorkflowService,
)
import modules.services.payroll_service as payroll_service
from modules.domain.payroll_audit_rules import PAYROLL_AUDIT_RULE_VERSION
from modules.repositories.payroll_repository import PayrollRepository
from modules.services.price_version_service import PriceVersionService


def _actors(db):
    preparer_id = ensure_user(db, "b2-preparer", "hash", "B2制单员", "admin", "B2-PREP")
    approver_id = ensure_user(db, "b2-approver", "hash", "B2审批员", "admin", "B2-APP")
    return (
        {"id": preparer_id, "name": "B2制单员"},
        {"id": approver_id, "name": "B2审批员"},
    )


def _seed_batch_inputs(
    db, *, statuses=("approved",), serials=("",),
    created_at="2026-07-01 08:00:00", quantity=4,
):
    process_id = ensure_process(db, "B2审计工序")
    route_id = create_process_route(
        db, [process_id], "B2审计路线-" + created_at.replace(" ", "-")
    )
    worker_id = ensure_user(db, "b2-worker", WORKER_HASH, "B2测试员工", "worker", "B2-WORK")
    order_id = create_order(db, [process_id], quantity=50, product_code="B2-PRODUCT")
    db.execute("UPDATE orders SET route_id=? WHERE id=?", (route_id, order_id))
    bind_order_process_versions(db, order_id)
    binding = db.execute(
        "SELECT route_version.id AS route_version_id,item.process_version_id,"
        "route_version.name AS route_name,route_version.content_digest AS route_digest,"
        "process_version.name AS process_name,process_version.content_digest AS process_digest "
        "FROM process_routes route "
        "JOIN process_route_versions route_version "
        "ON route_version.id=route.current_effective_version_id "
        "JOIN process_route_version_items item "
        "ON item.route_version_id=route_version.id AND item.process_id=? "
        "JOIN process_versions process_version ON process_version.id=item.process_version_id "
        "WHERE route.id=?",
        (process_id, route_id),
    ).fetchone()
    record_ids = []
    for index, status in enumerate(statuses):
        serial = serials[index] if index < len(serials) else ""
        cursor = db.execute(
            "INSERT INTO work_records "
            "(order_id,process_id,process_version_id,process_name_snapshot,user_id,type,"
            "quantity,status,serial_no,route_id,route_version_id,route_name_snapshot,created_at) "
            "VALUES (?,?,?,?,?,'normal',?, ?,?,?,?, ?,?)",
            (
                order_id, process_id, binding["process_version_id"],
                binding["process_name"], worker_id, quantity, status, serial, route_id,
                binding["route_version_id"], binding["route_name"], created_at,
            ),
        )
        record_ids.append(cursor.lastrowid)
    db.commit()

    price = PriceVersionService.create({
        "route_id": route_id,
        "route_version_id": binding["route_version_id"],
        "process_id": process_id,
        "process_version_id": binding["process_version_id"],
        "expected_route_content_digest": binding["route_digest"],
        "expected_process_content_digest": binding["process_digest"],
        "normal_unit_price": "2",
        "valid_from": "2026-07-01",
        "idempotency_key": f"b2-price-{order_id}",
    }, {"id": 1, "name": "B2工价制单员"})
    PriceVersionService.approve(
        price["id"], {"id": 2, "name": "B2工价审批员"}, price["row_version"]
    )
    return worker_id, record_ids


def _finding_by_type(db, batch_id, finding_type, subject_id=None):
    clauses = ["batch_id=?", "finding_type=?"]
    params = [batch_id, finding_type]
    if subject_id is not None:
        clauses.append("subject_id=?")
        params.append(subject_id)
    rows = db.execute(
        "SELECT * FROM payroll_audit_findings WHERE " + " AND ".join(clauses)
        + " ORDER BY id",
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def test_blocking_findings_require_source_correction_and_recalculation(client):
    with client.application.app_context():
        db = get_db()
        preparer, _approver = _actors(db)
        _worker_id, record_ids = _seed_batch_inputs(
            db,
            statuses=("approved", "pending"),
            serials=("SERIAL-1", "SERIAL-2"),
        )
        db.execute(
            "UPDATE work_records SET created_at='2026-07-01 08:00:01' WHERE id=?",
            (record_ids[1],),
        )
        db.commit()
        batch = PayrollWorkflowService.create_batch(
            "2026-07", preparer, "b2-pending-source"
        )
        findings = _finding_by_type(db, batch["id"], "pending_approval_work")
        assert [item["subject_id"] for item in findings] == [record_ids[1]]
        assert json.loads(findings[0]["snapshot_json"])["work_record"]["status"] == "pending"
        with pytest.raises(ValueError, match="未处理工资审计异常"):
            PayrollWorkflowService.submit(batch["id"], preparer, batch["row_version"])

        db.execute("UPDATE work_records SET status='approved' WHERE id=?", (record_ids[1],))
        db.commit()
        assert PayrollWorkflowService.batch_detail(batch["id"])["batch"]["input_changed"] is True
        regenerated = PayrollWorkflowService.regenerate(
            batch["id"], preparer, batch["row_version"]
        )
        assert regenerated["audit_finding_count"] == 0
        assert {
            row["status"] for row in db.execute(
                "SELECT status FROM payroll_audit_findings WHERE batch_id=?", (batch["id"],)
            ).fetchall()
        } == {"superseded"}
        submitted = PayrollWorkflowService.submit(
            batch["id"], preparer, regenerated["row_version"]
        )
        assert submitted["status"] == "review_pending"


def test_zero_finding_batch_freezes_rule_version_and_stale_review_can_be_recalculated(
    client, monkeypatch
):
    with client.application.app_context():
        db = get_db()
        preparer, approver = _actors(db)
        _seed_batch_inputs(db, statuses=("approved",), serials=("SERIAL-UNIQUE",))
        batch = PayrollWorkflowService.create_batch(
            "2026-07", preparer, "b2-zero-findings-rule-version"
        )

        stored = PayrollRepository.get_batch(batch["id"], db)
        event = PayrollRepository.latest_calculation_event(batch["id"], db)
        event_payload = json.loads(event["payload_json"])
        assert _finding_by_type(db, batch["id"], "duplicate_serial_work") == []
        assert stored["audit_rule_version"] == PAYROLL_AUDIT_RULE_VERSION
        assert event_payload["audit_rule_version"] == PAYROLL_AUDIT_RULE_VERSION

        submitted = PayrollWorkflowService.submit(
            batch["id"], preparer, batch["row_version"]
        )
        monkeypatch.setattr(
            payroll_service, "PAYROLL_AUDIT_RULE_VERSION", "payroll-audit-next"
        )
        with pytest.raises(ValueError, match="规则版本已变化"):
            PayrollWorkflowService.lock(
                batch["id"], approver, submitted["row_version"]
            )

        recalculated = PayrollWorkflowService.regenerate(
            batch["id"], preparer, submitted["row_version"]
        )
        assert recalculated["status"] == "draft"
        assert recalculated["submitted_at"] == ""
        assert recalculated["audit_rule_version"] == "payroll-audit-next"
        new_event = PayrollRepository.latest_calculation_event(batch["id"], db)
        assert json.loads(new_event["payload_json"])["audit_rule_version"] == "payroll-audit-next"
        resubmitted = PayrollWorkflowService.submit(
            batch["id"], preparer, recalculated["row_version"]
        )
        assert resubmitted["status"] == "review_pending"


def test_pre_audit_locked_batch_keeps_legacy_snapshot_gate_and_can_be_confirmed(client):
    with client.application.app_context():
        db = get_db()
        preparer, approver = _actors(db)
        _seed_batch_inputs(db, statuses=("approved",), serials=("SERIAL-LEGACY",))
        batch = PayrollWorkflowService.create_batch(
            "2026-07", preparer, "b2-pre-audit-locked"
        )
        stored = PayrollRepository.get_batch(batch["id"], db)
        lines = PayrollRepository.list_lines(batch["id"], db=db)
        details = PayrollRepository.list_details(batch["id"], db=db)
        legacy_digest = PayrollCalculationService.snapshot_digest(
            {**stored, "audit_rule_version": ""},
            lines,
            details,
            include_audit_rule_version=False,
        )
        event = PayrollRepository.latest_calculation_event(batch["id"], db)
        event_payload = json.loads(event["payload_json"])
        event_payload.pop("audit_rule_version", None)
        event_payload["snapshot_digest"] = legacy_digest

        db.execute("DROP TRIGGER protect_payroll_audit_rule_version")
        db.execute("DROP TRIGGER prevent_payroll_event_update")
        db.execute(
            "UPDATE payroll_batches SET audit_run_version=0,audit_rule_version='' WHERE id=?",
            (batch["id"],),
        )
        db.execute(
            "UPDATE payroll_events SET payload_json=? WHERE id=?",
            (json.dumps(event_payload, ensure_ascii=False), event["id"]),
        )
        db.execute(
            "UPDATE payroll_batches SET status='review_pending' WHERE id=?",
            (batch["id"],),
        )
        db.commit()

        with pytest.raises(ValueError, match="规则版本已变化"):
            PayrollWorkflowService.lock(batch["id"], approver, batch["row_version"])

        db.execute(
            "UPDATE payroll_batches SET status='locked' WHERE id=?",
            (batch["id"],),
        )
        db.commit()
        confirmed = PayrollWorkflowService.confirm(
            batch["id"], approver, batch["row_version"]
        )
        assert confirmed["status"] == "confirmed"


def test_duplicate_serial_work_blocks_until_one_source_record_is_rejected(client):
    with client.application.app_context():
        db = get_db()
        preparer, _approver = _actors(db)
        _worker_id, record_ids = _seed_batch_inputs(
            db,
            statuses=("approved", "approved"),
            serials=("SERIAL-DUP", "SERIAL-DUP"),
        )
        batch = PayrollWorkflowService.create_batch(
            "2026-07", preparer, "b2-duplicate-serial"
        )
        findings = _finding_by_type(db, batch["id"], "duplicate_serial_work")
        assert [item["subject_id"] for item in findings] == sorted(record_ids)
        assert all(item["severity"] == "blocking" for item in findings)
        assert all(
            json.loads(item["snapshot_json"])["work_record_ids"] == sorted(record_ids)
            for item in findings
        )
        with pytest.raises(ValueError, match="阻断"):
            PayrollWorkflowService.submit(batch["id"], preparer, batch["row_version"])

        db.execute("UPDATE work_records SET status='rejected' WHERE id=?", (record_ids[1],))
        db.commit()
        regenerated = PayrollWorkflowService.regenerate(
            batch["id"], preparer, batch["row_version"]
        )
        assert regenerated["audit_finding_count"] == 0
        current = PayrollWorkflowService.list_audit_findings(
            batch_id=batch["id"], status="open"
        )["audit_findings"]
        assert current == []


def test_duplicate_candidate_requires_approval_role_and_reason_before_submit(client):
    with client.application.app_context():
        db = get_db()
        preparer, approver = _actors(db)
        _worker_id, record_ids = _seed_batch_inputs(
            db, statuses=("approved", "approved"), serials=("", "")
        )
        batch = PayrollWorkflowService.create_batch(
            "2026-07", preparer, "b2-duplicate-candidate"
        )
        findings = _finding_by_type(db, batch["id"], "duplicate_work_candidate")
        assert [item["subject_id"] for item in findings] == sorted(record_ids)
        assert all(item["severity"] == "review" for item in findings)
        with pytest.raises(ValueError, match="未处理工资审计异常"):
            PayrollWorkflowService.submit(batch["id"], preparer, batch["row_version"])
        with pytest.raises(ValueError, match="复核人必须为不同用户"):
            PayrollAuditService.resolve(
                findings[0]["id"], preparer, {
                    "resolution_code": "confirmed_distinct_work",
                    "resolution_reason": "尝试由制单人自我复核",
                }
            )

        for finding in findings:
            PayrollAuditService.resolve(
                finding["id"], approver, {
                    "resolution_code": "confirmed_distinct_work",
                    "resolution_reason": "复核报工凭证后确认为两次独立作业",
                }
            )
        with pytest.raises(sqlite3.IntegrityError, match="evidence is immutable"):
            db.execute(
                "UPDATE payroll_audit_findings SET snapshot_json='{}' WHERE id=?",
                (findings[0]["id"],),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("DELETE FROM payroll_audit_findings WHERE id=?", (findings[0]["id"],))
        db.rollback()
        submitted = PayrollWorkflowService.submit(
            batch["id"], preparer, batch["row_version"]
        )
        assert submitted["status"] == "review_pending"


def test_high_deviation_compares_three_latest_active_confirmed_periods(client):
    with client.application.app_context():
        db = get_db()
        preparer, approver = _actors(db)
        historic_batches = []
        for month in ("2026-07", "2026-08", "2026-09"):
            _seed_batch_inputs(
                db,
                created_at=month + "-02 08:00:00",
                quantity=4,
            )
            batch = PayrollWorkflowService.create_batch(
                month, preparer, "b2-history-" + month
            )
            submitted = PayrollWorkflowService.submit(
                batch["id"], preparer, batch["row_version"]
            )
            locked = PayrollWorkflowService.lock(
                batch["id"], approver, submitted["row_version"]
            )
            confirmed = PayrollWorkflowService.confirm(
                batch["id"], approver, locked["row_version"]
            )
            historic_batches.append(confirmed)

        _seed_batch_inputs(
            db,
            created_at="2026-10-02 08:00:00",
            quantity=300,
        )
        current = PayrollWorkflowService.create_batch(
            "2026-10", preparer, "b2-high-deviation"
        )
        finding = _finding_by_type(db, current["id"], "high_payroll_deviation")
        assert len(finding) == 1
        snapshot = json.loads(finding[0]["snapshot_json"])
        assert snapshot["current_payable_cents"] == 60000
        assert [item["payroll_month"] for item in snapshot["historical_periods"]] == [
            "2026-09", "2026-08", "2026-07",
        ]
        assert snapshot["historical_median_twice_cents"] == 1600
        assert snapshot["difference_twice_cents"] == 118400
        assert finding[0]["severity"] == "review"
        with pytest.raises(ValueError, match="未处理工资审计异常"):
            PayrollWorkflowService.submit(
                current["id"], preparer, current["row_version"]
            )


def test_late_prior_period_confirmation_invalidates_audit_basis(client):
    with client.application.app_context():
        db = get_db()
        preparer, approver = _actors(db)

        for month in ("2026-07", "2026-08"):
            _seed_batch_inputs(db, created_at=month + "-02 08:00:00")
            batch = PayrollWorkflowService.create_batch(
                month, preparer, "b2-late-history-" + month
            )
            submitted = PayrollWorkflowService.submit(
                batch["id"], preparer, batch["row_version"]
            )
            locked = PayrollWorkflowService.lock(
                batch["id"], approver, submitted["row_version"]
            )
            PayrollWorkflowService.confirm(
                batch["id"], approver, locked["row_version"]
            )

        _seed_batch_inputs(
            db, created_at="2026-10-02 08:00:00", quantity=300
        )
        current = PayrollWorkflowService.create_batch(
            "2026-10", preparer, "b2-late-history-current"
        )
        assert not _finding_by_type(
            db, current["id"], "high_payroll_deviation"
        )

        _seed_batch_inputs(db, created_at="2026-09-02 08:00:00")
        late_history = PayrollWorkflowService.create_batch(
            "2026-09", preparer, "b2-late-history-september"
        )
        submitted = PayrollWorkflowService.submit(
            late_history["id"], preparer, late_history["row_version"]
        )
        locked = PayrollWorkflowService.lock(
            late_history["id"], approver, submitted["row_version"]
        )
        PayrollWorkflowService.confirm(
            late_history["id"], approver, locked["row_version"]
        )

        with pytest.raises(ValueError, match="工资输入已变化"):
            PayrollWorkflowService.submit(
                current["id"], preparer, current["row_version"]
            )

        refreshed = PayrollWorkflowService.regenerate(
            current["id"], preparer, current["row_version"]
        )
        assert refreshed["audit_finding_count"] == 1
        assert refreshed["audit_blocking_count"] == 0
        assert len(_finding_by_type(
            db, current["id"], "high_payroll_deviation"
        )) == 1


@pytest.mark.parametrize("permission", ["wages:view_all", "wages:prepare", "wages:approve"])
def test_audit_finding_list_accepts_payroll_reader_permissions(
    client, monkeypatch, permission
):
    actor = {
        "id": 23,
        "name": "工资审核用户",
        "username": "payroll-audit-reader",
        "_permissions": [permission],
    }
    monkeypatch.setattr(
        AuthSessionService, "authenticate", lambda _token: (dict(actor), None)
    )
    response = client.get(
        "/api/payroll/audit-findings?payroll_month=2026-07",
        headers={"Authorization": "Bearer payroll-audit-reader"},
    )
    assert response.status_code == 200
    assert response.headers["Cache-Control"].startswith("no-store")
    assert response.get_json() == {"audit_findings": []}


def test_audit_finding_resolution_requires_approval_permission(client, monkeypatch):
    actor = {
        "id": 23,
        "name": "只读工资用户",
        "username": "payroll-audit-reader",
        "_permissions": ["wages:view_all"],
    }
    monkeypatch.setattr(
        AuthSessionService, "authenticate", lambda _token: (dict(actor), None)
    )
    called = []
    monkeypatch.setattr(
        PayrollAuditService,
        "resolve",
        lambda *_args, **_kwargs: called.append(True),
    )
    response = client.post(
        "/api/payroll/audit-findings/1/resolve",
        json={
            "resolution_code": "confirmed_variance",
            "resolution_reason": "已复核",
        },
        headers={"Authorization": "Bearer payroll-audit-reader"},
    )
    assert response.status_code == 403
    assert called == []


def test_approval_role_can_resolve_review_finding_through_audited_api(client, monkeypatch):
    with client.application.app_context():
        db = get_db()
        preparer, approver = _actors(db)
        _seed_batch_inputs(db, statuses=("approved", "approved"))
        batch = PayrollWorkflowService.create_batch(
            "2026-07", preparer, "b2-review-api"
        )
        finding = _finding_by_type(
            db, batch["id"], "duplicate_work_candidate"
        )[0]

    actor = {
        "id": approver["id"],
        "name": approver["name"],
        "username": "b2-approver",
        "_permissions": ["wages:approve"],
    }
    monkeypatch.setattr(
        AuthSessionService, "authenticate", lambda _token: (dict(actor), None)
    )
    response = client.post(
        f"/api/payroll/audit-findings/{finding['id']}/resolve",
        json={
            "resolution_code": "confirmed_distinct_work",
            "resolution_reason": "现场凭证确认是两次独立作业",
        },
        headers={"Authorization": "Bearer payroll-audit-approver"},
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["status"] == "resolved"
    with client.application.app_context():
        result = PayrollWorkflowService.list_audit_findings(
            batch_id=batch["id"], status="resolved"
        )["audit_findings"]
    assert len(result) == 1
    assert result[0]["resolved_by_name"] == approver["name"]
    assert result[0]["resolution_reason"] == "现场凭证确认是两次独立作业"
