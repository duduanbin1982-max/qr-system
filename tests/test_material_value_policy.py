"""The shared material number boundary rejects nonfinite and coerced booleans."""

from decimal import Decimal

import pytest

from modules.domain.errors import ValidationError
from modules.domain.material_values import finite_number


pytestmark = pytest.mark.unit


@pytest.mark.parametrize("value", [2, 2.5, " 2.5 ", Decimal("2.5")])
def test_finite_number_accepts_finite_numeric_values(value):
    assert finite_number(value, "数量") == float(value)


@pytest.mark.parametrize(
    "value",
    [
        None, True, False, [], {}, object(), "", " ", "invalid",
        "nan", "inf", "-inf", "1e309", float("nan"), float("inf"),
        Decimal("Infinity"), Decimal("sNaN"), 10 ** 1000,
    ],
)
def test_finite_number_rejects_invalid_types_and_nonfinite_values(value):
    with pytest.raises(ValidationError, match="数量必须是有限数值"):
        finite_number(value, "数量")


def test_finite_number_preserves_signed_delta_but_checks_explicit_bounds():
    assert finite_number(-2, "变动数量") == -2
    assert finite_number(0, "库存数量", nonnegative=True) == 0
    assert finite_number("0.25", "工序用量", positive=True) == 0.25
    with pytest.raises(ValidationError, match="工序用量必须大于 0"):
        finite_number(0, "工序用量", positive=True)
    with pytest.raises(ValidationError, match="库存数量不得小于 0"):
        finite_number(-1, "库存数量", nonnegative=True)
