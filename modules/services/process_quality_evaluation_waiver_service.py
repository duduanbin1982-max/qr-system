"""Administrative waiver policy for process quality evaluation tasks."""

from modules.repositories.process_quality_evaluation_task_repository import (
    ProcessQualityEvaluationTaskRepository,
)
from modules.services import BaseService


class ProcessQualityEvaluationWaiverService:
    HISTORICAL_WAIVER_REASONS = (
        ("completed_order_history", "已完成订单历史遗留"),
        ("historical_import", "历史数据导入异常"),
        ("worker_departed", "原评价人员已离职"),
        ("no_actual_handoff", "现场确认未发生实际交接"),
    )
    LIVE_WAIVER_REASONS = (
        ("task_generated_in_error", "评价任务错误生成"),
        ("handoff_attribution_error", "工序交接归属错误"),
        ("emergency_authorized_release", "紧急生产授权放行"),
    )

    @classmethod
    def task_disposal_summary(cls, allow_live=False):
        summary = ProcessQualityEvaluationTaskRepository.task_disposal_summary()
        summary["waiver_policy"] = {
            "can_waive_live": bool(allow_live),
            "historical_reasons": [
                {"code": code, "label": label}
                for code, label in cls.HISTORICAL_WAIVER_REASONS
            ],
            "live_reasons": [
                {"code": code, "label": label}
                for code, label in cls.LIVE_WAIVER_REASONS
            ],
        }
        return summary

    @staticmethod
    def task_audits(keyword="", page=1, per_page=100):
        return ProcessQualityEvaluationTaskRepository.list_task_audits(
            keyword=keyword, page=page, per_page=per_page
        )

    @staticmethod
    def _task_ids(value):
        if not isinstance(value, list):
            return []
        task_ids = []
        for item in value:
            try:
                task_id = int(item)
            except (TypeError, ValueError):
                continue
            if task_id > 0 and task_id not in task_ids:
                task_ids.append(task_id)
        return task_ids

    @classmethod
    def _resolve_waiver_tasks(cls, data, db):
        task_ids = cls._task_ids(data.get("task_ids"))
        order_id = data.get("order_id")
        if order_id is not None:
            try:
                order_id = int(order_id)
            except (TypeError, ValueError) as exc:
                raise ValueError("订单参数无效") from exc
            if order_id <= 0:
                raise ValueError("订单参数无效")
        if not task_ids and order_id is None:
            raise ValueError("请选择待处置的评价任务")
        if task_ids and len(task_ids) > 200:
            raise ValueError("单次最多豁免200条任务")
        if order_id is not None and not task_ids:
            task_ids = ProcessQualityEvaluationTaskRepository.pending_task_ids_for_order(
                order_id, bool(data.get("required_only", True)), db
            )
        if not task_ids:
            raise ValueError("没有可豁免的待评价任务")
        if len(task_ids) > 200:
            raise ValueError("单次最多豁免200条任务")
        tasks = ProcessQualityEvaluationTaskRepository.pending_tasks_by_ids(task_ids, db)
        if len(tasks) != len(task_ids):
            raise ValueError("所选任务包含已处理或不存在的记录，请刷新后重试")
        return task_ids, tasks

    @staticmethod
    def _task_waiver_scope(task):
        if task["order_deleted_at"] or task["order_status"] in {"completed", "cancelled"}:
            return "historical"
        return "live"

    @classmethod
    def waiver_preview(cls, data, allow_live=False):
        with BaseService.transaction() as db:
            task_ids, tasks = cls._resolve_waiver_tasks(data, db)

        scopes = {cls._task_waiver_scope(task) for task in tasks}
        has_mixed_scopes = len(scopes) > 1
        waiver_scope = "mixed" if has_mixed_scopes else next(iter(scopes))
        requires_live_permission = "live" in scopes
        orders = {}
        for task in tasks:
            order = orders.setdefault(task["order_id"], {
                "order_id": task["order_id"],
                "order_no": task["order_no"],
                "order_status": task["order_status"],
                "waiver_scope": cls._task_waiver_scope(task),
                "task_count": 0,
                "required_count": 0,
                "optional_count": 0,
            })
            order["task_count"] += 1
            count_key = "required_count" if task["is_required"] else "optional_count"
            order[count_key] += 1

        warnings = []
        if has_mixed_scopes:
            warnings.append("生产中订单与历史订单不能混合豁免，请分开选择后再操作。")
        if requires_live_permission:
            warnings.append("包含生产中或待生产订单，提交后会立即解除对应员工的报工门禁。")
        if requires_live_permission and not allow_live:
            warnings.append("当前账号没有生产中订单豁免权限。")
        required_count = sum(1 for task in tasks if task["is_required"])
        if required_count:
            warnings.append(f"本次将豁免 {required_count} 条必评任务，评价数据将永久缺失并保留审计记录。")

        return {
            "task_ids": task_ids,
            "task_count": len(tasks),
            "required_count": required_count,
            "optional_count": len(tasks) - required_count,
            "affected_worker_count": len({task["evaluator_user_id"] for task in tasks}),
            "orders": sorted(orders.values(), key=lambda item: (item["order_no"], item["order_id"])),
            "waiver_scope": waiver_scope,
            "has_mixed_scopes": has_mixed_scopes,
            "requires_live_permission": requires_live_permission,
            "can_submit": not has_mixed_scopes and (allow_live or not requires_live_permission),
            "warnings": warnings,
        }

    @classmethod
    def waive_tasks(cls, data, current_user, allow_live=False):
        reason = str(data.get("reason") or "").strip()
        if len(reason) > 500:
            raise ValueError("豁免原因不能超过500个字符")
        reason_code = str(data.get("reason_code") or "").strip()

        with BaseService.transaction() as db:
            task_ids, tasks = cls._resolve_waiver_tasks(data, db)
            waiver_scope = cls._validate_waiver_policy(
                tasks, reason_code, reason, allow_live
            )
            updated = ProcessQualityEvaluationTaskRepository.waive_tasks(
                task_ids, reason_code, reason, current_user.get("id"), db
            )
        return {
            "ok": True,
            "status": "waived",
            "count": updated,
            "task_ids": task_ids,
            "reason_code": reason_code,
            "waiver_scope": waiver_scope,
            "order_ids": sorted({task["order_id"] for task in tasks}),
        }

    @classmethod
    def _validate_waiver_policy(cls, tasks, reason_code, reason, allow_live):
        scopes = {cls._task_waiver_scope(task) for task in tasks}
        if len(scopes) != 1:
            raise ValueError("生产中订单与历史订单的评价任务必须分开处置")
        scope = scopes.pop()
        allowed_reasons = dict(
            cls.HISTORICAL_WAIVER_REASONS
            if scope == "historical"
            else cls.LIVE_WAIVER_REASONS
        )
        if reason_code not in allowed_reasons:
            raise ValueError("请选择与订单状态匹配的豁免原因类型")
        if scope == "live" and not allow_live:
            raise PermissionError("生产中或待生产订单仅允许系统管理员授权豁免")
        minimum_length = 10 if scope == "live" else 2
        if len(reason) < minimum_length:
            raise ValueError(f"豁免说明至少填写{minimum_length}个字符")
        return scope
