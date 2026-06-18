#!/usr/bin/env python3
"""扫码报工系统 — 回归测试 v5 (自动发现可用订单)"""
import urllib.request, urllib.error, json, ssl, sys, os

BASE = os.environ.get("TEST_BASE", "https://127.0.0.1:3000")
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
P = F = 0

def api(method, path, data=None, token=None):
    url = BASE + path
    body = json.dumps(data).encode() if data else None
    h = {"Content-Type": "application/json"}
    if token: h["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        r = urllib.request.urlopen(req, context=ctx, timeout=10)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

def t(n, c, d=""):
    global P, F
    if c: P += 1; print(f"  ok {n}")
    else: F += 1; print(f"  FAIL {n}  {d}")

def hdr(s): print(f"\n{'='*50}\n  {s}\n{'='*50}")

print("regression v5")
token = api("POST","/api/auth/login",{"username":"admin","password":"admin123"})[1]["user"]["token"]
print("  login: admin")

# Find available order with capacity
s, orders = api("GET", "/api/orders?limit=20", None, token)
OID = PID = None
if s == 200:
    for o in orders.get("orders", []):
        if o.get("status") == "deleted": continue
        for p in o.get("processes", []):
            comp = p.get("completed", 0)
            if comp < o.get("quantity", 0):
                OID = o["id"]; PID = p["process_id"]
                break
        if OID: break

if not OID:
    print("  FAIL: no available order found"); sys.exit(1)

print(f"  using order={OID} proc={PID} qty remaining")

# 1. same-process dup
hdr("1. same-process dup")
s1 = f"RT1_{os.getpid()}"
s,d = api("POST","/api/mobile/report",{"order_id":OID,"process_id":PID,"quantity":1,"report_type":"normal","serial_no":s1},token)
t("first ok", s==200, f"{s}:{d}")
s,d = api("POST","/api/mobile/report",{"order_id":OID,"process_id":PID,"quantity":1,"report_type":"normal","serial_no":s1},token)
t("dup->409", s==409, f"{s}:{d}")
t("msg:dup", "不可重复" in str(d.get("error","")), str(d.get("error")))

# 2. cross-process dup [KEY FIX]
hdr("2. cross-process dup [KEY]")
# Find second process for same order
PID2 = None
for o in orders.get("orders", []):
    if o["id"] == OID:
        for p in o.get("processes", []):
            if p["process_id"] != PID and p.get("completed", 0) < o.get("quantity", 0):
                PID2 = p["process_id"]; break
        break

if PID2:
    s2 = f"RT2_{os.getpid()}"
    s,d = api("POST","/api/mobile/report",{"order_id":OID,"process_id":PID,"quantity":1,"report_type":"normal","serial_no":s2},token)
    t("procA ok", s==200, f"{s}:{d}")
    s,d = api("POST","/api/mobile/report",{"order_id":OID,"process_id":PID2,"quantity":1,"report_type":"normal","serial_no":s2},token)
    t("procB cross->409", s==409, f"{s}:{d}")
    t("msg:cross", "在此订单已报工" in str(d.get("error","")), str(d.get("error")))
else:
    t("cross-process", False, "no second process available")

# 3. desktop
hdr("3. desktop /api/report")
s3 = f"RT3_{os.getpid()}"
s,d = api("POST","/api/report",{"order_id":OID,"process_id":PID,"quantity":1,"report_type":"normal","serial_no":s3},token)
t("first ok", s==200, f"{s}:{d}")
s,d = api("POST","/api/report",{"order_id":OID,"process_id":PID,"quantity":1,"report_type":"normal","serial_no":s3},token)
t("dup->409", s==409, f"{s}:{d}")

# 4. serial guard
hdr("4. serial guard")
s,d = api("POST","/api/mobile/report",{"order_id":OID,"process_id":PID,"quantity":1,"report_type":"normal"},token)
t("no serial->400", s==400)
t("msg:serial", "序列号模式" in str(d.get("error","")))

# 5. permission
hdr("5. permission")
s,d = api("POST","/api/mobile/report",{"order_id":OID,"process_id":99999,"quantity":1,"report_type":"normal","serial_no":f"RT5_{os.getpid()}"},token)
t("bad proc->400", s==400)

# 6. wages
hdr("6. wages")
s,d = api("GET","/api/wages/snapshots",None,token); t("snapshots", s in(200,404))
s,d = api("GET","/api/wages/monthly?year=2026&month=6",None,token); t("monthly", s in(200,404))

# 7. auth
hdr("7. auth")
s,d = api("POST","/api/auth/login",{"username":"admin","password":"wrong____"})
t("bad pw", s in(400,401))
s,d = api("GET","/api/auth/info",None,token); t("valid token", s==200)
s,d = api("GET","/api/auth/info",None,"bad"); t("bad token", s in(401,403,500))

# 8. resources
hdr("8. resources")
s,d = api("GET","/api/orders?limit=5",None,token); t("orders", s==200)
s,d = api("GET","/api/products?limit=5",None,token); t("products", s==200)

# 9. scan
hdr("9. scan flow")
s,d = api("POST","/api/mobile/scan",{"code":f'{{"order_id":{OID}}}'},token); t("scan", s in(200,404))

# 10. dashboard
hdr("10. dashboard")
s,d = api("GET","/api/dashboard/kpi",None,token); t("kpi", s in(200,404))

print(f"\n{'='*50}\n  {P}/{P+F} passed {'🎉' if F==0 else '⚠️'}\n{'='*50}")
sys.exit(0 if F==0 else 1)
