"""Payroll read scopes and the employee-safe confirmed ledger projection."""

from modules.domain.errors import AuthorizationError, NotFoundError, ValidationError
from modules.domain.payroll_policy import cents_to_yuan
from modules.repositories.payroll_repository import PayrollRepository


class PayrollReadService:
    @staticmethod
    def employee_scope(actor_id, requested_employee_id=None, *, can_view_all=False):
        """Resolve omitted filters without letting an employee widen their scope."""
        requested_id = None
        if requested_employee_id not in (None, ""):
            try:
                requested_id = int(requested_employee_id)
            except (TypeError, ValueError) as exc:
                raise ValidationError("员工 ID 无效") from exc
            if requested_id <= 0:
                raise ValidationError("员工 ID 无效")
        if can_view_all:
            return requested_id
        if not actor_id or (requested_id is not None and requested_id != actor_id):
            raise AuthorizationError("无权限查看他人工资")
        return actor_id

    @staticmethod
    def confirmed_employee_detail(batch_id, employee_id):
        """Return own frozen amounts without global batch totals or workflow data."""
        if not employee_id:
            raise AuthorizationError("当前用户无员工身份")
        batch = PayrollRepository.get_batch(batch_id)
        if not batch:
            raise NotFoundError("工资批次不存在")
        if batch["status"] != "confirmed":
            raise AuthorizationError("仅可查看本人已确认工资")
        lines = PayrollRepository.list_lines(batch_id, employee_id)
        if not lines:
            raise NotFoundError("工资明细不存在")
        visible_batch = {
            key: batch[key]
            for key in ("id", "payroll_month", "version", "status", "confirmed_at")
        }
        for key in (
            "normal_wage_cents", "rework_wage_cents", "bonus_cents",
            "allowance_cents", "deduction_cents", "payable_wage_cents",
        ):
            visible_batch[key] = sum(line[key] for line in lines)
            visible_batch[key.replace("_cents", "_yuan")] = cents_to_yuan(visible_batch[key])
        return {
            "batch": visible_batch,
            "lines": lines,
            "details": PayrollRepository.list_details(batch_id, employee_id),
            "exceptions": [],
            "events": [],
        }
