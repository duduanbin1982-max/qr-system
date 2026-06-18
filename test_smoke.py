#!/usr/bin/env python3
import requests, sys, json, time, os

BASE = os.environ.get("SMOKE_BASE", "https://127.0.0.1")
USERNAME = os.environ.get("SMOKE_USER", "admin")
PASSWORD = os.environ.get("SMOKE_PASS", "admin123")
VERBOSE = "--verbose" in sys.argv or "-v" in sys.argv

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

def get(path):
    r = session.get(BASE + path, timeout=15, allow_redirects=False)
    if VERBOSE: print("    GET " + path + " -> " + str(r.status_code))
    return r

def post(path, data=None):
    r = session.post(BASE + path, json=data, timeout=15, allow_redirects=False)
    if VERBOSE: print("    POST " + path + " -> " + str(r.status_code))
    return r

print("=" * 60)
print("QR System Smoke Test")
print("=" * 60)

print("\n[1] Auth")
r = post("/api/auth/login", {"username": USERNAME, "password": PASSWORD})
if r.status_code == 200:
    data = r.json(); user = data.get("user", {}); token = user.get("token", "")
    if token:
        session.headers["Authorization"] = "Bearer " + token
        ok("Login: " + user.get("username","?") + " (role=" + user.get("role","?") + ")")
    else: fail("Login: no token")
else: fail("Login: HTTP " + str(r.status_code), r.text[:200])

tests = [
    ("Auth Info", "/api/auth/info", "GET", None),
    ("Dashboard", "/api/dashboard", "GET", None),
    ("Orders", "/api/orders", "GET", None),
    ("Products", "/api/products", "GET", None),
    ("Route Prices", "/api/route-prices", "GET", None),
    ("Dashboard KPI", "/api/reports/dashboard-kpi", "GET", None),
    ("Wages", "/api/wages", "GET", None),
]
for idx, (name, path, method, body) in enumerate(tests):
    print("\n[" + str(idx+2) + "] " + name)
    r = get(path)
    if r.status_code == 200: ok(name + " OK")
    else: fail(name + ": HTTP " + str(r.status_code))

print("\n[9] Health")
r = get("/api/process-routes")
if r.status_code == 200:
    routes = r.json().get("routes", []); ok("Process Routes: " + str(len(routes)))
else: fail("Process Routes: HTTP " + str(r.status_code))

r = get("/api/users")
if r.status_code == 200: ok("Users OK")
elif r.status_code in (403, 401): ok("Users: auth required (OK)")
else: fail("Users: HTTP " + str(r.status_code))

elapsed = time.time() - START
total = PASS + FAIL + SKIP
print("\n" + "=" * 60)
print("Results: " + str(PASS) + " passed, " + str(FAIL) + " failed, " + str(SKIP) + " skipped (" + format(elapsed,".1f") + "s)")
print("=" * 60)
sys.exit(0 if FAIL == 0 else 1)
