import sqlite3

from modules.services.mobile_scan_resolver import MobileScanResolver
from modules.services.order_process_sync_service import OrderProcessSyncService


def _process_db():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute(
        "CREATE TABLE process_route_items ("
        "id INTEGER PRIMARY KEY, route_id INTEGER, process_id INTEGER, "
        "seq_order INTEGER, required_audit INTEGER)"
    )
    db.execute(
        "CREATE TABLE process_routes ("
        "id INTEGER PRIMARY KEY, name TEXT, status TEXT, category TEXT)"
    )
    db.execute(
        "CREATE TABLE processes ("
        "id INTEGER PRIMARY KEY, name TEXT DEFAULT '', category TEXT DEFAULT '结构件', "
        "seq_order INTEGER, status TEXT)"
    )
    db.execute(
        "CREATE TABLE order_processes ("
        "order_id INTEGER, process_id INTEGER, seq_order INTEGER, "
        "required_audit INTEGER DEFAULT 0, process_version_id INTEGER, "
        "process_code_snapshot TEXT, process_name_snapshot TEXT, "
        "process_category_snapshot TEXT)"
    )
    return db


def _assigned_processes(db):
    rows = db.execute(
        "SELECT order_id, process_id, seq_order, COALESCE(required_audit, 0) AS required_audit "
        "FROM order_processes ORDER BY seq_order"
    ).fetchall()
    return [dict(row) for row in rows]


def test_order_process_assignment_uses_route_items_when_route_selected():
    db = _process_db()
    db.execute(
        "INSERT INTO process_routes (id, name, status, category) "
        "VALUES (2, 'Fixture Route', 'active', '结构件')"
    )
    db.execute(
        "INSERT INTO processes (id, name, category, seq_order, status) "
        "VALUES (10, 'Fixture Process', '结构件', 1, 'active')"
    )
    db.execute(
        "INSERT INTO process_route_items (route_id, process_id, seq_order, required_audit) "
        "VALUES (2, 10, 1, 1)"
    )

    OrderProcessSyncService.assign_processes(
        db,
        order_id=1,
        route_id=2,
        process_ids=None,
        assignment={
            "route_id": 2,
            "route_version_id": 20,
            "route_name_snapshot": "Fixture Route",
            "processes": [
                {
                    "process_id": 10,
                    "process_version_id": 100,
                    "process_code_snapshot": "PROC-0010",
                    "process_name_snapshot": "Fixture Process",
                    "process_category_snapshot": "结构件",
                    "seq_order": 1,
                    "required_audit": 1,
                }
            ],
        },
    )

    assert _assigned_processes(db) == [
        {"order_id": 1, "process_id": 10, "seq_order": 1, "required_audit": 1}
    ]


def test_order_process_assignment_falls_back_to_active_processes():
    db = _process_db()
    db.executemany(
        "INSERT INTO processes (id, seq_order, status) VALUES (?, ?, ?)",
        [(20, 2, "active"), (30, 1, "inactive")],
    )

    OrderProcessSyncService.assign_processes(
        db,
        order_id=1,
        assignment={
            "route_id": None,
            "route_version_id": None,
            "route_name_snapshot": "",
            "processes": [
                {
                    "process_id": 20,
                    "process_version_id": 200,
                    "process_code_snapshot": "PROC-0020",
                    "process_name_snapshot": "",
                    "process_category_snapshot": "结构件",
                    "seq_order": 2,
                    "required_audit": 0,
                }
            ],
        },
    )

    assert _assigned_processes(db) == [
        {"order_id": 1, "process_id": 20, "seq_order": 2, "required_audit": 0}
    ]


def test_mobile_scan_resolver_exposes_code_parsing_seam():
    assert MobileScanResolver.extract_code({"code": " A ", "qr_text": "B"}) == "A"
    assert MobileScanResolver.parse_code('{"order_id": 1}') == {"order_id": 1}
