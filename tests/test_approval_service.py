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
    record = None
    work_record = None
    order = None
    config = None
    order_process = None
    approval_status = None
    work_record_status = None
    advanced_level = None
    rejected = False
    approved = False
    steps = []

    @staticmethod
    def find_by_id(record_id, db=None):
        return _ApprovalRepoStub.record

    @staticmethod
    def find_work_record(work_record_id, db=None):
        return _ApprovalRepoStub.work_record

    @staticmethod
    def find_order(order_id, db=None):
        return _ApprovalRepoStub.order

    @staticmethod
    def find_approval_config(process_id, db=None):
        return _ApprovalRepoStub.config

    @staticmethod
    def find_order_process(order_id, process_id, db=None):
        return _ApprovalRepoStub.order_process

    @staticmethod
    def approve(record_id, approver_id, approver_name, comment, db=None):
        _ApprovalRepoStub.approved = True
        _ApprovalRepoStub.approval_status = "approved"
        return 1

    @staticmethod
    def update_work_record_status(work_record_id, status, db=None):
        _ApprovalRepoStub.work_record_status = status
        return 1

    @staticmethod
    def advance_level(record_id, approver_id, approver_name, comment, next_level, current_level, db=None):
        _ApprovalRepoStub.advanced_level = next_level
        return 1

    @staticmethod
    def reject(record_id, approver_id, approver_name, comment, db=None):
        _ApprovalRepoStub.rejected = True
        _ApprovalRepoStub.approval_status = "rejected"
        return 1

    @staticmethod
    def insert_approval_step(approval_record_id, step_level, approver_id, approver_name,
                             approver_role, action, comment, db=None):
        _ApprovalRepoStub.steps.append({
            "approval_record_id": approval_record_id,
            "step_level": step_level,
            "approver_role": approver_role,
            "action": action,
            "comment": comment,
        })
        return len(_ApprovalRepoStub.steps)


def _install_stub(monkeypatch):
    _ApprovalRepoStub.approval_status = None
    _ApprovalRepoStub.work_record_status = None
    _ApprovalRepoStub.advanced_level = None
    _ApprovalRepoStub.rejected = False
    _ApprovalRepoStub.approved = False
    _ApprovalRepoStub.steps = []
    applied = {"command": None, "validate_policy": None}
    monkeypatch.setattr(approval_service_module, "ApprovalRepository", _ApprovalRepoStub)
    monkeypatch.setattr(
        approval_service_module.AuthRepository,
        "get_user_role_code",
        staticmethod(lambda user_id, db=None: "admin"),
    )
    monkeypatch.setattr(
        approval_service_module.BaseService,
        "transaction",
        staticmethod(lambda: _DummyTransaction()),
    )
    monkeypatch.setattr(
        approval_service_module.WorkReportWriter,
        "apply_approved_normal_report",
        staticmethod(lambda command, db, work_record_id=None, validate_policy=True: applied.update(
            command=command,
            work_record_id=work_record_id,
            validate_policy=validate_policy,
        )),
    )
    return applied


def test_handle_approve_accepts_sqlite_rows(monkeypatch):
    applied = _install_stub(monkeypatch)
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
        "user_id": 13,
        "user_name": "Worker",
        "serial_no": "SERIAL-001",
    })
    _ApprovalRepoStub.order = _row({
        "quantity": 10,
        "completed": 3,
        "deleted_at": None,
    })
    _ApprovalRepoStub.config = _row({"approval_level": 1})
    _ApprovalRepoStub.order_process = _row({"completed": 3})

    result = ApprovalService.handle(
        1,
        "approve",
        approver={"id": 99, "name": "Admin", "role": "admin"},
        comment="ok",
    )

    assert result == "approve"
    assert _ApprovalRepoStub.approval_status == "approved"
    assert _ApprovalRepoStub.work_record_status == "approved"
    assert applied["command"].order_id == 11
    assert applied["command"].process_id == 5
    assert applied["command"].user_id == 13
    assert applied["command"].effective_quantity == 1
    assert applied["command"].serial_no == "SERIAL-001"
    assert applied["work_record_id"] == 7
    assert applied["validate_policy"] is True


def test_handle_approve_advances_multilevel_sqlite_rows(monkeypatch):
    applied = _install_stub(monkeypatch)
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
        "user_id": 14,
        "user_name": "Worker 2",
        "serial_no": "",
    })
    _ApprovalRepoStub.order = _row({
        "quantity": 10,
        "completed": 0,
        "deleted_at": None,
    })
    _ApprovalRepoStub.config = _row({"approval_level": 2})
    _ApprovalRepoStub.order_process = _row({"completed": 0})

    result = ApprovalService.handle(
        2,
        "approve",
        approver={"id": 99, "name": "Admin", "role": "admin"},
        comment="level1",
    )

    assert result == "approve"
    assert _ApprovalRepoStub.advanced_level == 2
    assert _ApprovalRepoStub.approved is False
    assert _ApprovalRepoStub.work_record_status is None
    assert applied["command"] is None


def test_handle_reject_does_not_require_valid_order_state(monkeypatch):
    _install_stub(monkeypatch)
    _ApprovalRepoStub.record = _row({
        "id": 3,
        "work_record_id": 9,
        "status": "pending",
        "current_level": 1,
    })
    _ApprovalRepoStub.work_record = _row({
        "id": 9,
        "quantity": 1,
        "order_id": 13,
        "status": "pending",
        "process_id": 7,
        "user_id": 15,
        "user_name": "Worker 3",
        "serial_no": "",
    })
    _ApprovalRepoStub.order = None
    _ApprovalRepoStub.order_process = None
    _ApprovalRepoStub.config = _row({"approval_level": 1})

    result = ApprovalService.handle(
        3,
        "reject",
        approver={"id": 99, "name": "Admin", "role": "admin"},
        comment="invalid order",
    )

    assert result == "reject"
    assert _ApprovalRepoStub.rejected is True
    assert _ApprovalRepoStub.work_record_status == "rejected"
    assert _ApprovalRepoStub.steps[0]["action"] == "reject"
