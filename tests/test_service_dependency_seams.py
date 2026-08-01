import pytest

from modules.services.approval_service import ApprovalService
from modules.services.material_service import MaterialService
from modules.services.order_completion_service import OrderCompletionService
from modules.services.order_service import OrderService
from modules.services.process_order_service import ProcessOrderService
from modules.services.process_quality_evaluation_service import (
    ProcessQualityEvaluationService,
)
from modules.services.work_report_writer import WorkReportWriter


@pytest.mark.parametrize(
    ("service", "attribute", "resolver"),
    [
        (ApprovalService, "approval_repository", "_approval_repository"),
        (ApprovalService, "auth_repository", "_auth_repository"),
        (ApprovalService, "process_repository", "_process_repository"),
        (ApprovalService, "role_repository", "_role_repository"),
        (ApprovalService, "work_report_writer", "_work_report_writer"),
        (ApprovalService, "serial_backfill_service", "_serial_backfill_service"),
        (ApprovalService, "unit_of_work", "_unit_of_work"),
        (MaterialService, "repository", "_repository"),
        (MaterialService, "consumption_repository", "_consumption_repository"),
        (MaterialService, "unit_of_work", "_unit_of_work"),
        (OrderCompletionService, "repository", "_repository"),
        (OrderCompletionService, "audit_repository", "_audit_repository"),
        (OrderCompletionService, "unit_of_work", "_unit_of_work"),
        (OrderService, "repository", "_repository"),
        (OrderService, "material_repository", "_material_repository"),
        (OrderService, "material_snapshot_service", "_material_snapshot_service"),
        (OrderService, "process_sync_service", "_process_sync_service"),
        (OrderService, "completion_service", "_completion_service"),
        (OrderService, "unit_of_work", "_unit_of_work"),
        (ProcessQualityEvaluationService, "repository", "_repository"),
        (ProcessQualityEvaluationService, "task_repository", "_task_repository"),
        (ProcessQualityEvaluationService, "settings_repository", "_settings_repository"),
        (
            ProcessQualityEvaluationService,
            "legacy_handoff_adapter",
            "_legacy_handoff_adapter",
        ),
        (ProcessQualityEvaluationService, "unit_of_work", "_unit_of_work"),
        (WorkReportWriter, "material_service", "_material_service"),
        (WorkReportWriter, "scan_repository", "_scan_repository"),
        (
            WorkReportWriter,
            "inventory_auto_inbound_service",
            "_inventory_auto_inbound_service",
        ),
        (WorkReportWriter, "order_completion_service", "_order_completion_service"),
        (WorkReportWriter, "scan_helper_service", "_scan_helper_service"),
        (WorkReportWriter, "quality_management_service", "_quality_management_service"),
        (WorkReportWriter, "quality_evaluation_service", "_quality_evaluation_service"),
        (WorkReportWriter, "unit_of_work", "_unit_of_work"),
    ],
)
def test_declared_service_dependencies_can_be_replaced(
    monkeypatch, service, attribute, resolver
):
    replacement = object()
    monkeypatch.setattr(service, attribute, replacement)

    assert getattr(service, resolver)() is replacement


@pytest.mark.parametrize(
    ("service", "attribute", "resolver"),
    [
        (ApprovalService, "permission_checker", "_permission_checker"),
        (OrderService, "setting_reader", "_setting_reader"),
    ],
)
def test_callable_dependencies_are_not_bound_as_methods(
    monkeypatch, service, attribute, resolver
):
    replacement = lambda *args: args
    monkeypatch.setattr(service, attribute, replacement)

    assert getattr(service, resolver)() is replacement


def test_process_order_policy_uses_replacement_setting_reader(monkeypatch):
    values = {
        "process_order_mode": ProcessOrderService.OUT_OF_ORDER,
        "limit_by_prev_process": "1",
    }
    monkeypatch.setattr(
        ProcessOrderService,
        "setting_reader",
        lambda key, default=None: values.get(key, default),
    )

    assert ProcessOrderService.policy() == {
        "mode": ProcessOrderService.OUT_OF_ORDER,
        "configured_previous_limit": True,
        "effective_previous_limit": False,
    }


def test_order_completion_uses_replacement_repository(monkeypatch):
    calls = []

    class RepositoryStub:
        @staticmethod
        def find_snapshot(order_id, db=None):
            calls.append(("find", order_id, db))
            return {
                "id": order_id,
                "quantity": 10,
                "qr_mode": "order",
                "final_process_completed": 4,
                "process_total": 1,
                "completed_processes": 0,
                "pending_approvals": 0,
                "pending_quality_gates": 0,
                "completed": 4,
                "status": "producing",
                "deleted_at": None,
                "completed_items": 0,
                "item_total": 0,
                "incomplete_items": 0,
            }

    monkeypatch.setattr(OrderCompletionService, "repository", RepositoryStub)

    result = OrderCompletionService.reconcile(7, db="transaction")

    assert calls == [("find", 7, "transaction")]
    assert result["found"] is True
    assert result["changed"] is False
