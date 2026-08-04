"""Pure validation, fixed-point money, and payroll workflow rules."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re

from modules.domain.reporting_day import reporting_month_bounds


MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
MAX_AMOUNT_CENTS = 9_000_000_000_000_000


class PayrollConflictError(ValueError):
    """Raised when optimistic locking or idempotency input conflicts."""


def validate_payroll_month(value):
    month = str(value or "").strip()
    if not MONTH_RE.fullmatch(month):
        raise ValueError("工资月份格式必须为 YYYY-MM")
    reporting_month_bounds(month)
    return month


def normalize_timestamp(value, field_name="时间"):
    text = str(value or "").strip()
    if len(text) == 10:
        text += " 00:00:00"
    if len(text) != 19:
        raise ValueError(f"{field_name}格式必须为 YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS")
    from datetime import datetime

    try:
        datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError as exc:
        raise ValueError(f"{field_name}无效") from exc
    return text


def yuan_to_cents(value):
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("金额格式无效") from exc
    cents = int(amount * 100)
    if cents <= 0:
        raise ValueError("金额必须大于 0")
    if cents > MAX_AMOUNT_CENTS:
        raise ValueError("金额超出允许范围")
    return cents


def yuan_to_micros(value):
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("工价格式无效") from exc
    micros = int(amount * 10000)
    if micros < 0:
        raise ValueError("工价不能为负数")
    if micros > MAX_AMOUNT_CENTS * 100:
        raise ValueError("工价超出允许范围")
    return micros


def round_half_up_fraction(numerator, denominator):
    numerator = int(numerator)
    denominator = int(denominator)
    if denominator <= 0:
        raise ValueError("金额计算分母无效")
    sign = -1 if numerator < 0 else 1
    value = (abs(numerator) * 2 + denominator) // (2 * denominator)
    result = sign * value
    if abs(result) > MAX_AMOUNT_CENTS:
        raise ValueError("工资金额超出允许范围")
    return result


def work_amount_cents(quantity, unit_price_micros, rework_rate_basis_points=None):
    quantity = int(quantity or 0)
    unit_price_micros = int(unit_price_micros or 0)
    if quantity < 0 or unit_price_micros < 0:
        raise ValueError("工资数量或工价不能为负数")
    if rework_rate_basis_points is None:
        return round_half_up_fraction(quantity * unit_price_micros, 100)
    rate = int(rework_rate_basis_points)
    if not 0 <= rate <= 10000:
        raise ValueError("返工倍率必须在 0% 到 100% 之间")
    return round_half_up_fraction(quantity * unit_price_micros * rate, 1_000_000)


def cents_to_yuan(cents):
    return f"{Decimal(int(cents or 0)) / Decimal(100):.2f}"


def require_row_version(value):
    try:
        version = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("缺少有效的 row_version") from exc
    if version < 0:
        raise ValueError("row_version 无效")
    return version
