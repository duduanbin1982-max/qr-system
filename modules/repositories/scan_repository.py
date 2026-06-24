"""
qr-system — ScanRepository（扫码报工数据访问层）
"""
from modules.db_unit_of_work import BaseService


class ScanRepository:
    """扫码报工数据访问 — 封装扫码流程中的数据库操作。"""

    @staticmethod
    def find_order_by_no(order_no, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT * FROM orders WHERE order_no = ? AND deleted_at IS NULL",
            (order_no,)
        ).fetchone()

    @staticmethod
    def get_order_processes(order_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            """SELECT op.*, p.name as process_name
               FROM order_processes op
               JOIN processes p ON op.process_id=p.id
               WHERE op.order_id = ? ORDER BY op.seq_order""",
            (order_id,)
        ).fetchall()

    @staticmethod
    def get_item_by_serial(serial_no, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT * FROM product_items WHERE serial_no = ?", (serial_no,)
        ).fetchone()

    @staticmethod
    def get_items_by_order(order_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT * FROM product_items WHERE order_id = ? ORDER BY position_no",
            (order_id,)
        ).fetchall()

    @staticmethod
    def insert_work_record(data, db=None):
        db = db or BaseService.db()
        cur = db.execute(
            """INSERT INTO work_records
               (order_id, process_id, user_id, serial_no, quantity, type, status, remark)
               VALUES (?,?,?,?,?,?,'approved',?)""",
            (data['order_id'], data['process_id'], data['user_id'],
             data.get('serial_no', ''), data.get('quantity', 1),
             data.get('type', 'normal'), data.get('remark', ''))
        )
        return cur.lastrowid


    @staticmethod
    def deduct_materials_for_process(order_id, process_id, quantity, user_id, user_name, db=None):
        """自动扣减工序物料：从 order_materials 或 product_bom 扣除库存并记录消耗。"""
        db = db or BaseService.db()
        from modules.repositories.order_material_repository import OrderMaterialRepository
        from modules.repositories.product_bom_repository import ProductBomRepository

        om_rows = OrderMaterialRepository.get_by_order_and_process(order_id, process_id, db=db)
        if not om_rows:
            config_row = db.execute(
                "SELECT value FROM system_settings WHERE key = 'auto_deduct_material'"
            ).fetchone()
            if config_row and config_row['value'] == '1':
                prod = db.execute(
                    "SELECT id FROM products WHERE product_code = (SELECT product_code FROM orders WHERE id = ?)",
                    (order_id,)
                ).fetchone()
                if prod:
                    bom_rows = ProductBomRepository.list_by_product(prod["id"], db=db)
                    bom_for_process = [
                        b for b in bom_rows
                        if b["process_id"] == process_id or not b["process_id"]
                    ]
                    for b in bom_for_process:
                        bd = dict(b)
                        stock = db.execute(
                            "SELECT quantity FROM materials WHERE id = ?", (b["material_id"],)
                        ).fetchone()
                        bd["stock_qty"] = stock["quantity"] if stock else 0
                        om_rows.append(bd)

        for om in om_rows:
            deduct_qty = quantity * om['quantity_per_unit']
            stock_qty = om['stock_qty'] if om['stock_qty'] else 0
            if stock_qty >= deduct_qty:
                db.execute(
                    "UPDATE materials SET quantity = quantity - ?, updated_at = datetime('now','localtime') WHERE id = ?",
                    (deduct_qty, om['material_id'])
                )
                db.execute(
                    "INSERT INTO material_consumptions (material_id, order_id, process_id, quantity, operator_id, operator_name, notes) VALUES (?,?,?,?,?,?,'auto-deduct from order BOM')",
                    (om['material_id'], order_id, process_id, deduct_qty, user_id, user_name)
                )
                db.execute(
                    "INSERT INTO material_logs (material_id, type, quantity, remark, operator_id, operator_name) VALUES (?, 'out', ?, 'auto-deduct', ?, ?)",
                    (om['material_id'], deduct_qty, user_id, user_name)
                )

    @staticmethod
    def auto_inbound_item(order_id, db=None):
        """自动入库：检查订单最后一道工序是否全部完成。"""
        db = db or BaseService.db()
        items = db.execute(
            "SELECT * FROM product_items WHERE order_id = ? AND status = 'in_progress'",
            (order_id,)
        ).fetchall()
        return len(items)

