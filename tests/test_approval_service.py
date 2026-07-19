import sqlite3

import modules.services.approval_service as approval_service_module
from modules.services.approval_service import ApprovalService


def _row(data):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    select_sql = ", ".join(f"? AS {key}" for key in data)
    return conn.execute("SELECT " + select_sql, tuple(data.values())).fetchone()


class _DummyTransaction:
    def __enter__(self):
        return object()

    def __exit__(self, exc_type, exc, traceback):
        return False


class _ApprovalRepoStub:
    calls = []
    record = None
    work_record = None
    order = None
    config = None

    @staticmethod
    def find_by_id(record_id):
        return _ApprovalRepoStub.record

    @staticmethod
    def find_work_record(work_record_id):
        return _ApprovalRepoStub.work_record

    @staticmethod
    def find_order(order_id):
        return _ApprovalRepoStub.order

    @staticmethod
    def find_approval_config(process_id):
        return _ApprovalRepoStub.config

    @staticmethod
    def approve(record_id, approver_id, approver_name, comment, db=None):
        _ApprovalRepoStub.calls.append(("approve", record_id, approver_id, approver_name, comment))

    @staticmethod
    def update_work_record_status(work_record_id, status, db=None):
        _ApprovalRepoStub.calls.append(("update_work_record_status", work_record_id, status))

    @staticmethod
    def increment_order_completed(order_id, quantity, db=None):
        _ApprovalRepoStub.calls.append(("increment_order_completed", order_id, quantity))

    @staticmethod
    def advance_level(record_id, approver_id, approver_name, comment, next_level, db=None):
        _ApprovalRepoStub.calls.append(("advance_level", record_id, next_level))

    @staticmethod
    def reject(record_id, approver_id, approver_name, comment, db=None):
        _ApprovalRepoStub.calls.append(("reject", record_id, approver_id, approver_name, comment))


def _install_stub(monkeypatch):
    _ApprovalRepoStub.calls = []
    monkeypatch.setattr(approval_service_module, "ApprovalRepository", _ApprovalRepoStub)
    monkeypatch.setattr(
        approval_service_module.BaseService,
        "transaction",
        staticmethod(lambda: _DummyTransaction()),
    )


def test_handle_approve_accepts_sqlite_rows(monkeypatch):
    _install_stub(monkeypatch)
    _ApprovalRepoStub.record = _row({
        "id": 1,
        "work_record_id": 7,
        "status": "pending",
        "current_level": 1,
    })
    _ApprovalRepoStub.work_record = _row({
        "id": 7,
        "quantity": 2,
        "order_id": 11,
        "status": "pending",
        "process_id": 5,
    })
    _ApprovalRepoStub.order = _row({
        "quantity": 10,
        "completed": 3,
        "deleted_at": None,
    })
    _ApprovalRepoStub.config = _row({"approval_level": 1})

    result = ApprovalService.handle(
        1,
        "approve",
        approver={"id": 99, "name": "Admin"},
        comment="ok",
    )

    assert result == "approve"
    assert _ApprovalRepoStub.calls == [
        ("approve", 1, 99, "Admin", "ok"),
        ("update_work_record_status", 7, "approved"),
        ("increment_order_completed", 11, 2),
    ]


def test_handle_approve_advances_multilevel_sqlite_rows(monkeypatch):
    _install_stub(monkeypatch)
    _ApprovalRepoStub.record = _row({
        "id": 2,
        "work_record_id": 8,
        "status": "pending",
        "current_level": 1,
    })
    _ApprovalRepoStub.work_record = _row({
        "id": 8,
        "quantity": 1,
        "order_id": 12,
        "status": "pending",
        "process_id": 6,
    })
    _ApprovalRepoStub.order = _row({
        "quantity": 10,
        "completed": 0,
        "deleted_at": None,
    })
    _ApprovalRepoStub.config = _row({"approval_level": 2})

    result = ApprovalService.handle(
        2,
        "approve",
        approver={"id": 99, "name": "Admin"},
        comment="level1",
    )

    assert result == "approve"
    assert _ApprovalRepoStub.calls == [("advance_level", 2, 2)]
