"""Shared validation for product and frozen order material recipes."""

from modules.domain.errors import ValidationError
from modules.domain.material_values import finite_number


class MaterialRecipePolicy:
    @staticmethod
    def optional_id(value, field):
        if value is None or value == "":
            return None
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise ValidationError(f"{field}无效")
        try:
            identity = int(value)
        except (TypeError, ValueError, OverflowError):
            raise ValidationError(f"{field}无效") from None
        if identity <= 0:
            raise ValidationError(f"{field}无效")
        return identity

    @classmethod
    def normalize(cls, data, *, quantity_field="quantity_per_unit"):
        material_id = cls.optional_id(data.get("material_id"), "物料 ID")
        if material_id is None:
            raise ValidationError("物料 ID 不能为空")
        alternate = "quantity" if quantity_field == "quantity_per_unit" else "quantity_per_unit"
        quantity = data[quantity_field] if quantity_field in data else data.get(alternate, 1)
        return {
            "material_id": material_id,
            "process_id": cls.optional_id(data.get("process_id"), "工序 ID"),
            "quantity_per_unit": finite_number(quantity, "单位用量", positive=True),
        }
