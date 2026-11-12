"""Real HTTP-to-database coverage for the payroll settlement close workflow."""

import csv
import io

from modules.db import get_db


def _insert_confirmed_batch(db):
    batch_id = db.execute(
        "INSERT INTO payroll_batches "
        "(payroll_month,version,period_start,period_end,status,source_cutoff_at,"
        "input_digest,payable_wage_cents) "
        "VALUES ('2026-10',1,'2026-10-01 07:00:00','2026-11-01 07:00:00',"
        "'draft','2026-11-01 06:59:59','http-flow-fixture',375)"
    ).lastrowid
    line_id = db.execute(
        "INSERT INTO payroll_employee_lines "
        "(batch_id,employee_name_snapshot,employee_no_snapshot,payable_wage_cents) "
        "VALUES (?,?,?,?)",
        (batch_id, "跨层测试员工", "PAY-HTTP-1", 375),
    ).lastrowid
    for status in ("review_pending", "locked", "confirmed"):
        db.execute("UPDATE payroll_batches SET status=? WHERE id=?", (status, batch_id))
    db.commit()
    return batch_id, line_id


def _receipt_csv(payment):
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
    writer.writerow([
        payment["payment_reference"],
        payment["employee_no"],
        payment["employee_name"],
        payment["payable_amount"],
        "success",
        "2026-11-02 10:00:00",
        "TX-PAYROLL-HTTP-1",
        "",
    ])
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def test_payroll_settlement_http_flow_persists_and_replays_commands(
    client, auth_headers
):
    with client.application.app_context():
        db = get_db()
        batch_id, line_id = _insert_confirmed_batch(db)

    export_headers = {**auth_headers, "Idempotency-Key": "http-export-1"}
    export_response = client.post(
        f"/api/payroll/batches/{batch_id}/settlement/exports",
        headers=export_headers,
        json={},
    )
    assert export_response.status_code == 201
    assert "no-store" in export_response.headers["Cache-Control"]
    export = export_response.get_json()
    export_id = export["id"]
    settlement_id = export["settlement_id"]

    export_replay = client.post(
        f"/api/payroll/batches/{batch_id}/settlement/exports",
        headers=export_headers,
        json={},
    )
    assert export_replay.status_code == 200
    assert export_replay.get_json()["id"] == export_id
    assert export_replay.get_json()["replayed"] is True

    download = client.get(
        f"/api/payroll/settlement/exports/{export_id}/download",
        headers=auth_headers,
    )
    assert download.status_code == 200
    assert download.headers["X-Payroll-Export-Mode"] == "payment_list"
    assert "no-store" in download.headers["Cache-Control"]
    payments = list(csv.DictReader(io.StringIO(download.data.decode("utf-8-sig"))))
    assert len(payments) == 1
    assert payments[0]["payment_reference"].endswith(f"L{line_id:010d}")
    assert payments[0]["payable_amount"] == "3.75"
    receipt_content = _receipt_csv(payments[0])

    receipt_headers = {**auth_headers, "Idempotency-Key": "http-receipt-1"}
    receipt_response = client.post(
        f"/api/payroll/settlement/exports/{export_id}/receipts",
        headers=receipt_headers,
        data={"file": (io.BytesIO(receipt_content), "receipt.csv")},
        content_type="multipart/form-data",
    )
    assert receipt_response.status_code == 201
    receipt_id = receipt_response.get_json()["id"]

    receipt_replay = client.post(
        f"/api/payroll/settlement/exports/{export_id}/receipts",
        headers=receipt_headers,
        data={"file": (io.BytesIO(receipt_content), "receipt.csv")},
        content_type="multipart/form-data",
    )
    assert receipt_replay.status_code == 200
    assert receipt_replay.get_json()["id"] == receipt_id
    assert receipt_replay.get_json()["replayed"] is True

    reconcile_headers = {**auth_headers, "Idempotency-Key": "http-reconcile-1"}
    reconcile_response = client.post(
        f"/api/payroll/settlements/{settlement_id}/reconcile",
        headers=reconcile_headers,
        json={},
    )
    assert reconcile_response.status_code == 201
    reconciliation = reconcile_response.get_json()
    assert reconciliation["status"] == "reconciled"
    assert reconciliation["expected_total_cents"] == 375
    assert reconciliation["successful_paid_cents"] == 375
    assert reconciliation["blocking_count"] == 0

    reconcile_replay = client.post(
        f"/api/payroll/settlements/{settlement_id}/reconcile",
        headers=reconcile_headers,
        json={},
    )
    assert reconcile_replay.status_code == 200
    assert reconcile_replay.get_json()["id"] == reconciliation["id"]
    assert reconcile_replay.get_json()["replayed"] is True

    settlement_response = client.get(
        f"/api/payroll/batches/{batch_id}/settlement",
        headers=auth_headers,
    )
    assert settlement_response.status_code == 200
    settlement = settlement_response.get_json()
    assert settlement["status"] == "reconciled"
    assert settlement["can_close"] is True

    close_payload = {
        "row_version": settlement["row_version"],
        "idempotency_key": "http-close-1",
        "close_reason": "HTTP 跨层支付回执核对一致",
    }
    close_response = client.post(
        f"/api/payroll/settlements/{settlement_id}/close",
        headers=auth_headers,
        json=close_payload,
    )
    assert close_response.status_code == 201
    close_record = close_response.get_json()

    close_replay = client.post(
        f"/api/payroll/settlements/{settlement_id}/close",
        headers=auth_headers,
        json=close_payload,
    )
    assert close_replay.status_code == 200
    assert close_replay.get_json()["id"] == close_record["id"]
    assert close_replay.get_json()["replayed"] is True

    with client.application.app_context():
        db = get_db()
        persisted = db.execute(
            "SELECT status,current_export_batch_id,latest_reconciliation_run_id "
            "FROM payroll_settlements WHERE id=?",
            (settlement_id,),
        ).fetchone()
        assert dict(persisted) == {
            "status": "closed",
            "current_export_batch_id": export_id,
            "latest_reconciliation_run_id": reconciliation["id"],
        }
        assert db.execute(
            "SELECT COUNT(*) FROM payroll_export_batches WHERE settlement_id=?",
            (settlement_id,),
        ).fetchone()[0] == 1
        assert db.execute(
            "SELECT COUNT(*) FROM payroll_receipt_batches WHERE export_batch_id=?",
            (export_id,),
        ).fetchone()[0] == 1
        assert db.execute(
            "SELECT COUNT(*) FROM payroll_close_records WHERE settlement_id=?",
            (settlement_id,),
        ).fetchone()[0] == 1


def test_payroll_settlement_export_rejects_worker_role(
    client, worker_auth_headers
):
    with client.application.app_context():
        batch_id, _line_id = _insert_confirmed_batch(get_db())

    response = client.post(
        f"/api/payroll/batches/{batch_id}/settlement/exports",
        headers={**worker_auth_headers, "Idempotency-Key": "worker-denied-export"},
        json={},
    )

    assert response.status_code == 403
    assert response.get_json()["error"] == "无权限"
    with client.application.app_context():
        assert get_db().execute(
            "SELECT COUNT(*) FROM payroll_settlements WHERE batch_id=?",
            (batch_id,),
        ).fetchone()[0] == 0
