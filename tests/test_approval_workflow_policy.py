import pytest

from modules.domain.approval_workflow import ApprovalWorkflow
from modules.domain.errors import ConflictError, ValidationError


def _config(level=2):
    return {
        "require_approval": 1,
        "approval_level": level,
        "approver_role": "production_manager",
        "approver_role_2": "qc_inspector",
        "approver_role_3": "admin",
    }


def test_approval_workflow_normalizes_legacy_role_aliases():
    assert ApprovalWorkflow.normalize_role_code("supervisor") == "production_manager"
    assert ApprovalWorkflow.normalize_role_code("quality") == "qc_inspector"


def test_approval_workflow_advances_intermediate_level():
    decision = ApprovalWorkflow.decide(
        "approve", _config(), 1, "production_manager"
    )

    assert decision.is_final is False
    assert decision.next_level == 2
    assert decision.step_action == "advance"


def test_approval_workflow_finalizes_last_level():
    decision = ApprovalWorkflow.decide(
        "approve", _config(), 2, "qc_inspector"
    )

    assert decision.is_final is True
    assert decision.next_level is None
    assert decision.step_action == "approve"


def test_approval_workflow_rejects_wrong_role():
    with pytest.raises(ConflictError, match="生产主管"):
        ApprovalWorkflow.decide(
            "approve",
            _config(),
            1,
            "worker",
            {"production_manager": "生产主管"},
        )


def test_approval_workflow_rejects_invalid_level():
    with pytest.raises(ValidationError, match="审批级别配置无效"):
        ApprovalWorkflow.decide("approve", _config(), 3, "admin")


def test_approval_workflow_checks_quantity_invariant():
    with pytest.raises(ConflictError, match="将超过订单数量"):
        ApprovalWorkflow.validate_quantity(9, 2, 10)
