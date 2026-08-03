import uuid

from modules.db import get_db
from modules.domain.reporting_day import reporting_range_bounds
from modules.repositories.order_repository import OrderRepository
from modules.repositories.reports_repository import ReportsRepository


def _seed_product_order(db, code, created_at="2026-07-01 09:00:00", customer_id=None):
    product_name = f"Reporting Product {code}"
    product_id = db.execute(
        "INSERT INTO products (product_name, product_code, model, spec, category) "
        "VALUES (?, ?, 'REPORT', 'Standard', 'fixture')",
        (product_name, code),
    ).lastrowid
    order_id = db.execute(
        "INSERT INTO orders (order_no, customer, customer_id, product_name, product_code, "
        "product_id, quantity, status, qr_mode, created_at) "
        "VALUES (?, 'Reporting Customer', ?, ?, ?, ?, 10, 'producing', '', ?)",
        (f"REPORT-{uuid.uuid4().hex[:10]}", customer_id, product_name, code, product_id, created_at),
    ).lastrowid
    return product_id, order_id


def _process_and_user(db):
    process = db.execute(
        "SELECT id FROM processes WHERE status='active' ORDER BY id LIMIT 1"
    ).fetchone()
    if process:
        process_id = process["id"]
    else:
        process_id = db.execute(
            "INSERT INTO processes (name, category, seq_order, status) "
            "VALUES ('Reporting Process', 'fixture', 1, 'active')"
        ).lastrowid
    user_id = db.execute(
        "SELECT id FROM users WHERE username='testrunner'"
    ).fetchone()["id"]
    return process_id, user_id


def test_product_report_includes_late_output_and_sums_defect_quantities(client, auth_headers):
    code = f"REPORT-PRODUCT-{uuid.uuid4().hex[:8]}"
    with client.application.app_context():
        db = get_db()
        _, order_id = _seed_product_order(db, code, "2026-01-10 09:00:00")
        process_id, user_id = _process_and_user(db)
        db.execute(
            "INSERT INTO product_items (order_id, serial_no, status, completed_at) "
            "VALUES (?, ?, 'completed', '2026-08-02 08:00:00')",
            (order_id, f"SER-{uuid.uuid4().hex[:8]}"),
        )
        db.execute(
            "INSERT INTO scrap_records (order_id, process_id, user_id, quantity, created_at) "
            "VALUES (?, ?, ?, 3, '2026-08-02 09:00:00')",
            (order_id, process_id, user_id),
        )
        db.execute(
            "INSERT INTO work_records (order_id, process_id, user_id, type, quantity, status, created_at) "
            "VALUES (?, ?, ?, 'rework', 4, 'approved', '2026-08-02 10:00:00')",
            (order_id, process_id, user_id),
        )
        db.commit()

    response = client.get(
        f"/api/stats/product?start=2026-08-02&end=2026-08-02&product_code={code}",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.get_json()
    data = response.get_json()
    assert len(data["by_product"]) == 1
    row = data["by_product"][0]
    assert row["order_qty"] == 0
    assert row["output"] == 1
    assert row["scrap"] == 3
    assert row["rework"] == 4
    assert data["summary"]["total_output"] == 1


def test_product_filtered_shipment_uses_matching_item_quantity(client, auth_headers):
    target_code = f"SHIP-TARGET-{uuid.uuid4().hex[:8]}"
    other_code = f"SHIP-OTHER-{uuid.uuid4().hex[:8]}"
    with client.application.app_context():
        db = get_db()
        _, target_order = _seed_product_order(db, target_code)
        _, other_order = _seed_product_order(db, other_code)
        target_inventory = db.execute(
            "INSERT INTO inventory (product_model, product_name, quantity, category) "
            "VALUES (?, 'Target', 10, 'finished')", (target_code,)
        ).lastrowid
        other_inventory = db.execute(
            "INSERT INTO inventory (product_model, product_name, quantity, category) "
            "VALUES (?, 'Other', 10, 'finished')", (other_code,)
        ).lastrowid
        shipment_id = db.execute(
            "INSERT INTO shipments (shipment_no, customer, status, total_quantity, created_at, completed_at) "
            "VALUES (?, 'Mixed Customer', 'completed', 8, '2026-08-02 09:00:00', '2026-08-02 10:00:00')",
            (f"SHIP-{uuid.uuid4().hex[:10]}",),
        ).lastrowid
        db.executemany(
            "INSERT INTO shipment_items (shipment_id, inventory_id, order_id, product_model, product_name, quantity) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (shipment_id, target_inventory, target_order, target_code, "Target", 1),
                (shipment_id, other_inventory, other_order, other_code, "Other", 7),
            ],
        )
        db.commit()

    response = client.get(
        f"/api/stats/shipment?start=2026-08-02&end=2026-08-02&product_code={target_code}",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.get_json()
    data = response.get_json()
    assert data["by_status"][0]["total_qty"] == 1
    assert data["by_customer"][0]["total_qty"] == 1
    assert data["monthly_trend"][0]["total_qty"] == 1


def test_material_summary_matches_filtered_active_consumptions(client, auth_headers):
    target_code = f"MAT-TARGET-{uuid.uuid4().hex[:8]}"
    other_code = f"MAT-OTHER-{uuid.uuid4().hex[:8]}"
    with client.application.app_context():
        db = get_db()
        _, target_order = _seed_product_order(db, target_code)
        _, other_order = _seed_product_order(db, other_code)
        process_id, _ = _process_and_user(db)
        material_id = db.execute(
            "INSERT INTO materials (name, spec, material_type, unit, quantity) "
            "VALUES (?, 'Standard', 'fixture', 'kg', 100)",
            (f"Material {uuid.uuid4().hex[:8]}",),
        ).lastrowid
        db.executemany(
            "INSERT INTO material_consumptions "
            "(order_id, material_id, process_id, quantity, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, '2026-08-02 09:00:00')",
            [
                (target_order, material_id, process_id, 5, "active"),
                (target_order, material_id, process_id, 11, "reversed"),
                (other_order, material_id, process_id, 7, "active"),
            ],
        )
        db.commit()

    response = client.get(
        f"/api/stats/material?start=2026-08-02&end=2026-08-02&product_code={target_code}",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.get_json()
    data = response.get_json()
    assert data["by_material"][0]["total_used"] == 5
    assert data["summary"]["total_consumed"] == 5
    assert data["summary"]["material_count"] == 1


def test_production_trend_aggregates_sources_before_joining(client):
    code = f"TREND-{uuid.uuid4().hex[:8]}"
    with client.application.app_context():
        db = get_db()
        _, order_id = _seed_product_order(db, code)
        process_id, user_id = _process_and_user(db)
        for hour in ("08:00:00", "09:00:00"):
            db.execute(
                "INSERT INTO product_items (order_id, serial_no, status, completed_at) "
                "VALUES (?, ?, 'completed', ?)",
                (order_id, f"SER-{uuid.uuid4().hex[:8]}", f"2026-08-02 {hour}"),
            )
        for quantity in (1, 2, 3):
            db.execute(
                "INSERT INTO work_records (order_id, process_id, user_id, type, quantity, status, created_at) "
                "VALUES (?, ?, ?, 'normal', ?, 'approved', '2026-08-02 10:00:00')",
                (order_id, process_id, user_id, quantity),
            )
        db.commit()
        row = dict(ReportsRepository.fetch_production_trend(
            "2026-08-02", "2026-08-02", db=db
        )[0])

    assert row["output"] == 2
    assert row["report_count"] == 3


def test_quality_subreports_share_date_and_product_filter(client, auth_headers):
    target_code = f"QI-TARGET-{uuid.uuid4().hex[:8]}"
    other_code = f"QI-OTHER-{uuid.uuid4().hex[:8]}"
    with client.application.app_context():
        db = get_db()
        customer_id = db.execute(
            "INSERT INTO customers (name) VALUES (?)",
            (f"Quality Customer {uuid.uuid4().hex[:8]}",),
        ).lastrowid
        _, target_order = _seed_product_order(db, target_code, customer_id=customer_id)
        _, other_order = _seed_product_order(db, other_code, customer_id=customer_id)
        process_id, user_id = _process_and_user(db)
        db.executemany(
            "INSERT INTO quality_inspections "
            "(order_id, process_id, inspector_id, quantity_checked, quantity_passed, "
            "quantity_failed, result, inspected_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (target_order, process_id, user_id, 10, 9, 1, "partial", "2026-08-02 08:00:00"),
                (other_order, process_id, user_id, 20, 0, 20, "fail", "2026-08-02 09:00:00"),
            ],
        )
        db.commit()

    response = client.get(
        f"/api/reports/quality-analysis?start=2026-08-02&end=2026-08-02&product_code={target_code}",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.get_json()
    data = response.get_json()
    assert data["spc_samples"] == [10.0]
    assert data["inspector_data"][0]["inspection_count"] == 1
    assert data["inspector_data"][0]["total_checked"] == 10
    assert data["supplier_data"][0]["inspection_count"] == 1
    assert data["qi_by_process"][0]["total_inspections"] == 1


def test_reporting_routes_reject_unsafe_ranges_and_print_actual_data(client, auth_headers):
    invalid_days = client.get("/api/reports/production-trend?days=367", headers=auth_headers)
    invalid_days_text = client.get("/api/reports/production-trend?days=all", headers=auth_headers)
    invalid_page = client.get("/api/stats/daily?per_page=-1", headers=auth_headers)
    invalid_page_text = client.get("/api/stats/daily?page=first", headers=auth_headers)
    reversed_range = client.get(
        "/api/stats/product?start=2026-08-03&end=2026-08-02", headers=auth_headers
    )
    printable = client.get(
        "/api/stats/export-pdf?tab=daily&start=2026-08-02&end=2026-08-02",
        headers=auth_headers,
    )

    assert invalid_days.status_code == 400
    assert invalid_days_text.status_code == 400
    assert invalid_page.status_code == 400
    assert invalid_page_text.status_code == 400
    assert reversed_range.status_code == 400
    assert printable.status_code == 200
    assert printable.mimetype == "text/html"
    assert b"<table>" in printable.data
    assert b"window.print" in printable.data


def test_reporting_range_uses_seven_am_half_open_boundaries():
    assert reporting_range_bounds("2026-08-02", "2026-08-03") == (
        "2026-08-02 07:00:00",
        "2026-08-04 07:00:00",
    )


def test_order_completion_timestamp_survives_edits_and_clears_on_reopen(client):
    code = f"COMPLETE-{uuid.uuid4().hex[:8]}"
    with client.application.app_context():
        db = get_db()
        _, order_id = _seed_product_order(db, code)
        db.execute(
            "UPDATE orders SET status='completed', completed_at='2026-07-15 12:00:00' "
            "WHERE id=?", (order_id,)
        )
        OrderRepository.update_form_fields(order_id, {"remark": "ordinary edit"}, db=db)
        after_edit = db.execute(
            "SELECT completed_at FROM orders WHERE id=?", (order_id,)
        ).fetchone()["completed_at"]
        OrderRepository.reopen_completed(order_id, "producing", db=db)
        after_reopen = db.execute(
            "SELECT completed_at FROM orders WHERE id=?", (order_id,)
        ).fetchone()["completed_at"]

    assert after_edit == "2026-07-15 12:00:00"
    assert after_reopen is None
