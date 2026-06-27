from modules.services.mobile_scan_service import MobileScanService
from modules.services.order_process_sync_service import OrderProcessSyncService


class _FakeRow(dict):
    def __getitem__(self, key):
        return dict.__getitem__(self, key)


class _FakeDb:
    def __init__(self):
        self.calls = []
        self.fetchone_result = None

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        if "FROM process_route_items" in sql:
            return self
        if "FROM processes WHERE status = 'active'" in sql:
            return self
        if "SELECT seq_order FROM processes" in sql:
            self.fetchone_result = _FakeRow(seq_order=7)
            return self
        return self

    def fetchall(self):
        sql, _ = self.calls[-1]
        if "FROM process_route_items" in sql:
            return [_FakeRow(process_id=10, seq_order=1, required_audit=0)]
        if "FROM processes WHERE status = 'active'" in sql:
            return [_FakeRow(id=20, seq_order=2)]
        return []

    def fetchone(self):
        return self.fetchone_result


def test_order_process_assignment_uses_route_items_when_route_selected():
    db = _FakeDb()

    OrderProcessSyncService.assign_processes(db, order_id=1, route_id=2, process_ids=None)

    assert any("FROM process_route_items" in sql for sql, _ in db.calls)
    assert any("required_audit" in sql and "INSERT INTO order_processes" in sql for sql, _ in db.calls)


def test_order_process_assignment_falls_back_to_active_processes():
    db = _FakeDb()

    OrderProcessSyncService.assign_processes(db, order_id=1, route_id=None, process_ids=None)

    assert any("FROM processes WHERE status = 'active'" in sql for sql, _ in db.calls)
    assert any("INSERT INTO order_processes" in sql for sql, _ in db.calls)


def test_mobile_scan_extract_code_prefers_code_then_qr_text():
    assert MobileScanService._extract_code({"code": " A ", "qr_text": "B"}) == "A"
    assert MobileScanService._extract_code({"code": "", "qr_text": " B "}) == "B"


def test_mobile_scan_parse_code_ignores_plain_text():
    assert MobileScanService._parse_code("plain-serial") is None
    assert MobileScanService._parse_code('{"order_id": 1, "serial_no": "SN1"}') == {
        "order_id": 1,
        "serial_no": "SN1",
    }
