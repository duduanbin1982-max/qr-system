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


    # ======================== 自动入库 ========================

    @staticmethod
    def auto_inbound_for_item(order_id, user_id, user_name, serial_no=None, app_logger=None):
        """Per-item auto-inbound: triggered when a piece completes its last process.
        Migrated from routes/scan_helpers.py to eliminate cross-route dependency.
        """
        try:
            order_row = ScanHelperService.get_order_for_stock(order_id)
            if not order_row or not order_row['product_code']:
                if app_logger:
                    app_logger.info('auto_inbound: order %s has no product_code, skip', order_id)
                return

            product_code = order_row['product_code']
            product_name = order_row['product_name'] or product_code
            inv_id = ScanHelperService.find_or_create_inventory(product_code, product_name)

            dup = ScanHelperService.check_inventory_log_dup(order_id, serial_no)
            if dup:
                if app_logger:
                    app_logger.info('auto_inbound: order %s serial %s already inbounded, skip', order_id, serial_no)
                return

            qty = 1 if serial_no else (order_row['quantity'] or 0)
            remark = 'Auto inbound'
            if serial_no:
                remark = 'Auto inbound - SN:' + serial_no

            ScanHelperService.stock_in(inv_id, qty, order_id, order_row['order_no'], user_id, user_name)
            if app_logger:
                app_logger.info('auto_inbound: order %s serial %s qty %s -> inventory %s',
                                order_id, serial_no, qty, product_code)
        except Exception as e:
            if app_logger:
                app_logger.warning('auto_inbound failed: %s', e)

    # ======================== 报工写入（从 routes/scan_helpers.py 迁移） ========================

    @staticmethod
    def execute_report_write(db, report_type, order_id, process_id, user_id, user_name,
                              quantity, remark, serial_no, need_approval, record_type='normal'):
        """共享报工写入逻辑 — work_records.type 使用 report_type (normal/scrap/rework)。
        Migrated from routes/scan_helpers.py to eliminate cross-route dependency.
        """
        from modules.app import app as _app
        work_status = 'pending' if need_approval else 'approved'

        if serial_no:
            quantity_local = 1
        else:
            quantity_local = quantity

        if report_type == 'normal':
            wr_id = ScanHelperService.insert_work_record(
                order_id, process_id, user_id, report_type, quantity_local, remark, work_status, serial_no)

            if need_approval:
                ScanHelperService.insert_approval_record(wr_id)

            if work_status == 'approved':
                op = ScanHelperService.get_order_process(order_id, process_id)
                if op:
                    new_completed = (op['completed'] or 0) + quantity_local
                    ScanHelperService.update_order_process_completed(order_id, process_id, new_completed)

                if not serial_no and op:
                    if ScanHelperService.is_last_process(order_id, process_id):
                        ScanHelperService.auto_inbound_for_item(order_id, user_id, user_name, serial_no=None, app_logger=_app.logger)

            if serial_no:
                current_op = ScanHelperService.get_order_process(order_id, process_id)
                if current_op:
                    item = ScanHelperService.get_product_item(serial_no)
                    if item:
                        current_seq = current_op['seq_order']
                        next_op = ScanHelperService.find_next_process(order_id, current_seq)
                        item_version = item['version'] or 1
                        if next_op:
                            cur = ScanHelperService.advance_product_item(item['id'], next_op['process_id'], item_version)
                            if cur.rowcount == 0:
                                raise ValueError(f'序列号 {serial_no} 已被其他操作修改，请刷新后重试')
                        else:
                            cur = ScanHelperService.complete_product_item(item['id'], item_version)
                            if cur.rowcount == 0:
                                raise ValueError(f'序列号 {serial_no} 已被其他操作修改，请刷新后重试')
                            ScanHelperService.auto_inbound_for_item(order_id, user_id, user_name, serial_no, app_logger=_app.logger)

                ScanHelperService.update_order_completed(order_id)
                order_info = ScanHelperService.get_order_quantity(order_id)
                if order_info:
                    completed_cnt = ScanHelperService.count_completed_items(order_id)
                    if completed_cnt >= order_info['quantity']:
                        ScanHelperService.complete_order(order_id)

        elif report_type == 'scrap':
            reason = remark or ''
            ScanHelperService.insert_scrap_record(order_id, process_id, user_id, quantity, reason)
            op = ScanHelperService.get_order_process(order_id, process_id)
            if op:
                new_scrapped = (op['scrapped'] or 0) + quantity
                ScanHelperService.update_order_process_scrapped(order_id, process_id, new_scrapped)
            ScanHelperService.update_order_scrapped(order_id)

        elif report_type == 'rework':
            reason = remark or ''
            ScanHelperService.insert_rework_record(order_id, process_id, user_id, quantity, reason)
            op = ScanHelperService.get_order_process(order_id, process_id)
            if op:
                new_rework = (op['rework'] or 0) + quantity
                ScanHelperService.update_order_process_rework(order_id, process_id, new_rework)
            ScanHelperService.update_order_rework(order_id)


    # ======================== 权限范围 ========================

    @staticmethod
    def check_order_scope(order_id, pids):
        # Guard: None means "all processes allowed" (admin/no scope restriction)
        if pids is None:
            return True
        if not pids:
            return False
        db = BaseService.db()
        placeholders = ",".join("?" for _ in pids)
        row = db.execute(
            f"SELECT 1 FROM order_processes WHERE order_id = ? AND process_id IN ({placeholders})",
            [order_id] + pids
        ).fetchone()
        return row is not None
