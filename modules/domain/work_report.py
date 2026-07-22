"""Work report command used across scan and approval workflows."""

from dataclasses import dataclass


REPORT_TYPES = {"normal", "scrap", "rework"}


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
        object.__setattr__(self, "report_type", report_type)
        object.__setattr__(self, "order_id", int(self.order_id))
        object.__setattr__(self, "process_id", int(self.process_id))
        object.__setattr__(self, "user_id", int(self.user_id))
        object.__setattr__(self, "user_name", (self.user_name or "").strip())
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "remark", (self.remark or "").strip())
        object.__setattr__(self, "serial_no", serial_no)
        object.__setattr__(self, "need_approval", bool(self.need_approval))

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
        )
