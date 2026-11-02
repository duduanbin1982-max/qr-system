import pytest

from modules.domain.errors import ConflictError, ValidationError
from modules.domain.material_requirements import MaterialRequirementPolicy


def test_material_requirement_policy_calculates_requirements_without_database():
    requirements, shortages = MaterialRequirementPolicy.calculate(
        [
            {
                "material_id": 7,
                "material_name": "钢板",
                "unit": "kg",
                "quantity_per_unit": 1.5,
                "stock_qty": 20,
            }
        ],
        4,
    )

    assert requirements[0]["required_quantity"] == 6
    assert requirements[0]["available_quantity"] == 20
    assert shortages == []


def test_material_requirement_policy_reports_shortage_details():
    _, shortages = MaterialRequirementPolicy.calculate(
        [
            {
                "material_id": 8,
                "material_name": "铜管",
                "unit": "m",
                "quantity_per_unit": 2,
                "stock_qty": 3,
            }
        ],
        2,
    )

    with pytest.raises(ConflictError, match="铜管需4m，现有3m") as exc_info:
        MaterialRequirementPolicy.assert_sufficient(shortages)

    assert exc_info.value.details["shortages"] == shortages


def test_material_requirement_policy_rejects_nonpositive_bom_quantity():
    with pytest.raises(ValidationError, match="工序用量必须大于 0"):
        MaterialRequirementPolicy.calculate(
            [
                {
                    "material_id": 9,
                    "material_name": "异常物料",
                    "quantity_per_unit": 0,
                    "stock_qty": 10,
                }
            ],
            1,
        )


@pytest.mark.parametrize("quantity", [True, "NaN", "Infinity", "1e309", -1, "text"])
def test_material_requirement_policy_rejects_invalid_raw_quantity(quantity):
    with pytest.raises(ValidationError):
        MaterialRequirementPolicy.calculate(
            [{"material_id": 1, "quantity_per_unit": quantity, "stock_qty": 20}], 1
        )


def test_material_requirement_policy_rejects_product_overflow():
    with pytest.raises(ValidationError, match="物料需求量必须是有限数值"):
        MaterialRequirementPolicy.calculate(
            [{"material_id": 1, "quantity_per_unit": 1e200, "stock_qty": 1e300}], 1e200
        )


def test_material_requirement_policy_checks_combined_common_and_process_demand():
    common, _ = MaterialRequirementPolicy.calculate(
        [{"material_id": 1, "quantity_per_unit": 2, "stock_qty": 12}], 5
    )
    process, _ = MaterialRequirementPolicy.calculate(
        [{"material_id": 1, "quantity_per_unit": 1, "stock_qty": 12}], 3
    )
    shortages = MaterialRequirementPolicy.combined_shortages(common + process)
    assert shortages[0]["required_quantity"] == 13
    assert shortages[0]["available_quantity"] == 12
