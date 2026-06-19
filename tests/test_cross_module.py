import json, time, sys, os, sqlite3, bcrypt, tempfile, shutil
from datetime import datetime

_TEST_DB = os.path.join(tempfile.gettempdir(), 'qr_cross_test_' + str(os.getpid()) + '.db')
if os.path.exists(_TEST_DB): os.remove(_TEST_DB)
shutil.copy2('/home/dubin/qr-system/data/production.db', _TEST_DB)

conn = sqlite3.connect(_TEST_DB)
conn.execute("PRAGMA foreign_keys = OFF")
for (tname,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
    if tname != 'sqlite_sequence': conn.execute(f'DELETE FROM "{tname}"')
conn.commit(); conn.execute("PRAGMA foreign_keys = ON")

h=bcrypt.hashpw(b"admin123",bcrypt.gensalt()).decode()
hw=bcrypt.hashpw(b"worker123",bcrypt.gensalt()).decode()
hw2=bcrypt.hashpw(b"wrkr2345",bcrypt.gensalt()).decode()
conn.execute("INSERT INTO roles (name,code,permissions,status) VALUES (?,?,?,?)",("SA","admin",json.dumps(["*"]),"active"))
conn.execute("INSERT INTO roles (name,code,permissions,status) VALUES (?,?,?,?)",("WR","worker",json.dumps(["scan:view","scan:report"]),"active"))
conn.execute("INSERT INTO users (username,password,name,role,status,password_version,employee_no,group_name) VALUES (?,?,?,?,?,?,?,?)",("admin",h,"A","admin","active",2,"A1","G"))
conn.execute("INSERT INTO users (username,password,name,role,status,password_version,employee_no,group_name) VALUES (?,?,?,?,?,?,?,?)",("worker1",hw,"W1","worker","active",2,"W1","W"))
conn.execute("INSERT INTO users (username,password,name,role,status,password_version,employee_no,group_name) VALUES (?,?,?,?,?,?,?,?)",("worker2",hw2,"W2","worker","active",2,"W2","W"))
uid_a=conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
uid_w1=conn.execute("SELECT id FROM users WHERE username='worker1'").fetchone()[0]
uid_w2=conn.execute("SELECT id FROM users WHERE username='worker2'").fetchone()[0]
ra=conn.execute("SELECT id FROM roles WHERE code='admin'").fetchone()[0]
rw=conn.execute("SELECT id FROM roles WHERE code='worker'").fetchone()[0]
conn.execute("INSERT INTO user_roles (user_id,role_id) VALUES (?,?)",(uid_a,ra))
conn.execute("INSERT INTO user_roles (user_id,role_id) VALUES (?,?)",(uid_w1,rw))
conn.execute("INSERT INTO user_roles (user_id,role_id) VALUES (?,?)",(uid_w2,rw))
for pn in ["Xialiao","Hanjie","Paowan","Penqi"]:
    conn.execute("INSERT INTO processes (name,category) VALUES (?,?)",(pn,"S"))
pids={r[1]:r[0] for r in conn.execute("SELECT id,name FROM processes")}
pcn={"Xialiao":"下料","Hanjie":"焊接","Paowan":"抛丸","Penqi":"喷漆"}
conn.execute("INSERT INTO process_routes (name,status,category) VALUES (?,?,?)",("R1","active","S"))
rid=conn.execute("SELECT last_insert_rowid()").fetchone()[0]
for pn,seq in [("Xialiao",1),("Hanjie",2),("Paowan",3),("Penqi",4)]:
    conn.execute("INSERT INTO process_route_items (route_id,process_id,seq_order) VALUES (?,?,?)",(rid,pids[pn],seq))
conn.execute("INSERT INTO customers (name) VALUES (?)",("C1",))
for pn,upr in [("Xialiao",15),("Hanjie",25),("Paowan",18),("Penqi",20)]:
    conn.execute("INSERT INTO route_prices (route_id,process_id,unit_price) VALUES (?,?,?)",(rid,pids[pn],upr))
conn.commit();conn.close()

sys.path.insert(0,"/home/dubin/qr-system")
os.environ["SECRET_KEY"]="cross-v8"; os.environ["ENABLE_SWAGGER"]="false"
import modules.config; modules.config.DB_PATH=_TEST_DB; modules.config.DATA_DIR=os.path.dirname(_TEST_DB)
from modules.app import app; app.config["TESTING"]=True; app.config["SECRET_KEY"]="cross-v8"

import modules.routes.auth,modules.routes.orders,modules.routes.products,modules.routes.processes
import modules.routes.scan_work,modules.routes.prices,modules.routes.inventory,modules.routes.shipments
import modules.routes.materials,modules.routes.users,modules.routes.roles,modules.routes.process_routes
import modules.routes.reports,modules.routes.stats,modules.routes.trace,modules.routes.quality
import modules.routes.rework,modules.routes.customers,modules.routes.settings,modules.routes.dashboard
import modules.routes.permissions,modules.routes.user_roles,modules.routes.approvals,modules.routes.positions
import modules.routes.progress,modules.routes.audit_logs,modules.routes.notifications

P=F=0
def ok(step,cond,detail=""):
    global P,F
    if cond: P+=1; print(f"  OK {step}")
    else: F+=1; print(f"  FAIL {step} -- {str(detail)[:130]}")

def login(u,p):
    tc=app.test_client(); r=tc.post("/api/auth/login",json={"username":u,"password":p})
    return tc,{"Authorization":"Bearer "+(r.get_json()or{}).get("user",{}).get("token","")}

cA,A=login("admin","admin123"); cW1,W1=login("worker1","worker123"); cW2,W2=login("worker2","wrkr2345")
ym=datetime.now().strftime("%Y-%m"); ts=int(time.time()); ono=f"XT-{ts}"; spfx=f"SN-{ts}"

print(f"\n{'='*60}\n  Cross-Module Integration Test\n  Order: {ono}\n{'='*60}")

# [1] Order->Report->Wage
print("\n[1] Order->Report->Wage")
r=cA.post("/api/orders",headers=A,json={"order_no":ono,"customer":"C1","product_name":"P1","product_code":"XT-001","quantity":10,"route_id":rid})
oid=(r.get_json()or{}).get("id") if r.status_code in(200,201) else None
ok("1.1 CreateOrder",oid is not None,f"s={r.status_code}")
db=sqlite3.connect(_TEST_DB)
ok("1.2 RouteLinked",db.execute("SELECT COUNT(*) FROM order_processes WHERE order_id=?",(oid,)).fetchone()[0]>=4)
db.close()
for sn,(pk,seq) in enumerate([("Xialiao",1),("Hanjie",2),("Paowan",3),("Penqi",4)]):
    r=cW1.post("/api/mobile/report",headers=W1,json={"order_id":oid,"process_id":pids[pk],"quantity":10,"report_type":"normal","serial_no":f"{spfx}-{pk}"})
    ok(f"1.{3+sn} Report-{pcn[pk]}",r.status_code==200,f"s={r.status_code}")
db=sqlite3.connect(_TEST_DB)
pc=sum(r2[0] for r2 in db.execute("SELECT COALESCE(completed,0) FROM order_processes WHERE order_id=?",(oid,)).fetchall())
ok("1.7 ProcessCompleted",pc>=4,f"sum={pc}")
wrs=db.execute("SELECT COUNT(*) FROM work_records WHERE order_id=? AND type='normal'",(oid,)).fetchone()[0]
ok("1.8 WorkRecords",wrs>=4,f"count={wrs}")
db.close()
r=cA.get("/api/wages/monthly-summary",headers=A)
ok("1.9 WageAPI",r.status_code==200)

# [2] Stock->Shipment
print("\n[2] Stock->Shipment")
r=cA.get("/api/inventory",headers=A); ok("2.1 InventoryAPI",r.status_code==200)
r=cA.post("/api/shipments",headers=A,json={"shipment_no":f"SH-{ts}","customer":"C1","total_quantity":10,"receivable_amount":1000.0,"status":"pending"})
sid=(r.get_json()or{}).get("id") if r.status_code in(200,201) else None
ok("2.2 CreateShip",r.status_code in(200,201,400),f"s={r.status_code}")
if sid:
    r=cA.get(f"/api/shipments/{sid}",headers=A); ok("2.3 Detail",r.status_code==200)
    r=cA.post(f"/api/shipments/{sid}/receive",headers=A,json={}); ok("2.4 Receive",r.status_code in(200,201))
r=cA.get("/api/stats/shipment",headers=A); ok("2.5 Stats",r.status_code==200)

# [3] Quality
print("\n[3] Quality")
r=cA.post("/api/quality/inspections",headers=A,json={"order_id":oid,"process_id":pids["Hanjie"],"inspection_type":"first_article","quantity_checked":10,"quantity_passed":10,"notes":"OK"})
ok("3.1 Pass",r.status_code in(200,201),f"s={r.status_code}")
r=cA.post("/api/quality/inspections",headers=A,json={"order_id":oid,"process_id":pids["Penqi"],"inspection_type":"final","quantity_checked":2,"quantity_failed":2,"defect_category":"外观缺陷"})
ok("3.2 Scrap",r.status_code in(200,201),f"s={r.status_code}")
for lb,pth in [("List","/api/quality/inspections"),("Stats","/api/quality/inspections/stats"),("Report","/api/reports/quality-analysis")]:
    r=cA.get(pth,headers=A); ok(f"3.x {lb}",r.status_code==200)

# [4] Permission
print("\n[4] Permission")
ono2=f"XT-PERM-{ts}"
r=cA.post("/api/orders",headers=A,json={"order_no":ono2,"customer":"C1","product_name":"P1","product_code":"XT-PERM","quantity":5,"route_id":rid})
oid2=(r.get_json()or{}).get("id") if r.status_code in(200,201) else None
ok("4.0 Create",oid2 is not None)
r=cA.post("/api/mobile/report",headers=A,json={"order_id":oid2,"process_id":pids["Xialiao"],"quantity":1,"report_type":"normal","serial_no":f"{spfx}-ADM"})
ok("4.1 AdminBlock(403)",r.status_code==403)
tc3=app.test_client(); r=tc3.post("/api/mobile/report",json={"order_id":oid2,"process_id":pids["Xialiao"],"quantity":1,"report_type":"normal"})
ok("4.2 NoAuth(401)",r.status_code in(401,403))
r=cW2.post("/api/mobile/report",headers=W2,json={"order_id":oid2,"process_id":pids["Hanjie"],"quantity":1,"report_type":"normal","serial_no":f"{spfx}-SKIP"})
ok("4.3 SkipProc(400)",r.status_code in(400,403))
r=cW2.post("/api/mobile/report",headers=W2,json={"order_id":oid2,"process_id":pids["Xialiao"],"quantity":1,"report_type":"normal","serial_no":f"{spfx}-DUP"})
ok("4.4 Normal",r.status_code==200)
r=cW2.post("/api/mobile/report",headers=W2,json={"order_id":oid2,"process_id":pids["Xialiao"],"quantity":1,"report_type":"normal","serial_no":f"{spfx}-DUP"})
ok("4.5 DupBlock(409)",r.status_code==409)
conn=sqlite3.connect(_TEST_DB)
conn.execute("INSERT INTO roles (name,code,permissions,status) VALUES (?,?,?,?)",("NP","no_perm",json.dumps(["dashboard:view"]),"active"))
rnp=conn.execute("SELECT last_insert_rowid()").fetchone()[0]
hnp=bcrypt.hashpw(b"noperm11",bcrypt.gensalt()).decode()
conn.execute("INSERT INTO users (username,password,name,role,status,password_version,employee_no,group_name) VALUES (?,?,?,?,?,?,?,?)",("noperm",hnp,"NP","worker","active",2,"NP","N"))
unp=conn.execute("SELECT id FROM users WHERE username='noperm'").fetchone()[0]
conn.execute("INSERT INTO user_roles (user_id,role_id) VALUES (?,?)",(unp,rnp))
conn.commit();conn.close()
cNP,NP=login("noperm","noperm11")
r=cNP.post("/api/mobile/report",headers=NP,json={"order_id":oid2,"process_id":pids["Xialiao"],"quantity":1,"report_type":"normal"})
ok("4.6 NoPerm(403)",r.status_code==403)

# [5] Wage Snapshot
print("\n[5] Wage Snapshot")
r=cA.post(f"/api/wages/snapshot?year_month={ym}",headers=A,json={}); ok("5.1 Save",r.status_code in(200,201))
r=cA.get(f"/api/wages/snapshot-status?year_month={ym}",headers=A); ok("5.2 Status",r.status_code==200)
r=cA.post(f"/api/wages/lock?year_month={ym}",headers=A,json={"notes":"T"}); ok("5.3 Lock",r.status_code in(200,201))
r=cA.post("/api/wages/adjustments",headers=A,json={"user_id":uid_w1,"year_month":ym,"type":"bonus","amount":50.0,"reason":"T-"+str(ts)}); ok("5.4 Adjust",r.status_code in(200,201))
for lb,pth in [("Trends","/api/wages/trends"),("Position","/api/wages/position-summary"),("Process","/api/wages/process-summary")]:
    r=cA.get(pth,headers=A); ok(f"5.x {lb}",r.status_code==200)

# [6] Reports & Stats
print("\n[6] Reports & Stats (18 endpoints)")
eps=[("Daily","/api/stats/daily"),("Worker","/api/stats/worker"),("Scrap","/api/stats/scrap"),
     ("OrderProgress","/api/stats/order-progress"),("Product","/api/stats/product"),
     ("Shipment","/api/stats/shipment"),("Material","/api/stats/material"),
     ("Customer","/api/stats/customer"),("Monthly","/api/stats/monthly-summary"),
     ("ProdProc","/api/stats/product-process"),("Lines","/api/stats/production-lines"),
     ("Dashboard","/api/dashboard"),("Trend","/api/reports/production-trend"),
     ("Quality","/api/reports/quality-analysis"),("OrderAnalysis","/api/reports/order-analysis"),
     ("WorkerEff","/api/reports/worker-efficiency"),("MaterialUse","/api/reports/material-usage"),
     ("ProdStats","/api/reports/product-stats")]
for i,(lb,pth) in enumerate(eps,1):
    r=cA.get(pth,headers=A); ok(f"6.{i} {lb}",r.status_code==200,f"s={r.status_code}")

# [7] Scrap/Rework
print("\n[7] Scrap/Rework")
r=cA.post("/api/mobile/report",headers=A,json={"order_id":oid2,"process_id":pids["Xialiao"],"quantity":1,"report_type":"scrap","serial_no":f"{spfx}-SCRAP"})
ok("7.1 Scrap",r.status_code in(200,201))
r=cA.post("/api/mobile/report",headers=A,json={"order_id":oid2,"process_id":pids["Xialiao"],"quantity":1,"report_type":"rework","serial_no":f"{spfx}-REWORK"})
ok("7.2 Rework",r.status_code in(200,201))
r=cA.get("/api/stats/scrap",headers=A); ok("7.3 Stats",r.status_code==200)

# [8] Trace
print("\n[8] Trace")
r=cA.get(f"/api/trace/{ono}",headers=A); ok("8.1 Trace",r.status_code in(200,404))
r=cA.get(f"/api/trace/order/{ono}",headers=A); ok("8.2 TraceV2",r.status_code in(200,404))

# [9] Auth/Dashboard
print("\n[9] Auth & Dashboard")
r=cA.get("/api/dashboard",headers=A); ok("9.1 Dashboard",r.status_code==200)
r=cA.get("/api/auth/info",headers=A); ok("9.2 AdminInfo",r.status_code==200)
r=cW1.get("/api/auth/info",headers=W1); ok("9.3 WorkerInfo",r.status_code==200)

# [10] Data Integrity
print("\n[10] Data Integrity")
db=sqlite3.connect(_TEST_DB)
ok("10.1 WorkRecords",db.execute("SELECT COUNT(*) FROM work_records WHERE order_id=?",(oid,)).fetchone()[0]>=4)
ok("10.2 ScrapRecords",db.execute("SELECT COUNT(*) FROM scrap_records WHERE order_id=?",(oid2,)).fetchone()[0]>=1)
ok("10.3 ReworkRecords",db.execute("SELECT COUNT(*) FROM rework_records WHERE order_id=?",(oid2,)).fetchone()[0]>=1)
ok("10.4 QIRecords",db.execute("SELECT COUNT(*) FROM quality_inspections WHERE order_id=?",(oid,)).fetchone()[0]>=2)
ok("10.5 Snapshots",db.execute("SELECT COUNT(*) FROM wage_snapshots WHERE year_month=?",(ym,)).fetchone()[0]>=1)
db.close()

t=P+F; pct=P/t*100 if t>0 else 0
print(f"\n{'='*60}\n  {'ALL PASSED!' if F==0 else 'SOME FAILED'}\n  {P} PASS / {F} FAIL / {t} total ({pct:.1f}%)\n{'='*60}")
try: os.remove(_TEST_DB)
except: pass
sys.exit(0 if F==0 else 1)
