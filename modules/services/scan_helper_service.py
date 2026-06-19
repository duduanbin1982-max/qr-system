"""qr-system — ScanHelperService（扫码报工核心数据操作）
CRITICAL FIX: 所有写操作事务化 — 消除 23 个裸 db.commit()，统一使用 BaseService.transaction()
"""
import logging
from datetime import datetime
from modules.services import BaseService
from modules.repositories.scan_repository import ScanRepository
from modules.repositories.order_material_repository import OrderMaterialRepository
from modules.repositories.product_bom_repository import ProductBomRepository

_logger = logging.getLogger(__name__)


class ScanHelperService:
    """扫码报工辅助 - 所有 DB 操作集中管理，写操作接受可选 db 参数实现事务共享。"""

    # ======================== 内部辅助 ========================

    @staticmethod
    def _db(db=None):
        """获取数据库连接：优先使用传入的 db（事务中），否则新建连接。"""
        return db if db is not None else BaseService.db()

    # ======================== 订单查询 ========================

    @staticmethod
    def get_order_by_no(order_no, db=None):
        return ScanHelperService._db(db).execute(
            "SELECT * FROM orders WHERE order_no = ? AND deleted_at IS NULL", (order_no,)
        ).fetchone()

    @staticmethod
    def get_order(order_id, db=None):
        return ScanHelperService._db(db).execute(
            "SELECT * FROM orders WHERE id = ? AND deleted_at IS NULL", (order_id,)
        ).fetchone()

    @staticmethod
    def get_order_for_stock(order_id, db=None):
        return ScanHelperService._db(db).execute(
            "SELECT o.id, o.order_no, o.product_code, o.product_name, o.quantity, p.spec FROM orders o LEFT JOIN products p ON o.product_code = p.product_code WHERE o.id = ?",
            (order_id,)
        ).fetchone()

    @staticmethod
    def get_order_quantity(order_id, db=None):
        return ScanHelperService._db(db).execute(
            "SELECT quantity FROM orders WHERE id = ?", (order_id,)
        ).fetchone()

    # ======================== 产品序列号查询 ========================

    @staticmethod
    def get_product_item(serial_no, db=None):
        return ScanHelperService._db(db).execute(
            "SELECT * FROM product_items WHERE serial_no = ?", (serial_no,)
        ).fetchone()

    @staticmethod
    def get_product_item_by_position(order_id, position_no, db=None):
        return ScanHelperService._db(db).execute(
            "SELECT * FROM product_items WHERE order_id = ? AND position_no = ?",
            (order_id, position_no)
        ).fetchone()

    @staticmethod
    def get_product_items_by_order(order_id, db=None):
        return ScanHelperService._db(db).execute(
            "SELECT * FROM product_items WHERE order_id = ? ORDER BY position_no",
            (order_id,)
        ).fetchall()

    # ======================== 工序相关查询 ========================

    @staticmethod
    def get_order_process(order_id, process_id, db=None):
        return ScanHelperService._db(db).execute(
            "SELECT * FROM order_processes WHERE order_id = ? AND process_id = ?",
            (order_id, process_id)
        ).fetchone()

    @staticmethod
    def check_process_in_order(order_id, process_id, db=None):
        return ScanHelperService._db(db).execute(
            "SELECT id FROM order_processes WHERE order_id = ? AND process_id = ?",
            (order_id, process_id)
        ).fetchone()

    @staticmethod
    def get_order_processes(order_id, db=None):
        return ScanHelperService._db(db).execute(
            "SELECT op.*, p.name as process_name FROM order_processes op "
            "JOIN processes p ON op.process_id = p.id "
            "WHERE op.order_id = ? ORDER BY op.seq_order", (order_id,)
        ).fetchall()

    @staticmethod
    def get_prev_incomplete_processes(order_id, current_seq, db=None):
        return ScanHelperService._db(db).execute(
            "SELECT op.seq_order, p.name as process_name FROM order_processes op "
            "JOIN processes p ON op.process_id = p.id "
            "WHERE op.order_id = ? AND op.seq_order < ? AND (op.completed IS NULL OR op.completed = 0) "
            "ORDER BY op.seq_order", (order_id, current_seq)
        ).fetchall()
    @staticmethod
    def check_process_order(order_id, current_seq, db=None):
        """Check sequential process order. Returns (None, None) if OK, or (error_json, status_code)."""
        from modules.db import get_setting
        mode = get_setting("process_order_mode", "sequential")
        if mode == "out_of_order":
            return None, None
        prev = ScanHelperService.get_prev_incomplete_processes(order_id, current_seq, db)
        if prev:
            names = "\u3001".join([p["process_name"] for p in prev])
            return {"error": f"\u8bf7\u5148\u5b8c\u6210\u524d\u7f6e\u5de5\u5e8f\uff1a{names}"}, 400
        return None, None

    @staticmethod
    def check_quantity_limits(order_id, current_seq, current_completed, quantity, order_quantity, db=None):
        """Check quantity limits. Returns (None, None) or (error_json, status_code)."""
        from modules.db import get_setting
        # Upper limit: previous process completed count
        if get_setting("limit_by_prev_process", "1") == "1" and current_seq > 1:
            prev_op = ScanHelperService.get_prev_order_process(order_id, current_seq, db)
            if prev_op:
                new_completed = (current_completed or 0) + quantity
                prev_completed = prev_op["completed"] or 0
                if new_completed > prev_completed:
                    return {"error": f"报工数量不能超过上道工序({prev_op['process_name']})的累计数量 {prev_completed}"}, 400
        # Order total limit
        if get_setting("limit_by_order_qty", "1") == "1":
            new_completed = (current_completed or 0) + quantity
            if new_completed > order_quantity:
                return {"error": f"报工累计({new_completed})不能超过订单数量({order_quantity})"}, 400
        return None, None

    @staticmethod
    def get_prev_order_process(order_id, current_seq, db=None):
        """Find the actual previous process (max seq_order < current_seq), not seq-1."""
        return ScanHelperService._db(db).execute(
            "SELECT op.*, p.name as process_name FROM order_processes op "
            "JOIN processes p ON op.process_id = p.id "
            "WHERE op.order_id = ? AND op.seq_order < ? "
            "ORDER BY op.seq_order DESC LIMIT 1", (order_id, current_seq)
        ).fetchone()

    @staticmethod
    def find_next_process(order_id, current_seq, db=None):
        return ScanHelperService._db(db).execute(
            "SELECT op.process_id FROM order_processes op WHERE op.order_id = ? AND op.seq_order > ? "
            "ORDER BY op.seq_order LIMIT 1", (order_id, current_seq)
        ).fetchone()

    # ======================== 报工记录查询 ========================

    @staticmethod
    def get_last_process_seq(order_id, db=None):
        row = ScanHelperService._db(db).execute(
            "SELECT MAX(seq_order) as max_seq FROM order_processes WHERE order_id = ?",
            (order_id,)
        ).fetchone()
        return row["max_seq"] if row else None

    @staticmethod
    def is_last_process(order_id, process_id, db=None):
        d = ScanHelperService._db(db)
        max_row = d.execute(
            "SELECT MAX(seq_order) as max_seq FROM order_processes WHERE order_id = ?",
            (order_id,)
        ).fetchone()
        if not max_row or max_row["max_seq"] is None:
            return False
        cur_row = d.execute(
            "SELECT seq_order FROM order_processes WHERE order_id = ? AND process_id = ?",
            (order_id, process_id)
        ).fetchone()
        return cur_row is not None and cur_row["seq_order"] == max_row["max_seq"]

    @staticmethod
    def get_work_records(order_id, db=None, limit=None):
        d = ScanHelperService._db(db)
        if limit:
            return d.execute(
                "SELECT wr.*, u.name as worker_name FROM work_records wr "
                "LEFT JOIN users u ON wr.user_id = u.id "
                "WHERE wr.order_id = ? ORDER BY wr.created_at DESC LIMIT ?", (order_id, limit)
            ).fetchall()
        return d.execute(
            "SELECT wr.*, u.name as worker_name FROM work_records wr "
            "LEFT JOIN users u ON wr.user_id = u.id "
            "WHERE wr.order_id = ? ORDER BY wr.created_at DESC", (order_id,)
        ).fetchall()

    @staticmethod
    @staticmethod
    def get_user_order_reports(order_id, user_id, db=None):
        d = ScanHelperService._db(db)
        return d.execute(
            "SELECT id FROM work_records WHERE order_id = ? AND user_id = ? AND type = 'normal'",
            (order_id, user_id)
        ).fetchone()

    @staticmethod
    def get_process_name(process_id, db=None):
        d = ScanHelperService._db(db)
        row = d.execute("SELECT name FROM processes WHERE id = ?", (process_id,)).fetchone()
        return row["name"] if row else "未知工序"

    def check_duplicate_normal_report(order_id, process_id, serial_no, user_id, db=None):
        d = ScanHelperService._db(db)
        if serial_no:
            return d.execute(
                "SELECT id FROM work_records WHERE order_id = ? AND process_id = ? "
                "AND serial_no = ? AND type = 'normal' AND status != 'rejected'", (order_id, process_id, serial_no)
            ).fetchone()
        return d.execute(
            "SELECT id FROM work_records WHERE order_id = ? AND process_id = ? "
            "AND user_id = ? AND type = 'normal' AND status != 'rejected'", (order_id, process_id, user_id)
        ).fetchone()


    @staticmethod
    def check_serial_duplicate_in_order(order_id, serial_no, user_id, db=None):
        """Check if a serial_no has been reported by this user on ANY process in this order."""
        d = ScanHelperService._db(db)
        return d.execute(
            "SELECT id FROM work_records WHERE order_id = ? AND serial_no = ? AND user_id = ? LIMIT 1",
            (order_id, serial_no, user_id)
        ).fetchone() is not None
    @staticmethod
    def check_duplicate_defect_report(order_id, process_id, user_id, report_type, db=None):
        d = ScanHelperService._db(db)
        return d.execute(
            "SELECT id FROM work_records WHERE order_id = ? AND process_id = ? "
            "AND user_id = ? AND type = ? "
            "AND created_at > datetime('now', '-10 seconds')",
            (order_id, process_id, user_id, report_type)
        ).fetchone()

    @staticmethod
    def check_approval_required(process_id, db=None):
        from modules.db import get_setting
        # Master switch: if approval_enabled is off, skip all approval checks
        if get_setting("approval_enabled", "1") != "1":
            return None
        return ScanHelperService._db(db).execute(
            "SELECT id FROM approval_config WHERE process_id = ? AND require_approval = 1",
            (process_id,)
        ).fetchone()

    # ======================== 报工写入操作（全部接受 db 参数，不自行 commit） ========================

    @staticmethod
    def insert_work_record(order_id, process_id, user_id, report_type, quantity, remark, work_status, serial_no, db=None):
        d = ScanHelperService._db(db)
        cur = d.execute(
            "INSERT INTO work_records (order_id, process_id, user_id, type, quantity, remark, status, serial_no) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (order_id, process_id, user_id, report_type, quantity, remark, work_status, serial_no)
        )
        return cur.lastrowid

    @staticmethod
    def insert_approval_record(wr_id, db=None):
        ScanHelperService._db(db).execute(
            "INSERT INTO approval_records (work_record_id, status) VALUES (?, 'pending')", (wr_id,)
        )

    @staticmethod
    def update_order_process_completed(order_id, process_id, new_completed, db=None):
        ScanHelperService._db(db).execute(
            "UPDATE order_processes SET completed = ? WHERE order_id = ? AND process_id = ?",
            (new_completed, order_id, process_id)
        )

    @staticmethod
    def advance_product_item(item_id, next_process_id, version, db=None):
        return ScanHelperService._db(db).execute(
            "UPDATE product_items SET current_process_id = ?, status = 'in_progress', version = version + 1 "
            "WHERE id = ? AND version = ?", (next_process_id, item_id, version)
        )

    @staticmethod
    def complete_product_item(item_id, version, db=None):
        return ScanHelperService._db(db).execute(
            "UPDATE product_items SET current_process_id = NULL, status = 'completed', "
            "completed_at = datetime('now','localtime'), version = version + 1 WHERE id = ? AND version = ?",
            (item_id, version)
        )

    @staticmethod
    def update_order_completed(order_id, db=None):
        ScanHelperService._db(db).execute(
            "UPDATE orders SET completed = (SELECT COUNT(*) FROM product_items WHERE order_id = ? AND status = 'completed'), "
            "updated_at = datetime('now','localtime'), status = 'producing' WHERE id = ?",
            (order_id, order_id)
        )

    @staticmethod
    def count_completed_items(order_id, db=None):
        return ScanHelperService._db(db).execute(
            "SELECT COUNT(*) as cnt FROM product_items WHERE order_id = ? AND status = 'completed'", (order_id,)
        ).fetchone()["cnt"]

    @staticmethod
    def complete_order(order_id, db=None):
        ScanHelperService._db(db).execute(
            "UPDATE orders SET status = 'completed', updated_at = datetime('now','localtime') WHERE id = ?", (order_id,)
        )

    # ======================== 废品/返工操作 ========================

    @staticmethod
    def insert_scrap_record(order_id, process_id, user_id, quantity, reason, db=None):
        ScanHelperService._db(db).execute(
            "INSERT INTO scrap_records (order_id, process_id, user_id, quantity, reason) VALUES (?,?,?,?,?)",
            (order_id, process_id, user_id, quantity, reason)
        )

    @staticmethod
    def update_order_process_scrapped(order_id, process_id, new_scrapped, db=None):
        ScanHelperService._db(db).execute(
            "UPDATE order_processes SET scrapped = ? WHERE order_id = ? AND process_id = ?",
            (new_scrapped, order_id, process_id)
        )

    @staticmethod
    def update_order_scrapped(order_id, db=None):
        ScanHelperService._db(db).execute(
            "UPDATE orders SET scrapped = (SELECT COALESCE(SUM(scrapped),0) FROM order_processes WHERE order_id = ?), "
            "updated_at = datetime('now','localtime') WHERE id = ?", (order_id, order_id)
        )

    @staticmethod
    def insert_rework_record(order_id, process_id, user_id, quantity, reason, db=None):
        ScanHelperService._db(db).execute(
            "INSERT INTO rework_records (order_id, process_id, user_id, quantity, reason) VALUES (?,?,?,?,?)",
            (order_id, process_id, user_id, quantity, reason)
        )

    @staticmethod
    def update_order_process_rework(order_id, process_id, new_rework, db=None):
        ScanHelperService._db(db).execute(
            "UPDATE order_processes SET rework = ? WHERE order_id = ? AND process_id = ?",
            (new_rework, order_id, process_id)
        )

    @staticmethod
    def update_order_rework(order_id, db=None):
        ScanHelperService._db(db).execute(
            "UPDATE orders SET rework = (SELECT COALESCE(SUM(rework),0) FROM order_processes WHERE order_id = ?), "
            "updated_at = datetime('now','localtime') WHERE id = ?", (order_id, order_id)
        )

    # ======================== 库存相关 ========================

    @staticmethod
    def find_inventory_by_model(product_code, db=None):
        return ScanHelperService._db(db).execute(
            "SELECT id, product_model, product_name, quantity FROM inventory WHERE product_model = ?",
            (product_code,)
        ).fetchone()

    @staticmethod
    def find_or_create_inventory(product_code, product_name, order_id=None, specification="", db=None):
        """Per-order inventory: each order gets its own inventory record, no merging."""
        d = ScanHelperService._db(db)
        if order_id:
            inv = d.execute(
                "SELECT id FROM inventory WHERE product_model = ? AND order_id = ?",
                (product_code, order_id)
            ).fetchone()
            if inv:
                return inv["id"]
        # Always create new per-order record; never reuse unassigned inventory
        cur = d.execute(
            "INSERT INTO inventory (product_model, product_name, quantity, order_id, specification) VALUES (?, ?, 0, ?, ?)",
            (product_code, product_name or product_code, order_id, specification or "")
        )
        return cur.lastrowid
    @staticmethod
    def check_inventory_log_dup(order_id, serial_no=None, db=None):
        d = ScanHelperService._db(db)
        if serial_no:
            return d.execute(
                "SELECT id FROM inventory_logs WHERE order_id = ? AND type = 'in' AND remark LIKE ?",
                (order_id, "%" + serial_no + "%")
            ).fetchone()
        return d.execute(
            "SELECT id FROM inventory_logs WHERE order_id = ? AND type = 'in'", (order_id,)
        ).fetchone()

    @staticmethod
    def stock_in(inv_id, quantity, order_id, order_no, user_id, user_name, db=None):
        d = ScanHelperService._db(db)
        d.execute(
            "UPDATE inventory SET quantity = quantity + ?, updated_at = datetime('now','localtime') WHERE id = ?",
            (quantity, inv_id)
        )
        d.execute(
            "INSERT INTO inventory_logs (inventory_id, type, quantity, order_id, order_no, remark, operator_id, operator_name) "
            "VALUES (?, 'in', ?, ?, ?, ?, ?, ?)",
            (inv_id, quantity, order_id, order_no, "Order complete auto-inbound", user_id, user_name)
        )

    # ======================== 自动入库 ========================

    @staticmethod
    def auto_inbound_for_item(order_id, user_id, user_name, serial_no=None, db=None):
        """Per-item auto-inbound: triggered when a piece completes its last process."""
        d = ScanHelperService._db(db)
        try:
            order_row = ScanHelperService.get_order_for_stock(order_id, db=d)
            if not order_row or not order_row['product_code']:
                _logger.info('auto_inbound: order %s has no product_code, skip', order_id)
                return

            product_code = order_row['product_code']
            product_name = order_row['product_name'] or product_code
            inv_id = ScanHelperService.find_or_create_inventory(product_code, product_name, order_id, (order_row["spec"] or "") if order_row else "", db=d)

            dup = ScanHelperService.check_inventory_log_dup(order_id, serial_no, db=d)
            if dup:
                _logger.info('auto_inbound: dup detected for order %s item %s, skip', order_id, serial_no)
                return

            ScanHelperService.stock_in(inv_id, 1, order_id, order_row['order_no'], user_id, user_name, db=d)
        except Exception as e:
            _logger.warning('auto_inbound failed: %s', e)

    # ======================== 报工写入（事务化核心） ========================

    @staticmethod
    def execute_report_write(report_type, order_id, process_id, user_id, user_name,
                              quantity, remark, serial_no, need_approval, record_type='normal'):
        """共享报工写入逻辑。整个方法在事务中执行，全部成功或全部回滚。"""
        with BaseService.transaction() as db:
            # === In-transaction re-checks (TOCTOU protection) ===
            if report_type == "normal":
                dup = ScanHelperService.check_duplicate_normal_report(order_id, process_id, serial_no, user_id, db=db)
                if dup:
                    msg = "Sequence {} already reported at this process".format(serial_no) if serial_no else "Already reported at this process"
                    raise ValueError(msg)
            elif report_type in ("scrap", "rework"):
                dup = ScanHelperService.check_duplicate_defect_report(order_id, process_id, user_id, report_type, db=db)
                if dup:
                    raise ValueError("Duplicate defect report")
            current_op = dict(ScanHelperService.get_order_process(order_id, process_id, db=db) or {})
            if not current_op:
                raise ValueError("Process not in order route")
            # 顺序 & 数量上限检查仅对普通报工生效
            if report_type == "normal":
                err, code = ScanHelperService.check_process_order(order_id, current_op.get("seq_order", 0), db=db)
                if err:
                    raise ValueError(err.get("error", "Process order check failed"))
                order = dict(ScanHelperService.get_order(order_id, db=db) or {})
                if order:
                    err2, code2 = ScanHelperService.check_quantity_limits(
                        order_id, current_op.get("seq_order", 0), current_op.get("completed", 0) or 0, quantity, order.get("quantity", 0), db=db)
                    if err2:
                        raise ValueError(err2.get("error", "Quantity limit exceeded"))
            work_status = 'pending' if need_approval else 'approved'
            quantity_local = 1 if serial_no else quantity

            if report_type == 'normal':
                wr_id = ScanHelperService.insert_work_record(
                    order_id, process_id, user_id, report_type, quantity_local, remark, work_status, serial_no, db=db)

                if need_approval:
                    ScanHelperService.insert_approval_record(wr_id, db=db)

                if work_status == 'approved':
                    op = ScanHelperService.get_order_process(order_id, process_id, db=db)
                    if op:
                        new_completed = (op['completed'] or 0) + quantity_local
                        ScanHelperService.update_order_process_completed(order_id, process_id, new_completed, db=db)

                    # Auto-create first-article inspection if this is the first work on this process
                    first_count = db.execute(
                        "SELECT COUNT(*) FROM work_records WHERE order_id=? AND process_id=? AND type='normal' AND status='approved'",
                        (order_id, process_id)
                    ).fetchone()[0]
                    if first_count <= 1:
                        # Check if inspection already exists
                        existing = db.execute(
                            "SELECT id FROM quality_inspections WHERE order_id=? AND process_id=? AND inspection_type='first_article'",
                            (order_id, process_id)
                        ).fetchone()
                        if not existing:
                            try:
                                from modules.services.quality_service import QualityService
                                QualityService.create_inspection({
                                    'order_id': order_id,
                                    'process_id': process_id,
                                    'inspection_type': 'first_article',
                                    'quantity_checked': 1,
                                    'quantity_passed': 0,
                                    'quantity_failed': 0,
                                    'defect_category': '',
                                    'defect_quantity': 0,
                                    'notes': '自动创建: 首件报工',
                                    'inspected_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                }, user_id)
                            except Exception:
                                pass  # Non-critical

                    # Auto-deduct materials via ScanRepository
                    ScanRepository.deduct_materials_for_process(
                        order_id, process_id, quantity_local, user_id, user_name, db=db)

                    if not serial_no and op:
                        order_status = db.execute('SELECT status FROM orders WHERE id = ?', (order_id,)).fetchone()
                        if order_status and order_status['status'] != 'completed':
                            if ScanHelperService.is_last_process(order_id, process_id, db=db):
                                ScanHelperService.auto_inbound_for_item(order_id, user_id, user_name, serial_no=None, db=db)

                if serial_no:
                    current_op = dict(ScanHelperService.get_order_process(order_id, process_id, db=db) or {})
                    if current_op:
                        item = ScanHelperService.get_product_item(serial_no, db=db)
                        if item:
                            current_seq = current_op['seq_order']
                            next_op = ScanHelperService.find_next_process(order_id, current_seq, db=db)
                            item_version = item['version'] or 1
                            if next_op:
                                cur = ScanHelperService.advance_product_item(item['id'], next_op['process_id'], item_version, db=db)
                                if cur.rowcount == 0:
                                    raise ValueError(f'序列号 {serial_no} 已被其他操作修改，请刷新后重试')
                            else:
                                cur = ScanHelperService.complete_product_item(item['id'], item_version, db=db)
                                if cur.rowcount == 0:
                                    raise ValueError(f'序列号 {serial_no} 已被其他操作修改，请刷新后重试')
                                ScanHelperService.auto_inbound_for_item(order_id, user_id, user_name, serial_no, db=db)

                    ScanHelperService.update_order_completed(order_id, db=db)
                    order_info = ScanHelperService.get_order_quantity(order_id, db=db)
                    if order_info:
                        completed_cnt = ScanHelperService.count_completed_items(order_id, db=db)
                        if completed_cnt >= order_info['quantity']:
                            ScanHelperService.complete_order(order_id, db=db)

            elif report_type == 'scrap':
                reason = remark or ''
                ScanHelperService.insert_scrap_record(order_id, process_id, user_id, quantity, reason, db=db)
                op = ScanHelperService.get_order_process(order_id, process_id, db=db)
                if op:
                    new_scrapped = (op['scrapped'] or 0) + quantity
                    ScanHelperService.update_order_process_scrapped(order_id, process_id, new_scrapped, db=db)
                ScanHelperService.update_order_scrapped(order_id, db=db)

            elif report_type == 'rework':
                reason = remark or ''
                ScanHelperService.insert_rework_record(order_id, process_id, user_id, quantity, reason, db=db)
                op = ScanHelperService.get_order_process(order_id, process_id, db=db)
                if op:
                    new_rework = (op['rework'] or 0) + quantity
                    ScanHelperService.update_order_process_rework(order_id, process_id, new_rework, db=db)
                ScanHelperService.update_order_rework(order_id, db=db)

    # ======================== 权限范围 ========================

    @staticmethod
    def check_order_scope(order_id, pids, db=None):
        if pids is None:
            return True
        if not pids:
            return False
        d = ScanHelperService._db(db)
        placeholders = ",".join("?" for _ in pids)
        row = d.execute(
            f"SELECT 1 FROM order_processes WHERE order_id = ? AND process_id IN ({placeholders})",
            [order_id] + pids
        ).fetchone()
        return row is not None
