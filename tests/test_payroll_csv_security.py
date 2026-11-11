"""HTTP regression coverage for payroll spreadsheet-formula neutralization."""

import csv
import io

from modules.db import get_db
from modules.services.wage_service import WageService


def _csv_rows(response):
    return list(csv.reader(io.StringIO(response.data.decode("utf-8-sig"))))


def test_live_wage_csv_neutralizes_formula_like_text(client, auth_headers, monkeypatch):
    monkeypatch.setattr(
        WageService,
        "calculate_wages",
        staticmethod(lambda *_args, **_kwargs: {
            "wages": [{
                "employee_name": "  =HYPERLINK(\"bad\")",
                "employee_no": "\tplain",
                "total_quantity": 1,
                "total_wage": 2.5,
                "details": [{
                    "date": "2026-11-10 08:00:00",
                    "order_no": "+CMD",
                    "product_name": "\rplain",
                    "process_name": "@SUM(A1)",
                    "quantity": 1,
                    "unit_price": 2.5,
                    "wage": 2.5,
                }],
            }],
            "total": 1,
        }),
    )

    response = client.get("/api/wages?export=csv", headers=auth_headers)

    assert response.status_code == 200
    row = _csv_rows(response)[1]
    assert row[0] == "'  =HYPERLINK(\"bad\")"
    assert row[1] == "'\tplain"
    assert row[5] == "'+CMD"
    assert row[6] == "'\rplain"
    assert row[7] == "'@SUM(A1)"


def test_payroll_preview_csv_neutralizes_whitespace_prefixed_formulas(
    client, auth_headers
):
    with client.application.app_context():
        db = get_db()
        batch_id = db.execute(
            "INSERT INTO payroll_batches "
            "(payroll_month,version,period_start,period_end,status,source_cutoff_at,"
            "input_digest,payable_wage_cents) "
            "VALUES ('2026-11',1,'2026-11-01 07:00:00','2026-12-01 07:00:00',"
            "'draft','2026-12-01 06:59:59','csv-security',250)"
        ).lastrowid
        db.execute(
            "INSERT INTO payroll_employee_lines "
            "(batch_id,employee_name_snapshot,employee_no_snapshot,payable_wage_cents) "
            "VALUES (?,?,?,250)",
            (batch_id, " \t=SUM(A1)", "\rplain"),
        )
        for status in ("review_pending", "locked"):
            db.execute(
                "UPDATE payroll_batches SET status=? WHERE id=?",
                (status, batch_id),
            )
        db.commit()

    response = client.get(
        f"/api/payroll/batches/{batch_id}/export", headers=auth_headers
    )

    assert response.status_code == 200
    assert response.headers["X-Payroll-Export-Mode"] == "preview"
    row = _csv_rows(response)[1]
    assert row[2] == "' \t=SUM(A1)"
    assert row[3] == "'\rplain"


def test_formal_payment_list_neutralizes_formula_like_employee_fields(
    client, auth_headers
):
    with client.application.app_context():
        db = get_db()
        batch_id = db.execute(
            "INSERT INTO payroll_batches "
            "(payroll_month,version,period_start,period_end,status,source_cutoff_at,"
            "input_digest,payable_wage_cents) "
            "VALUES ('2026-11',1,'2026-11-01 07:00:00','2026-12-01 07:00:00',"
            "'draft','2026-12-01 06:59:59','payment-csv-security',250)"
        ).lastrowid
        db.execute(
            "INSERT INTO payroll_employee_lines "
            "(batch_id,employee_name_snapshot,employee_no_snapshot,payable_wage_cents) "
            "VALUES (?,?,?,250)",
            (batch_id, '  =HYPERLINK("bad")', "\t@CMD"),
        )
        for status in ("review_pending", "locked", "confirmed"):
            db.execute(
                "UPDATE payroll_batches SET status=? WHERE id=?",
                (status, batch_id),
            )
        db.commit()

    create = client.post(
        f"/api/payroll/batches/{batch_id}/settlement/exports",
        headers={**auth_headers, "Idempotency-Key": "payment-csv-security-export"},
        json={},
    )
    assert create.status_code == 201
    export_id = create.get_json()["id"]

    download = client.get(
        f"/api/payroll/settlement/exports/{export_id}/download",
        headers=auth_headers,
    )

    assert download.status_code == 200
    assert download.headers["X-Payroll-Export-Mode"] == "payment_list"
    row = next(csv.DictReader(io.StringIO(download.data.decode("utf-8-sig"))))
    assert row["employee_no"] == "'\t@CMD"
    assert row["employee_name"] == "'  =HYPERLINK(\"bad\")"
