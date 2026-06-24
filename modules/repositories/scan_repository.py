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
    def get_order(order_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT * FROM orders WHERE id = ? AND deleted_at IS NULL",
            (order_id,)
        ).fetchone()

    @staticmethod
    def get_order_for_stock(order_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT o.id, o.order_no, o.product_code, o.product_name, o.quantity, p.spec "
            "FROM orders o LEFT JOIN products p ON o.product_code = p.product_code "
            "WHERE o.id = ?",
            (order_id,)
        ).fetchone()

    @staticmethod
    def get_order_quantity(order_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT quantity FROM orders WHERE id = ?",
            (order_id,)
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
    def get_item_by_position(order_id, position_no, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT * FROM product_items WHERE order_id = ? AND position_no = ?",
            (order_id, position_no)
        ).fetchone()

    @staticmethod
    def get_items_by_order(order_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT * FROM product_items WHERE order_id = ? ORDER BY position_no",
            (order_id,)
        ).fetchall()

    @staticmethod
    def get_order_process(order_id, process_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT * FROM order_processes WHERE order_id = ? AND process_id = ?",
            (order_id, process_id)
        ).fetchone()

    @staticmethod
    def find_order_process_id(order_id, process_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT id FROM order_processes WHERE order_id = ? AND process_id = ?",
            (order_id, process_id)
        ).fetchone()

    @staticmethod
    def get_prev_incomplete_processes(order_id, current_seq, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT op.seq_order, p.name as process_name FROM order_processes op "
            "JOIN processes p ON op.process_id = p.id "
            "WHERE op.order_id = ? AND op.seq_order < ? AND (op.completed IS NULL OR op.completed = 0) "
            "ORDER BY op.seq_order",
            (order_id, current_seq)
        ).fetchall()

    @staticmethod
    def get_prev_order_process(order_id, current_seq, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT op.*, p.name as process_name FROM order_processes op "
            "JOIN processes p ON op.process_id = p.id "
            "WHERE op.order_id = ? AND op.seq_order < ? "
            "ORDER BY op.seq_order DESC LIMIT 1",
            (order_id, current_seq)
        ).fetchone()

    @staticmethod
    def find_next_process(order_id, current_seq, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT op.process_id FROM order_processes op WHERE op.order_id = ? AND op.seq_order > ? "
            "ORDER BY op.seq_order LIMIT 1",
            (order_id, current_seq)
        ).fetchone()

    @staticmethod
    def get_last_process_seq(order_id, db=None):
        db = db or BaseService.db()
        row = db.execute(
            "SELECT MAX(seq_order) as max_seq FROM order_processes WHERE order_id = ?",
            (order_id,)
        ).fetchone()
        return row["max_seq"] if row else None

    @staticmethod
    def is_last_process(order_id, process_id, db=None):
        db = db or BaseService.db()
        max_row = db.execute(
            "SELECT MAX(seq_order) as max_seq FROM order_processes WHERE order_id = ?",
            (order_id,)
        ).fetchone()
        if not max_row or max_row["max_seq"] is None:
            return False
        cur_row = db.execute(
            "SELECT seq_order FROM order_processes WHERE order_id = ? AND process_id = ?",
            (order_id, process_id)
        ).fetchone()
        return cur_row is not None and cur_row["seq_order"] == max_row["max_seq"]

    @staticmethod
    def get_work_records(order_id, db=None, limit=None):
        db = db or BaseService.db()
        if limit:
            return db.execute(
                "SELECT wr.*, u.name as worker_name FROM work_records wr "
                "LEFT JOIN users u ON wr.user_id = u.id "
                "WHERE wr.order_id = ? ORDER BY wr.created_at DESC LIMIT ?",
                (order_id, limit)
            ).fetchall()
        return db.execute(
            "SELECT wr.*, u.name as worker_name FROM work_records wr "
            "LEFT JOIN users u ON wr.user_id = u.id "
            "WHERE wr.order_id = ? ORDER BY wr.created_at DESC",
            (order_id,)
        ).fetchall()

    @staticmethod
    def get_user_order_report(order_id, user_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT id FROM work_records WHERE order_id = ? AND user_id = ? AND type = 'normal'",
            (order_id, user_id)
        ).fetchone()

    @staticmethod
    def get_process_name(process_id, db=None):
        db = db or BaseService.db()
        row = db.execute("SELECT name FROM processes WHERE id = ?", (process_id,)).fetchone()
        return row["name"] if row else "\u672a\u77e5\u5de5\u5e8f"

    @staticmethod
    def find_duplicate_normal_report(order_id, process_id, serial_no, user_id, db=None):
        db = db or BaseService.db()
        if serial_no:
            return db.execute(
                "SELECT id FROM work_records WHERE order_id = ? AND process_id = ? "
                "AND serial_no = ? AND type = 'normal' AND status != 'rejected'",
                (order_id, process_id, serial_no)
            ).fetchone()
        return db.execute(
            "SELECT id FROM work_records WHERE order_id = ? AND process_id = ? "
            "AND user_id = ? AND type = 'normal' AND status != 'rejected'",
            (order_id, process_id, user_id)
        ).fetchone()

    @staticmethod
    def has_serial_duplicate_in_order(order_id, serial_no, user_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT id FROM work_records WHERE order_id = ? AND serial_no = ? AND user_id = ? LIMIT 1",
            (order_id, serial_no, user_id)
        ).fetchone() is not None

    @staticmethod
    def find_duplicate_defect_report(order_id, process_id, user_id, report_type, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT id FROM work_records WHERE order_id = ? AND process_id = ? "
            "AND user_id = ? AND type = ? "
            "AND created_at > datetime('now', '-10 seconds')",
            (order_id, process_id, user_id, report_type)
        ).fetchone()

    @staticmethod
    def find_approval_config(process_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT id FROM approval_config WHERE process_id = ? AND require_approval = 1",
            (process_id,)
        ).fetchone()

    @staticmethod
    def count_completed_items(order_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT COUNT(*) as cnt FROM product_items WHERE order_id = ? AND status = 'completed'",
            (order_id,)
        ).fetchone()["cnt"]

    @staticmethod
    def find_inventory_by_model(product_code, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT id, product_model, product_name, quantity FROM inventory WHERE product_model = ?",
            (product_code,)
        ).fetchone()

    @staticmethod
    def find_inbound_inventory_log(order_id, serial_no=None, db=None):
        db = db or BaseService.db()
        if serial_no:
            return db.execute(
                "SELECT id FROM inventory_logs WHERE order_id = ? AND type = 'in' AND remark LIKE ?",
                (order_id, "%" + serial_no + "%")
            ).fetchone()
        return db.execute(
            "SELECT id FROM inventory_logs WHERE order_id = ? AND type = 'in'",
            (order_id,)
        ).fetchone()

    @staticmethod
    def order_has_process_in_scope(order_id, process_ids, db=None):
        db = db or BaseService.db()
        placeholders = ",".join("?" for _ in process_ids)
        row = db.execute(
            f"SELECT 1 FROM order_processes WHERE order_id = ? AND process_id IN ({placeholders})",
            [order_id] + process_ids
        ).fetchone()
        return row is not None

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
