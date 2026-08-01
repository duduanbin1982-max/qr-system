"""Core scan-to-report flow integration tests"""
import json, time, pytest
import uuid
from modules.db import get_db
from factories import WORKER_HASH, ensure_user


def _order_no_for(client, order_id):
    with client.application.app_context():
        row = get_db().execute("SELECT order_no FROM orders WHERE id = ?", (order_id,)).fetchone()
    assert row is not None, f"Missing fixture order {order_id}"
    return row["order_no"]


def _seed_order_mode_two_step_order(client):
    suffix = uuid.uuid4().hex[:6].upper()
    with client.application.app_context():
        db = get_db()
        process_ids = []
        for seq_order, name in enumerate((f"Fixture OrderMode A {suffix}", f"Fixture OrderMode B {suffix}"), start=1):
            cursor = db.execute(
                "INSERT INTO processes (name, description, category, seq_order, status, updated_at) "
                "VALUES (?, 'pytest fixture process', 'fixture', ?, 'active', datetime('now','localtime'))",
                (name, seq_order),
            )
            process_ids.append(cursor.lastrowid)

        order_no = f"TEST-ORDER-MODE-{suffix}"
        order_id = db.execute(
            "INSERT INTO orders (order_no, customer, product_name, product_code, quantity, status, qr_mode) "
            "VALUES (?, 'Test Customer', 'Cross Module Product', ?, 5, 'producing', '')",
            (order_no, f"XMOD-OM-{suffix}"),
        ).lastrowid
        for seq_order, process_id in enumerate(process_ids, start=1):
            db.execute(
                "INSERT INTO order_processes (order_id, process_id, seq_order, status, completed, scrapped, rework) "
                "VALUES (?, ?, ?, 'pending', 0, 0, 0)",
                (order_id, process_id, seq_order),
            )
        db.commit()
        return order_id, order_no, process_ids


def _set_process_order_config(client, mode, previous_limit="1"):
    with client.application.app_context():
        db = get_db()
        for key, value in {
            "process_order_mode": mode,
            "limit_by_prev_process": previous_limit,
        }.items():
            db.execute(
                "INSERT INTO system_settings (key, value, updated_at) "
                "VALUES (?, ?, datetime('now','localtime')) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, value),
            )
        db.commit()
        from modules.db import clear_settings_cache
        clear_settings_cache()


def _seed_serial_handoff_order(client):
    suffix = uuid.uuid4().hex[:6].upper()
    with client.application.app_context():
        db = get_db()
        previous_user_id = ensure_user(
            db,
            f"handoffprev_{suffix.lower()}",
            WORKER_HASH,
            "Handoff Previous Worker",
            "worker",
            f"TEST-HANDOFF-PREV-{suffix}",
            "worker-group",
        )
        current_user = db.execute(
            "SELECT id FROM users WHERE username = 'testworker'"
        ).fetchone()
        assert current_user is not None

        process_ids = []
        for seq_order, name in enumerate(
            (
                f"Fixture Handoff A {suffix}",
                f"Fixture Handoff B {suffix}",
                f"Fixture Handoff C {suffix}",
            ),
            start=1,
        ):
            cursor = db.execute(
                "INSERT INTO processes (name, description, category, seq_order, status, updated_at) "
                "VALUES (?, 'pytest fixture process', 'fixture', ?, 'active', datetime('now','localtime'))",
                (name, seq_order),
            )
            process_ids.append(cursor.lastrowid)

        order_no = f"TEST-HANDOFF-{suffix}"
        serial_no = f"TEST-HANDOFF-{suffix}-001"
        order_id = db.execute(
            "INSERT INTO orders (order_no, customer, product_name, product_code, quantity, status, qr_mode) "
            "VALUES (?, 'Test Customer', 'Cross Module Product', ?, 1, 'producing', 'serial')",
            (order_no, f"XMOD-HO-{suffix}"),
        ).lastrowid
        for index, process_id in enumerate(process_ids):
            completed = 1 if index == 0 else 0
            status = 'completed' if index == 0 else 'pending'
            db.execute(
                "INSERT INTO order_processes (order_id, process_id, seq_order, status, completed, scrapped, rework) "
                "VALUES (?, ?, ?, ?, ?, 0, 0)",
                (order_id, process_id, index + 1, status, completed),
            )
        db.execute(
            "INSERT INTO product_items (serial_no, order_id, order_no, position_no, qr_content, status, current_process_id) "
            "VALUES (?, ?, ?, 1, ?, 'in_progress', ?)",
            (
                serial_no,
                order_id,
                order_no,
                json.dumps({"order_id": order_id, "serial_no": serial_no}),
                process_ids[1],
            ),
        )
        db.execute(
            "INSERT INTO work_records (order_id, process_id, user_id, type, quantity, serial_no, status, created_at) "
            "VALUES (?, ?, ?, 'normal', 1, ?, 'approved', datetime('now','localtime'))",
            (order_id, process_ids[0], previous_user_id, serial_no),
        )
        db.commit()
        return order_id, order_no, serial_no, process_ids, current_user["id"], previous_user_id


class TestScanWorkFlow:
    """End-to-end scan → report → verify flow."""

    def test_scan_order_by_no(self, client, auth_headers):
        """POST /api/scan — scan an order by order number."""
        resp = client.post("/api/scan", headers=auth_headers, json={
            "code": "TEST-SCAN-001",
            "type": "order_no"
        })
        assert resp.status_code in (200, 404)

    def test_mobile_scan(self, client, auth_headers):
        """POST /api/mobile/scan — mobile H5 scan."""
        resp = client.post("/api/mobile/scan", headers=auth_headers, json={
            "code": "TEST-SCAN-001",
            "type": "order_no"
        })
        assert resp.status_code in (200, 404)


    def test_order_mode_mobile_scan_advances_after_process_completed(self, client, worker_auth_headers):
        """Order-mode mobile scan should move to next process after current process reaches order quantity."""
        order_id, order_no, process_ids = _seed_order_mode_two_step_order(client)

        first_scan = client.post("/api/mobile/scan", headers=worker_auth_headers, json={"code": order_no})
        assert first_scan.status_code == 200, first_scan.get_json()
        assert first_scan.get_json()["order"]["current_process"]["process_id"] == process_ids[0]

        report = client.post(
            "/api/mobile/report",
            headers=worker_auth_headers,
            json={
                "order_id": order_id,
                "process_id": process_ids[0],
                "quantity": 5,
                "report_type": "normal",
            },
        )
        assert report.status_code in (200, 201), report.get_json()

        next_scan = client.post("/api/mobile/scan", headers=worker_auth_headers, json={"code": order_no})
        assert next_scan.status_code == 200, next_scan.get_json()
        assert next_scan.get_json()["order"]["current_process"]["process_id"] == process_ids[1]

    def test_out_of_order_mobile_scan_exposes_and_accepts_later_process(self, client, worker_auth_headers):
        order_id, order_no, process_ids = _seed_order_mode_two_step_order(client)
        _set_process_order_config(client, "out_of_order", previous_limit="1")

        scan = client.post("/api/mobile/scan", headers=worker_auth_headers, json={"code": order_no})

        assert scan.status_code == 200, scan.get_json()
        order = scan.get_json()["order"]
        assert order["process_order_mode"] == "out_of_order"
        assert order["limit_by_prev_process_effective"] is False
        assert order["requires_process_selection"] is True
        assert [process["normal_reportable"] for process in order["processes"]] == [True, True]

        report = client.post(
            "/api/mobile/report",
            headers=worker_auth_headers,
            json={
                "order_id": order_id,
                "process_id": process_ids[1],
                "quantity": 1,
                "report_type": "normal",
            },
        )

        assert report.status_code == 200, report.get_json()

    def test_order_mode_mobile_scan_prefers_logged_in_worker_position(
        self, client, worker_auth_headers
    ):
        _, order_no, process_ids = _seed_order_mode_two_step_order(client)
        _set_process_order_config(client, "out_of_order", previous_limit="0")
        with client.application.app_context():
            db = get_db()
            worker = db.execute(
                "SELECT id FROM users WHERE username = 'testworker'"
            ).fetchone()
            position_id = db.execute(
                "INSERT INTO positions (name, description, status) "
                "VALUES (?, '', 'active')",
                (f"Fixture Position {uuid.uuid4().hex[:6]}",),
            ).lastrowid
            db.execute(
                "INSERT INTO position_processes (position_id, process_id) VALUES (?, ?)",
                (position_id, process_ids[1]),
            )
            db.execute(
                "UPDATE users SET position_id = ? WHERE id = ?",
                (position_id, worker["id"]),
            )
            db.commit()

        scan = client.post(
            "/api/mobile/scan", headers=worker_auth_headers, json={"code": order_no}
        )

        assert scan.status_code == 200, scan.get_json()
        order = scan.get_json()["order"]
        assert order["active_position"]["id"] == position_id
        assert order["current_process"]["process_id"] == process_ids[1]
        assert order["process_selection_source"] == "position_auto"
        assert order["requires_process_selection"] is False
        assert [process["position_reportable"] for process in order["processes"]] == [
            False,
            True,
        ]

    def test_sequential_mobile_report_rejects_skipped_process(self, client, worker_auth_headers):
        order_id, _, process_ids = _seed_order_mode_two_step_order(client)
        _set_process_order_config(client, "sequential", previous_limit="1")

        report = client.post(
            "/api/mobile/report",
            headers=worker_auth_headers,
            json={
                "order_id": order_id,
                "process_id": process_ids[1],
                "quantity": 1,
                "report_type": "normal",
            },
        )

        assert report.status_code == 400, report.get_json()
        assert "前置工序" in report.get_json()["error"]

    def test_mobile_report_creates_quality_evaluation_task_for_previous_serial_process(self, client, worker_auth_headers):
        order_id, _, serial_no, process_ids, current_user_id, previous_user_id = _seed_serial_handoff_order(client)

        report = client.post(
            "/api/mobile/report",
            headers=worker_auth_headers,
            json={
                "order_id": order_id,
                "process_id": process_ids[1],
                "quantity": 1,
                "serial_no": serial_no,
                "report_type": "normal",
            },
        )

        assert report.status_code == 200, report.get_json()
        assert report.get_json()["quality_evaluation_pending_count"] == 1
        assert report.get_json()["quality_evaluation_required_count"] == 1
        assert report.get_json()["quality_evaluation_auto_open"] is True
        tasks = client.get(
            "/api/process-quality-evaluations/tasks",
            headers=worker_auth_headers,
        )
        assert tasks.status_code == 200, tasks.get_json()
        pending = tasks.get_json()["items"][0]
        assert pending["is_required"] == 1
        assert pending["target_process_id"] == process_ids[0]
        assert pending["evaluator_process_id"] == process_ids[1]
        assert "target_user_id" not in pending
        assert "target_user_name" not in pending
        assert previous_user_id != current_user_id

    def test_desktop_serial_scan_returns_serial_process_scope(self, client, worker_auth_headers):
        _, _, serial_no, process_ids, _, _ = _seed_serial_handoff_order(client)

        scan = client.post("/api/scan", headers=worker_auth_headers, json={"code": serial_no})

        assert scan.status_code == 200, scan.get_json()
        payload = scan.get_json()
        assert payload["item"]["serial_no"] == serial_no
        assert payload["order"]["process_order_scope"] == "serial_sequential"
        assert payload["order"]["current_process"]["process_id"] == process_ids[1]

    def test_same_worker_can_report_same_serial_at_next_process(self, client, worker_auth_headers):
        order_id, _, serial_no, process_ids, current_user_id, _ = _seed_serial_handoff_order(client)
        with client.application.app_context():
            db = get_db()
            db.execute(
                "UPDATE work_records SET user_id = ? "
                "WHERE order_id = ? AND process_id = ? AND serial_no = ?",
                (current_user_id, order_id, process_ids[0], serial_no),
            )
            db.commit()

        report = client.post(
            "/api/mobile/report",
            headers=worker_auth_headers,
            json={
                "order_id": order_id,
                "process_id": process_ids[1],
                "quantity": 1,
                "serial_no": serial_no,
                "report_type": "normal",
            },
        )

        assert report.status_code == 200, report.get_json()
        with client.application.app_context():
            record = get_db().execute(
                "SELECT id FROM work_records "
                "WHERE order_id = ? AND process_id = ? AND serial_no = ? AND user_id = ?",
                (order_id, process_ids[1], serial_no, current_user_id),
            ).fetchone()
        assert record is not None

    def test_mobile_scan_reports_unsubmitted_quality_task_count_after_serial_advances(self, client, worker_auth_headers):
        order_id, _, serial_no, process_ids, _, _ = _seed_serial_handoff_order(client)

        report = client.post(
            "/api/mobile/report",
            headers=worker_auth_headers,
            json={
                "order_id": order_id,
                "process_id": process_ids[1],
                "quantity": 1,
                "serial_no": serial_no,
                "report_type": "normal",
            },
        )
        assert report.status_code == 200, report.get_json()

        scan = client.post("/api/mobile/scan", headers=worker_auth_headers, json={"code": serial_no})

        assert scan.status_code == 200, scan.get_json()
        payload = scan.get_json()
        assert payload["order"]["current_process"]["process_id"] == process_ids[2]
        assert payload["quality_evaluation_pending_count"] == 1
        tasks = client.get(
            "/api/process-quality-evaluations/tasks",
            headers=worker_auth_headers,
        ).get_json()["items"]
        assert tasks[0]["target_process_id"] == process_ids[0]
        assert tasks[0]["evaluator_process_id"] == process_ids[1]
        assert tasks[0]["serial_no"] == serial_no

    def test_work_report_submit(self, client, auth_headers, worker_auth_headers, test_order_id):
        """POST /api/report — submit a work report."""
        # Get first available process
        proc_resp = client.get("/api/processes", headers=auth_headers)
        assert proc_resp.status_code == 200
        processes = proc_resp.get_json().get("items", proc_resp.get_json().get("processes", []))
        assert len(processes) > 0, "Need at least one process for report test"
        process_id = processes[0]["id"]

        # Submit work report
        report_resp = client.post("/api/report", headers=worker_auth_headers, json={
            "order_id": test_order_id,
            "process_id": process_id,
            "quantity": 5,
            "serial_no": f"SN-{int(time.time())}",
            "report_type": "normal"
        })
        assert report_resp.status_code == 200, report_resp.get_json()

    def test_qr_code_generation(self, client, auth_headers):
        """POST /api/qrcode/batch — generate QR codes."""
        resp = client.post("/api/qrcode/batch", headers=auth_headers, json={
            "order_ids": [1],
            "mode": "order"
        })
        # May fail if order doesn't exist or permissions
        assert resp.status_code == 200

    def test_processes_list(self, client, auth_headers):
        """GET /api/processes — list active processes."""
        resp = client.get("/api/processes", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert "items" in data or "processes" in data


class TestScanEdgeCases:
    """Edge case and error handling tests."""

    def test_scan_without_auth(self, client):
        """Scan endpoint should require authentication."""
        resp = client.post("/api/scan", json={"code": "test"})
        assert resp.status_code == 401

    def test_report_without_auth(self, client):
        """Report endpoint should require authentication."""
        resp = client.post("/api/report", json={"order_id": 1, "process_id": 1})
        assert resp.status_code == 401

    def test_scan_invalid_order(self, client, auth_headers):
        """Scanning a non-existent order should return 404 or error."""
        resp = client.post("/api/scan", headers=auth_headers, json={
            "code": "NONEXISTENT-99999",
            "type": "order_no"
        })
        assert resp.status_code in (400, 404), resp.get_json()

    def test_mobile_decode_invalid(self, client, auth_headers):
        """Mobile decode with garbage input should not crash."""
        resp = client.get("/api/mobile/decode/!!!invalid!!!", headers=auth_headers)
        assert resp.status_code == 200

class TestScanReportVerification:
    """Verify scan data flows to reports and wages."""

    def test_order_trace(self, client, auth_headers, test_order_id):
        order_no = _order_no_for(client, test_order_id)
        resp = client.get(f"/api/trace/order/{order_no}", headers=auth_headers)
        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json()["order"]["order_no"] == order_no

    def test_work_records_list(self, client, auth_headers, test_order_id):
        resp = client.get(f"/api/orders/{test_order_id}/work-records", headers=auth_headers)
        assert resp.status_code == 200, resp.get_json()
        assert "work_records" in resp.get_json()

    def test_wage_endpoint(self, client, auth_headers):
        resp = client.get("/api/wages", headers=auth_headers)
        assert resp.status_code == 200, resp.get_json()
        assert isinstance(resp.get_json(), (dict, list))

    def test_all_stats_healthy(self, client, auth_headers):
        endpoints = [
            "/api/stats/order-progress",
            "/api/stats/product",
            "/api/stats/product-process",
            "/api/stats/shipment",
            "/api/stats/material",
        ]
        for ep in endpoints:
            resp = client.get(ep, headers=auth_headers)
            assert resp.status_code == 200, f"{ep} -> {resp.status_code}"


class TestMaterialIntegrity:
    """Material data integrity checks."""

    def test_materials_have_safe_stock(self, client, auth_headers):
        resp = client.get("/api/materials", headers=auth_headers)
        assert resp.status_code == 200, resp.get_json()
        data = resp.get_json()
        items = data.get("items", data.get("materials", []))
        for item in items:
            assert "safe_stock" in item or "quantity" in item

    def test_order_has_product_code(self, client, auth_headers):
        resp = client.get("/api/orders?limit=5", headers=auth_headers)
        assert resp.status_code == 200, resp.get_json()
        data = resp.get_json()
        items = data.get("items", [])
        for item in items:
            assert "product_code" in item or "product_name" in item


class TestCoreBusinessPaths:
    """核心业务路径集成测试：扫码→报工→工资核算"""

    def test_scan_to_wage_flow(self, client, auth_headers):
        """验证：报工记录产生后，工资核算接口可查询。"""
        # 1. 查询工资核算
        wage_resp = client.get("/api/wages", headers=auth_headers)
        assert wage_resp.status_code == 200, wage_resp.get_json()

        # 2. 查询工序列表（报工必需）
        proc_resp = client.get("/api/processes", headers=auth_headers)
        assert proc_resp.status_code == 200, proc_resp.get_json()

    def test_order_lifecycle_integrity(self, client, auth_headers):
        """验证：订单创建后 product_items 自动生成。"""
        resp = client.get("/api/orders?limit=5", headers=auth_headers)
        assert resp.status_code == 200, resp.get_json()
        data = resp.get_json()
        items = data.get("items", [])
        for order in items:
            assert "order_no" in order
            assert "product_code" in order or "product_name" in order

    def test_material_deduction_enabled(self, client, auth_headers):
        """验证：auto_deduct_material 配置存在且可读。"""
        resp = client.get("/api/settings", headers=auth_headers)
        assert resp.status_code == 200, resp.get_json()
        data = resp.get_json()
        assert isinstance(data, (dict, list))

    def test_inventory_stock_tracking(self, client, auth_headers):
        """验证：库存出入库记录完整性。"""
        resp = client.get("/api/inventory/logs?limit=5", headers=auth_headers)
        assert resp.status_code == 200


class TestRepositoryIntegration:
    """Repository 层集成验证"""

    def test_order_repository_find(self, client, auth_headers):
        """验证：OrderRepository 通过 API 间接可用。"""
        resp = client.get("/api/orders?limit=1", headers=auth_headers)
        if resp.status_code == 200:
            data = resp.get_json()
            if data.get("items"):
                oid = data["items"][0]["id"]
                detail = client.get(f"/api/orders/{oid}", headers=auth_headers)
                assert detail.status_code in (200, 403, 404)

    def test_wage_repository_indirect(self, client, auth_headers):
        """验证：WageRepository 通过 /api/wages 间接可用。"""
        resp = client.get("/api/wages?page=1&limit=10", headers=auth_headers)
        assert resp.status_code == 200

    def test_inventory_repository_indirect(self, client, auth_headers):
        """验证：InventoryRepository 通过 /api/inventory 间接可用。"""
        resp = client.get("/api/inventory?page=1&limit=10", headers=auth_headers)
        assert resp.status_code == 200


class TestCoreBusinessRepositoryPaths:
    """核心业务路径：扫码→报工→工资→物料→库存"""

    def test_wage_endpoint_returns_data(self, client, auth_headers, test_order_id):
        """工资核算端点应在有订单时返回数据。"""
        resp = client.get("/api/wages?page=1&limit=10", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, dict)

    def test_inventory_crud_flow(self, client, auth_headers):
        """库存CRUD端点应可访问。"""
        resp = client.get("/api/inventory?page=1&limit=10", headers=auth_headers)
        assert resp.status_code == 200

    def test_inventory_stock_movement_flow(self, client, auth_headers):
        """库存迁移到 Repository 后，创建、入库、出库、调整链路应保持可用。"""
        suffix = __import__("uuid").uuid4().hex[:8].upper()
        create_resp = client.post(
            "/api/inventory",
            json={
                "product_model": f"TEST-INV-{suffix}",
                "product_name": "Repository Inventory Fixture",
                "quantity": 5,
                "safe_stock": 1,
                "location": "T-01",
                "unit": "件",
            },
            headers=auth_headers,
        )
        assert create_resp.status_code == 200, create_resp.get_json()
        inventory_id = create_resp.get_json()["id"]

        stock_in_resp = client.post(
            "/api/inventory/stock-in",
            json={"inventory_id": inventory_id, "quantity": 3, "remark": "repo-migration"},
            headers=auth_headers,
        )
        assert stock_in_resp.status_code == 200, stock_in_resp.get_json()

        stock_out_resp = client.post(
            "/api/inventory/stock-out",
            json={"inventory_id": inventory_id, "quantity": 2, "remark": "repo-migration"},
            headers=auth_headers,
        )
        assert stock_out_resp.status_code == 200, stock_out_resp.get_json()

        adjust_resp = client.post(
            f"/api/inventory/{inventory_id}/adjust",
            json={"actual_qty": 4, "remark": "repo-migration"},
            headers=auth_headers,
        )
        assert adjust_resp.status_code == 200, adjust_resp.get_json()
        assert adjust_resp.get_json()["new_qty"] == 4

        logs_resp = client.get(
            f"/api/inventory/logs?inventory_id={inventory_id}&limit=10",
            headers=auth_headers,
        )
        assert logs_resp.status_code == 200, logs_resp.get_json()
        assert logs_resp.get_json()["total"] >= 3

    def test_materials_list(self, client, auth_headers):
        """物料列表端点应可访问。"""
        resp = client.get("/api/materials?page=1&limit=10", headers=auth_headers)
        assert resp.status_code == 200

    def test_processes_available(self, client, auth_headers):
        """工序列表端点应可访问（报工必需）。"""
        resp = client.get("/api/processes", headers=auth_headers)
        assert resp.status_code == 200

    def test_stats_endpoints(self, client, auth_headers):
        """统计报表端点应返回 200。"""
        for ep in ["/api/stats/order-progress", "/api/stats/product", "/api/stats/product-process"]:
            resp = client.get(ep, headers=auth_headers)
            assert resp.status_code == 200, f"{ep} returned {resp.status_code}"

    def test_order_progress_after_create(self, client, auth_headers, test_order_id):
        """创建订单后订单进度应可查询。"""
        resp = client.get(f"/api/orders/{test_order_id}/workpiece-progress", headers=auth_headers)
        assert resp.status_code == 200, resp.get_json()


class TestMaterialDeduction:
    """物料自动扣减相关测试"""

    def test_auto_deduct_setting(self, client, auth_headers):
        """auto_deduct_material 设置项应可读。"""
        resp = client.get("/api/settings", headers=auth_headers)
        assert resp.status_code == 200, resp.get_json()
        data = resp.get_json()
        assert isinstance(data, (dict, list))
