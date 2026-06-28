from datetime import datetime
import uuid

from modules.db import get_db


def _seed_route_bundle(client):
    suffix = uuid.uuid4().hex[:6].upper()
    process_names = [
        f"Fixture Cut {suffix}",
        f"Fixture Weld {suffix}",
    ]

    with client.application.app_context():
        db = get_db()
        process_ids = []
        for seq_order, name in enumerate(process_names, start=1):
            cursor = db.execute(
                "INSERT INTO processes (name, description, category, seq_order, status, updated_at) "
                "VALUES (?, ?, ?, ?, 'active', datetime('now','localtime'))",
                (name, "cross module fixture", "fixture", seq_order),
            )
            process_ids.append(cursor.lastrowid)

        cursor = db.execute(
            "INSERT INTO process_routes (name, description, status, category, updated_at) "
            "VALUES (?, ?, 'active', ?, datetime('now','localtime'))",
            (f"Fixture Route {suffix}", "cross module fixture", "fixture"),
        )
        route_id = cursor.lastrowid

        for seq_order, (process_id, unit_price) in enumerate(zip(process_ids, (10.0, 12.5)), start=1):
            db.execute(
                "INSERT INTO process_route_items (route_id, process_id, seq_order, required_audit) "
                "VALUES (?, ?, ?, 0)",
                (route_id, process_id, seq_order),
            )
            db.execute(
                "INSERT INTO route_prices (route_id, process_id, unit_price, effective_date, status, remark) "
                "VALUES (?, ?, ?, ?, 'active', ?)",
                (route_id, process_id, unit_price, datetime.now().strftime("%Y-%m-%d"), "fixture"),
            )

        db.commit()
        return route_id, process_ids


def _create_order(client, auth_headers, route_id):
    order_no = f"XT-{uuid.uuid4().hex[:8].upper()}"
    response = client.post(
        "/api/orders",
        headers=auth_headers,
        json={
            "order_no": order_no,
            "customer": "Cross Module Customer",
            "product_name": "Cross Module Product",
            "product_code": f"XMOD-{uuid.uuid4().hex[:6].upper()}",
            "quantity": 10,
            "route_id": route_id,
        },
    )
    assert response.status_code == 200, response.get_json()
    return response.get_json()["id"], order_no


class TestCrossModuleIntegration:
    def test_order_report_and_wage_flow(self, client, auth_headers, worker_auth_headers):
        route_id, process_ids = _seed_route_bundle(client)
        order_id, _order_no = _create_order(client, auth_headers, route_id)

        first_report = client.post(
            "/api/mobile/report",
            headers=worker_auth_headers,
            json={
                "order_id": order_id,
                "process_id": process_ids[0],
                "quantity": 5,
                "report_type": "normal",
            },
        )
        assert first_report.status_code in (200, 201), first_report.get_json()

        second_report = client.post(
            "/api/mobile/report",
            headers=worker_auth_headers,
            json={
                "order_id": order_id,
                "process_id": process_ids[1],
                "quantity": 5,
                "report_type": "normal",
            },
        )
        assert second_report.status_code in (200, 201), second_report.get_json()

        records = client.get(f"/api/orders/{order_id}/work-records", headers=auth_headers)
        assert records.status_code == 200
        with client.application.app_context():
            db = get_db()
            work_record_count = db.execute(
                "SELECT COUNT(*) FROM work_records WHERE order_id = ? AND type = 'normal'",
                (order_id,),
            ).fetchone()[0]
        assert work_record_count >= 2

        monthly_summary = client.get("/api/wages/monthly-summary", headers=auth_headers)
        assert monthly_summary.status_code == 200

        product_process_stats = client.get("/api/stats/product-process", headers=auth_headers)
        assert product_process_stats.status_code == 200

    def test_permissions_quality_and_trace_flow(self, client, auth_headers, worker_auth_headers):
        route_id, process_ids = _seed_route_bundle(client)
        order_id, order_no = _create_order(client, auth_headers, route_id)

        admin_report = client.post(
            "/api/mobile/report",
            headers=auth_headers,
            json={
                "order_id": order_id,
                "process_id": process_ids[0],
                "quantity": 1,
                "report_type": "normal",
            },
        )
        assert admin_report.status_code == 403

        skipped_process = client.post(
            "/api/mobile/report",
            headers=worker_auth_headers,
            json={
                "order_id": order_id,
                "process_id": process_ids[1],
                "quantity": 1,
                "report_type": "normal",
            },
        )
        assert skipped_process.status_code in (400, 403), skipped_process.get_json()

        first_report = client.post(
            "/api/mobile/report",
            headers=worker_auth_headers,
            json={
                "order_id": order_id,
                "process_id": process_ids[0],
                "quantity": 1,
                "report_type": "normal",
                "serial_no": f"SN-{uuid.uuid4().hex[:8].upper()}",
            },
        )
        assert first_report.status_code in (200, 201), first_report.get_json()

        duplicate_report = client.post(
            "/api/mobile/report",
            headers=worker_auth_headers,
            json={
                "order_id": order_id,
                "process_id": process_ids[0],
                "quantity": 1,
                "report_type": "normal",
            },
        )
        assert duplicate_report.status_code == 409, duplicate_report.get_json()

        quality_response = client.post(
            "/api/quality/inspections",
            headers=auth_headers,
            json={
                "order_id": order_id,
                "process_id": process_ids[0],
                "inspection_type": "first_article",
                "quantity_checked": 1,
                "quantity_passed": 1,
                "notes": "fixture inspection",
            },
        )
        assert quality_response.status_code in (200, 201), quality_response.get_json()

        quality_stats = client.get("/api/quality/inspections/stats", headers=auth_headers)
        assert quality_stats.status_code == 200

        trace_response = client.get(f"/api/trace/{order_no}", headers=auth_headers)
        assert trace_response.status_code in (200, 404)

    def test_wage_snapshot_adjustment_and_trend_flow(self, client, auth_headers, worker_auth_headers):
        route_id, process_ids = _seed_route_bundle(client)
        order_id, _order_no = _create_order(client, auth_headers, route_id)

        report_response = client.post(
            "/api/mobile/report",
            headers=worker_auth_headers,
            json={
                "order_id": order_id,
                "process_id": process_ids[0],
                "quantity": 2,
                "report_type": "normal",
            },
        )
        assert report_response.status_code in (200, 201), report_response.get_json()

        year_month = datetime.now().strftime("%Y-%m")

        snapshot_response = client.post(
            f"/api/wages/snapshot?year_month={year_month}",
            headers=auth_headers,
            json={},
        )
        assert snapshot_response.status_code == 200

        snapshot_status = client.get(
            f"/api/wages/snapshot-status?year_month={year_month}",
            headers=auth_headers,
        )
        assert snapshot_status.status_code == 200

        lock_response = client.post(
            f"/api/wages/lock?year_month={year_month}",
            headers=auth_headers,
            json={"notes": "fixture"},
        )
        assert lock_response.status_code == 200

        with client.application.app_context():
            db = get_db()
            worker_id = db.execute(
                "SELECT id FROM users WHERE username = ?",
                ("testworker",),
            ).fetchone()["id"]

        adjustment_response = client.post(
            "/api/wages/adjustments",
            headers=auth_headers,
            json={
                "user_id": worker_id,
                "year_month": year_month,
                "type": "bonus",
                "amount": 50.0,
                "reason": "fixture adjustment",
            },
        )
        assert adjustment_response.status_code == 200, adjustment_response.get_json()

        trends_response = client.get("/api/wages/trends", headers=auth_headers)
        assert trends_response.status_code == 200

        position_response = client.get(
            f"/api/wages/position-summary?year_month={year_month}",
            headers=auth_headers,
        )
        assert position_response.status_code == 200

    def test_inventory_endpoint_contract(self, client, auth_headers):
        inventory_response = client.get("/api/inventory", headers=auth_headers)

        assert inventory_response.status_code == 200, inventory_response.get_json()
        assert isinstance(inventory_response.get_json(), dict)

    def test_shipments_endpoint_contract(self, client, auth_headers):
        shipments_response = client.get("/api/shipments", headers=auth_headers)

        assert shipments_response.status_code == 200, shipments_response.get_json()
        assert isinstance(shipments_response.get_json(), dict)
