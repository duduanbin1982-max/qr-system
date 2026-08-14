from datetime import datetime
import uuid

from modules.db import get_db
from factories import ensure_process_version, ensure_route_version


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
            process_id = cursor.lastrowid
            ensure_process_version(db, process_id)
            process_ids.append(process_id)

        cursor = db.execute(
            "INSERT INTO process_routes (name, description, status, category, updated_at) "
            "VALUES (?, ?, 'active', ?, datetime('now','localtime'))",
            (f"Fixture Route {suffix}", "cross module fixture", "fixture"),
        )
        route_id = cursor.lastrowid

        for seq_order, process_id in enumerate(process_ids, start=1):
            db.execute(
                "INSERT INTO process_route_items (route_id, process_id, seq_order, required_audit) "
                "VALUES (?, ?, ?, 0)",
                (route_id, process_id, seq_order),
            )

        route_version_id = ensure_route_version(db, route_id)
        for process_id, unit_price in zip(process_ids, (10.0, 12.5)):
            process_version_id = db.execute(
                "SELECT process_version_id FROM process_route_version_items "
                "WHERE route_version_id=? AND process_id=?",
                (route_version_id, process_id),
            ).fetchone()["process_version_id"]
            db.execute(
                """
                INSERT INTO route_price_versions (
                    route_id,route_version_id,process_id,process_version_id,
                    normal_unit_price_micros,rework_rate_basis_points,
                    rework_rate_configured,valid_from,status,created_by_name,approved_by_name,
                    approved_at,remark
                ) VALUES (?,?,?,?,?,0,0,?,'approved','fixture','fixture',
                          datetime('now','localtime'),'fixture')
                """,
                (
                    route_id,
                    route_version_id,
                    process_id,
                    process_version_id,
                    int(unit_price * 10000),
                    datetime.now().strftime("%Y-%m-%d 00:00:00"),
                ),
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


def _seed_worker_report(client, auth_headers, worker_auth_headers, quantity=2):
    route_id, process_ids = _seed_route_bundle(client)
    order_id, _order_no = _create_order(client, auth_headers, route_id)
    response = client.post(
        "/api/mobile/report",
        headers=worker_auth_headers,
        json={
            "order_id": order_id,
            "process_id": process_ids[0],
            "quantity": quantity,
            "report_type": "normal",
        },
    )
    assert response.status_code in (200, 201), response.get_json()
    return datetime.now().strftime("%Y-%m")


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

    def test_admin_cannot_report_as_worker(self, client, auth_headers, worker_auth_headers):
        route_id, process_ids = _seed_route_bundle(client)
        order_id, _order_no = _create_order(client, auth_headers, route_id)

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

    def test_worker_cannot_skip_process(self, client, auth_headers, worker_auth_headers):
        route_id, process_ids = _seed_route_bundle(client)
        order_id, _order_no = _create_order(client, auth_headers, route_id)

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

    def test_duplicate_worker_report_returns_conflict(self, client, auth_headers, worker_auth_headers):
        route_id, process_ids = _seed_route_bundle(client)
        order_id, _order_no = _create_order(client, auth_headers, route_id)

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

    def test_quality_and_trace_endpoints_follow_worker_report(self, client, auth_headers, worker_auth_headers):
        route_id, process_ids = _seed_route_bundle(client)
        order_id, order_no = _create_order(client, auth_headers, route_id)
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

    def test_wage_snapshot_and_lock_flow(self, client, auth_headers, worker_auth_headers):
        year_month = _seed_worker_report(client, auth_headers, worker_auth_headers)
        snapshot_response = client.post(
            f"/api/wages/snapshot?year_month={year_month}",
            headers=auth_headers,
            json={},
        )
        assert snapshot_response.status_code == 410
        assert snapshot_response.get_json()["code"] == "LEGACY_WAGE_WRITE_DISABLED"

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
        assert lock_response.status_code == 410

    def test_wage_adjustment_and_trends_flow(self, client, auth_headers, worker_auth_headers):
        year_month = _seed_worker_report(client, auth_headers, worker_auth_headers)

        with client.application.app_context():
            db = get_db()
            worker_id = db.execute(
                "SELECT id FROM users WHERE username = ?",
                ("testworker",),
            ).fetchone()["id"]

        legacy_response = client.post(
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
        assert legacy_response.status_code == 410

        adjustment_response = client.post(
            "/api/payroll/adjustments",
            headers=auth_headers,
            json={
                "employee_id": worker_id,
                "payroll_month": year_month,
                "adjustment_type": "bonus",
                "amount": "50.00",
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

    def test_shipment_number_uses_validated_system_prefix(self, client, auth_headers):
        save_response = client.post(
            "/api/settings",
            headers=auth_headers,
            json={"shipment_no_prefix": "out-"},
        )
        assert save_response.status_code == 200, save_response.get_json()

        draft_response = client.get("/api/shipments/draft", headers=auth_headers)
        assert draft_response.status_code == 200, draft_response.get_json()
        assert draft_response.get_json()["shipment_no"].startswith("OUT-")

        invalid_response = client.post(
            "/api/settings",
            headers=auth_headers,
            json={"shipment_no_prefix": "invalid prefix!"},
        )
        assert invalid_response.status_code == 400


    def test_shipments_endpoint_includes_product_codes(self, client, auth_headers):
        suffix = uuid.uuid4().hex[:6].upper()
        shipment_no = f"TEST-SHIP-{suffix}"
        first_code = f"XMOD-SHIP-{suffix}"
        second_code = f"XMOD-SHIP-B-{suffix}"
        with client.application.app_context():
            db = get_db()
            first_inventory_id = db.execute(
                "INSERT INTO inventory (product_model, product_name, quantity, unit) VALUES (?, 'Fixture Product A', 10, '件')",
                (first_code,),
            ).lastrowid
            second_inventory_id = db.execute(
                "INSERT INTO inventory (product_model, product_name, quantity, unit) VALUES (?, 'Fixture Product B', 10, '件')",
                (second_code,),
            ).lastrowid
            shipment_id = db.execute(
                "INSERT INTO shipments (shipment_no, customer, contact_person, status, total_quantity, created_by) "
                "VALUES (?, 'Shipment Code Customer', 'Fixture Contact', 'pending', 3, 'pytest')",
                (shipment_no,),
            ).lastrowid
            db.execute(
                "INSERT INTO shipment_items (shipment_id, inventory_id, product_model, product_name, quantity, unit, product_code) "
                "VALUES (?, ?, 'Fixture Model A', 'Fixture Product A', 1, '件', ?)",
                (shipment_id, first_inventory_id, first_code),
            )
            db.execute(
                "INSERT INTO shipment_items (shipment_id, inventory_id, product_model, product_name, quantity, unit, product_code) "
                "VALUES (?, ?, 'Fixture Model B', 'Fixture Product B', 2, '件', ?)",
                (shipment_id, second_inventory_id, second_code),
            )
            db.commit()

        response = client.get(f"/api/shipments?keyword={shipment_no}", headers=auth_headers)

        assert response.status_code == 200, response.get_json()
        row = next(item for item in response.get_json()["shipments"] if item["shipment_no"] == shipment_no)
        assert first_code in row["product_codes"]
        assert second_code in row["product_codes"]
