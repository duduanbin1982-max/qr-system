import sqlite3

from modules.services.mobile_scan_resolver import MobileScanResolver
from modules.services.mobile_scan_service import MobileScanService
from modules.services.order_process_sync_service import OrderProcessSyncService


def _process_db():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute(
        "CREATE TABLE process_route_items ("
        "route_id INTEGER, process_id INTEGER, seq_order INTEGER, required_audit INTEGER)"
    )
    db.execute(
        "CREATE TABLE processes ("
        "id INTEGER PRIMARY KEY, seq_order INTEGER, status TEXT)"
    )
    db.execute(
        "CREATE TABLE order_processes ("
        "order_id INTEGER, process_id INTEGER, seq_order INTEGER, required_audit INTEGER DEFAULT 0)"
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
        "INSERT INTO process_route_items (route_id, process_id, seq_order, required_audit) "
        "VALUES (2, 10, 1, 1)"
    )

    OrderProcessSyncService.assign_processes(db, order_id=1, route_id=2, process_ids=None)

    assert _assigned_processes(db) == [
        {"order_id": 1, "process_id": 10, "seq_order": 1, "required_audit": 1}
    ], "route assignment should preserve required_audit from route items"


def test_order_process_assignment_falls_back_to_active_processes():
    db = _process_db()
    db.executemany(
        "INSERT INTO processes (id, seq_order, status) VALUES (?, ?, ?)",
        [(20, 2, "active"), (30, 1, "inactive")],
    )

    OrderProcessSyncService.assign_processes(db, order_id=1, route_id=None, process_ids=None)

    assert _assigned_processes(db) == [
        {"order_id": 1, "process_id": 20, "seq_order": 2, "required_audit": 0}
    ], "fallback assignment should include only active processes"


def test_mobile_scan_resolver_exposes_code_parsing_seam():
    assert MobileScanResolver.extract_code({"code": " A ", "qr_text": "B"}) == "A"
    assert MobileScanResolver.parse_code('{"order_id": 1}') == {"order_id": 1}


def test_mobile_scan_extract_code_prefers_code_then_qr_text():
    assert MobileScanService._extract_code({"code": " A ", "qr_text": "B"}) == "A", "explicit code should win over qr_text"
    assert MobileScanService._extract_code({"code": "", "qr_text": " B "}) == "B", "qr_text should be trimmed when code is blank"


def test_mobile_scan_parse_code_ignores_plain_text():
    assert MobileScanService._parse_code("plain-serial") is None, "plain serial text should not be treated as JSON QR payload"
    assert MobileScanService._parse_code('{"order_id": 1, "serial_no": "SN1"}') == {
        "order_id": 1,
        "serial_no": "SN1",
    }, "JSON QR payload should parse into a dict"
