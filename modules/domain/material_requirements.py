"""Pure material requirement and shortage policies for work reports."""

from modules.domain.errors import ConflictError
from modules.domain.material_values import finite_number


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
        report_quantity = finite_number(report_quantity, "报工数量", positive=True)
        for material in material_rows:
            material_id = cls._value(material, "material_id")
            material_name = (
                cls._value(material, "material_name") or f"物料#{material_id}"
            )
            unit = cls._value(material, "unit") or ""
            per_unit = finite_number(
                cls._value(material, "quantity_per_unit"),
                f"物料「{material_name}」的工序用量",
                positive=True,
            )
            required_quantity = finite_number(
                report_quantity * per_unit, "物料需求量", positive=True
            )
            available_quantity = finite_number(
                cls._value(material, "stock_qty"),
                f"物料「{material_name}」的库存",
                nonnegative=True,
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
    def combined_shortages(requirements):
        """Check common and process demand together before either is written."""
        combined = {}
        for requirement in requirements:
            material_id = requirement["material_id"]
            if material_id not in combined:
                combined[material_id] = dict(requirement)
            else:
                combined[material_id]["required_quantity"] = finite_number(
                    combined[material_id]["required_quantity"]
                    + requirement["required_quantity"],
                    "合计物料需求量",
                    positive=True,
                )
        return [
            item for item in combined.values()
            if item["available_quantity"] < item["required_quantity"]
        ]

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
