"""Pure normalization rules for work time records."""

from datetime import datetime


RECORD_STATUSES = {"running", "completed", "abnormal"}
REVIEW_STATUSES = {"pending", "approved", "rejected"}


def to_int(value, default=None):
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def to_float(value, default=0.0):
    if value in (None, ""):
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def parse_datetime(value):
    if not value:
        return None
    text = str(value).strip().replace("T", " ")
    for fmt, length in (
        ("%Y-%m-%d %H:%M:%S", 19),
        ("%Y-%m-%d %H:%M", 16),
        ("%Y-%m-%d", 10),
    ):
        try:
            return datetime.strptime(text[:length], fmt)
        except ValueError:
            continue
    raise ValueError("时间格式不正确")


class WorkTimeRecordPolicy:
    @staticmethod
    def standard_total_minutes(standard, quantity):
        if not standard:
            return 0
        setup = to_float(standard["setup_minutes"], 0)
        unit = to_float(standard["standard_minutes_per_unit"], 0)
        factor = to_float(standard["difficulty_factor"], 1)
        return round(setup + unit * max(int(quantity or 1), 1) * factor, 2)

    @staticmethod
    def _timing(data, now_text):
        start_time = (data.get("start_time") or now_text).strip().replace("T", " ")
        end_time = (data.get("end_time") or "").strip().replace("T", " ")
        status = (data.get("status") or ("completed" if end_time else "running")).strip()
        if status not in RECORD_STATUSES:
            raise ValueError("工时流水状态不正确")
        if status == "completed" and not end_time:
            end_time = now_text
        start_dt = parse_datetime(start_time)
        end_dt = parse_datetime(end_time) if end_time else None
        pause_minutes = max(to_float(data.get("pause_minutes"), 0), 0)
        actual_minutes = to_float(data.get("actual_minutes"), 0)
        if start_dt and end_dt:
            if end_dt < start_dt:
                raise ValueError("结束时间不能早于开始时间")
            actual_minutes = round(max((end_dt - start_dt).total_seconds() / 60 - pause_minutes, 0), 2)
        effective_minutes = round(max(to_float(data.get("effective_minutes"), actual_minutes), 0), 2)
        return start_time, end_time, status, pause_minutes, actual_minutes, effective_minutes

    @staticmethod
    def _review_state(data, status):
        abnormal_reason = (data.get("abnormal_reason") or "").strip()
        review_status = (data.get("review_status") or "").strip()
        if not review_status:
            review_status = "pending" if status in {"running", "abnormal"} or abnormal_reason else "approved"
        if review_status not in REVIEW_STATUSES:
            raise ValueError("审核状态不正确")
        if abnormal_reason and status == "completed":
            return "abnormal", "pending", abnormal_reason
        return status, review_status, abnormal_reason

    @staticmethod
    def normalize(data, context, creator_id, now_text):
        quantity = max(to_int(data.get("quantity"), 1) or 1, 1)
        start_time, end_time, status, pause, actual, effective = WorkTimeRecordPolicy._timing(
            data, now_text
        )
        status, review_status, abnormal_reason = WorkTimeRecordPolicy._review_state(data, status)
        standard_minutes = to_float(data.get("standard_minutes"), 0)
        if standard_minutes <= 0:
            standard_minutes = WorkTimeRecordPolicy.standard_total_minutes(context.get("standard"), quantity)
        return {
            "order_id": context.get("order_id"),
            "order_no": context.get("order_no", ""),
            "serial_no": (data.get("serial_no") or "").strip(),
            "route_id": context.get("route_id"),
            "route_name": context.get("route_name", ""),
            "product_code": context.get("product_code", ""),
            "product_name": context.get("product_name", ""),
            "standard_missing": 0 if context.get("standard") else 1,
            "process_id": context["process_id"],
            "process_name": context["process_name"],
            "user_id": context["user_id"],
            "user_name": context["user_name"],
            "standard_id": context.get("standard_id"),
            "source_work_record_id": to_int(data.get("source_work_record_id")),
            "quantity": quantity,
            "standard_minutes": round(standard_minutes, 2),
            "start_time": start_time,
            "end_time": end_time,
            "pause_minutes": round(pause, 2),
            "actual_minutes": actual,
            "effective_minutes": effective,
            "status": status,
            "abnormal_reason": abnormal_reason,
            "review_status": review_status,
            "reviewed_by": creator_id if review_status == "approved" else None,
            "reviewed_at": now_text if review_status == "approved" else "",
            "review_note": (data.get("review_note") or "").strip(),
            "created_by": creator_id,
        }
