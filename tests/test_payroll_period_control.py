"""Regression coverage for payroll period controls and adjustment guards."""

import pytest

from modules.db import get_db
from modules.services.payroll_service import PayrollWorkflowService
from test_payroll_ledger import _actors, _seed_price_and_work


def test_period_control_reports_draft_snapshot_and_adjustment_readiness(client):
    with client.application.app_context():
        db = get_db()
        preparer, _approver = _actors(db)
        worker_id, _route_id, _process_id, _worker = _seed_price_and_work(db)

        before = PayrollWorkflowService.period_control("2026-07")
        assert before["status"] == "unstarted"
        assert before["batch"] is None
        assert before["pending_exception_count"] == 0
        assert before["can_adjust"] is True
        assert before["can_regenerate"] is False

        batch = PayrollWorkflowService.create_batch("2026-07", preparer, "period-control-draft")
        control = PayrollWorkflowService.period_control("2026-07")
        assert control["status"] == "draft"
        assert control["version"] == batch["version"]
        assert control["source_cutoff_at"] == batch["source_cutoff_at"]
        assert control["can_adjust"] is True
        assert control["can_regenerate"] is True
        assert control["requires_revision"] is False

        PayrollWorkflowService.create_adjustment(preparer, {
            "employee_id": worker_id,
            "payroll_month": "2026-07",
            "adjustment_type": "bonus",
            "amount_cents": 100,
            "reason": "草稿期间追加奖金",
        })
        assert PayrollWorkflowService.batch_detail(batch["id"])["batch"]["input_changed"] is True

        regenerated = PayrollWorkflowService.regenerate(
            batch["id"], preparer, batch["row_version"]
        )
        detail = PayrollWorkflowService.batch_detail(batch["id"])
        assert regenerated["payable_wage_cents"] == 475
        assert detail["batch"]["input_changed"] is False


def test_period_control_endpoint_requires_payroll_management_access(
    client, auth_headers, worker_auth_headers
):
    denied = client.get(
        "/api/payroll/periods/2026-07/control", headers=worker_auth_headers
    )
    assert denied.status_code == 403

    response = client.get(
        "/api/payroll/periods/2026-07/control", headers=auth_headers
    )
    assert response.status_code == 200
    assert response.get_json()["status"] == "unstarted"

    invalid = client.get(
        "/api/payroll/periods/not-a-month/control", headers=auth_headers
    )
    assert invalid.status_code == 400


def test_locked_period_rejects_new_and_reversal_adjustments(client):
    with client.application.app_context():
        db = get_db()
        preparer, approver = _actors(db)
        worker_id, _route_id, _process_id, _worker = _seed_price_and_work(db)
        original = PayrollWorkflowService.create_adjustment(preparer, {
            "employee_id": worker_id,
            "payroll_month": "2026-07",
            "adjustment_type": "bonus",
            "amount_cents": 100,
            "reason": "锁定前奖金",
        })
        batch = PayrollWorkflowService.create_batch("2026-07", preparer, "period-control-locked")
        submitted = PayrollWorkflowService.submit(batch["id"], preparer, batch["row_version"])
        locked = PayrollWorkflowService.lock(batch["id"], approver, submitted["row_version"])

        control = PayrollWorkflowService.period_control("2026-07")
        assert control["status"] == "locked"
        assert control["can_adjust"] is False
        assert control["can_regenerate"] is False
        assert control["requires_revision"] is True

        with pytest.raises(ValueError, match="锁定"):
            PayrollWorkflowService.create_adjustment(preparer, {
                "employee_id": worker_id,
                "payroll_month": "2026-07",
                "adjustment_type": "allowance",
                "amount_cents": 50,
                "reason": "不应绕过锁定",
            })
        with pytest.raises(ValueError, match="锁定"):
            PayrollWorkflowService.reverse_adjustment(original["id"], preparer, "锁定后冲销")

        confirmed = PayrollWorkflowService.confirm(batch["id"], approver, locked["row_version"])
        confirmed_control = PayrollWorkflowService.period_control("2026-07")
        assert confirmed_control["status"] == "confirmed"
        assert confirmed_control["can_adjust"] is False
        with pytest.raises(ValueError, match="确认"):
            PayrollWorkflowService.create_adjustment(preparer, {
                "employee_id": worker_id,
                "payroll_month": "2026-07",
                "adjustment_type": "allowance",
                "amount_cents": 50,
                "reason": "不应绕过确认状态",
            })

        revision = PayrollWorkflowService.create_batch(
            "2026-07", preparer, "period-control-revision", "锁定后修订", confirmed["id"]
        )
        assert revision["status"] == "draft"
        revision_control = PayrollWorkflowService.period_control("2026-07")
        assert revision_control["can_adjust"] is True
        assert revision_control["can_regenerate"] is True


def test_submitted_period_reports_revision_requirement_and_rejects_adjustment(client):
    with client.application.app_context():
        db = get_db()
        preparer, _approver = _actors(db)
        worker_id, _route_id, _process_id, _worker = _seed_price_and_work(db)
        batch = PayrollWorkflowService.create_batch("2026-07", preparer, "period-control-review")
        PayrollWorkflowService.submit(batch["id"], preparer, batch["row_version"])

        control = PayrollWorkflowService.period_control("2026-07")
        assert control["status"] == "review_pending"
        assert control["can_adjust"] is False
        assert control["requires_revision"] is True
        with pytest.raises(ValueError, match="已提交复核"):
            PayrollWorkflowService.create_adjustment(preparer, {
                "employee_id": worker_id,
                "payroll_month": "2026-07",
                "adjustment_type": "bonus",
                "amount_cents": 100,
                "reason": "送审中不可直接调整",
            })


def test_legacy_imported_period_requires_revision_for_adjustments(client):
    with client.application.app_context():
        db = get_db()
        preparer, _approver = _actors(db)
        worker_id, _route_id, _process_id, _worker = _seed_price_and_work(db)
        original = PayrollWorkflowService.create_adjustment(preparer, {
            "employee_id": worker_id,
            "payroll_month": "2026-07",
            "adjustment_type": "bonus",
            "amount_cents": 100,
            "reason": "导入前调整",
        })
        batch = PayrollWorkflowService.create_batch("2026-07", preparer, "period-control-legacy")
        db.execute("UPDATE payroll_batches SET legacy_imported=1 WHERE id=?", (batch["id"],))
        db.commit()

        control = PayrollWorkflowService.period_control("2026-07")
        assert control["status"] == "draft"
        assert control["can_adjust"] is False
        assert control["can_regenerate"] is False
        assert control["requires_revision"] is True
        with pytest.raises(ValueError, match="旧版导入快照"):
            PayrollWorkflowService.create_adjustment(preparer, {
                "employee_id": worker_id,
                "payroll_month": "2026-07",
                "adjustment_type": "allowance",
                "amount_cents": 50,
                "reason": "导入后不可直接调整",
            })
        with pytest.raises(ValueError, match="旧版导入快照"):
            PayrollWorkflowService.reverse_adjustment(original["id"], preparer, "导入后不可冲销")
