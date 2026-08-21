"""Work report command used across scan and approval workflows."""

from dataclasses import dataclass


REPORT_TYPES = {"normal", "scrap", "rework"}
REPORT_SOURCES = {"standard", "serial_backfill"}


@dataclass(frozen=True)
class WorkReportCommand:
    report_type: str
    order_id: int
    process_id: int
    user_id: int
    user_name: str
    quantity: int
    remark: str = ""
    serial_no: str | None = None
    need_approval: bool = False
    report_source: str = "standard"
    actual_completed_at: str | None = None
    backfill_reason: str = ""
    submit_position_id: int | None = None
    submit_position_name: str = ""

    def __post_init__(self):
        report_type = (self.report_type or "normal").strip().lower()
        if report_type not in REPORT_TYPES:
            raise ValueError("报工类型不正确")
        if not self.order_id or not self.process_id or not self.user_id:
            raise ValueError("缺少报工身份信息")
        try:
            quantity = int(self.quantity)
        except (TypeError, ValueError) as exc:
            raise ValueError("报工数量必须为整数") from exc
        if quantity <= 0:
            raise ValueError("报工数量必须大于 0")

        serial_no = (self.serial_no or "").strip() or None
        report_source = (self.report_source or "standard").strip().lower()
        if report_source not in REPORT_SOURCES:
            raise ValueError("报工来源不正确")
        actual_completed_at = (self.actual_completed_at or "").strip() or None
        backfill_reason = (self.backfill_reason or "").strip()
        if report_source == "serial_backfill":
            if report_type != "normal" or not serial_no:
                raise ValueError("跨工序补报仅支持序列号正常报工")
        object.__setattr__(self, "report_type", report_type)
        object.__setattr__(self, "order_id", int(self.order_id))
        object.__setattr__(self, "process_id", int(self.process_id))
        object.__setattr__(self, "user_id", int(self.user_id))
        object.__setattr__(self, "user_name", (self.user_name or "").strip())
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "remark", (self.remark or "").strip())
        object.__setattr__(self, "serial_no", serial_no)
        object.__setattr__(self, "need_approval", bool(self.need_approval))
        object.__setattr__(self, "report_source", report_source)
        object.__setattr__(self, "actual_completed_at", actual_completed_at)
        object.__setattr__(self, "backfill_reason", backfill_reason)
        object.__setattr__(self, "submit_position_id", int(self.submit_position_id) if self.submit_position_id else None)
        object.__setattr__(self, "submit_position_name", (self.submit_position_name or "").strip())

    @property
    def effective_quantity(self):
        return 1 if self.serial_no else self.quantity

    @classmethod
    def from_submission(cls, data, user, quantity, serial_no, need_approval):
        return cls(
            report_type=data.get("report_type", "normal"),
            order_id=data.get("order_id"),
            process_id=data.get("process_id"),
            user_id=user["id"],
            user_name=user.get("name", ""),
            quantity=quantity,
            remark=data.get("remark", ""),
            serial_no=serial_no,
            need_approval=need_approval,
            report_source=data.get("report_source", "standard"),
            actual_completed_at=data.get("actual_completed_at"),
            backfill_reason=data.get("backfill_reason", ""),
            submit_position_id=(
                user.get("active_position_id")
                or user.get("position_id")
                or data.get("submit_position_id")
            ),
            submit_position_name=data.get("submit_position_name", ""),
        )

    @classmethod
    def from_approved_record(cls, work_record):
        return cls(
            report_type="normal",
            order_id=work_record["order_id"],
            process_id=work_record["process_id"],
            user_id=work_record["user_id"],
            user_name=work_record.get("user_name", ""),
            quantity=work_record["quantity"],
            serial_no=work_record.get("serial_no"),
            need_approval=False,
            report_source=work_record.get("report_source", "standard"),
            actual_completed_at=work_record.get("actual_completed_at"),
            backfill_reason=work_record.get("backfill_reason", ""),
            submit_position_id=work_record.get("submit_position_id"),
            submit_position_name=work_record.get("submit_position_name", ""),
        )
