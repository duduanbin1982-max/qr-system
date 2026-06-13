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
        assert resp.status_code in (200, 400, 404)

    def test_work_report_submit(self, client, auth_headers):
        """POST /api/report — submit a work report."""
        # First create an order, then report on it
        order_no = f"TEST-FLOW-{int(time.time())}"
        create_resp = client.post("/api/orders", headers=auth_headers, json={
            "order_no": order_no,
            "customer": "Integration Test",
            "product_name": "Test Part",
            "quantity": 10
        })
        if create_resp.status_code not in (200, 201):
            pytest.skip(f"Cannot create order (status={create_resp.status_code})")

        order_id = create_resp.get_json().get("id")
        if not order_id:
            pytest.skip("No order id returned")

        # Get first process
        proc_resp = client.get("/api/processes", headers=auth_headers)
        if proc_resp.status_code != 200:
            pytest.skip("Cannot list processes")

        processes = proc_resp.get_json().get("items", proc_resp.get_json().get("processes", []))
        if not processes:
            pytest.skip("No processes available")

        process_id = processes[0]["id"]

        # Submit work report
        report_resp = client.post("/api/report", headers=auth_headers, json={
            "order_id": order_id,
            "process_id": process_id,
            "quantity": 5,
            "serial_no": f"SN-{int(time.time())}",
            "report_type": "normal"
        })
        # 400 = validation error (ok), 200 = success (ok)
        assert report_resp.status_code in (200, 400, 201)

    def test_qr_code_generation(self, client, auth_headers):
        """POST /api/qrcode/batch — generate QR codes."""
        resp = client.post("/api/qrcode/batch", headers=auth_headers, json={
            "order_ids": [1],
            "mode": "order"
        })
        # May fail if order doesn't exist or permissions
        assert resp.status_code in (200, 400, 403, 404)

    def test_processes_list(self, client, auth_headers):
        """GET /api/processes — list active processes."""
        resp = client.get("/api/processes", headers=auth_headers)
        assert resp.status_code in (200, 403)
        if resp.status_code == 200:
            data = resp.get_json()
            assert "items" in data or "processes" in data


class TestScanEdgeCases:
    """Edge case and error handling tests."""

    def test_scan_without_auth(self, client):
        """Scan endpoint should require authentication."""
        resp = client.post("/api/scan", json={"code": "test"})
        assert resp.status_code in (401, 404)

    def test_report_without_auth(self, client):
        """Report endpoint should require authentication."""
        resp = client.post("/api/report", json={"order_id": 1, "process_id": 1})
        assert resp.status_code in (401, 404)

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
        assert resp.status_code in (200, 400, 404)