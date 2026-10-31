import pytest

from factories import WORKER_HASH, ensure_user
from modules.db import get_db
from modules.services.payroll_service import PayrollWorkflowService
from modules.services.price_version_service import PriceVersionService
from modules.services.wage_service import WageService
from test_payroll_ledger import _actors, _exact_binding, _seed_price_and_work


def _seed_estimate_source(db, *, price="1.005", work_type="normal", rate=None):
    worker_id, route_id, process_id, _ = _seed_price_and_work(
        db, with_price=False, work_type=work_type
    )
    binding = _exact_binding(db, route_id, process_id)
    version = PriceVersionService.create({
        "route_id": route_id,
        "route_version_id": binding["route_version_id"],
        "process_id": process_id,
        "process_version_id": binding["process_version_id"],
        "expected_route_content_digest": binding["route_content_digest"],
        "expected_process_content_digest": binding["process_content_digest"],
        "normal_unit_price": price,
        "valid_from": "2025-01-01",
        "rework_rate_percent": rate,
        "idempotency_key": f"estimate-price-{route_id}",
    }, {"id": 1, "name": "工价制单员"})
    PriceVersionService.approve(
        version["id"], {"id": 2, "name": "工价审批员"}, version["row_version"]
    )
    return worker_id


def _replace_work(db, worker_id, entries):
    source = dict(db.execute(
        "SELECT * FROM work_records WHERE user_id=? ORDER BY id LIMIT 1",
        (worker_id,),
    ).fetchone())
    db.execute("DELETE FROM work_records WHERE user_id=?", (worker_id,))
    for entry in entries:
        row = {**source, **entry}
        db.execute(
            "INSERT INTO work_records "
            "(order_id,process_id,process_version_id,process_name_snapshot,user_id,type,"
            "quantity,status,route_id,route_version_id,route_name_snapshot,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            tuple(row[key] for key in (
                "order_id", "process_id", "process_version_id", "process_name_snapshot",
                "user_id", "type", "quantity", "status", "route_id", "route_version_id",
                "route_name_snapshot", "created_at",
            )),
        )
    db.commit()


def test_estimate_rework_uses_formal_multiplier_and_rounding(client):
    with client.application.app_context():
        db = get_db()
        worker_id = _seed_estimate_source(db, price="1.25", work_type="rework", rate=50)
        preparer, _ = _actors(db)
        batch = PayrollWorkflowService.create_batch("2026-07", preparer, "estimate-rework")
        result = WageService.calculate_wages(employee_id=worker_id, include_rework=True)
        assert batch["payable_wage_cents"] == 188
        assert result["wages"][0]["total_wage"] == 1.88
        assert result["wages"][0]["details"][0]["wage"] == 1.88
        assert result["wages"][0]["details"][0]["unit_price"] == 1.25


def test_missing_rework_multiplier_does_not_use_normal_wage(client):
    with client.application.app_context():
        db = get_db()
        worker_id = _seed_estimate_source(db, price="1.25", work_type="rework")
        result = WageService.calculate_wages(employee_id=worker_id, include_rework=True)
        detail = result["wages"][0]["details"][0]
        assert result["wages"][0]["total_wage"] == 0
        assert detail["wage"] == 0
        assert "返工倍率" in detail["price_match_reason"]


def test_all_live_aggregates_sum_individually_rounded_cents(client, monkeypatch):
    with client.application.app_context():
        db = get_db()
        worker_id = _seed_estimate_source(db)
        _replace_work(db, worker_id, [
            {"quantity": 1, "created_at": "2026-07-02 08:00:00"},
            {"quantity": 1, "created_at": "2026-07-03 08:00:00"},
        ])
        monkeypatch.setattr(
            "modules.repositories.wage_repository.current_reporting_day",
            lambda: "2026-07-15",
        )
        preparer, _ = _actors(db)
        batch = PayrollWorkflowService.create_batch("2026-07", preparer, "estimate-rounding")
        assert batch["payable_wage_cents"] == 202
        estimate = WageService.calculate_wages(employee_id=worker_id)["wages"][0]
        assert estimate["total_wage"] == 2.02
        assert [detail["wage"] for detail in estimate["details"]] == [1.01, 1.01]
        monthly = WageService.monthly_summary("2026-07")
        assert monthly["summary"][0]["total_wage"] == 2.02
        assert monthly["grand_total_wage"] == 2.02
        for summary in (
            WageService.process_wage_summary("2026-07"),
            WageService.position_summary("2026-07"),
        ):
            assert summary["summary"][0]["total_wage"] == 2.02
            assert summary["grand_total_wage"] == 2.02
        trends = WageService.wage_trends(1)
        assert trends == [{
            "year_month": "2026-07", "total_wage": 2.02,
            "total_quantity": 2, "employee_count": 1,
        }]


@pytest.mark.parametrize("month,start_previous,start,end_previous,end", [
    ("2026-07", "2026-07-01 06:59:59", "2026-07-01 07:00:00",
     "2026-08-01 06:59:59", "2026-08-01 07:00:00"),
    ("2025-12", "2025-12-01 06:59:59", "2025-12-01 07:00:00",
     "2026-01-01 06:59:59", "2026-01-01 07:00:00"),
])
def test_all_monthly_analytics_use_reporting_month_bounds(
    client, monkeypatch, month, start_previous, start, end_previous, end
):
    with client.application.app_context():
        db = get_db()
        worker_id = _seed_estimate_source(db, price="1")
        _replace_work(db, worker_id, [
            {"quantity": 1, "created_at": start_previous},
            {"quantity": 2, "created_at": start},
            {"quantity": 4, "created_at": end_previous},
            {"quantity": 8, "created_at": end},
        ])
        monkeypatch.setattr(
            "modules.repositories.wage_repository.current_reporting_day",
            lambda: end[:7] + "-15",
        )
        monthly = WageService.monthly_summary(month, limit=1)
        assert monthly["total"] == 1
        assert monthly["summary"][0]["total_quantity"] == 6
        assert monthly["summary"][0]["total_wage"] == 6
        assert monthly["grand_total_quantity"] == 6
        assert monthly["grand_total_wage"] == 6
        empty_page = WageService.monthly_summary(month, page=2, limit=1)
        assert empty_page["summary"] == []
        assert empty_page["total"] == 1
        assert empty_page["grand_total_quantity"] == 6
        for summary in (
            WageService.process_wage_summary(month),
            WageService.position_summary(month),
        ):
            assert summary["summary"][0]["total_quantity"] == 6
            assert summary["grand_total_wage"] == 6
        trends = {row["year_month"]: row for row in WageService.wage_trends(3)}
        assert trends[month]["total_quantity"] == 6
        assert trends[month]["total_wage"] == 6
        assert trends[end[:7]]["total_quantity"] == 8


def test_hide_zero_counts_matching_workers_before_paging(client):
    with client.application.app_context():
        db = get_db()
        worker_id = _seed_estimate_source(db, price="0")
        worker_ids = [worker_id]
        for index in range(1, 6):
            worker_ids.append(ensure_user(
                db, f"estimate-worker-{index}", WORKER_HASH,
                f"估算员工{index}", "worker", f"EST-{index}",
            ))
        _replace_work(db, worker_id, [
            {"user_id": worker_ids[1], "quantity": 3, "created_at": "2026-07-02 08:00:00"},
            {"user_id": worker_ids[3], "quantity": 2, "created_at": "2026-07-03 08:00:00"},
            {"user_id": worker_ids[5], "quantity": 1, "created_at": "2026-07-04 08:00:00"},
            {"user_id": worker_ids[0], "quantity": 1, "status": "pending"},
            {"user_id": worker_ids[2], "quantity": 1, "type": "rework"},
            {"user_id": worker_ids[4], "quantity": 1, "created_at": "2026-08-02 08:00:00"},
        ])
        query = {"date_from": "2026-07-01", "date_to": "2026-07-31", "hide_zero": True}
        first = WageService.calculate_wages(page=1, limit=2, **query)
        second = WageService.calculate_wages(page=2, limit=2, **query)
        third = WageService.calculate_wages(page=3, limit=2, **query)
        assert first["total"] == second["total"] == third["total"] == 3
        assert [row["employee_id"] for row in first["wages"]] == worker_ids[1:4:2]
        assert [row["employee_id"] for row in second["wages"]] == [worker_ids[5]]
        assert third["wages"] == []
        # Hiding zero is a quantity filter: legitimate zero-priced work stays visible.
        assert all(row["total_wage"] == 0 for row in first["wages"] + second["wages"])
        assert WageService.calculate_wages(include_pending=True, **query)["total"] == 4
        assert WageService.calculate_wages(include_rework=True, **query)["total"] == 4
        own = WageService.calculate_wages(employee_id=worker_ids[5], **query)
        assert own["total"] == 1
        assert own["wages"][0]["employee_id"] == worker_ids[5]


@pytest.mark.parametrize("quantity,price", [(3, "90000000000000"), (-1, "1.25")])
def test_invalid_source_amounts_do_not_break_live_analytics(client, monkeypatch, quantity, price):
    with client.application.app_context():
        db = get_db()
        worker_id = _seed_estimate_source(db, price=price)
        _replace_work(db, worker_id, [{"quantity": quantity}])
        monkeypatch.setattr(
            "modules.repositories.wage_repository.current_reporting_day",
            lambda: "2026-07-15",
        )
        result = WageService.calculate_wages(employee_id=worker_id)
        assert result["wages"][0]["total_wage"] == 0
        assert "未计入估算" in result["wages"][0]["details"][0]["price_match_reason"]
        assert WageService.monthly_summary("2026-07")["grand_total_wage"] == 0
        assert WageService.process_wage_summary("2026-07")["grand_total_wage"] == 0
        assert WageService.position_summary("2026-07")["grand_total_wage"] == 0
        assert WageService.wage_trends(1)[0]["total_wage"] == 0


@pytest.mark.parametrize("endpoint", (
    "/api/wages/monthly-summary",
    "/api/wages/process-summary",
    "/api/wages/position-summary",
))
@pytest.mark.parametrize("year_month", ("2026-13", "2026-7", "0000-01", "9999-12"))
def test_invalid_monthly_analytics_input_returns_validation_error(
    client, auth_headers, endpoint, year_month
):
    response = client.get(
        endpoint, query_string={"year_month": year_month}, headers=auth_headers
    )
    assert response.status_code == 400
    assert response.get_json()["code"] == "validation_error"
