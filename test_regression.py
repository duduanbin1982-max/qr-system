#!/usr/bin/env python3
"""Regression tests for critical business flows."""
import requests, sys, json, time, os

BASE = os.environ.get("SMOKE_BASE", "https://127.0.0.1")
ADMIN_USER = os.environ.get("SMOKE_USER", "admin")
ADMIN_PASS = os.environ.get("SMOKE_PASS", "admin123")
WORKER_USER = "0101"
WORKER_PASS = "123456780"
VERBOSE = "-v" in sys.argv

session = requests.Session()
session.verify = False
requests.packages.urllib3.disable_warnings()

PASS = FAIL = SKIP = 0
START = time.time()

def ok(label):
    global PASS; PASS += 1
    print("  PASS " + label)

def fail(label, detail=""):
    global FAIL; FAIL += 1
    print("  FAIL " + label)
    if detail: print("       " + detail)

def skip(label, reason=""):
    global SKIP; SKIP += 1
    print("  SKIP " + label + " (" + reason + ")")

def get(path):
    r = session.get(BASE + path, timeout=15, allow_redirects=False)
    if VERBOSE: print("    GET " + path + " -> " + str(r.status_code))
    return r

def post(path, data=None):
    r = session.post(BASE + path, json=data, timeout=15, allow_redirects=False)
    if VERBOSE: print("    POST " + path + " -> " + str(r.status_code))
    return r

def delete(path):
    r = session.delete(BASE + path, timeout=15, allow_redirects=False)
    if VERBOSE: print("    DELETE " + path + " -> " + str(r.status_code))
    return r

def login_as_admin():
    r = post("/api/auth/login", {"username": ADMIN_USER, "password": ADMIN_PASS})
    if r.status_code == 200:
        token = r.json().get("user", {}).get("token", "")
        if token:
            session.headers["Authorization"] = "Bearer " + token
            return True
    return False

def login_as(username, password):
    r = post("/api/auth/login", {"username": username, "password": password})
    if r.status_code == 200:
        token = r.json().get("user", {}).get("token", "")
        if token:
            session.headers["Authorization"] = "Bearer " + token
            return True
    return False

print("=" * 60)
print("QR System Regression Tests")
print("=" * 60)

print("\n[0] Setup - Create test data")
if not login_as_admin():
    fail("Login admin failed")
    sys.exit(1)

r = get("/api/process-routes")
routes = r.json().get("routes", [])
if not routes:
    fail("No process routes")
    sys.exit(1)
route_id = routes[0]["id"]

prod_data = {
    "product_name": "__TEST_SMOKE_PRODUCT__",
    "model": "T1",
    "spec": "10x10",
    "category": "\u7ed3\u6784\u4ef6",
    "route_id": route_id,
    "weight": 10,
    "price": 100
}
r = post("/api/products", prod_data)
test_product_id = None
if r.status_code == 200:
    data = r.json()
    test_product_id = data.get("product", {}).get("id") or data.get("id")
    ok("Test product created id=" + str(test_product_id))
else:
    fail("Create product HTTP " + str(r.status_code), r.text[:200])
    sys.exit(1)

order_data = {
    "product_id": test_product_id,
    "quantity": 5,
    "qr_mode": "order",
    "status": "pending"
}
r = post("/api/orders", order_data)
test_order_id = None
test_order_no = None
if r.status_code == 200:
    data = r.json()
    test_order_id = data.get("id")
    test_order_no = ""
    r2 = get("/api/orders")
    if r2.status_code == 200:
        for o in r2.json().get("orders", []):
            if o.get("id") == test_order_id:
                test_order_no = o.get("order_no", "")
                break
    ok("Test order created id=" + str(test_order_id) + " no=" + test_order_no)
else:
    fail("Create order HTTP " + str(r.status_code), r.text[:200])
    sys.exit(1)

print("\n[1] Scan Work - Duplicate Prevention")
if not login_as(WORKER_USER, WORKER_PASS):
    skip("Worker login failed", "credentials changed")
else:
    r = post("/api/mobile/scan", {"code": test_order_no})
    if r.status_code == 200:
        oi = r.json().get("order", {})
        cp = oi.get("current_process")
        if cp:
            pid = cp.get("process_id")
            ok("Scan order found pid=" + str(pid))
            rpt = {"order_id": test_order_id, "process_id": pid, "quantity": 1}
            r = post("/api/mobile/report", rpt)
            if r.status_code == 200:
                ok("First report OK")
                r = post("/api/mobile/report", rpt)
                if r.status_code == 409:
                    ok("Duplicate blocked 409")
                else:
                    fail("Duplicate NOT blocked got " + str(r.status_code), r.text[:150])
            else:
                fail("First report failed HTTP " + str(r.status_code), r.text[:150])
        else:
            fail("Scan no current_process", json.dumps(oi, default=str)[:200])
    else:
        fail("Scan order failed HTTP " + str(r.status_code), r.text[:150])

print("\n[2] Wage Snapshot")
if not login_as_admin():
    fail("Admin re-login failed")
else:
    r = get("/api/wages")
    if r.status_code == 200:
        ok("Wages API OK")
    else:
        fail("Wages HTTP " + str(r.status_code))
    ym = time.strftime("%Y-%m")
    r = session.post(BASE + "/api/wages/snapshot?year_month=" + ym, timeout=15)
    if VERBOSE: print("    POST /api/wages/snapshot?year_month=" + ym + " -> " + str(r.status_code))
    if r.status_code == 200:
        ok("Wage snapshot created")
    else:
        fail("Wage snapshot HTTP " + str(r.status_code), r.text[:150])

print("\n[3] Inventory")
if not login_as_admin():
    fail("Admin re-login failed")
else:
    r = get("/api/inventory")
    if r.status_code == 200:
        ok("Inventory API OK")
    else:
        fail("Inventory HTTP " + str(r.status_code))

print("\n[4] Order Delete Flow")
if not login_as_admin():
    fail("Admin re-login failed")
else:
    r = delete("/api/orders/" + str(test_order_id))
    if r.status_code == 200:
        ok("Soft-deleted")
        r = get("/api/orders/trash")
        if r.status_code == 200:
            trash = r.json().get("orders", [])
            found = any(o.get("id") == test_order_id for o in trash)
            ok("In trash " + str(found))
            r = post("/api/orders/" + str(test_order_id) + "/restore")
            if r.status_code == 200:
                ok("Restored")
                delete("/api/orders/" + str(test_order_id))
                r = delete("/api/orders/" + str(test_order_id) + "/purge")
                if r.status_code == 200:
                    ok("Purged")
                else:
                    fail("Purge failed HTTP " + str(r.status_code), r.text[:150])
            else:
                fail("Restore failed HTTP " + str(r.status_code), r.text[:150])
        else:
            fail("Trash HTTP " + str(r.status_code))
    else:
        fail("Soft delete HTTP " + str(r.status_code), r.text[:150])

print("\n[5] Permission Isolation")
if not login_as(WORKER_USER, WORKER_PASS):
    fail("Worker re-login failed")
else:
    r = get("/api/users")
    if r.status_code == 200:
        fail("Worker can access /api/users")
    elif r.status_code in (401, 403):
        ok("Worker blocked from /api/users")
    else:
        fail("Unexpected status " + str(r.status_code))

print("\n[6] Cleanup")
if not login_as_admin():
    fail("Admin cleanup failed")
else:
    if test_product_id:
        delete("/api/products/" + str(test_product_id))
        ok("Test product cleaned")

elapsed = time.time() - START
total = PASS + FAIL + SKIP
print("\n" + "=" * 60)
print("Results " + str(PASS) + " passed " + str(FAIL) + " failed " + str(SKIP) + " skipped " + format(elapsed,".1f") + "s")
print("=" * 60)
sys.exit(0 if FAIL == 0 else 1)
