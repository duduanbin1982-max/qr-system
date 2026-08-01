"""Pure material requirement and shortage policies for work reports."""

from modules.domain.errors import ConflictError, ValidationError


class MaterialRequirementPolicy:
    @staticmethod
    def _value(row, key, default=None):
        if hasattr(row, "get"):
            return row.get(key, default)
        try:
            return row[key]
        except (KeyError, IndexError, TypeError):
            return default

    @classmethod
    def calculate(cls, material_rows, report_quantity):
        requirements = []
        shortages = []
        for material in material_rows:
            material_id = cls._value(material, "material_id")
            required_quantity = float(report_quantity) * float(
                cls._value(material, "quantity_per_unit", 0) or 0
            )
            material_name = (
                cls._value(material, "material_name") or f"物料#{material_id}"
            )
            unit = cls._value(material, "unit") or ""
            if required_quantity <= 0:
                raise ValidationError(f"物料「{material_name}」的工序用量必须大于 0")
            available_quantity = float(
                cls._value(material, "stock_qty", 0) or 0
            )
            requirement = {
                "material_id": material_id,
                "material_name": material_name,
                "unit": unit,
                "required_quantity": required_quantity,
                "available_quantity": available_quantity,
            }
            requirements.append(requirement)
            if available_quantity < required_quantity:
                shortages.append(requirement)
        return requirements, shortages

    @staticmethod
    def assert_sufficient(shortages):
        if not shortages:
            return
        shortage_text = "；".join(
            f"{item['material_name']}需{item['required_quantity']:g}{item['unit']}，"
            f"现有{item['available_quantity']:g}{item['unit']}"
            for item in shortages
        )
        raise ConflictError(
            f"物料库存不足，报工未提交：{shortage_text}",
            details={"shortages": shortages},
        )
