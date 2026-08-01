"""Policy and validation for controlled serial-number process backfill."""

from modules.domain.errors import ValidationError
from modules.repositories.scan_repository import ScanRepository
from modules.services.access_policy_service import has_permission
from modules.services.active_position_service import ActivePositionService
from modules.setting_reader import get_setting


class SerialBackfillService:
    STRICT = "strict"
    CONTROLLED = "controlled_backfill"
    SETTING_KEY = "serial_process_report_mode"
    SUBMIT_PERMISSION = "scan:serial_backfill"
    APPROVE_PERMISSION = "scan:serial_backfill_approve"

    @classmethod
    def mode(cls):
        mode = get_setting(cls.SETTING_KEY, cls.STRICT)
        return mode if mode in {cls.STRICT, cls.CONTROLLED} else cls.STRICT

    @classmethod
    def is_available(cls, user):
        return cls.mode() == cls.CONTROLLED and has_permission(
            user, cls.SUBMIT_PERMISSION
        )

    @staticmethod
    def _active_position_for_process(user, process_id):
        context = ActivePositionService.get_context(user)
        position = context.get("active_position")
        if not position:
            raise ValidationError("请先选择当前岗位")
        if int(process_id or 0) not in {
            int(value) for value in position.get("process_ids") or []
        }:
            raise ValidationError("所选工序不属于当前岗位，请重新选择")
        return position

    @classmethod
    def validate_submission(
        cls,
        order_id,
        process_id,
        serial_no,
        user,
        report_type,
        reason=None,
        actual_completed_at=None,
    ):
        if cls.mode() != cls.CONTROLLED:
            raise ValidationError("序列号跨工序补报功能未开启")
        if not has_permission(user, cls.SUBMIT_PERMISSION):
            raise ValidationError("您没有序列号跨工序补报权限")
        if report_type != "normal" or not serial_no:
            raise ValidationError("跨工序补报仅支持序列号正常报工")
        position = cls._active_position_for_process(user, process_id)

        item = ScanRepository.get_item_by_serial(serial_no)
        if not item or int(item["order_id"] or 0) != int(order_id or 0):
            raise ValidationError("序列号与订单不匹配")
        if item["status"] == "completed":
            raise ValidationError("该序列号已完成，不能再补报")
        if int(item["current_process_id"] or 0) == int(process_id or 0):
            raise ValidationError("当前工序请使用正常报工，无需提交跨工序补报")

        return {
            "submit_position_id": position["id"],
            "submit_position_name": position.get("name", ""),
        }
