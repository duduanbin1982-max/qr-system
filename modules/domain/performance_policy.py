"""Pure performance workflow, production-month, and concurrency rules."""

from datetime import datetime, timedelta
import re

from modules.domain.reporting_day import (
    REPORTING_DAY_START_HOUR,
    reporting_month_bounds,
)


MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

ELIGIBILITY_ELIGIBLE = "eligible"
ELIGIBILITY_INSUFFICIENT_DATA = "insufficient_data"

REASON_MISSING_POSITION = "missing_position"
REASON_MISSING_POSITION_TARGET = "missing_position_target"
REASON_POSITION_TARGET_MISMATCH = "position_target_mismatch"
REASON_ZERO_OUTPUT = "zero_output"
REASON_INSUFFICIENT_WORK_DAYS = "insufficient_work_days"
REASON_UNRESOLVED_DATA_EXCEPTION = "unresolved_data_exception"

BATCH_STATUS_DRAFT = "draft"
BATCH_STATUS_SUPERVISOR_REVIEW = "supervisor_review"
BATCH_STATUS_APPROVAL_PENDING = "approval_pending"
BATCH_STATUS_APPROVED = "approved"
BATCH_STATUS_SUPERSEDED = "superseded"
BATCH_STATUS_CANCELLED = "cancelled"

PLAN_STATUS_DRAFT = "draft"
PLAN_STATUS_ACTIVE = "active"
PLAN_STATUS_REASSESSMENT_PENDING = "reassessment_pending"
PLAN_STATUS_CLOSED = "closed"
PLAN_STATUS_CANCELLED = "cancelled"

BATCH_TRANSITIONS = {
    BATCH_STATUS_DRAFT: {BATCH_STATUS_SUPERVISOR_REVIEW, BATCH_STATUS_CANCELLED},
    BATCH_STATUS_SUPERVISOR_REVIEW: {
        BATCH_STATUS_DRAFT,
        BATCH_STATUS_APPROVAL_PENDING,
        BATCH_STATUS_CANCELLED,
    },
    BATCH_STATUS_APPROVAL_PENDING: {
        BATCH_STATUS_SUPERVISOR_REVIEW,
        BATCH_STATUS_APPROVED,
    },
    BATCH_STATUS_APPROVED: {BATCH_STATUS_SUPERSEDED},
    BATCH_STATUS_SUPERSEDED: set(),
    BATCH_STATUS_CANCELLED: set(),
}

PLAN_TRANSITIONS = {
    PLAN_STATUS_DRAFT: {PLAN_STATUS_ACTIVE, PLAN_STATUS_CANCELLED},
    PLAN_STATUS_ACTIVE: {PLAN_STATUS_REASSESSMENT_PENDING, PLAN_STATUS_CANCELLED},
    PLAN_STATUS_REASSESSMENT_PENDING: {PLAN_STATUS_ACTIVE, PLAN_STATUS_CLOSED},
    PLAN_STATUS_CLOSED: set(),
    PLAN_STATUS_CANCELLED: set(),
}


class PerformanceConflictError(ValueError):
    """Raised when a workflow or optimistic-locking precondition conflicts."""


def validate_production_month(value):
    month = str(value or "").strip()
    if not MONTH_RE.fullmatch(month):
        raise ValueError("生产月份格式必须为 YYYY-MM")
    reporting_month_bounds(month)
    return month


def production_month_for_timestamp(value):
    if isinstance(value, datetime):
        moment = value
    else:
        text = str(value or "").strip()
        try:
            moment = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError as exc:
            raise ValueError("绩效业务时间格式必须为 YYYY-MM-DD HH:MM:SS") from exc
    shifted = moment - timedelta(hours=REPORTING_DAY_START_HOUR)
    return shifted.strftime("%Y-%m")


def require_row_version(value):
    try:
        version = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("缺少有效的 row_version") from exc
    if version < 0:
        raise ValueError("row_version 无效")
    return version


def assert_row_version(expected, actual):
    expected_version = require_row_version(expected)
    actual_version = require_row_version(actual)
    if expected_version != actual_version:
        raise PerformanceConflictError("绩效记录已被其他操作修改，请刷新后重试")
    return actual_version


def _validate_transition(current, target, transitions, label):
    current_status = str(current or "").strip()
    target_status = str(target or "").strip()
    if current_status not in transitions or target_status not in transitions:
        raise ValueError(f"{label}状态无效")
    if current_status == target_status:
        return target_status
    if target_status not in transitions[current_status]:
        raise PerformanceConflictError(
            f"不允许的{label}状态转换：{current_status} -> {target_status}"
        )
    return target_status


def validate_batch_transition(current, target):
    return _validate_transition(current, target, BATCH_TRANSITIONS, "绩效批次")


def validate_plan_transition(current, target):
    return _validate_transition(current, target, PLAN_TRANSITIONS, "绩效改进计划")
