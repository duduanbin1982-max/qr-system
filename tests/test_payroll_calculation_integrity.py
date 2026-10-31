"""Payroll approval must use a complete, current and auditable calculation."""

from datetime import datetime
import json

import pytest

from modules.db import get_db
from modules.domain.payroll_policy import MAX_AMOUNT_CENTS, PayrollConflictError
from modules.repositories.payroll_repository import PayrollRepository
from modules.services import payroll_service
from modules.services.payroll_service import PayrollWorkflowService
from modules.services.price_version_service import PriceVersionService
from test_payroll_ledger import _actors, _exact_binding, _seed_price_and_work


@pytest.fixture
def calculation_clock(monkeypatch):
    # All report and adjustment timestamps precede this clock. Advancing it
    # must affect the cutoff only when an explicit regeneration succeeds.
    state = {"now": datetime(2030, 8, 1, 12, 0)}

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            value = state["now"]
            return value if tz is None else value.astimezone(tz)

    monkeypatch.setattr(payroll_service, "datetime", Clock)
    return state


def _work_id(db, employee_id):
    return db.execute(
        "SELECT id FROM work_records WHERE user_id=? ORDER BY id LIMIT 1",
        (employee_id,),
    ).fetchone()[0]


def _copy_work(db, source_id, *, status="approved"):
    result = db.execute(
        "INSERT INTO work_records "
        "(order_id,process_id,process_version_id,process_name_snapshot,user_id,type,"
        "quantity,status,route_id,route_version_id,route_name_snapshot,created_at) "
        "SELECT order_id,process_id,process_version_id,process_name_snapshot,user_id,"
        "type,quantity,?,route_id,route_version_id,route_name_snapshot,"
        "'2026-07-02 09:00:00' FROM work_records WHERE id=?",
        (status, source_id),
    )
    db.commit()
    return result.lastrowid


def _manual_resolution(db, work_id, actor, price_micros=10000):
    PayrollRepository.insert_price_resolution(
        {
            "work_record_id": work_id,
            "override_unit_price_micros": price_micros,
            "resolution_method": "manual_exception_resolution",
            "resolution_reason": "双人复核后核定历史报工工价",
            "policy_code": "dual_review_manual_resolution_v1",
            "resolved_by": actor["id"],
            "resolved_by_name": actor["name"],
        },
        db,
    )
    db.commit()


def _historical_no_settlement(
    db, work_id, route_id, process_id, preparer, approver, *, decision="no_settlement"
):
    """Seed an immutable V083.1 decision without weakening any database guard."""
    binding = _exact_binding(db, route_id, process_id)
    run_id = db.execute(
        "INSERT INTO historical_price_binding_repair_runs "
        "(idempotency_key,manifest_digest,status,operator_id,operator_name,"
        "approver_id,approver_name,approved_at,reason,source_user_version,"
        "target_user_version,manifest_json) "
        "VALUES ('integrity-history-run','integrity-history-manifest','approved',"
        "?,?,?,?, '2026-08-01 10:00:00','历史不结算复核',83,83,'{}')",
        (preparer["id"], preparer["name"], approver["id"], approver["name"]),
    ).lastrowid
    item_id = db.execute(
        "INSERT INTO historical_price_binding_repair_items "
        "(run_id,item_key,action,target_route_id,target_route_version_id,"
        "target_process_id,target_process_version_id,rework_rate_basis_points,"
        "target_route_content_digest,target_process_content_digest,"
        "affected_work_record_count,affected_quantity,affected_work_record_digest) "
        "VALUES (?,'integrity-history-item','manual',?,?,?,?,NULL,?,?,1,3,?)",
        (
            run_id, route_id, binding["route_version_id"], process_id,
            binding["process_version_id"], binding["route_content_digest"],
            binding["process_content_digest"], f"work-{work_id}",
        ),
    ).lastrowid
    price_id = None
    if decision == "zero_price":
        price_id = db.execute(
            "INSERT INTO route_price_versions "
            "(route_id,route_version_id,process_id,process_version_id,"
            "normal_unit_price_micros,valid_from,status,created_by_name,"
            "approved_by_name,approved_at) "
            "VALUES (?,?,?,?,0,'2026-07-01 00:00:00','approved',"
            "'historical','historical','2026-08-01 10:00:00')",
            (route_id, binding["route_version_id"], process_id, binding["process_version_id"]),
        ).lastrowid
    settlement_id = db.execute(
        "INSERT INTO historical_price_binding_settlements "
        "(repair_item_id,decision,price_version_id,reason,decided_by,decided_by_name,decided_at,"
        "idempotency_key,evidence_digest) "
        "VALUES (?,?,?,'历史试运行报工核定零额',?,?,"
        "'2026-08-01 10:00:00','integrity-no-settlement','integrity-evidence')",
        (item_id, decision, price_id, approver["id"], approver["name"]),
    ).lastrowid
    db.execute(
        "INSERT INTO historical_price_binding_settlement_facts "
        "(settlement_id,work_record_id,quantity,created_at) "
        "SELECT ?,id,quantity,created_at FROM work_records WHERE id=?",
        (settlement_id, work_id),
    )
    db.commit()


def _saved_calculation(db, batch_id):
    return {
        "batch": PayrollRepository.get_batch(batch_id, db),
        "lines": PayrollRepository.list_lines(batch_id, db=db),
        "details": PayrollRepository.list_details(batch_id, db=db),
        "events": PayrollRepository.list_events(batch_id, db=db),
    }


def _confirm(batch, preparer, approver):
    submitted = PayrollWorkflowService.submit(
        batch["id"], preparer, batch["row_version"]
    )
    locked = PayrollWorkflowService.lock(
        batch["id"], approver, submitted["row_version"]
    )
    return PayrollWorkflowService.confirm(
        batch["id"], approver, locked["row_version"]
    )


def _save_legacy_calculation_events(monkeypatch):
    original_insert_event = PayrollRepository.insert_event

    def insert_without_snapshot_digest(payload, connection):
        if payload["event_type"] in ("generated", "regenerated"):
            payload = {
                **payload,
                "payload": {
                    key: value for key, value in payload["payload"].items()
                    if key != "snapshot_digest"
                },
            }
        return original_insert_event(payload, connection)

    monkeypatch.setattr(
        PayrollRepository, "insert_event", insert_without_snapshot_digest
    )


def test_exception_approval_invalidates_version_and_requires_regeneration(
    client, calculation_clock
):
    with client.application.app_context():
        db = get_db()
        preparer, approver = _actors(db)
        _seed_price_and_work(db, with_price=False)
        batch = PayrollWorkflowService.create_batch(
            "2026-07", preparer, "integrity-approved-exception"
        )
        exception = PayrollRepository.list_exceptions(batch_id=batch["id"], db=db)[0]
        PayrollWorkflowService.propose_exception(
            exception["id"], preparer,
            {"proposed_price_micros": 10000, "resolution_reason": "人工核定一元"},
        )
        result = PayrollWorkflowService.approve_exception(exception["id"], approver)
        assert result["batch_row_version"] == batch["row_version"] + 1
        approved_batch = PayrollRepository.get_batch(batch["id"], db)
        assert approved_batch["row_version"] == result["batch_row_version"]
        assert approved_batch["status"] == "exceptions_pending"

        with pytest.raises(ValueError, match="重算|重新|完整"):
            PayrollWorkflowService.submit(
                batch["id"], preparer, result["batch_row_version"]
            )
        with pytest.raises(PayrollConflictError, match="版本"):
            PayrollWorkflowService.regenerate(
                batch["id"], preparer, batch["row_version"]
            )

        regenerated = PayrollWorkflowService.regenerate(
            batch["id"], preparer, result["batch_row_version"]
        )
        assert regenerated["status"] == "draft"
        assert regenerated["exception_count"] == 0
        assert regenerated["source_record_count"] == regenerated["priced_record_count"] == 1
        assert regenerated["payable_wage_cents"] == 300
        assert _confirm(regenerated, preparer, approver)["status"] == "confirmed"


@pytest.mark.parametrize(
    ("quantity", "approved_price"),
    ((0, 10000), (3, MAX_AMOUNT_CENTS * 100)),
    ids=("zero-quantity", "amount-overflow"),
)
def test_approved_invalid_amount_remains_unsettled_with_audit(
    client, calculation_clock, quantity, approved_price
):
    with client.application.app_context():
        db = get_db()
        preparer, approver = _actors(db)
        employee_id, _route_id, _process_id, _actor = _seed_price_and_work(
            db, with_price=not bool(quantity)
        )
        work_id = _work_id(db, employee_id)
        db.execute("UPDATE work_records SET quantity=? WHERE id=?", (quantity, work_id))
        db.commit()
        batch = PayrollWorkflowService.create_batch(
            "2026-07", preparer, f"integrity-invalid-{quantity}"
        )
        exception = PayrollRepository.list_exceptions(batch_id=batch["id"], db=db)[0]
        assert exception["exception_type"] == ("missing_price" if quantity else "invalid_amount")
        PayrollWorkflowService.propose_exception(
            exception["id"], preparer,
            {"proposed_price_micros": approved_price, "resolution_reason": "复核原始报工"},
        )
        approval = PayrollWorkflowService.approve_exception(exception["id"], approver)
        version = approval["batch_row_version"]
        approved = dict(db.execute(
            "SELECT * FROM payroll_exceptions WHERE id=?", (exception["id"],)
        ).fetchone())
        before_events = PayrollRepository.list_events(batch["id"], db=db)

        regenerated = PayrollWorkflowService.regenerate(batch["id"], preparer, version)
        assert regenerated["status"] == "exceptions_pending"
        assert regenerated["exception_count"] == 1
        assert regenerated["priced_record_count"] == 0
        assert PayrollRepository.list_lines(batch["id"], db=db)[0]["exception_count"] == 1
        assert dict(db.execute(
            "SELECT * FROM payroll_exceptions WHERE id=?", (exception["id"],)
        ).fetchone()) == approved
        assert all(event in PayrollRepository.list_events(batch["id"], db=db)
                   for event in before_events)
        with pytest.raises(ValueError):
            PayrollWorkflowService.submit(
                batch["id"], preparer, regenerated["row_version"]
            )


@pytest.mark.parametrize(
    "change",
    ("new-work", "delayed-approval", "effective-price", "manual-resolution",
     "historical-decision", "adjustment", "adjustment-reversal"),
)
def test_draft_input_drift_is_read_only_and_requires_regeneration(
    client, calculation_clock, change
):
    with client.application.app_context():
        db = get_db()
        preparer, approver = _actors(db)
        employee_id, route_id, process_id, _actor = _seed_price_and_work(db)
        work_id = _work_id(db, employee_id)
        pending_work_id = None
        adjustment = None
        if change == "delayed-approval":
            pending_work_id = _copy_work(db, work_id, status="pending")
        if change == "adjustment-reversal":
            adjustment = PayrollWorkflowService.create_adjustment(
                preparer, {"employee_id": employee_id, "payroll_month": "2026-07",
                           "adjustment_type": "bonus", "amount_cents": 100,
                           "reason": "月度奖金"},
            )
        batch = PayrollWorkflowService.create_batch(
            "2026-07", preparer, f"integrity-drift-{change}"
        )
        assert PayrollWorkflowService.batch_detail(batch["id"])["batch"]["input_changed"] is False
        original = _saved_calculation(db, batch["id"])
        calculation_clock["now"] = datetime(2030, 8, 1, 12, 1)

        if change == "new-work":
            _copy_work(db, work_id)
        elif change == "delayed-approval":
            db.execute("UPDATE work_records SET status='approved' WHERE id=?", (pending_work_id,))
            db.commit()
        elif change == "effective-price":
            binding = _exact_binding(db, route_id, process_id)
            price = PriceVersionService.create(
                {"route_id": route_id, "route_version_id": binding["route_version_id"],
                 "process_id": process_id, "process_version_id": binding["process_version_id"],
                 "expected_route_content_digest": binding["route_content_digest"],
                 "expected_process_content_digest": binding["process_content_digest"],
                 "normal_unit_price": "2", "valid_from": "2026-07-01 07:00:00",
                 "idempotency_key": "integrity-effective-price"},
                preparer,
            )
            PriceVersionService.approve(price["id"], approver, price["row_version"])
        elif change == "manual-resolution":
            _manual_resolution(db, work_id, approver)
        elif change == "historical-decision":
            _historical_no_settlement(db, work_id, route_id, process_id, preparer, approver)
        elif change == "adjustment":
            PayrollWorkflowService.create_adjustment(
                preparer, {"employee_id": employee_id, "payroll_month": "2026-07",
                           "adjustment_type": "bonus", "amount_cents": 100,
                           "reason": "追加月度奖金"},
            )
        else:
            PayrollWorkflowService.reverse_adjustment(adjustment["id"], preparer, "奖金复核冲销")

        for _ in range(2):
            detail = PayrollWorkflowService.batch_detail(batch["id"])
            assert detail["batch"]["input_changed"] is True
            assert _saved_calculation(db, batch["id"]) == original
        with pytest.raises(PayrollConflictError, match="变化|重算|重新"):
            PayrollWorkflowService.submit(batch["id"], preparer, batch["row_version"])
        assert _saved_calculation(db, batch["id"]) == original

        regenerated = PayrollWorkflowService.regenerate(
            batch["id"], preparer, batch["row_version"]
        )
        assert regenerated["status"] == "draft"
        assert regenerated["source_cutoff_at"] == "2030-08-01 12:01:00"
        assert regenerated["input_digest"] != batch["input_digest"]
        assert PayrollWorkflowService.batch_detail(batch["id"])["batch"]["input_changed"] is False
        assert _confirm(regenerated, preparer, approver)["status"] == "confirmed"


def test_deleted_calculation_detail_blocks_submit_without_partial_transition(
    client, calculation_clock
):
    with client.application.app_context():
        db = get_db()
        preparer, _approver = _actors(db)
        _seed_price_and_work(db)
        batch = PayrollWorkflowService.create_batch("2026-07", preparer, "integrity-missing-detail")
        db.execute("DELETE FROM payroll_detail_lines WHERE batch_id=?", (batch["id"],))
        db.commit()
        original = _saved_calculation(db, batch["id"])
        with pytest.raises(ValueError, match="完整|重算|重新"):
            PayrollWorkflowService.submit(batch["id"], preparer, batch["row_version"])
        assert _saved_calculation(db, batch["id"]) == original


def test_report_after_saved_cutoff_is_visible_as_drift_and_only_regeneration_includes_it(
    client, calculation_clock
):
    with client.application.app_context():
        db = get_db()
        preparer, _approver = _actors(db)
        calculation_clock["now"] = datetime(2026, 7, 1, 12, 0)
        employee_id, _route_id, _process_id, _actor = _seed_price_and_work(db)
        batch = PayrollWorkflowService.create_batch(
            "2026-07", preparer, "integrity-new-work-after-cutoff"
        )
        original = _saved_calculation(db, batch["id"])
        new_id = _copy_work(db, _work_id(db, employee_id))
        db.execute(
            "UPDATE work_records SET created_at='2026-07-01 12:00:01' WHERE id=?",
            (new_id,),
        )
        db.commit()
        calculation_clock["now"] = datetime(2026, 7, 1, 12, 0, 2)
        assert PayrollWorkflowService.batch_detail(batch["id"])["batch"]["input_changed"] is True
        assert _saved_calculation(db, batch["id"]) == original
        with pytest.raises(PayrollConflictError, match="变化|重算|重新"):
            PayrollWorkflowService.submit(batch["id"], preparer, batch["row_version"])
        assert _saved_calculation(db, batch["id"]) == original
        regenerated = PayrollWorkflowService.regenerate(
            batch["id"], preparer, batch["row_version"]
        )
        assert regenerated["source_cutoff_at"] == "2026-07-01 12:00:02"
        assert regenerated["source_record_count"] == regenerated["priced_record_count"] == 2
        assert regenerated["payable_wage_cents"] == 750
        assert {row["work_record_id"] for row in PayrollRepository.list_details(
            batch["id"], db=db
        )} == {_work_id(db, employee_id), new_id}


@pytest.mark.parametrize(
    "zero_kind", ("rounding", "historical-no-settlement", "historical-zero-price")
)
def test_legitimate_zero_amount_can_complete_workflow(
    client, calculation_clock, zero_kind
):
    with client.application.app_context():
        db = get_db()
        preparer, approver = _actors(db)
        employee_id, route_id, process_id, _actor = _seed_price_and_work(
            db, with_price=zero_kind != "historical-zero-price"
        )
        work_id = _work_id(db, employee_id)
        if zero_kind == "rounding":
            _manual_resolution(db, work_id, approver, price_micros=1)
        else:
            _historical_no_settlement(
                db, work_id, route_id, process_id, preparer, approver,
                decision="zero_price" if zero_kind == "historical-zero-price" else "no_settlement",
            )
        batch = PayrollWorkflowService.create_batch(
            "2026-07", preparer, f"integrity-zero-{zero_kind}"
        )
        assert batch["status"] == "draft"
        assert batch["priced_record_count"] == batch["source_record_count"] == 1
        assert batch["exception_count"] == 0
        assert batch["payable_wage_cents"] == 0
        assert PayrollRepository.list_details(batch["id"], db=db)[0]["amount_cents"] == 0
        assert _confirm(batch, preparer, approver)["status"] == "confirmed"


@pytest.mark.parametrize(
    "with_snapshot_digest", (True, False), ids=("current-event", "legacy-event")
)
def test_submitted_snapshot_freezes_inputs_through_lock_and_confirmation(
    client, calculation_clock, monkeypatch, with_snapshot_digest
):
    if not with_snapshot_digest:
        _save_legacy_calculation_events(monkeypatch)
    with client.application.app_context():
        db = get_db()
        preparer, approver = _actors(db)
        employee_id, _route_id, _process_id, _actor = _seed_price_and_work(db)
        work_id = _work_id(db, employee_id)
        batch = PayrollWorkflowService.create_batch("2026-07", preparer, "integrity-frozen")
        submitted = PayrollWorkflowService.submit(batch["id"], preparer, batch["row_version"])
        saved = _saved_calculation(db, batch["id"])
        calculation_event = PayrollRepository.latest_calculation_event(batch["id"], db)
        assert (
            "snapshot_digest" in json.loads(calculation_event["payload_json"])
        ) is with_snapshot_digest
        _copy_work(db, work_id)
        _manual_resolution(db, work_id, approver)
        PayrollWorkflowService.create_adjustment(
            preparer, {"employee_id": employee_id, "payroll_month": "2026-07",
                       "adjustment_type": "bonus", "amount_cents": 100,
                       "reason": "已提交后的新奖金"},
        )
        assert PayrollWorkflowService.batch_detail(batch["id"])["batch"]["input_changed"] is False
        locked = PayrollWorkflowService.lock(batch["id"], approver, submitted["row_version"])
        confirmed = PayrollWorkflowService.confirm(batch["id"], approver, locked["row_version"])
        actual = _saved_calculation(db, batch["id"])
        assert confirmed["status"] == "confirmed"
        assert confirmed["payable_wage_cents"] == 375
        assert actual["lines"] == saved["lines"]
        assert actual["details"] == saved["details"]
        for field in ("source_cutoff_at", "input_digest", "source_record_count",
                      "priced_record_count", "payable_wage_cents"):
            assert actual["batch"][field] == saved["batch"][field]


@pytest.mark.parametrize("transition", ("lock", "confirm"))
def test_legacy_calculation_event_rejects_corrupt_saved_amount_without_partial_writes(
    client, calculation_clock, monkeypatch, transition
):
    _save_legacy_calculation_events(monkeypatch)
    with client.application.app_context():
        db = get_db()
        preparer, approver = _actors(db)
        _seed_price_and_work(db)
        batch = PayrollWorkflowService.create_batch(
            "2026-07", preparer, f"integrity-legacy-corrupt-{transition}"
        )
        current = PayrollWorkflowService.submit(
            batch["id"], preparer, batch["row_version"]
        )
        if transition == "confirm":
            current = PayrollWorkflowService.lock(
                batch["id"], approver, current["row_version"]
            )
        calculation_event = PayrollRepository.latest_calculation_event(batch["id"], db)
        assert "snapshot_digest" not in json.loads(calculation_event["payload_json"])
        before = _saved_calculation(db, batch["id"])
        original_list_details = PayrollRepository.list_details

        def list_corrupt_details(batch_id, employee_id=None, db=None):
            details = original_list_details(batch_id, employee_id, db)
            if batch_id == batch["id"]:
                details[0] = {
                    **details[0], "amount_cents": details[0]["amount_cents"] + 1
                }
            return details

        with monkeypatch.context() as patch:
            patch.setattr(PayrollRepository, "list_details", list_corrupt_details)
            with pytest.raises(ValueError, match="金额不一致"):
                getattr(PayrollWorkflowService, transition)(
                    batch["id"], approver, current["row_version"]
                )
        assert _saved_calculation(db, batch["id"]) == before


def test_exception_approval_audit_failure_rolls_back_resolution_and_version(
    client, calculation_clock, monkeypatch
):
    with client.application.app_context():
        db = get_db()
        preparer, approver = _actors(db)
        _seed_price_and_work(db, with_price=False)
        batch = PayrollWorkflowService.create_batch("2026-07", preparer, "integrity-audit-rollback")
        exception = PayrollRepository.list_exceptions(batch_id=batch["id"], db=db)[0]
        PayrollWorkflowService.propose_exception(
            exception["id"], preparer,
            {"proposed_price_micros": 10000, "resolution_reason": "人工工价核定"},
        )
        original = _saved_calculation(db, batch["id"])
        original_insert_event = PayrollRepository.insert_event

        def fail_approval_event(payload, connection):
            if payload["event_type"] == "exception_approved":
                raise RuntimeError("payroll audit unavailable")
            return original_insert_event(payload, connection)

        monkeypatch.setattr(PayrollRepository, "insert_event", fail_approval_event)
        with pytest.raises(RuntimeError, match="audit unavailable"):
            PayrollWorkflowService.approve_exception(exception["id"], approver)
        assert _saved_calculation(db, batch["id"]) == original
        assert PayrollRepository.price_resolution(exception["work_record_id"], db) is None
        assert db.execute(
            "SELECT status FROM payroll_exceptions WHERE id=?", (exception["id"],)
        ).fetchone()[0] == "proposed"


@pytest.mark.parametrize(
    "tamper", ("source", "employee", "zero-detail", "period", "preparer")
)
def test_submitted_snapshot_tampering_blocks_lock_without_partial_writes(
    client, calculation_clock, tamper
):
    with client.application.app_context():
        db = get_db()
        preparer, approver = _actors(db)
        employee_id, _route_id, _process_id, _actor = _seed_price_and_work(db)
        batch = PayrollWorkflowService.create_batch(
            "2026-07", preparer, f"integrity-tamper-{tamper}"
        )
        submitted = PayrollWorkflowService.submit(
            batch["id"], preparer, batch["row_version"]
        )
        line = PayrollRepository.list_lines(batch["id"], db=db)[0]
        if tamper == "source":
            alternate_id = _copy_work(db, _work_id(db, employee_id))
            db.execute(
                "UPDATE payroll_detail_lines SET source_id=?,work_record_id=? WHERE batch_id=?",
                (alternate_id, alternate_id, batch["id"]),
            )
        elif tamper == "employee":
            db.execute(
                "UPDATE payroll_employee_lines SET employee_id=? WHERE id=?",
                (approver["id"], line["id"]),
            )
        elif tamper == "zero-detail":
            db.execute(
                "INSERT INTO payroll_detail_lines "
                "(batch_id,employee_line_id,source_type,source_id,amount_cents) "
                "VALUES (?,?,'bonus',987654321,0)",
                (batch["id"], line["id"]),
            )
        elif tamper == "period":
            db.execute(
                "UPDATE payroll_batches SET period_start='2026-07-02 07:00:00' WHERE id=?",
                (batch["id"],),
            )
        else:
            db.execute("UPDATE payroll_batches SET prepared_by=NULL WHERE id=?", (batch["id"],))
        db.commit()
        before_lock = _saved_calculation(db, batch["id"])
        with pytest.raises(ValueError, match="完整|变化|重新"):
            PayrollWorkflowService.lock(batch["id"], approver, submitted["row_version"])
        assert _saved_calculation(db, batch["id"]) == before_lock
