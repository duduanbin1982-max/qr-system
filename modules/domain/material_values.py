"""Pure numeric validation shared by material stock and usage operations."""

from decimal import Decimal
from math import isfinite
from numbers import Real

from modules.domain.errors import ValidationError


def finite_number(value, field, *, positive=False, nonnegative=False) -> float:
    """Normalize numeric input without accepting bools or nonfinite balances."""
    if isinstance(value, bool) or not isinstance(value, (Real, Decimal, str)):
        raise ValidationError(f"{field}必须是有限数值")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValidationError(f"{field}必须是有限数值") from None
    if not isfinite(number):
        raise ValidationError(f"{field}必须是有限数值")
    if positive and number <= 0:
        raise ValidationError(f"{field}必须大于 0")
    if nonnegative and number < 0:
        raise ValidationError(f"{field}不得小于 0")
    return number
