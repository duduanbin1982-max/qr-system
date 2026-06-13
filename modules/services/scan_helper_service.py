"""qr-system — ScanHelperService（扫码报工核心数据操作）"""
from modules.services import BaseService


class ScanHelperService:
    """扫码报工辅助 - 所有 DB 操作集中管理。"""

    # ======================== 订单查询 ========================

    @staticmethod
    def get_order_by_no(order_no):
        db = BaseService.db()
        return db.execute(
            "SELECT * FROM orders WHERE order_no = ? AND deleted_at IS NULL", (order_no,)
        ).fetchone()

    @staticmethod
    def get_order(order_id):
        db = BaseService.db()
        return db.execute(
            "SELECT * FROM orders WHERE id = ? AND deleted_at IS NULL", (order_id,)
        ).fetchone()

    @staticmethod
    def get_order_for_stock(order_id):
        db = BaseService.db()
        return db.execute(
            "SELECT id, order_no, product_code, product_name, quantity FROM orders WHERE id = ?",
            (order_id,)
        ).fetchone()

    @staticmethod
    def get_order_quantity(order_id):
        db = BaseService.db()
        return db.execute("SELECT quantity FROM orders WHERE id = ?", (order_id,)).fetchone()

    # ======================== 产品序列号查询 ========================

    @staticmethod
    def get_product_item(serial_no):
        db = BaseService.db()
        return db.execute("SELECT * FROM product_items WHERE serial_no = ?", (serial_no,)).fetchone()

    @staticmethod
    def get_product_item_by_position(order_id, position_no):
        db = BaseService.db()
        return db.execute(
            "SELECT * FROM product_items WHERE order_id = ? AND position_no = ?",
            (order_id, position_no)
        ).fetchone()

    @staticmethod
    def get_product_items_by_order(order_id):
        db = BaseService.db()
        return db.execute(
            "SELECT * FROM product_items WHERE order_id = ? ORDER BY position_no",
            (order_id,)
        ).fetchall()

    # ======================== 工序相关查询 ========================

    @staticmethod
    def get_order_process(order_id, process_id):
        db = BaseService.db()
        return db.execute(
            "SELECT * FROM order_processes WHERE order_id = ? AND process_id = ?",
            (order_id, process_id)
        ).fetchone()

    @staticmethod
    def check_process_in_order(order_id, process_id):
        db = BaseService.db()
        return db.execute(
            "SELECT id FROM order_processes WHERE order_id = ? AND process_id = ?",
            (order_id, process_id)
        ).fetchone()

    @staticmethod
    def get_order_processes(order_id):
        db = BaseService.db()
        return db.execute(
            "SELECT op.*, p.name as process_name FROM order_processes op "
            "JOIN processes p ON op.process_id = p.id "
            "WHERE op.order_id = ? ORDER BY op.seq_order", (order_id,)
        ).fetchall()

    @staticmethod
    def get_prev_incomplete_processes(order_id, current_seq):
        db = BaseService.db()
        return db.execute(
            "SELECT op.seq_order, p.name as process_name FROM order_processes op "
            "JOIN processes p ON op.process_id = p.id "
            "WHERE op.order_id = ? AND op.seq_order < ? AND (op.completed IS NULL OR op.completed = 0) "
            "ORDER BY op.seq_order", (order_id, current_seq)
        ).fetchall()

    @staticmethod
    def get_prev_order_process(order_id, seq_order):
        db = BaseService.db()
        return db.execute(
            "SELECT op.*, p.name as process_name FROM order_processes op "
            "JOIN processes p ON op.process_id = p.id "
            "WHERE op.order_id = ? AND op.seq_order = ?", (order_id, seq_order)
        ).fetchone()

    @staticmethod
    def find_next_process(order_id, current_seq):
        db = BaseService.db()
        return db.execute(
            "SELECT op.process_id FROM order_processes op WHERE op.order_id = ? AND op.seq_order > ? "
            "ORDER BY op.seq_order LIMIT 1", (order_id, current_seq)
        ).fetchone()

    # ======================== 报工记录查询 ========================

    @staticmethod
    def get_last_process_seq(order_id):
        db = BaseService.db()
        row = db.execute(
            "SELECT MAX(seq_order) as max_seq FROM order_processes WHERE order_id = ?",
            (order_id,)
        ).fetchone()
        return row["max_seq"] if row else None

    @staticmethod
    def is_last_process(order_id, process_id):
        db = BaseService.db()
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
    def get_work_records(order_id, limit=50):
        db = BaseService.db()
        return db.execute(
            "SELECT wr.*, u.name as worker_name, p.name as process_name "
            "FROM work_records wr JOIN users u ON wr.user_id = u.id "
            "JOIN processes p ON wr.process_id = p.id "
            "WHERE wr.order_id = ? ORDER BY wr.created_at DESC LIMIT ?",
            (order_id, limit)
        ).fetchall()

    @staticmethod
    def check_duplicate_normal_report(order_id, process_id, serial_no=None, user_id=None):
        db = BaseService.db()
        if serial_no:
            return db.execute(
                "SELECT id FROM work_records WHERE order_id = ? AND process_id = ? AND serial_no = ?",
                (order_id, process_id, serial_no)
            ).fetchone()
        return db.execute(
            "SELECT id FROM work_records WHERE order_id = ? AND process_id = ? AND user_id = ?",
            (order_id, process_id, user_id)
        ).fetchone()

    @staticmethod
    def check_duplicate_defect_report(order_id, process_id, user_id, report_type):
        db = BaseService.db()
        return db.execute(
            "SELECT id FROM work_records WHERE order_id = ? AND process_id = ? AND user_id = ? "
            "AND type = ? AND created_at > datetime('now','localtime','-30 seconds')",
            (order_id, process_id, user_id, report_type)
        ).fetchone()

    # ======================== 审批配置查询 ========================

    @staticmethod
    def check_approval_required(process_id):
        db = BaseService.db()
        return db.execute(
            "SELECT * FROM approval_config WHERE process_id = ? AND require_approval = 1",
            (process_id,)
        ).fetchone()

    # ======================== 报工写入操作 ========================

    @staticmethod
    def insert_work_record(order_id, process_id, user_id, report_type, quantity, remark, work_status, serial_no):
        db = BaseService.db()
        cur = db.execute(
            "INSERT INTO work_records (order_id, process_id, user_id, type, quantity, remark, status, serial_no) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (order_id, process_id, user_id, report_type, quantity, remark, work_status, serial_no)
        )
        db.commit()
        return cur.lastrowid

    @staticmethod
    def insert_approval_record(wr_id):
        db = BaseService.db()
        db.execute("INSERT INTO approval_records (work_record_id, status) VALUES (?, 'pending')", (wr_id,))
        db.commit()

    @staticmethod
    def update_order_process_completed(order_id, process_id, new_completed):
        db = BaseService.db()
        db.execute(
            "UPDATE order_processes SET completed = ? WHERE order_id = ? AND process_id = ?",
            (new_completed, order_id, process_id)
        )
        db.commit()

    @staticmethod
    def advance_product_item(item_id, next_process_id, version):
        db = BaseService.db()
        return db.execute(
            "UPDATE product_items SET current_process_id = ?, status = 'in_progress', version = version + 1 "
            "WHERE id = ? AND version = ?", (next_process_id, item_id, version)
        )

    @staticmethod
    def complete_product_item(item_id, version):
        db = BaseService.db()
        return db.execute(
            "UPDATE product_items SET current_process_id = NULL, status = 'completed', "
            "completed_at = datetime('now','localtime'), version = version + 1 WHERE id = ? AND version = ?",
            (item_id, version)
        )

    @staticmethod
    def update_order_completed(order_id):
        db = BaseService.db()
        db.execute(
            "UPDATE orders SET completed = (SELECT COUNT(*) FROM product_items WHERE order_id = ? AND status = 'completed'), "
            "updated_at = datetime('now','localtime'), status = 'producing' WHERE id = ?",
            (order_id, order_id)
        )
        db.commit()

    @staticmethod
    def count_completed_items(order_id):
        db = BaseService.db()
        return db.execute(
            "SELECT COUNT(*) as cnt FROM product_items WHERE order_id = ? AND status = 'completed'", (order_id,)
        ).fetchone()["cnt"]

    @staticmethod
    def complete_order(order_id):
        db = BaseService.db()
        db.execute("UPDATE orders SET status = 'completed' WHERE id = ?", (order_id,))
        db.commit()

    # ======================== 废品/返工操作 ========================

    @staticmethod
    def insert_scrap_record(order_id, process_id, user_id, quantity, reason):
        db = BaseService.db()
        db.execute(
            "INSERT INTO scrap_records (order_id, process_id, user_id, quantity, reason) VALUES (?,?,?,?,?)",
            (order_id, process_id, user_id, quantity, reason)
        )
        db.commit()

    @staticmethod
    def update_order_process_scrapped(order_id, process_id, new_scrapped):
        db = BaseService.db()
        db.execute(
            "UPDATE order_processes SET scrapped = ? WHERE order_id = ? AND process_id = ?",
            (new_scrapped, order_id, process_id)
        )
        db.commit()

    @staticmethod
    def update_order_scrapped(order_id):
        db = BaseService.db()
        db.execute(
            "UPDATE orders SET scrapped = (SELECT COALESCE(SUM(scrapped),0) FROM order_processes WHERE order_id = ?), "
            "updated_at = datetime('now','localtime') WHERE id = ?", (order_id, order_id)
        )
        db.commit()

    @staticmethod
    def insert_rework_record(order_id, process_id, user_id, quantity, reason):
        db = BaseService.db()
        db.execute(
            "INSERT INTO rework_records (order_id, process_id, user_id, quantity, reason) VALUES (?,?,?,?,?)",
            (order_id, process_id, user_id, quantity, reason)
        )
        db.commit()

    @staticmethod
    def update_order_process_rework(order_id, process_id, new_rework):
        db = BaseService.db()
        db.execute(
            "UPDATE order_processes SET rework = ? WHERE order_id = ? AND process_id = ?",
            (new_rework, order_id, process_id)
        )
        db.commit()

    @staticmethod
    def update_order_rework(order_id):
        db = BaseService.db()
        db.execute(
            "UPDATE orders SET rework = (SELECT COALESCE(SUM(rework),0) FROM order_processes WHERE order_id = ?), "
            "updated_at = datetime('now','localtime') WHERE id = ?", (order_id, order_id)
        )
        db.commit()

    # ======================== 库存相关 ========================

    @staticmethod
    def find_inventory_by_model(product_code):
        db = BaseService.db()
        return db.execute(
            "SELECT id, product_model, product_name, quantity FROM inventory WHERE product_model = ?",
            (product_code,)
        ).fetchone()

    @staticmethod
    def find_or_create_inventory(product_code, product_name):
        db = BaseService.db()
        inv = db.execute(
            "SELECT id, product_model FROM inventory WHERE product_model = ?",
            (product_code,)
        ).fetchone()
        if inv:
            return inv["id"]
        cur = db.execute(
            "INSERT INTO inventory (product_model, product_name, quantity) VALUES (?, ?, 0)",
            (product_code, product_name or product_code)
        )
        db.commit()
        return cur.lastrowid

    @staticmethod
    def check_inventory_log_dup(order_id, serial_no=None):
        db = BaseService.db()
        if serial_no:
            return db.execute(
                "SELECT id FROM inventory_logs WHERE order_id = ? AND type = 'in' AND remark LIKE ?",
                (order_id, "%" + serial_no + "%")
            ).fetchone()
        return db.execute(
            "SELECT id FROM inventory_logs WHERE order_id = ? AND type = 'in'", (order_id,)
        ).fetchone()

    @staticmethod
    def stock_in(inv_id, quantity, order_id, order_no, user_id, user_name):
        db = BaseService.db()
        db.execute(
            "UPDATE inventory SET quantity = quantity + ?, updated_at = datetime('now','localtime') WHERE id = ?",
            (quantity, inv_id)
        )
        db.execute(
            "INSERT INTO inventory_logs (inventory_id, type, quantity, order_id, order_no, remark, operator_id, operator_name) "
            "VALUES (?, 'in', ?, ?, ?, ?, ?, ?)",
            (inv_id, quantity, order_id, order_no, "Order complete auto-inbound", user_id, user_name)
        )
        db.commit()

    # ======================== 权限范围 ========================

    @staticmethod
    def check_order_scope(order_id, pids):
        db = BaseService.db()
        placeholders = ",".join("?" for _ in pids)
        row = db.execute(
            f"SELECT 1 FROM order_processes WHERE order_id = ? AND process_id IN ({placeholders})",
            [order_id] + pids
        ).fetchone()
        return row is not None
