"""Material consumption persistence for approved work reports."""

from modules.repositories.context import resolve_db
from modules.domain.errors import NotFoundError
from modules.domain.material_values import finite_number


class MaterialConsumptionRepository:
    """Owns automatic material deduction as one transactional operation."""

    @staticmethod
    def snapshot_rows(order_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT om.material_id, om.quantity_per_unit, om.process_id, "
            "m.quantity AS stock_qty, m.name AS material_name, m.unit "
            "FROM order_materials om "
            "LEFT JOIN materials m ON m.id = om.material_id "
            "WHERE om.order_id = ?",
            (order_id,),
        ).fetchall()

    @staticmethod
    def deduction_candidates(order_id, process_id, db=None, *, snapshot=None):
        """Read frozen rows; absence never falls back to a live BOM."""
        db = resolve_db(db)
        if not MaterialConsumptionRepository.auto_deduction_enabled(db):
            return []
        if snapshot is None:
            snapshot = MaterialConsumptionRepository.snapshot_rows(order_id, db=db)
        grouped = {}
        for row in snapshot:
            # Validate original rows before aggregation: SQLite SUM otherwise
            # turns text into zero and can hide negative/positive cancellation.
            per_unit = finite_number(row["quantity_per_unit"], "单位用量", positive=True)
            if row["stock_qty"] is None:
                raise NotFoundError(f"物料#{row['material_id']}不存在")
            if row["process_id"] is not None and row["process_id"] != process_id:
                continue
            key = (row["material_id"], row["process_id"])
            if key not in grouped:
                grouped[key] = dict(row)
                grouped[key]["quantity_per_unit"] = per_unit
            else:
                grouped[key]["quantity_per_unit"] = finite_number(
                    grouped[key]["quantity_per_unit"] + per_unit,
                    "合计单位用量", positive=True,
                )

        return list(grouped.values())

    @staticmethod
    def auto_deduction_enabled(db):
        setting = db.execute(
            "SELECT value FROM system_settings WHERE key = 'auto_deduct_material'"
        ).fetchone()
        return setting is not None and setting["value"] == "1"
