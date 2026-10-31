"""Read APIs must apply the same payroll data scope to rows and metadata."""

import pytest

from factories import WORKER_HASH, ensure_user
from modules.db import get_db
from modules.middleware.auth import AuthSessionService
from modules.repositories.payroll_repository import PayrollRepository
from modules.services.wage_service import WageService


def _authenticate(monkeypatch, user_id, permissions):
    actor = {
        "id": user_id,
        "name": "工资范围测试员",
        "_permissions": list(permissions),
    }
    monkeypatch.setattr(
        AuthSessionService, "authenticate", lambda _token: (dict(actor), None)
    )
    return {"Authorization": "Bearer payroll-scope-test"}


def _employees(db):
    own_id = ensure_user(db, "wage-scope-own", WORKER_HASH, "本人", "worker", "SCOPE-OWN")
    other_id = ensure_user(db, "wage-scope-other", WORKER_HASH, "他人", "worker", "SCOPE-OTHER")
    return own_id, other_id


def _batch(db, own_id, other_id, status="confirmed"):
    batch_id = db.execute(
        "INSERT INTO payroll_batches "
        "(payroll_month,version,period_start,period_end,source_cutoff_at,"
        "normal_wage_cents,payable_wage_cents,source_record_count,priced_record_count,"
        "input_digest,prepared_by_name,revision_reason) "
        "VALUES ('2026-07',1,'2026-07-01 07:00:00','2026-08-01 07:00:00',"
        "'2026-08-02 00:00:00',12500,12500,2,2,'private-digest','制单员','他人调整原因')"
    ).lastrowid
    for employee_id, name, amount in ((own_id, "本人", 2500), (other_id, "他人", 10000)):
        line_id = db.execute(
            "INSERT INTO payroll_employee_lines "
            "(batch_id,employee_id,employee_name_snapshot,normal_quantity,"
            "normal_wage_cents,payable_wage_cents) VALUES (?,?,?,1,?,?)",
            (batch_id, employee_id, name, amount, amount),
        ).lastrowid
        db.execute(
            "INSERT INTO payroll_detail_lines "
            "(batch_id,employee_line_id,source_type,source_id,quantity,amount_cents) "
            "VALUES (?,?,'normal_work',?,1,?)",
            (batch_id, line_id, employee_id, amount),
        )
    db.execute(
        "INSERT INTO payroll_events (batch_id,event_type,reason,payload_json) "
        "VALUES (?,'scope_test','他人工资调整','{\"private_wage\":10000}')",
        (batch_id,),
    )
    if status == "confirmed":
        for next_status in ("review_pending", "locked", "confirmed"):
            db.execute("UPDATE payroll_batches SET status=? WHERE id=?", (next_status, batch_id))
    db.commit()
    return batch_id


@pytest.mark.parametrize("employee_filter", ("", "?employee_id={own_id}"))
def test_self_batch_lines_scope_totals_and_exclude_workflow_metadata(
    client, monkeypatch, employee_filter
):
    with client.application.app_context():
        db = get_db()
        own_id, other_id = _employees(db)
        batch_id = _batch(db, own_id, other_id)
    headers = _authenticate(monkeypatch, own_id, ["wages:view_self"])
    monkeypatch.setattr(
        PayrollRepository, "list_exceptions",
        lambda **_filters: [{"employee_id": other_id, "snapshot_json": "他人工资异常"}],
    )

    response = client.get(
        f"/api/payroll/batches/{batch_id}/lines"
        + employee_filter.format(own_id=own_id),
        headers=headers,
    )

    assert response.status_code == 200
    result = response.get_json()
    assert {row["employee_id"] for row in result["lines"]} == {own_id}
    assert {row["employee_id"] for row in result["details"]} == {own_id}
    assert result["batch"]["payable_wage_cents"] == 2500
    assert result["batch"]["payable_wage_yuan"] == "25.00"
    assert result["exceptions"] == []
    assert result["events"] == []
    assert not ({"input_digest", "source_cutoff_at", "revision_reason", "prepared_by_name"}
                & result["batch"].keys())
    assert "他人" not in response.get_data(as_text=True)


def test_self_cannot_view_draft_or_other_employee_batch_lines(client, monkeypatch):
    with client.application.app_context():
        db = get_db()
        own_id, other_id = _employees(db)
        batch_id = _batch(db, own_id, other_id, status="draft")
    headers = _authenticate(monkeypatch, own_id, ["wages:view_self"])
    assert client.get(
        f"/api/payroll/batches/{batch_id}/lines?employee_id={own_id}", headers=headers
    ).status_code == 403
    assert client.get(
        f"/api/payroll/batches/{batch_id}/lines?employee_id={other_id}", headers=headers
    ).status_code == 403


@pytest.mark.parametrize("permission", ("wages:view_all", "wages:prepare", "wages:approve"))
def test_privileged_batch_reader_preserves_full_metadata(client, monkeypatch, permission):
    with client.application.app_context():
        db = get_db()
        own_id, other_id = _employees(db)
        batch_id = _batch(db, own_id, other_id, status="draft")
    headers = _authenticate(monkeypatch, own_id, [permission])
    response = client.get(f"/api/payroll/batches/{batch_id}/lines", headers=headers)
    assert response.status_code == 200
    result = response.get_json()
    assert {row["employee_id"] for row in result["lines"]} == {own_id, other_id}
    assert result["batch"]["payable_wage_cents"] == 12500
    assert result["batch"]["input_digest"] == "private-digest"
    assert result["events"][0]["reason"] == "他人工资调整"


GLOBAL_READS = (
    "/api/daily-report?date=2026-07-01",
    "/api/wages/monthly-summary?year_month=2026-07",
    "/api/wages/process-summary?year_month=2026-07",
    "/api/wages/trends",
    "/api/wages/position-summary?year_month=2026-07",
    "/api/wages/prediction",
    "/api/wages/snapshot-status?year_month=2026-07",
)


@pytest.mark.parametrize("permission", ("wages:view_self", "wages:view", "wages:edit"))
@pytest.mark.parametrize("url", GLOBAL_READS)
def test_global_wage_analytics_require_explicit_global_read(
    client, monkeypatch, permission, url
):
    headers = _authenticate(monkeypatch, 1, [permission])
    assert client.get(url, headers=headers).status_code == 403


@pytest.mark.parametrize("permission", ("wages:view_all", "wages:prepare", "wages:approve"))
@pytest.mark.parametrize("url", GLOBAL_READS)
def test_global_read_permissions_allow_wage_analytics(client, monkeypatch, permission, url):
    headers = _authenticate(monkeypatch, 1, [permission])
    assert client.get(url, headers=headers).status_code == 200


@pytest.mark.parametrize("filter_suffix", ("", "&user_id={own_id}"))
def test_legacy_adjustment_reads_are_self_scoped(client, monkeypatch, filter_suffix):
    with client.application.app_context():
        db = get_db()
        own_id, other_id = _employees(db)
        # Model pre-cutover history, then restore the actual read-only guard.
        guard_sql = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND name='prevent_legacy_wage_adjustment_insert'"
        ).fetchone()[0]
        db.execute("DROP TRIGGER prevent_legacy_wage_adjustment_insert")
        db.executemany(
            "INSERT INTO wage_adjustments "
            "(user_id,year_month,type,amount,reason) VALUES (?,'2026-07','bonus',?,?)",
            ((own_id, 10, "本人奖金"), (other_id, 999, "他人奖金")),
        )
        db.execute(guard_sql)
        db.commit()
    headers = _authenticate(monkeypatch, own_id, ["wages:view_self"])
    suffix = "?year_month=2026-07" + filter_suffix.format(own_id=own_id)
    response = client.get("/api/wages/adjustments" + suffix, headers=headers)
    assert response.status_code == 200
    assert [row["user_id"] for row in response.get_json()] == [own_id]
    assert client.get(
        "/api/wages/adjustments-total" + suffix, headers=headers
    ).get_json()["net"] == 10
    for path in ("/api/wages/adjustments", "/api/wages/adjustments-total"):
        assert client.get(
            path + f"?year_month=2026-07&user_id={other_id}", headers=headers
        ).status_code == 403


def test_employee_estimate_scope_cannot_be_widened(client, monkeypatch):
    headers = _authenticate(monkeypatch, 321, ["wages:view_self"])
    called = []

    def calculate(employee_id, *args):
        called.append(employee_id)
        return {"wages": [], "total": 0, "page": 1, "limit": 200}

    monkeypatch.setattr(WageService, "calculate_wages", calculate)
    for suffix in ("", "?employee_id=321"):
        assert client.get("/api/wages" + suffix, headers=headers).status_code == 200
    assert called == [321, 321]
    assert client.get("/api/wages?employee_id=322", headers=headers).status_code == 403


@pytest.mark.parametrize("permission", ("wages:view", "wages:edit"))
def test_legacy_permissions_do_not_authorize_new_ledger(client, monkeypatch, permission):
    headers = _authenticate(monkeypatch, 1, [permission])
    for url in ("/api/payroll/me", "/api/payroll/batches", "/api/payroll/batches/1/lines"):
        assert client.get(url, headers=headers).status_code == 403


@pytest.mark.parametrize("query", ("employee_id=0", "employee_id=-1", "employee_id=invalid"))
def test_invalid_employee_filter_fails_instead_of_widening_scope(client, monkeypatch, query):
    headers = _authenticate(monkeypatch, 1, ["wages:view_all"])
    assert client.get("/api/wages?" + query, headers=headers).status_code == 400
    assert client.get("/api/payroll/batches/1/lines?" + query, headers=headers).status_code == 400
