"""Pure decisions for multi-level work-report approval."""

from dataclasses import dataclass

from modules.domain.errors import ConflictError, ValidationError


ROLE_ALIASES = {
    "supervisor": "production_manager",
    "quality": "qc_inspector",
}
DEFAULT_APPROVER_ROLE = "admin"


@dataclass(frozen=True)
class ApprovalDecision:
    action: str
    current_level: int
    current_role: str
    required_role: str
    is_final: bool
    next_level: int | None
    step_action: str


class ApprovalWorkflow:
    """Validate approval state and determine the next workflow transition."""

    @staticmethod
    def normalize_role_code(role_code):
        code = (role_code or "").strip().lower()
        if not code:
            return ""
        return ROLE_ALIASES.get(code, code)

    @classmethod
    def approval_roles_from_config(cls, config):
        if not config or not config.get("require_approval", 1):
            return [DEFAULT_APPROVER_ROLE]
        try:
            approval_level = int(config.get("approval_level") or 1)
        except (TypeError, ValueError) as exc:
            raise ValidationError("审批级别必须为 1 到 3 级") from exc
        if approval_level < 1 or approval_level > 3:
            raise ValidationError("审批级别必须为 1 到 3 级")

        configured_roles = [
            cls.normalize_role_code(config.get("approver_role") or DEFAULT_APPROVER_ROLE),
            cls.normalize_role_code(config.get("approver_role_2")),
            cls.normalize_role_code(config.get("approver_role_3")),
        ]
        roles = []
        last_role = DEFAULT_APPROVER_ROLE
        for index in range(approval_level):
            role = configured_roles[index] or last_role or DEFAULT_APPROVER_ROLE
            roles.append(role)
            last_role = role
        return roles

    @staticmethod
    def validate_pending(record_status, work_record_status):
        if record_status != "pending":
            raise ConflictError("审批记录已处理，请勿重复操作")
        if work_record_status == "approved":
            raise ConflictError("报工记录已审批，请勿重复操作")

    @staticmethod
    def validate_action(action):
        if action not in {"approve", "reject"}:
            raise ValidationError("审批操作必须是通过或驳回")

    @classmethod
    def decide(cls, action, config, current_level, current_role, role_names=None):
        cls.validate_action(action)
        roles = cls.approval_roles_from_config(config)
        try:
            level = int(current_level or 1)
        except (TypeError, ValueError) as exc:
            raise ValidationError("审批级别配置无效") from exc
        if level < 1 or level > len(roles):
            raise ValidationError("审批级别配置无效")

        normalized_role = cls.normalize_role_code(current_role)
        required_role = roles[level - 1]
        if normalized_role != required_role:
            names = role_names or {}
            raise ConflictError(
                f"当前审批步骤需要“{names.get(required_role, required_role)}”角色处理"
            )

        is_final = action == "approve" and level >= len(roles)
        return ApprovalDecision(
            action=action,
            current_level=level,
            current_role=normalized_role,
            required_role=required_role,
            is_final=is_final,
            next_level=level + 1 if action == "approve" and not is_final else None,
            step_action=("approve" if is_final else "advance") if action == "approve" else "reject",
        )

    @staticmethod
    def validate_quantity(process_completed, report_quantity, order_quantity):
        completed = process_completed or 0
        if completed + report_quantity > order_quantity:
            raise ConflictError(
                f"审批后工序完成数量({completed}+{report_quantity})"
                f"将超过订单数量({order_quantity})"
            )
