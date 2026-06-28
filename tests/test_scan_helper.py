"""ScanHelperService ?????? ? ???? SQLite ?????"""

import sqlite3

import modules.services.scan_helper_service as scan_helper_module
from modules.services.scan_helper_service import ScanHelperService


def _scan_db():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute(
        "CREATE TABLE processes ("
        "id INTEGER PRIMARY KEY, name TEXT, seq_order INTEGER)"
    )
    db.execute(
        "CREATE TABLE order_processes ("
        "order_id INTEGER, process_id INTEGER, seq_order INTEGER, completed INTEGER)"
    )
    db.execute(
        "CREATE TABLE work_records ("
        "id INTEGER PRIMARY KEY, order_id INTEGER, process_id INTEGER, "
        "serial_no TEXT, user_id INTEGER, type TEXT, status TEXT)"
    )
    return db


def _add_process(db, process_id, name, seq_order, completed=0, order_id=1):
    db.execute(
        "INSERT INTO processes (id, name, seq_order) VALUES (?, ?, ?)",
        (process_id, name, seq_order),
    )
    db.execute(
        "INSERT INTO order_processes (order_id, process_id, seq_order, completed) "
        "VALUES (?, ?, ?, ?)",
        (order_id, process_id, seq_order, completed),
    )


class TestCheckDuplicateNormalReport:
    def test_serial_dup_found_returns_row(self):
        db = _scan_db()
        db.execute(
            "INSERT INTO work_records "
            "(id, order_id, process_id, serial_no, user_id, type, status) "
            "VALUES (99, 1, 10, 'SN-001', 100, 'normal', 'approved')"
        )

        result = ScanHelperService.check_duplicate_normal_report(1, 10, "SN-001", 100, db)

        assert result is not None
        assert result["id"] == 99

    def test_serial_no_dup_returns_none(self):
        db = _scan_db()

        result = ScanHelperService.check_duplicate_normal_report(1, 10, "SN-NEW", 100, db)

        assert result is None

    def test_non_serial_user_dup_found_returns_row(self):
        db = _scan_db()
        db.execute(
            "INSERT INTO work_records "
            "(id, order_id, process_id, serial_no, user_id, type, status) "
            "VALUES (42, 1, 10, NULL, 100, 'normal', 'approved')"
        )

        result = ScanHelperService.check_duplicate_normal_report(1, 10, None, 100, db)

        assert result is not None
        assert result["id"] == 42

    def test_non_serial_no_dup_returns_none(self):
        db = _scan_db()

        result = ScanHelperService.check_duplicate_normal_report(1, 10, None, 100, db)

        assert result is None


class TestIsLastProcess:
    def test_is_last_process_true(self):
        db = _scan_db()
        _add_process(db, 10, "??", 5)

        assert ScanHelperService.is_last_process(1, 10, db) is True

    def test_is_last_process_false(self):
        db = _scan_db()
        _add_process(db, 10, "??", 3)
        _add_process(db, 20, "??", 5)

        assert ScanHelperService.is_last_process(1, 10, db) is False

    def test_is_last_process_no_max_row(self):
        db = _scan_db()

        assert ScanHelperService.is_last_process(1, 999, db) is False


class TestGetPrevIncompleteProcesses:
    def test_has_prev_incomplete(self):
        db = _scan_db()
        _add_process(db, 10, "??", 1)
        _add_process(db, 20, "??", 2)
        _add_process(db, 30, "??", 3)

        result = ScanHelperService.get_prev_incomplete_processes(1, 3, db)

        assert [row["process_name"] for row in result] == ["??", "??"]

    def test_no_prev_incomplete(self):
        db = _scan_db()
        _add_process(db, 10, "??", 1)

        result = ScanHelperService.get_prev_incomplete_processes(1, 1, db)

        assert result == []


class TestCheckProcessOrder:
    def test_sequential_blocks_skip(self, monkeypatch):
        db = _scan_db()
        _add_process(db, 10, "??", 1)
        _add_process(db, 30, "??", 3)
        monkeypatch.setattr(scan_helper_module, "get_setting", lambda key, default=None: "sequential")

        error, status = ScanHelperService.check_process_order(1, 3, db)

        assert error is not None
        assert "??" in error["error"]
        assert status == 400

    def test_out_of_order_allows_skip(self, monkeypatch):
        db = _scan_db()
        _add_process(db, 10, "??", 1)
        _add_process(db, 30, "??", 3)
        monkeypatch.setattr(scan_helper_module, "get_setting", lambda key, default=None: "out_of_order")

        error, status = ScanHelperService.check_process_order(1, 3, db)

        assert error is None
        assert status is None

    def test_sequential_no_prev_ok(self, monkeypatch):
        db = _scan_db()
        _add_process(db, 10, "??", 1)
        monkeypatch.setattr(scan_helper_module, "get_setting", lambda key, default=None: "sequential")

        error, status = ScanHelperService.check_process_order(1, 1, db)

        assert error is None
        assert status is None


class TestGetOrderProcesses:
    def test_returns_processes_with_ids_and_names(self):
        db = _scan_db()
        _add_process(db, 10, "??", 1, completed=5)
        _add_process(db, 20, "??", 2, completed=3)

        result = ScanHelperService.get_order_processes(1, db)

        assert [row["process_id"] for row in result] == [10, 20]
        assert [row["process_name"] for row in result] == ["??", "??"]
