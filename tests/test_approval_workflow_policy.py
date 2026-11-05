from itertools import permutations

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


@pytest.mark.parametrize("roles", list(permutations(["admin", "production_manager", "qc_inspector"])))
@pytest.mark.parametrize("level", [1, 2, 3])
@pytest.mark.parametrize("action", ["approve", "reject"])
def test_multiple_roles_record_the_matched_step_role(roles, level, action):
    decision = ApprovalWorkflow.decide(action, _config(3), level, list(roles))
    expected = ["production_manager", "qc_inspector", "admin"][level - 1]
    assert decision.current_role == expected
    assert decision.required_role == expected
    assert decision.is_final is (action == "approve" and level == 3)


@pytest.mark.parametrize("roles", ["supervisor", ["worker", "supervisor"], {"admin", "supervisor"}])
def test_legacy_alias_audit_uses_normalized_required_role(roles):
    decision = ApprovalWorkflow.decide("approve", _config(), 1, roles)
    assert decision.current_role == decision.required_role == "production_manager"
