"""Material consumption persistence for approved work reports."""

from modules.repositories.context import resolve_db


class MaterialConsumptionRepository:
    """Owns automatic material deduction as one transactional operation."""

    @staticmethod
    def deduct_for_process(order_id, process_id, quantity, user_id, user_name, db=None):
        db = resolve_db(db)
        material_rows = db.execute(
            "SELECT om.material_id, om.quantity_per_unit, m.quantity AS stock_qty "
            "FROM order_materials om "
            "JOIN materials m ON m.id = om.material_id "
            "WHERE om.order_id = ? AND om.process_id = ?",
            (order_id, process_id),
        ).fetchall()

        if not material_rows and MaterialConsumptionRepository._auto_deduction_enabled(db):
            material_rows = db.execute(
                "SELECT pb.material_id, pb.quantity_per_unit, m.quantity AS stock_qty "
                "FROM orders o "
                "JOIN products p ON p.product_code = o.product_code "
                "JOIN product_bom pb ON pb.product_id = p.id "
                "JOIN materials m ON m.id = pb.material_id "
                "WHERE o.id = ? AND (pb.process_id = ? OR COALESCE(pb.process_id, 0) = 0)",
                (order_id, process_id),
            ).fetchall()

        for material in material_rows:
            deduct_quantity = quantity * material["quantity_per_unit"]
            stock_quantity = material["stock_qty"] or 0
            if stock_quantity < deduct_quantity:
                continue

            db.execute(
                "UPDATE materials SET quantity = quantity - ?, "
                "updated_at = datetime('now','localtime') WHERE id = ?",
                (deduct_quantity, material["material_id"]),
            )
            db.execute(
                "INSERT INTO material_consumptions "
                "(material_id, order_id, process_id, quantity, operator_id, operator_name, notes) "
                "VALUES (?, ?, ?, ?, ?, ?, 'auto-deduct from order BOM')",
                (
                    material["material_id"],
                    order_id,
                    process_id,
                    deduct_quantity,
                    user_id,
                    user_name,
                ),
            )
            db.execute(
                "INSERT INTO material_logs "
                "(material_id, type, quantity, remark, operator_id, operator_name) "
                "VALUES (?, 'out', ?, 'auto-deduct', ?, ?)",
                (material["material_id"], deduct_quantity, user_id, user_name),
            )

    @staticmethod
    def _auto_deduction_enabled(db):
        setting = db.execute(
            "SELECT value FROM system_settings WHERE key = 'auto_deduct_material'"
        ).fetchone()
        return setting is not None and setting["value"] == "1"
