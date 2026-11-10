import csv
import io
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
from modules.domain.payroll_policy import PayrollConflictError, work_amount_cents
from modules.services.payroll_service import PayrollWorkflowService
from modules.services.payroll_settlement_service import (
    PayrollSettlementService,
    _parse_receipt,
)
from modules.services.price_version_service import PriceVersionService
from modules.services.wage_service import WageService


def _actors(db):
    preparer_id = ensure_user(db, "payroll-preparer", "hash", "工资制单员", "admin", "PAY-PREP")
    approver_id = ensure_user(db, "payroll-approver", "hash", "工资审批员", "admin", "PAY-APP")
    return (
        {"id": preparer_id, "name": "工资制单员", "username": "payroll-preparer"},
        {"id": approver_id, "name": "工资审批员", "username": "payroll-approver"},
    )


def _exact_binding(db, route_id, process_id):
    return db.execute(
        "SELECT route_version.id AS route_version_id,"
        "item.process_version_id,route_version.name AS route_name,"
        "route_version.content_digest AS route_content_digest,"
        "process_version.name AS process_name,"
        "process_version.content_digest AS process_content_digest "
        "FROM process_routes route "
        "JOIN process_route_versions route_version "
        "ON route_version.id=route.current_effective_version_id "
        "JOIN process_route_version_items item "
        "ON item.route_version_id=route_version.id AND item.process_id=? "
        "JOIN process_versions process_version "
        "ON process_version.id=item.process_version_id WHERE route.id=?",
        (process_id, route_id),
    ).fetchone()


def _seed_price_and_work(
    db,
    created_at="2026-07-01 07:00:00",
    with_price=True,
    work_type="normal",
    configure_rework_rate=True,
):
    process_id = ensure_process(db, "工资测试工序")
    route_id = create_process_route(db, [process_id], "工资测试路线")
    worker_id = ensure_user(db, "payroll-worker", WORKER_HASH, "工资测试员工", "worker", "PAY-WORK")
    order_id = create_order(db, [process_id], quantity=20, product_code="PAY-PRODUCT")
    db.execute("UPDATE orders SET route_id=? WHERE id=?", (route_id, order_id))
    bind_order_process_versions(db, order_id)
    binding = _exact_binding(db, route_id, process_id)
    db.execute(
        "INSERT INTO work_records "
        "(order_id,process_id,process_version_id,process_name_snapshot,user_id,type,"
        "quantity,status,route_id,route_version_id,route_name_snapshot,created_at) "
        "VALUES (?,?,?,?,?,?,?,'approved',?,?,?,?)",
        (
            order_id,
            process_id,
            binding["process_version_id"],
            binding["process_name"],
            worker_id,
            work_type,
            3,
            route_id,
            binding["route_version_id"],
            binding["route_name"],
            created_at,
        ),
    )
    db.commit()
    actor = {"id": worker_id, "name": "工资测试员工"}
    if with_price:
        admin = {"id": 1, "name": "工价制单员"}
        version = PriceVersionService.create({
            "route_id": route_id,
            "route_version_id": binding["route_version_id"],
            "process_id": process_id,
            "process_version_id": binding["process_version_id"],
            "expected_route_content_digest": binding["route_content_digest"],
            "expected_process_content_digest": binding["process_content_digest"],
            "normal_unit_price": "1.25",
            "valid_from": "2026-07-01",
            "rework_rate_percent": 50 if work_type == "rework" and configure_rework_rate else None,
            "idempotency_key": (
                f"payroll-price-{binding['route_version_id']}-"
                f"{binding['process_version_id']}"
            ),
        }, admin)
        # Approve with a different identity to exercise the two-person rule.
        PriceVersionService.approve(version["id"], {"id": 2, "name": "工价审批员"}, version["row_version"])
    return worker_id, route_id, process_id, actor


def test_fixed_point_rounding_and_reporting_boundary():
    assert work_amount_cents(3, 12500) == 375
    assert work_amount_cents(1, 1) == 0
    with pytest.raises(ValueError):
        work_amount_cents(1, 10000, 10001)


def test_live_wage_estimate_uses_exact_approved_price_version(client):
    with client.application.app_context():
        db = get_db()
        worker_id, route_id, process_id, _ = _seed_price_and_work(db)
        binding = _exact_binding(db, route_id, process_id)

        # The legacy route_prices table is intentionally empty.  The estimate
        # must still resolve the approved route/process price version captured
        # on the work record.
        assert db.execute(
            "SELECT COUNT(*) FROM route_prices WHERE route_id=? AND process_id=?",
            (route_id, process_id),
        ).fetchone()[0] == 0

        result = WageService.calculate_wages(
            employee_id=str(worker_id),
            date_from="2026-07-01",
            date_to="2026-07-01",
            page=1,
            limit=50,
        )
        wage = result["wages"][0]
        detail = wage["details"][0]
        assert wage["total_quantity"] == 3
        assert wage["total_wage"] == pytest.approx(3.75)
        assert detail["unit_price"] == pytest.approx(1.25)
        assert detail["price_version_id"] is not None
        assert detail["price_source"] == "versioned_exact"
        assert detail["price_match_reason"] == "按路线版本和工序版本精确匹配"


def test_live_wage_estimate_blocks_unbound_work_when_versioned_prices_exist(client):
    with client.application.app_context():
        db = get_db()
        worker_id, route_id, process_id, _ = _seed_price_and_work(db)
        db.execute(
            "UPDATE work_records SET route_version_id=NULL, process_version_id=NULL "
            "WHERE user_id=? AND route_id=? AND process_id=?",
            (worker_id, route_id, process_id),
        )
        db.commit()

        result = WageService.calculate_wages(
            employee_id=str(worker_id),
            date_from="2026-07-01",
            date_to="2026-07-01",
            page=1,
            limit=50,
        )
        detail = result["wages"][0]["details"][0]
        assert result["wages"][0]["total_wage"] == 0
        assert detail["unit_price"] == 0
        assert detail["price_version_id"] is None
        assert detail["price_source"] == "missing_exact"
        assert detail["price_match_reason"] == "报工缺少路线版本和工序版本，无法精确匹配"


def test_payroll_batch_blocks_unbound_work_without_root_price_fallback(client):
    with client.application.app_context():
        db = get_db()
        preparer, _approver = _actors(db)
        worker_id, route_id, process_id, _ = _seed_price_and_work(db)
        db.execute(
            "UPDATE work_records SET route_version_id=NULL, process_version_id=NULL "
            "WHERE user_id=? AND route_id=? AND process_id=?",
            (worker_id, route_id, process_id),
        )
        db.commit()

        batch = PayrollWorkflowService.create_batch(
            "2026-07", preparer, "payroll-unbound-version-1"
        )
        assert batch["status"] == "exceptions_pending"
        assert batch["priced_record_count"] == 0
        assert batch["payable_wage_cents"] == 0
        exception = db.execute(
            "SELECT exception_type FROM payroll_exceptions WHERE batch_id=?",
            (batch["id"],),
        ).fetchone()
        assert exception["exception_type"] == "missing_price"


def test_payroll_batch_is_idempotent_and_confirms_with_two_actors(client):
    with client.application.app_context():
        db = get_db()
        preparer, approver = _actors(db)
        worker_id, _route_id, _process_id, _ = _seed_price_and_work(db)
        batch = PayrollWorkflowService.create_batch("2026-07", preparer, "payroll-test-1")
        assert batch["status"] == "draft"
        assert batch["payable_wage_cents"] == 375
        duplicate = PayrollWorkflowService.create_batch("2026-07", preparer, "payroll-test-1")
        assert duplicate["id"] == batch["id"]
        submitted = PayrollWorkflowService.submit(batch["id"], preparer, batch["row_version"])
        locked = PayrollWorkflowService.lock(batch["id"], approver, submitted["row_version"])
        confirmed = PayrollWorkflowService.confirm(batch["id"], approver, locked["row_version"])
        assert confirmed["status"] == "confirmed"
        mine = PayrollWorkflowService.my_payroll({"id": worker_id}, "2026-07")
        assert mine["lines"][0]["payable_wage_cents"] == 375
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE payroll_detail_lines SET amount_cents=1 WHERE batch_id=?", (batch["id"],))


def test_missing_price_requires_exception_and_dual_approval(client):
    with client.application.app_context():
        db = get_db()
        preparer, approver = _actors(db)
        _worker_id, _route_id, _process_id, _ = _seed_price_and_work(db, with_price=False)
        batch = PayrollWorkflowService.create_batch("2026-07", preparer, "payroll-exception-1")
        assert batch["status"] == "exceptions_pending"
        exception = PayrollWorkflowService.batch_detail(batch["id"])["events"]
        rows = db.execute("SELECT * FROM payroll_exceptions WHERE batch_id=?", (batch["id"],)).fetchall()
        assert len(rows) == 1
        exception_id = rows[0]["id"]
        PayrollWorkflowService.propose_exception(exception_id, preparer, {
            "proposed_price_micros": 10000,
            "resolution_reason": "人工核定测试工价",
        })
        with pytest.raises(ValueError, match="不同"):
            PayrollWorkflowService.approve_exception(exception_id, preparer)
        approval = PayrollWorkflowService.approve_exception(exception_id, approver)
        regenerated = PayrollWorkflowService.regenerate(
            batch["id"], preparer, approval["batch_row_version"]
        )
        assert regenerated["status"] == "draft"
        assert regenerated["payable_wage_cents"] == 300


def test_zero_price_is_an_exception_and_cannot_be_manually_confirmed_as_zero(client):
    with client.application.app_context():
        db = get_db()
        preparer, _approver = _actors(db)
        _worker_id, route_id, process_id, _ = _seed_price_and_work(
            db, with_price=False
        )
        db.execute(
            """
            INSERT INTO route_price_versions (
                route_id,route_version_id,process_id,process_version_id,
                normal_unit_price_micros,valid_from,status,
                created_by_name,approved_by_name,approved_at
            ) VALUES (?,?,?,?,0,'2026-07-01 00:00:00','approved',
                      'legacy','legacy',datetime('now'))
            """,
            (
                route_id,
                _exact_binding(db, route_id, process_id)["route_version_id"],
                process_id,
                _exact_binding(db, route_id, process_id)["process_version_id"],
            ),
        )
        db.commit()

        batch = PayrollWorkflowService.create_batch(
            "2026-07", preparer, "payroll-zero-price-1"
        )
        exception = db.execute(
            "SELECT * FROM payroll_exceptions WHERE batch_id=?",
            (batch["id"],),
        ).fetchone()
        assert batch["status"] == "exceptions_pending"
        assert batch["priced_record_count"] == 0
        assert exception["exception_type"] == "zero_price"
        with pytest.raises(ValueError, match="大于 0"):
            PayrollWorkflowService.propose_exception(
                exception["id"],
                preparer,
                {
                    "proposed_price_micros": 0,
                    "resolution_reason": "零工价不得直接通过",
                },
            )


def test_reporting_month_uses_0700_boundary(client):
    with client.application.app_context():
        db = get_db()
        preparer, _approver = _actors(db)
        _seed_price_and_work(db, created_at="2026-07-01 06:59:59")
        june = PayrollWorkflowService.create_batch("2026-06", preparer, "payroll-boundary-june")
        july = PayrollWorkflowService.create_batch("2026-07", preparer, "payroll-boundary-july")
        assert june["source_record_count"] == 1
        assert july["source_record_count"] == 0


def test_same_type_adjustments_are_append_only_and_reversible(client):
    with client.application.app_context():
        db = get_db()
        preparer, _approver = _actors(db)
        worker_id = ensure_user(db, "payroll-adjust-worker", WORKER_HASH, "调整员工", "worker", "PAY-ADJ")
        first = PayrollWorkflowService.create_adjustment(preparer, {
            "employee_id": worker_id, "payroll_month": "2026-07", "adjustment_type": "bonus",
            "amount_cents": 100, "reason": "第一笔奖金",
        })
        second = PayrollWorkflowService.create_adjustment(preparer, {
            "employee_id": worker_id, "payroll_month": "2026-07", "adjustment_type": "bonus",
            "amount_cents": 200, "reason": "第二笔奖金",
        })
        assert first["id"] != second["id"]
        reversal = PayrollWorkflowService.reverse_adjustment(first["id"], preparer, "冲销第一笔")
        rows = db.execute(
            "SELECT amount_cents,reversal_of_id FROM payroll_adjustments WHERE employee_id=? ORDER BY id",
            (worker_id,),
        ).fetchall()
        assert len(rows) == 3
        assert rows[-1]["reversal_of_id"] == first["id"]
        assert reversal["reversal_of_id"] == first["id"]


def test_manual_rework_rate_resolution_persists_into_revision(client):
    with client.application.app_context():
        db = get_db()
        preparer, approver = _actors(db)
        _seed_price_and_work(
            db, work_type="rework", configure_rework_rate=False
        )
        batch = PayrollWorkflowService.create_batch(
            "2026-07", preparer, "payroll-rework-rate-1"
        )
        assert batch["status"] == "exceptions_pending"
        exception = db.execute(
            "SELECT * FROM payroll_exceptions WHERE batch_id=?",
            (batch["id"],),
        ).fetchone()
        assert exception["exception_type"] == "missing_rework_rate"

        PayrollWorkflowService.propose_exception(
            exception["id"],
            preparer,
            {
                "proposed_rework_rate_basis_points": 5000,
                "resolution_reason": "按已审批返工倍率 50%",
            },
        )
        approval = PayrollWorkflowService.approve_exception(exception["id"], approver)
        resolution = db.execute(
            "SELECT * FROM payroll_work_price_resolutions WHERE work_record_id=?",
            (exception["work_record_id"],),
        ).fetchone()
        assert resolution["price_version_id"] is not None
        assert resolution["override_rework_rate_basis_points"] == 5000

        regenerated = PayrollWorkflowService.regenerate(
            batch["id"], preparer, approval["batch_row_version"]
        )
        assert regenerated["status"] == "draft"
        assert regenerated["payable_wage_cents"] == 188
        submitted = PayrollWorkflowService.submit(
            batch["id"], preparer, regenerated["row_version"]
        )
        locked = PayrollWorkflowService.lock(
            batch["id"], approver, submitted["row_version"]
        )
        confirmed = PayrollWorkflowService.confirm(
            batch["id"], approver, locked["row_version"]
        )
        revision = PayrollWorkflowService.create_batch(
            "2026-07",
            preparer,
            "payroll-rework-rate-revision",
            "验证人工核定跨版本复用",
            confirmed["id"],
        )
        assert revision["status"] == "draft"
        assert revision["exception_count"] == 0
        assert revision["payable_wage_cents"] == 188


def test_idempotency_key_cannot_be_reused_for_different_month(client):
    with client.application.app_context():
        db = get_db()
        preparer, _approver = _actors(db)
        PayrollWorkflowService.create_batch("2026-07", preparer, "same-payroll-key")
        with pytest.raises(PayrollConflictError, match="幂等键"):
            PayrollWorkflowService.create_batch("2026-08", preparer, "same-payroll-key")


def _confirmed_batch_for_settlement(db, preparer, approver):
    _seed_price_and_work(db)
    batch = PayrollWorkflowService.create_batch(
        "2026-07", preparer, "payroll-settlement-batch"
    )
    submitted = PayrollWorkflowService.submit(
        batch["id"], preparer, batch["row_version"]
    )
    locked = PayrollWorkflowService.lock(
        batch["id"], approver, submitted["row_version"]
    )
    return PayrollWorkflowService.confirm(
        batch["id"], approver, locked["row_version"]
    )


def _receipt_csv_for_payments(payments):
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow([
        "payment_reference", "employee_no", "employee_name", "paid_amount",
        "payment_status", "paid_at", "external_transaction_no", "failure_reason",
    ])
    for index, payment in enumerate(payments, start=1):
        writer.writerow([
            payment["payment_reference"], payment["employee_no"], payment["employee_name"],
            payment["payable_amount"], "success", "2026-07-02 10:00:00",
            f"TX-{index}", "",
        ])
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def _receipt_csv_for_transactions(payment, transactions):
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow([
        "payment_reference", "employee_no", "employee_name", "paid_amount",
        "payment_status", "paid_at", "external_transaction_no", "failure_reason",
    ])
    for index, (amount, transaction_no) in enumerate(transactions, start=1):
        writer.writerow([
            payment["payment_reference"], payment["employee_no"], payment["employee_name"],
            amount, "success", f"2026-07-02 10:0{index}:00", transaction_no, "",
        ])
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def _export_payment_rows(content):
    return list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))


@pytest.mark.parametrize(
    "header",
    [
        "银行账户", "收款账户", "收款人账号", "银行账号", "银行卡号",
        "账户", "帐号", "account_number", "bank_account",
    ],
)
def test_receipt_parser_rejects_account_headers(header):
    content = (
        "payment_reference,employee_no,employee_name,paid_amount,payment_status,"
        f"{header}\nPAY-1,EMP-1,员工,1.00,success,ignored\n"
    ).encode("utf-8")

    with pytest.raises(ValueError, match="不得包含银行卡号"):
        _parse_receipt(content)


def test_settlement_export_metadata_is_separate_from_download_content(client):
    with client.application.app_context():
        db = get_db()
        preparer, approver = _actors(db)
        batch = _confirmed_batch_for_settlement(db, preparer, approver)

        export = PayrollSettlementService.create_export(
            batch["id"], preparer, "settlement-export-1"
        )
        assert "csv_content_blob" not in export
        replay = PayrollSettlementService.create_export(
            batch["id"], preparer, "settlement-export-1"
        )
        assert replay["id"] == export["id"]
        assert replay["replayed"] is True
        assert "csv_content_blob" not in replay

        status = PayrollSettlementService.get_by_batch(batch["id"])
        assert "csv_content_blob" not in status["current_export"]
        content = PayrollSettlementService.download_export(export["id"])
        assert isinstance(content, bytes)
        payment = _export_payment_rows(content)[0]
        assert payment["payable_amount"] == "3.75"


def test_settlement_receipt_reconciliation_and_close_are_idempotent(client):
    with client.application.app_context():
        db = get_db()
        preparer, approver = _actors(db)
        batch = _confirmed_batch_for_settlement(db, preparer, approver)
        export = PayrollSettlementService.create_export(
            batch["id"], preparer, "settlement-export-close"
        )
        payments = _export_payment_rows(
            PayrollSettlementService.download_export(export["id"])
        )
        content = _receipt_csv_for_payments(payments)

        receipt = PayrollSettlementService.upload_receipt(
            export["id"], approver, "settlement-receipt-1", "bank.csv", content
        )
        receipt_replay = PayrollSettlementService.upload_receipt(
            export["id"], approver, "settlement-receipt-1", "bank.csv", content
        )
        assert receipt_replay["id"] == receipt["id"]
        assert receipt_replay["replayed"] is True

        run = PayrollSettlementService.reconcile(
            export["settlement_id"], approver, "settlement-reconcile-1"
        )
        assert run["status"] == "reconciled"
        assert run["expected_total_cents"] == run["successful_paid_cents"] == 375
        replay = PayrollSettlementService.reconcile(
            export["settlement_id"], approver, "settlement-reconcile-1"
        )
        assert replay["id"] == run["id"]
        assert replay["replayed"] is True

        status = PayrollSettlementService.get_by_batch(batch["id"])
        close_data = {
            "row_version": status["row_version"],
            "idempotency_key": "settlement-close-1",
            "close_reason": "财务回执核对一致",
        }
        close_record = PayrollSettlementService.close(
            export["settlement_id"], approver, close_data
        )
        close_replay = PayrollSettlementService.close(
            export["settlement_id"], approver, close_data
        )
        assert close_replay["id"] == close_record["id"]
        assert close_replay["replayed"] is True
        assert PayrollSettlementService.get_by_batch(batch["id"])["status"] == "closed"
        with pytest.raises(PayrollConflictError, match="不同的工资结账请求"):
            PayrollSettlementService.close(
                export["settlement_id"],
                approver,
                {**close_data, "close_reason": "同一键不能更换结账说明"},
            )
        with pytest.raises(PayrollConflictError, match="不同的工资结账请求"):
            PayrollSettlementService.close(
                export["settlement_id"],
                approver,
                {**close_data, "row_version": close_data["row_version"] + 1},
            )


def test_invalid_receipt_without_reference_blocks_close_until_explicitly_excluded(client):
    with client.application.app_context():
        db = get_db()
        preparer, approver = _actors(db)
        batch = _confirmed_batch_for_settlement(db, preparer, approver)
        export = PayrollSettlementService.create_export(
            batch["id"], preparer, "settlement-export-missing-reference"
        )
        payments = _export_payment_rows(
            PayrollSettlementService.download_export(export["id"])
        )
        receipt_text = _receipt_csv_for_payments(payments).decode("utf-8-sig").rstrip("\r\n")
        receipt_text += (
            "\r\n,UNKNOWN,未知员工,1.00,success,2026-07-02 10:05:00,TX-UNKNOWN,"
            "\r\n"
        )
        PayrollSettlementService.upload_receipt(
            export["id"], approver, "settlement-receipt-missing-reference",
            "bank.csv", receipt_text.encode("utf-8"),
        )

        run = PayrollSettlementService.reconcile(
            export["settlement_id"], approver,
            "settlement-reconcile-missing-reference",
        )
        assert run["status"] == "difference_pending"
        unknown = next(
            item for item in run["items"]
            if item["difference_type"] == "unknown_reference"
        )
        assert unknown["payment_reference"] == ""
        detail = json.loads(unknown["detail_json"])
        assert detail["receipt_item_id"]
        assert detail["validation_error"] == "缺少 payment_reference"

        status = PayrollSettlementService.get_by_batch(batch["id"])
        with pytest.raises(ValueError, match="只有最新对账完全通过"):
            PayrollSettlementService.close(
                export["settlement_id"], approver,
                {
                    "row_version": status["row_version"],
                    "idempotency_key": "settlement-close-missing-reference",
                    "close_reason": "不应通过",
                },
            )

        resolution = PayrollSettlementService.resolve_difference(
            unknown["id"],
            approver,
            {
                "resolution_code": "exclude_unknown_reference",
                "resolution_reason": "财务确认该空引用行为回执附加噪声，予以排除",
                "receipt_item_id": detail["receipt_item_id"],
                "idempotency_key": "settlement-resolution-missing-reference",
            },
        )
        assert resolution["ok"] is True
        resolved_run = PayrollSettlementService.reconcile(
            export["settlement_id"], approver,
            "settlement-reconcile-after-missing-reference-resolution",
        )
        assert resolved_run["status"] == "reconciled"
        assert resolved_run["blocking_count"] == 0
        assert resolved_run["successful_paid_cents"] == 375


def test_duplicate_payment_requires_resolution_before_settlement_close(client):
    with client.application.app_context():
        db = get_db()
        preparer, approver = _actors(db)
        batch = _confirmed_batch_for_settlement(db, preparer, approver)
        export = PayrollSettlementService.create_export(
            batch["id"], preparer, "settlement-export-duplicate"
        )
        payment = _export_payment_rows(
            PayrollSettlementService.download_export(export["id"])
        )[0]
        content = _receipt_csv_for_transactions(payment, [
            (payment["payable_amount"], "TX-DUPLICATE"),
            (payment["payable_amount"], "TX-DUPLICATE"),
        ])
        PayrollSettlementService.upload_receipt(
            export["id"], approver, "settlement-receipt-duplicate", "bank.csv", content
        )

        run = PayrollSettlementService.reconcile(
            export["settlement_id"], approver, "settlement-reconcile-duplicate"
        )
        duplicate = next(
            item for item in run["items"]
            if item["difference_type"] == "duplicate_success"
        )
        status = PayrollSettlementService.get_by_batch(batch["id"])
        with pytest.raises(ValueError, match="只有最新对账完全通过"):
            PayrollSettlementService.close(
                export["settlement_id"], approver,
                {
                    "row_version": status["row_version"],
                    "idempotency_key": "settlement-close-blocked",
                    "close_reason": "不应通过",
                },
            )

        detail = json.loads(duplicate["detail_json"])
        resolution = PayrollSettlementService.resolve_difference(
            duplicate["id"],
            approver,
            {
                "resolution_code": "exclude_duplicate",
                "resolution_reason": "银行回执重复行，经财务核实排除",
                "receipt_item_id": detail["receipt_item_id"],
                "idempotency_key": "settlement-resolution-duplicate",
            },
        )
        assert resolution["ok"] is True
        for changed_data in (
            {
                "resolution_code": "exclude_duplicate",
                "resolution_reason": "同一键不能更换处理原因",
                "receipt_item_id": detail["receipt_item_id"],
                "idempotency_key": "settlement-resolution-duplicate",
            },
            {
                "resolution_code": "exclude_unknown_reference",
                "resolution_reason": "银行回执重复行，经财务核实排除",
                "receipt_item_id": detail["receipt_item_id"],
                "idempotency_key": "settlement-resolution-duplicate",
            },
            {
                "resolution_code": "exclude_duplicate",
                "resolution_reason": "银行回执重复行，经财务核实排除",
                "receipt_item_id": detail["receipt_item_id"] + 999,
                "idempotency_key": "settlement-resolution-duplicate",
            },
        ):
            with pytest.raises(PayrollConflictError, match="不同的差异处理请求"):
                PayrollSettlementService.resolve_difference(
                    duplicate["id"], approver, changed_data
                )
        resolved_run = PayrollSettlementService.reconcile(
            export["settlement_id"], approver, "settlement-reconcile-after-resolution"
        )
        assert resolved_run["status"] == "reconciled"
        assert resolved_run["successful_paid_cents"] == 375


@pytest.mark.parametrize(
    "transactions",
    [
        [("2.00", "TX-PART-1"), ("1.75", "TX-PART-2")],
        [("2.00", ""), ("1.75", "")],
    ],
)
def test_split_payments_with_distinct_or_missing_transaction_numbers_reconcile(
    client, transactions
):
    with client.application.app_context():
        db = get_db()
        preparer, approver = _actors(db)
        batch = _confirmed_batch_for_settlement(db, preparer, approver)
        export = PayrollSettlementService.create_export(
            batch["id"], preparer, f"settlement-export-split-{transactions[0][1] or 'blank'}"
        )
        payment = _export_payment_rows(
            PayrollSettlementService.download_export(export["id"])
        )[0]
        PayrollSettlementService.upload_receipt(
            export["id"], approver,
            f"settlement-receipt-split-{transactions[0][1] or 'blank'}",
            "bank.csv", _receipt_csv_for_transactions(payment, transactions),
        )

        run = PayrollSettlementService.reconcile(
            export["settlement_id"], approver,
            f"settlement-reconcile-split-{transactions[0][1] or 'blank'}",
        )

        assert run["status"] == "reconciled"
        assert run["successful_paid_cents"] == 375
        assert run["blocking_count"] == 0
        assert run["items"] == []


def test_underpaid_receipt_blocks_settlement_and_identifies_employee(client):
    with client.application.app_context():
        db = get_db()
        preparer, approver = _actors(db)
        batch = _confirmed_batch_for_settlement(db, preparer, approver)
        export = PayrollSettlementService.create_export(
            batch["id"], preparer, "settlement-export-underpaid"
        )
        payment = _export_payment_rows(
            PayrollSettlementService.download_export(export["id"])
        )[0]
        PayrollSettlementService.upload_receipt(
            export["id"], approver, "settlement-receipt-underpaid", "bank.csv",
            _receipt_csv_for_transactions(payment, [("2.00", "TX-UNDERPAID")]),
        )

        run = PayrollSettlementService.reconcile(
            export["settlement_id"], approver, "settlement-reconcile-underpaid"
        )

        assert run["status"] == "difference_pending"
        assert run["successful_paid_cents"] == 200
        assert run["difference_cents"] == 175
        assert run["blocking_count"] == 1
        underpaid = run["items"][0]
        assert underpaid["difference_type"] == "underpaid"
        assert underpaid["employee_no_snapshot"] == payment["employee_no"]
        assert underpaid["employee_name_snapshot"] == payment["employee_name"]


def test_success_rows_without_transaction_numbers_are_overpaid_not_duplicates(client):
    with client.application.app_context():
        db = get_db()
        preparer, approver = _actors(db)
        batch = _confirmed_batch_for_settlement(db, preparer, approver)
        export = PayrollSettlementService.create_export(
            batch["id"], preparer, "settlement-export-blank-overpaid"
        )
        payment = _export_payment_rows(
            PayrollSettlementService.download_export(export["id"])
        )[0]
        PayrollSettlementService.upload_receipt(
            export["id"], approver, "settlement-receipt-blank-overpaid", "bank.csv",
            _receipt_csv_for_transactions(payment, [("3.75", ""), ("3.75", "")]),
        )

        run = PayrollSettlementService.reconcile(
            export["settlement_id"], approver, "settlement-reconcile-blank-overpaid"
        )

        assert run["successful_paid_cents"] == 750
        assert [item["difference_type"] for item in run["items"]] == ["overpaid"]


def test_reconciliation_idempotency_rejects_changed_receipt_digest(client):
    with client.application.app_context():
        db = get_db()
        preparer, approver = _actors(db)
        batch = _confirmed_batch_for_settlement(db, preparer, approver)
        export = PayrollSettlementService.create_export(
            batch["id"], preparer, "settlement-export-reconcile-conflict"
        )
        payment = _export_payment_rows(
            PayrollSettlementService.download_export(export["id"])
        )[0]
        content = _receipt_csv_for_payments([payment])
        PayrollSettlementService.upload_receipt(
            export["id"], approver, "settlement-receipt-reconcile-conflict-1",
            "bank.csv", content,
        )
        PayrollSettlementService.reconcile(
            export["settlement_id"], approver, "settlement-reconcile-conflict"
        )
        changed = content.decode("utf-8-sig").rstrip("\r\n") + (
            f"\r\n{payment['payment_reference']},{payment['employee_no']},"
            f"{payment['employee_name']},0.00,processing,2026-07-02 11:00:00,TX-PENDING,"
            "\r\n"
        )
        PayrollSettlementService.upload_receipt(
            export["id"], approver, "settlement-receipt-reconcile-conflict-2",
            "bank-2.csv", changed.encode("utf-8"),
        )

        with pytest.raises(PayrollConflictError, match="不同的工资对账请求"):
            PayrollSettlementService.reconcile(
                export["settlement_id"], approver, "settlement-reconcile-conflict"
            )


def test_export_versions_link_superseded_batch_to_replacement(client):
    with client.application.app_context():
        db = get_db()
        preparer, approver = _actors(db)
        batch = _confirmed_batch_for_settlement(db, preparer, approver)
        first = PayrollSettlementService.create_export(
            batch["id"], preparer, "settlement-export-version-1"
        )
        second = PayrollSettlementService.create_export(
            batch["id"], preparer, "settlement-export-version-2"
        )

        status = PayrollSettlementService.get_by_batch(batch["id"])
        versions = {row["id"]: row for row in status["exports"]}
        assert status["current_export"]["id"] == second["id"]
        assert versions[first["id"]]["status"] == "superseded"
        assert versions[first["id"]]["superseded_by_export_id"] == second["id"]
        assert versions[second["id"]]["status"] == "active"


def test_closed_settlement_rejects_all_child_ledger_mutations_in_database(client):
    with client.application.app_context():
        db = get_db()
        preparer, approver = _actors(db)
        batch = _confirmed_batch_for_settlement(db, preparer, approver)
        export = PayrollSettlementService.create_export(
            batch["id"], preparer, "settlement-export-db-lock"
        )
        payment = _export_payment_rows(
            PayrollSettlementService.download_export(export["id"])
        )[0]
        receipt = PayrollSettlementService.upload_receipt(
            export["id"], approver, "settlement-receipt-db-lock", "bank.csv",
            _receipt_csv_for_payments([payment]),
        )
        run = PayrollSettlementService.reconcile(
            export["settlement_id"], approver, "settlement-reconcile-db-lock"
        )
        fixture_item_id = db.execute(
            "INSERT INTO payroll_reconciliation_items "
            "(reconciliation_run_id,export_item_id,payment_reference,expected_cents,"
            "successful_paid_cents,difference_cents,difference_type,blocking,detail_json) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (run["id"], None, "FIXTURE", 0, 0, 0, "unknown_reference", 0, "{}"),
        ).lastrowid
        db.commit()
        status = PayrollSettlementService.get_by_batch(batch["id"])
        PayrollSettlementService.close(
            export["settlement_id"], approver,
            {
                "row_version": status["row_version"],
                "idempotency_key": "settlement-close-db-lock",
                "close_reason": "验证数据库结账锁定",
            },
        )
        export_item = db.execute(
            "SELECT * FROM payroll_export_items WHERE export_batch_id=? LIMIT 1",
            (export["id"],),
        ).fetchone()
        receipt_item = db.execute(
            "SELECT * FROM payroll_receipt_items WHERE receipt_batch_id=? LIMIT 1",
            (receipt["id"],),
        ).fetchone()
        statements = [
            (
                "UPDATE payroll_export_batches SET status='cancelled' WHERE id=?",
                (export["id"],), "reject export updates",
            ),
            (
                "INSERT INTO payroll_export_batches "
                "(settlement_id,export_version,status,row_count,total_cents,content_sha256,"
                "csv_content_blob,idempotency_key,created_by_name) "
                "VALUES (?,99,'active',0,0,?,?,'closed-export','fixture')",
                (export["settlement_id"], "0" * 64, b""), "reject export batches",
            ),
            (
                "INSERT INTO payroll_export_items "
                "(export_batch_id,employee_line_id,employee_name_snapshot,payable_cents,"
                "payment_reference,sequence_no) VALUES (?,?,?,?,?,?)",
                (export["id"], export_item["employee_line_id"], "fixture", 1, "CLOSED-ITEM", 99),
                "reject export items",
            ),
            (
                "INSERT INTO payroll_receipt_batches "
                "(export_batch_id,status,content_sha256,idempotency_key,uploaded_by_name) "
                "VALUES (?,'accepted',?,'closed-receipt','fixture')",
                (export["id"], "1" * 64), "reject receipt batches",
            ),
            (
                "INSERT INTO payroll_receipt_items "
                "(receipt_batch_id,row_number,validation_status) VALUES (?,99,'invalid')",
                (receipt["id"],), "reject receipt items",
            ),
            (
                "INSERT INTO payroll_reconciliation_runs "
                "(settlement_id,export_batch_id,run_version,status,expected_total_cents,"
                "successful_paid_cents,difference_cents,blocking_count,receipt_digest,"
                "idempotency_key,executed_by_name) "
                "VALUES (?,?,99,'reconciled',0,0,0,0,?,'closed-run','fixture')",
                (export["settlement_id"], export["id"], "2" * 64),
                "reject reconciliation runs",
            ),
            (
                "INSERT INTO payroll_reconciliation_items "
                "(reconciliation_run_id,payment_reference,difference_type,blocking) "
                "VALUES (?,'CLOSED','unknown_reference',1)",
                (run["id"],), "reject reconciliation items",
            ),
            (
                "INSERT INTO payroll_reconciliation_resolutions "
                "(reconciliation_item_id,receipt_item_id,resolution_code,resolution_reason,"
                "idempotency_key,resolved_by_name) VALUES (?,?,?,?,?,?)",
                (fixture_item_id, receipt_item["id"], "exclude_unknown_reference",
                 "fixture", "closed-resolution", "fixture"),
                "reject resolutions",
            ),
        ]
        for statement, params, message in statements:
            with pytest.raises(sqlite3.IntegrityError, match=message):
                db.execute(statement, params)
