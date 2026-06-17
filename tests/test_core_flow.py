"""Core flow tests for QR System"""
import json


class TestAuth:
    """Authentication tests."""

    def test_login_success(self, client):
        resp = client.post("/api/auth/login", json={
            "username": "testrunner",
            "password": "Test@1234"
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert "user" in data or "token" in data

    def test_login_failure(self, client):
        resp = client.post("/api/auth/login", json={
            "username": "testrunner",
            "password": "wrongpassword"
        })
        assert resp.status_code in (400, 401, 429)

    def test_health_check(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert "db" in data

    def test_unauthorized_access(self, client):
        resp = client.get("/api/auth/info")
        assert resp.status_code == 401


class TestOrders:
    """Order CRUD tests."""

    def test_list_orders(self, client, auth_headers):
        resp = client.get("/api/orders", headers=auth_headers)
        assert resp.status_code == 200

    def test_create_order(self, client, auth_headers):
        import time
        order_no = f"TEST-{int(time.time())}"
        resp = client.post("/api/orders", headers=auth_headers, json={
            "order_no": order_no,
            "customer": "Test Customer",
            "product_name": "Test Product",
            "quantity": 10
        })
        assert resp.status_code in (200, 201)

    def test_order_detail(self, client, auth_headers):
        lst = client.get("/api/orders?limit=1", headers=auth_headers)
        if lst.status_code in (200, 403):
            data = lst.get_json()
            items = data.get("items", data.get("orders", []))
            if items:
                oid = items[0]["id"]
                resp = client.get(f"/api/orders/{oid}", headers=auth_headers)
                assert resp.status_code in (200, 405)


class TestScanWorkReport:
    """Scan and work reporting tests."""

    def test_list_processes(self, client, auth_headers):
        resp = client.get("/api/processes", headers=auth_headers)
        assert resp.status_code == 200

    def test_scan_unauthorized(self, client):
        resp = client.post("/api/scan/report", json={
            "order_id": 1,
            "process_id": 1
        })
        assert resp.status_code in (401, 404)


class TestSystem:
    """System-level tests."""

    def test_cors_headers(self, client):
        resp = client.get("/api/health", headers={
            "Origin": "https://evil.com"
        })
        assert "Access-Control-Allow-Origin" not in resp.headers

    def test_security_headers(self, client):
        resp = client.get("/")
        if resp.status_code == 200:
            assert resp.headers.get("X-Content-Type-Options") == "nosniff"
            assert resp.headers.get("X-Frame-Options") == "DENY"

    def test_swagger_disabled(self, client):
        resp = client.get("/api/docs/")
        assert resp.status_code in (404, 403)