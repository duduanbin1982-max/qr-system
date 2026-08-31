import sqlite3

import pytest

from factories import (
    WORKER_HASH,
    bind_order_process_versions,
    create_order,
    create_process_route,
    ensure_process,
    ensure_user,
)
from modules.db import get_db
from modules.domain.payroll_policy import PayrollConflictError, work_amount_cents
from modules.services.payroll_service import PayrollWorkflowService
from modules.services.price_version_service import PriceVersionService


def _actors(db):
    preparer_id = ensure_user(db, "payroll-preparer", "hash", "工资制单员", "admin", "PAY-PREP")
    approver_id = ensure_user(db, "payroll-approver", "hash", "工资审批员", "admin", "PAY-APP")
    return (
        {"id": preparer_id, "name": "工资制单员", "username": "payroll-preparer"},
        {"id": approver_id, "name": "工资审批员", "username": "payroll-approver"},
    )


def _exact_binding(db, route_id, process_id):
    return db.execute(
        "SELECT route_version.id AS route_version_id,"
        "item.process_version_id,route_version.name AS route_name,"
        "route_version.content_digest AS route_content_digest,"
        "process_version.name AS process_name,"
        "process_version.content_digest AS process_content_digest "
        "FROM process_routes route "
        "JOIN process_route_versions route_version "
        "ON route_version.id=route.current_effective_version_id "
        "JOIN process_route_version_items item "
        "ON item.route_version_id=route_version.id AND item.process_id=? "
        "JOIN process_versions process_version "
        "ON process_version.id=item.process_version_id WHERE route.id=?",
        (process_id, route_id),
    ).fetchone()


def _seed_price_and_work(
    db,
    created_at="2026-07-01 07:00:00",
    with_price=True,
    work_type="normal",
    configure_rework_rate=True,
):
    process_id = ensure_process(db, "工资测试工序")
    route_id = create_process_route(db, [process_id], "工资测试路线")
    worker_id = ensure_user(db, "payroll-worker", WORKER_HASH, "工资测试员工", "worker", "PAY-WORK")
    order_id = create_order(db, [process_id], quantity=20, product_code="PAY-PRODUCT")
    db.execute("UPDATE orders SET route_id=? WHERE id=?", (route_id, order_id))
    bind_order_process_versions(db, order_id)
    binding = _exact_binding(db, route_id, process_id)
    db.execute(
        "INSERT INTO work_records "
        "(order_id,process_id,process_version_id,process_name_snapshot,user_id,type,"
        "quantity,status,route_id,route_version_id,route_name_snapshot,created_at) "
        "VALUES (?,?,?,?,?,?,?,'approved',?,?,?,?)",
        (
            order_id,
            process_id,
            binding["process_version_id"],
            binding["process_name"],
            worker_id,
            work_type,
            3,
            route_id,
            binding["route_version_id"],
            binding["route_name"],
            created_at,
        ),
    )
    db.commit()
    actor = {"id": worker_id, "name": "工资测试员工"}
    if with_price:
        admin = {"id": 1, "name": "工价制单员"}
        version = PriceVersionService.create({
            "route_id": route_id,
            "route_version_id": binding["route_version_id"],
            "process_id": process_id,
            "process_version_id": binding["process_version_id"],
            "expected_route_content_digest": binding["route_content_digest"],
            "expected_process_content_digest": binding["process_content_digest"],
            "normal_unit_price": "1.25",
            "valid_from": "2026-07-01",
            "rework_rate_percent": 50 if work_type == "rework" and configure_rework_rate else None,
            "idempotency_key": (
                f"payroll-price-{binding['route_version_id']}-"
                f"{binding['process_version_id']}"
            ),
        }, admin)
        # Approve with a different identity to exercise the two-person rule.
        PriceVersionService.approve(version["id"], {"id": 2, "name": "工价审批员"}, version["row_version"])
    return worker_id, route_id, process_id, actor


def test_fixed_point_rounding_and_reporting_boundary():
    assert work_amount_cents(3, 12500) == 375
    assert work_amount_cents(1, 1) == 0
    with pytest.raises(ValueError):
        work_amount_cents(1, 10000, 10001)


def test_payroll_batch_is_idempotent_and_confirms_with_two_actors(client):
    with client.application.app_context():
        db = get_db()
        preparer, approver = _actors(db)
        worker_id, _route_id, _process_id, _ = _seed_price_and_work(db)
        batch = PayrollWorkflowService.create_batch("2026-07", preparer, "payroll-test-1")
        assert batch["status"] == "draft"
        assert batch["payable_wage_cents"] == 375
        duplicate = PayrollWorkflowService.create_batch("2026-07", preparer, "payroll-test-1")
        assert duplicate["id"] == batch["id"]
        submitted = PayrollWorkflowService.submit(batch["id"], preparer, batch["row_version"])
        locked = PayrollWorkflowService.lock(batch["id"], approver, submitted["row_version"])
        confirmed = PayrollWorkflowService.confirm(batch["id"], approver, locked["row_version"])
        assert confirmed["status"] == "confirmed"
        mine = PayrollWorkflowService.my_payroll({"id": worker_id}, "2026-07")
        assert mine["lines"][0]["payable_wage_cents"] == 375
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE payroll_detail_lines SET amount_cents=1 WHERE batch_id=?", (batch["id"],))


def test_missing_price_requires_exception_and_dual_approval(client):
    with client.application.app_context():
        db = get_db()
        preparer, approver = _actors(db)
        _worker_id, _route_id, _process_id, _ = _seed_price_and_work(db, with_price=False)
        batch = PayrollWorkflowService.create_batch("2026-07", preparer, "payroll-exception-1")
        assert batch["status"] == "exceptions_pending"
        exception = PayrollWorkflowService.batch_detail(batch["id"])["events"]
        rows = db.execute("SELECT * FROM payroll_exceptions WHERE batch_id=?", (batch["id"],)).fetchall()
        assert len(rows) == 1
        exception_id = rows[0]["id"]
        PayrollWorkflowService.propose_exception(exception_id, preparer, {
            "proposed_price_micros": 10000,
            "resolution_reason": "人工核定测试工价",
        })
        with pytest.raises(ValueError, match="不同"):
            PayrollWorkflowService.approve_exception(exception_id, preparer)
        PayrollWorkflowService.approve_exception(exception_id, approver)
        regenerated = PayrollWorkflowService.regenerate(batch["id"], preparer, batch["row_version"])
        assert regenerated["status"] == "draft"
        assert regenerated["payable_wage_cents"] == 300


def test_zero_price_is_an_exception_and_cannot_be_manually_confirmed_as_zero(client):
    with client.application.app_context():
        db = get_db()
        preparer, _approver = _actors(db)
        _worker_id, route_id, process_id, _ = _seed_price_and_work(
            db, with_price=False
        )
        db.execute(
            """
            INSERT INTO route_price_versions (
                route_id,route_version_id,process_id,process_version_id,
                normal_unit_price_micros,valid_from,status,
                created_by_name,approved_by_name,approved_at
            ) VALUES (?,?,?,?,0,'2026-07-01 00:00:00','approved',
                      'legacy','legacy',datetime('now'))
            """,
            (
                route_id,
                _exact_binding(db, route_id, process_id)["route_version_id"],
                process_id,
                _exact_binding(db, route_id, process_id)["process_version_id"],
            ),
        )
        db.commit()

        batch = PayrollWorkflowService.create_batch(
            "2026-07", preparer, "payroll-zero-price-1"
        )
        exception = db.execute(
            "SELECT * FROM payroll_exceptions WHERE batch_id=?",
            (batch["id"],),
        ).fetchone()
        assert batch["status"] == "exceptions_pending"
        assert batch["priced_record_count"] == 0
        assert exception["exception_type"] == "zero_price"
        with pytest.raises(ValueError, match="大于 0"):
            PayrollWorkflowService.propose_exception(
                exception["id"],
                preparer,
                {
                    "proposed_price_micros": 0,
                    "resolution_reason": "零工价不得直接通过",
                },
            )


def test_reporting_month_uses_0700_boundary(client):
    with client.application.app_context():
        db = get_db()
        preparer, _approver = _actors(db)
        _seed_price_and_work(db, created_at="2026-07-01 06:59:59")
        june = PayrollWorkflowService.create_batch("2026-06", preparer, "payroll-boundary-june")
        july = PayrollWorkflowService.create_batch("2026-07", preparer, "payroll-boundary-july")
        assert june["source_record_count"] == 1
        assert july["source_record_count"] == 0


def test_same_type_adjustments_are_append_only_and_reversible(client):
    with client.application.app_context():
        db = get_db()
        preparer, _approver = _actors(db)
        worker_id = ensure_user(db, "payroll-adjust-worker", WORKER_HASH, "调整员工", "worker", "PAY-ADJ")
        first = PayrollWorkflowService.create_adjustment(preparer, {
            "employee_id": worker_id, "payroll_month": "2026-07", "adjustment_type": "bonus",
            "amount_cents": 100, "reason": "第一笔奖金",
        })
        second = PayrollWorkflowService.create_adjustment(preparer, {
            "employee_id": worker_id, "payroll_month": "2026-07", "adjustment_type": "bonus",
            "amount_cents": 200, "reason": "第二笔奖金",
        })
        assert first["id"] != second["id"]
        reversal = PayrollWorkflowService.reverse_adjustment(first["id"], preparer, "冲销第一笔")
        rows = db.execute(
            "SELECT amount_cents,reversal_of_id FROM payroll_adjustments WHERE employee_id=? ORDER BY id",
            (worker_id,),
        ).fetchall()
        assert len(rows) == 3
        assert rows[-1]["reversal_of_id"] == first["id"]
        assert reversal["reversal_of_id"] == first["id"]


def test_manual_rework_rate_resolution_persists_into_revision(client):
    with client.application.app_context():
        db = get_db()
        preparer, approver = _actors(db)
        _seed_price_and_work(
            db, work_type="rework", configure_rework_rate=False
        )
        batch = PayrollWorkflowService.create_batch(
            "2026-07", preparer, "payroll-rework-rate-1"
        )
        assert batch["status"] == "exceptions_pending"
        exception = db.execute(
            "SELECT * FROM payroll_exceptions WHERE batch_id=?",
            (batch["id"],),
        ).fetchone()
        assert exception["exception_type"] == "missing_rework_rate"

        PayrollWorkflowService.propose_exception(
            exception["id"],
            preparer,
            {
                "proposed_rework_rate_basis_points": 5000,
                "resolution_reason": "按已审批返工倍率 50%",
            },
        )
        PayrollWorkflowService.approve_exception(exception["id"], approver)
        resolution = db.execute(
            "SELECT * FROM payroll_work_price_resolutions WHERE work_record_id=?",
            (exception["work_record_id"],),
        ).fetchone()
        assert resolution["price_version_id"] is not None
        assert resolution["override_rework_rate_basis_points"] == 5000

        regenerated = PayrollWorkflowService.regenerate(
            batch["id"], preparer, batch["row_version"]
        )
        assert regenerated["status"] == "draft"
        assert regenerated["payable_wage_cents"] == 188
        submitted = PayrollWorkflowService.submit(
            batch["id"], preparer, regenerated["row_version"]
        )
        locked = PayrollWorkflowService.lock(
            batch["id"], approver, submitted["row_version"]
        )
        confirmed = PayrollWorkflowService.confirm(
            batch["id"], approver, locked["row_version"]
        )
        revision = PayrollWorkflowService.create_batch(
            "2026-07",
            preparer,
            "payroll-rework-rate-revision",
            "验证人工核定跨版本复用",
            confirmed["id"],
        )
        assert revision["status"] == "draft"
        assert revision["exception_count"] == 0
        assert revision["payable_wage_cents"] == 188


def test_idempotency_key_cannot_be_reused_for_different_month(client):
    with client.application.app_context():
        db = get_db()
        preparer, _approver = _actors(db)
        PayrollWorkflowService.create_batch("2026-07", preparer, "same-payroll-key")
        with pytest.raises(PayrollConflictError, match="幂等键"):
            PayrollWorkflowService.create_batch("2026-08", preparer, "same-payroll-key")
