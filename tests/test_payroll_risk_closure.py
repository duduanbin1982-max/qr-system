import csv
import io
import json

import pytest

from modules.db import get_db
from modules.services.payroll_settlement_service import PayrollSettlementService


ACTOR = {"id": None, "name": "工资风险收口测试"}


def _insert_confirmed_batch(db, *, month="2026-10", payable_cents=375):
    batch_id = db.execute(
        "INSERT INTO payroll_batches "
        "(payroll_month,version,period_start,period_end,status,source_cutoff_at,"
        "input_digest,payable_wage_cents) "
        "VALUES (?,1,?,?,'draft',?,?,?)",
        (
            month,
            f"{month}-01 07:00:00",
            f"{month}-28 07:00:00",
            f"{month}-28 06:59:59",
            "risk-closure-fixture",
            payable_cents,
        ),
    ).lastrowid
    db.execute(
        "INSERT INTO payroll_employee_lines "
        "(batch_id,employee_name_snapshot,employee_no_snapshot,payable_wage_cents) "
        "VALUES (?,?,?,?)",
        (batch_id, "工资测试员工", "PAY-RISK-1", payable_cents),
    )
    if payable_cents < 0:
        # Model a historical V97-confirmed negative batch, which V98 must keep
        # visible but must refuse to export. Reinstall the V98 transition guard
        # immediately after creating the legacy fixture.
        from modules.migration_payroll_risk_closure import m098_payroll_risk_closure

        db.execute("DROP TRIGGER trg_payroll_batch_nonnegative_transition")
    for status in ("review_pending", "locked", "confirmed"):
        db.execute("UPDATE payroll_batches SET status=? WHERE id=?", (status, batch_id))
    db.commit()
    if payable_cents < 0:
        m098_payroll_risk_closure(db)
    return batch_id


def _payment_row(export_id):
    content = PayrollSettlementService.download_export(export_id)
    return next(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))


def _receipt_content(payment, rows=None):
    rows = rows or [(payment["payable_amount"], "TX-RISK-1")]
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow([
        "payment_reference",
        "employee_no",
        "employee_name",
        "paid_amount",
        "payment_status",
        "paid_at",
        "external_transaction_no",
        "failure_reason",
    ])
    for index, (amount, transaction_no) in enumerate(rows, start=1):
        writer.writerow([
            payment["payment_reference"],
            payment["employee_no"],
            payment["employee_name"],
            amount,
            "success",
            f"2026-10-02 10:0{index}:00",
            transaction_no,
            "",
        ])
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def _simulate_legacy_invalidated_batch(db, batch_id):
    triggers = db.execute(
        "SELECT name,sql FROM sqlite_master "
        "WHERE type='trigger' AND tbl_name='payroll_batches'"
    ).fetchall()
    settlement_guards = [
        row["name"] for row in triggers
        if "payroll_settlements" in str(row["sql"] or "").lower()
    ]
    assert settlement_guards, "V98 must install a settled-batch database guard"
    for name in settlement_guards:
        db.execute(f"DROP TRIGGER \"{name}\"")
    db.execute("UPDATE payroll_batches SET status='voided' WHERE id=?", (batch_id,))
    db.commit()


def test_formal_export_rejects_historical_negative_confirmed_batch(client):
    with client.application.app_context():
        db = get_db()
        batch_id = _insert_confirmed_batch(db, payable_cents=-125)

        with pytest.raises(ValueError, match="1 名员工应付金额为负数"):
            PayrollSettlementService.create_export(
                batch_id, ACTOR, "negative-formal-export"
            )

        assert db.execute(
            "SELECT COUNT(*) FROM payroll_settlements WHERE batch_id=?",
            (batch_id,),
        ).fetchone()[0] == 0
        assert db.execute(
            "SELECT COUNT(*) FROM payroll_events WHERE batch_id=?",
            (batch_id,),
        ).fetchone()[0] == 0


def test_receipt_and_reconciliation_revalidate_linked_batch(client):
    with client.application.app_context():
        db = get_db()
        batch_id = _insert_confirmed_batch(db)
        export = PayrollSettlementService.create_export(
            batch_id, ACTOR, "risk-export-revalidate"
        )
        content = _receipt_content(_payment_row(export["id"]))
        _simulate_legacy_invalidated_batch(db, batch_id)

        with pytest.raises(ValueError, match="当前有效的已确认批次"):
            PayrollSettlementService.upload_receipt(
                export["id"], ACTOR, "risk-receipt-invalid-batch", "bank.csv", content
            )
        with pytest.raises(ValueError, match="当前有效的已确认批次"):
            PayrollSettlementService.reconcile(
                export["settlement_id"], ACTOR, "risk-reconcile-invalid-batch"
            )


def test_difference_resolution_revalidates_linked_batch(client):
    with client.application.app_context():
        db = get_db()
        batch_id = _insert_confirmed_batch(db)
        export = PayrollSettlementService.create_export(
            batch_id, ACTOR, "risk-export-difference"
        )
        payment = _payment_row(export["id"])
        content = _receipt_content(payment, [
            (payment["payable_amount"], "TX-RISK-DUPLICATE"),
            (payment["payable_amount"], "TX-RISK-DUPLICATE"),
        ])
        PayrollSettlementService.upload_receipt(
            export["id"], ACTOR, "risk-receipt-difference", "bank.csv", content
        )
        run = PayrollSettlementService.reconcile(
            export["settlement_id"], ACTOR, "risk-reconcile-difference"
        )
        duplicate = next(
            item for item in run["items"] if item["difference_type"] == "duplicate_success"
        )
        receipt_item_id = json.loads(duplicate["detail_json"])["receipt_item_id"]
        _simulate_legacy_invalidated_batch(db, batch_id)

        with pytest.raises(ValueError, match="当前有效的已确认批次"):
            PayrollSettlementService.resolve_difference(
                duplicate["id"],
                ACTOR,
                {
                    "resolution_code": "exclude_duplicate",
                    "resolution_reason": "财务确认重复回执",
                    "receipt_item_id": receipt_item_id,
                    "idempotency_key": "risk-resolve-invalid-batch",
                },
            )


def test_close_revalidates_linked_batch_and_disables_can_close(client):
    with client.application.app_context():
        db = get_db()
        batch_id = _insert_confirmed_batch(db)
        export = PayrollSettlementService.create_export(
            batch_id, ACTOR, "risk-export-close"
        )
        payment = _payment_row(export["id"])
        PayrollSettlementService.upload_receipt(
            export["id"],
            ACTOR,
            "risk-receipt-close",
            "bank.csv",
            _receipt_content(payment),
        )
        PayrollSettlementService.reconcile(
            export["settlement_id"], ACTOR, "risk-reconcile-close"
        )
        before = PayrollSettlementService.get_by_batch(batch_id)
        assert before["can_close"] is True
        _simulate_legacy_invalidated_batch(db, batch_id)

        after = PayrollSettlementService.get_by_batch(batch_id)
        assert after["can_close"] is False
        with pytest.raises(ValueError, match="当前有效的已确认批次"):
            PayrollSettlementService.close(
                export["settlement_id"],
                ACTOR,
                {
                    "row_version": after["row_version"],
                    "idempotency_key": "risk-close-invalid-batch",
                    "close_reason": "不应允许结账",
                },
            )


def test_committed_settlement_command_replays_remain_stable_after_batch_invalidation(client):
    with client.application.app_context():
        db = get_db()
        batch_id = _insert_confirmed_batch(db)
        export = PayrollSettlementService.create_export(
            batch_id, ACTOR, "risk-export-replay"
        )
        content = _receipt_content(_payment_row(export["id"]))
        receipt = PayrollSettlementService.upload_receipt(
            export["id"], ACTOR, "risk-receipt-replay", "bank.csv", content
        )
        run = PayrollSettlementService.reconcile(
            export["settlement_id"], ACTOR, "risk-reconcile-replay"
        )
        _simulate_legacy_invalidated_batch(db, batch_id)

        receipt_replay = PayrollSettlementService.upload_receipt(
            export["id"], ACTOR, "risk-receipt-replay", "bank.csv", content
        )
        run_replay = PayrollSettlementService.reconcile(
            export["settlement_id"], ACTOR, "risk-reconcile-replay"
        )

        assert receipt_replay["id"] == receipt["id"]
        assert receipt_replay["replayed"] is True
        assert run_replay["id"] == run["id"]
        assert run_replay["replayed"] is True
