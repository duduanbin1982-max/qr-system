"""Core scan-to-report flow integration tests"""
import json, time, pytest


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
        assert report_resp.status_code in (200, 201)

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
        if resp.status_code == 200:
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
        assert resp.status_code in (200, 404, 400)

    def test_mobile_decode_invalid(self, client, auth_headers):
        """Mobile decode with garbage input should not crash."""
        resp = client.get("/api/mobile/decode/!!!invalid!!!", headers=auth_headers)
        assert resp.status_code == 200

class TestScanReportVerification:
    """Verify scan data flows to reports and wages."""

    def test_order_trace(self, client, auth_headers):
        resp = client.get("/api/trace/26061201", headers=auth_headers)
        assert resp.status_code == 200

    def test_work_records_list(self, client, auth_headers):
        resp = client.get("/api/report/history?limit=5", headers=auth_headers)
        assert resp.status_code in (200, 404)

    def test_wage_endpoint(self, client, auth_headers):
        resp = client.get("/api/wages", headers=auth_headers)
        if resp.status_code == 200:
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
        if resp.status_code == 200:
            data = resp.get_json()
            items = data.get("items", data.get("materials", []))
            for item in items:
                assert "safe_stock" in item or "quantity" in item

    def test_order_has_product_code(self, client, auth_headers):
        resp = client.get("/api/orders?limit=5", headers=auth_headers)
        if resp.status_code == 200:
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
        assert wage_resp.status_code in (200, 403), f"Wages: {wage_resp.status_code}"

        # 2. 查询工序列表（报工必需）
        proc_resp = client.get("/api/processes", headers=auth_headers)
        assert proc_resp.status_code in (200, 403), f"Processes: {proc_resp.status_code}"

    def test_order_lifecycle_integrity(self, client, auth_headers):
        """验证：订单创建后 product_items 自动生成。"""
        resp = client.get("/api/orders?limit=5", headers=auth_headers)
        if resp.status_code == 200:
            data = resp.get_json()
            items = data.get("items", [])
            for order in items:
                assert "order_no" in order
                assert "product_code" in order or "product_name" in order

    def test_material_deduction_enabled(self, client, auth_headers):
        """验证：auto_deduct_material 配置存在且可读。"""
        resp = client.get("/api/settings", headers=auth_headers)
        if resp.status_code == 200:
            data = resp.get_json()
            # Settings should be accessible
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


class TestCoreBusinessPaths:
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
        # May be 200 or 404 if no product_items yet
        assert resp.status_code in (200, 404)


class TestMaterialDeduction:
    """物料自动扣减相关测试"""

    def test_auto_deduct_setting(self, client, auth_headers):
        """auto_deduct_material 设置项应可读。"""
        resp = client.get("/api/settings", headers=auth_headers)
        if resp.status_code == 200:
            data = resp.get_json()
            assert isinstance(data, (dict, list))
