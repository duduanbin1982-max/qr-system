#!/usr/bin/env python3
"""QR System — Regression Test Suite"""
import requests, sys
BASE = "https://127.0.0.1"
requests.packages.urllib3.disable_warnings()
VERIFY = False

def login(username="admin", password="admin123"):
    r = requests.post(f"{BASE}/api/auth/login", json={"username": username, "password": password}, verify=VERIFY)
    assert r.status_code == 200, f"Login failed: {r.status_code}"
    token = r.cookies.get("qr_token")
    assert token, "No qr_token cookie"
    return {"qr_token": token}

passed = 0
failed = 0

def test(name, fn):
    global passed, failed
    try:
        result = fn()
        if isinstance(result, requests.Response) and result.status_code >= 400:
            raise Exception(f"HTTP {result.status_code}: {result.text[:100]}")
        print(f"  \033[32mPASS\033[0m  {name}")
        passed += 1
    except Exception as e:
        print(f"  \033[31mFAIL\033[0m  {name}: {e}")
        failed += 1

print("=== QR System Regression Tests ===")
cookies = login()

def api(method, path, **kw):
    return requests.request(method, f"{BASE}{path}", cookies=cookies, verify=VERIFY, **kw)

# ── Core APIs ──
test("GET  /api/auth/info",        lambda: api("GET", "/api/auth/info").json())
test("GET  /api/products",         lambda: api("GET", "/api/products?limit=5").json())
test("GET  /api/orders",           lambda: api("GET", "/api/orders?limit=5").json())
test("GET  /api/processes",        lambda: api("GET", "/api/processes").json())
test("GET  /api/users",            lambda: api("GET", "/api/users").json())
test("GET  /api/inventory",        lambda: api("GET", "/api/inventory?limit=5").json())
test("GET  /api/shipments",        lambda: api("GET", "/api/shipments?limit=5").json())
test("GET  /api/inventory/stats",  lambda: api("GET", "/api/inventory/stats").json())
test("GET  /api/shipments/stats",  lambda: api("GET", "/api/shipments/stats").json())
test("GET  /api/board/kpi",       lambda: api("GET", "/api/board/kpi").json())
test("GET  /static/index.html",   lambda: api("GET", "/static/index.html").status_code)

# ── Wages ──
test("GET  /api/wages/route-prices", lambda: api("GET", "/api/wages/route-prices").json())

print(f"\n=== Results: {passed} passed, {failed} failed ===")
sys.exit(0 if failed == 0 else 1)
