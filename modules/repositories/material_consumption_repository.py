"""Material consumption persistence for approved work reports."""

from modules.repositories.context import resolve_db


class MaterialConsumptionRepository:
    """Owns automatic material deduction as one transactional operation."""

    @staticmethod
    def deduction_candidates(order_id, process_id, db=None):
        """Return the order snapshot or fallback BOM rows for one process."""
        db = resolve_db(db)
        if not MaterialConsumptionRepository._auto_deduction_enabled(db):
            return []

        material_rows = db.execute(
            "SELECT om.material_id, SUM(om.quantity_per_unit) AS quantity_per_unit, "
            "m.quantity AS stock_qty, m.name AS material_name, m.unit "
            "FROM order_materials om "
            "JOIN materials m ON m.id = om.material_id "
            "WHERE om.order_id = ? AND om.process_id = ? "
            "GROUP BY om.material_id, m.quantity, m.name, m.unit",
            (order_id, process_id),
        ).fetchall()

        if not material_rows:
            material_rows = db.execute(
                "SELECT pb.material_id, SUM(pb.quantity_per_unit) AS quantity_per_unit, "
                "m.quantity AS stock_qty, m.name AS material_name, m.unit "
                "FROM orders o "
                "JOIN order_product_links opl ON opl.order_id = o.id "
                "JOIN products p ON p.id = opl.product_id "
                "JOIN product_bom pb ON pb.product_id = p.id "
                "JOIN materials m ON m.id = pb.material_id "
                "WHERE o.id = ? AND (pb.process_id = ? OR COALESCE(pb.process_id, 0) = 0) "
                "GROUP BY pb.material_id, m.quantity, m.name, m.unit",
                (order_id, process_id),
            ).fetchall()

        return material_rows

    @staticmethod
    def _auto_deduction_enabled(db):
        setting = db.execute(
            "SELECT value FROM system_settings WHERE key = 'auto_deduct_material'"
        ).fetchone()
        return setting is not None and setting["value"] == "1"
