"""qr-system — ScanHelperService（扫码报工核心数据操作）
CRITICAL FIX: 所有写操作事务化 — 消除 23 个裸 db.commit()，统一使用 BaseService.transaction()
"""
from modules.services import BaseService
from modules.repositories.scan_repository import ScanRepository
from modules.setting_reader import get_setting


class ScanHelperService:
    """扫码报工辅助 - 所有 DB 操作集中管理，写操作接受可选 db 参数实现事务共享。"""

    # ======================== 内部辅助 ========================

    @staticmethod
    def _db(db=None):
        """获取数据库连接：优先使用传入的 db（事务中），否则新建连接。"""
        return db if db is not None else BaseService.db()

    # ======================== Order queries ========================

    @staticmethod
    def get_order_by_no(order_no, db=None):
        return ScanRepository.find_order_by_no(order_no, db=ScanHelperService._db(db))

    @staticmethod
    def get_order(order_id, db=None):
        return ScanRepository.get_order(order_id, db=ScanHelperService._db(db))

    @staticmethod
    def get_order_for_stock(order_id, db=None):
        return ScanRepository.get_order_for_stock(order_id, db=ScanHelperService._db(db))

    @staticmethod
    def get_order_quantity(order_id, db=None):
        return ScanRepository.get_order_quantity(order_id, db=ScanHelperService._db(db))

    # ======================== Product item queries ========================

    @staticmethod
    def get_product_item(serial_no, db=None):
        return ScanRepository.get_item_by_serial(serial_no, db=ScanHelperService._db(db))

    @staticmethod
    def get_product_item_by_position(order_id, position_no, db=None):
        return ScanRepository.get_item_by_position(order_id, position_no, db=ScanHelperService._db(db))

    @staticmethod
    def get_product_items_by_order(order_id, db=None):
        return ScanRepository.get_items_by_order(order_id, db=ScanHelperService._db(db))

    # ======================== Process queries ========================

    @staticmethod
    def get_order_process(order_id, process_id, db=None):
        return ScanRepository.get_order_process(order_id, process_id, db=ScanHelperService._db(db))

    @staticmethod
    def check_process_in_order(order_id, process_id, db=None):
        return ScanRepository.find_order_process_id(order_id, process_id, db=ScanHelperService._db(db))

    @staticmethod
    def get_order_processes(order_id, db=None):
        return ScanRepository.get_order_processes(order_id, db=ScanHelperService._db(db))

    @staticmethod
    def get_prev_incomplete_processes(order_id, current_seq, db=None):
        return ScanRepository.get_prev_incomplete_processes(order_id, current_seq, db=ScanHelperService._db(db))

    @staticmethod
    def check_process_order(order_id, current_seq, db=None):
        """Check sequential process order. Returns (None, None) if OK, or (error_json, status_code)."""
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
        if get_setting("limit_by_prev_process", "1") == "1" and current_seq > 1:
            prev_op = ScanHelperService.get_prev_order_process(order_id, current_seq, db)
            if prev_op:
                new_completed = (current_completed or 0) + quantity
                prev_completed = prev_op["completed"] or 0
                if new_completed > prev_completed:
                    return {"error": f"\u62a5\u5de5\u6570\u91cf\u4e0d\u80fd\u8d85\u8fc7\u4e0a\u9053\u5de5\u5e8f({prev_op['process_name']})\u7684\u7d2f\u8ba1\u6570\u91cf {prev_completed}"}, 400
        if get_setting("limit_by_order_qty", "1") == "1":
            new_completed = (current_completed or 0) + quantity
            if new_completed > order_quantity:
                return {"error": f"\u62a5\u5de5\u7d2f\u8ba1({new_completed})\u4e0d\u80fd\u8d85\u8fc7\u8ba2\u5355\u6570\u91cf({order_quantity})"}, 400
        return None, None

    @staticmethod
    def get_prev_order_process(order_id, current_seq, db=None):
        """Find the actual previous process (max seq_order < current_seq), not seq-1."""
        return ScanRepository.get_prev_order_process(order_id, current_seq, db=ScanHelperService._db(db))

    @staticmethod
    def find_next_process(order_id, current_seq, db=None):
        return ScanRepository.find_next_process(order_id, current_seq, db=ScanHelperService._db(db))

    # ======================== Work-record queries ========================

    @staticmethod
    def get_last_process_seq(order_id, db=None):
        return ScanRepository.get_last_process_seq(order_id, db=ScanHelperService._db(db))

    @staticmethod
    def is_last_process(order_id, process_id, db=None):
        return ScanRepository.is_last_process(order_id, process_id, db=ScanHelperService._db(db))

    @staticmethod
    def get_work_records(order_id, db=None, limit=None):
        return ScanRepository.get_work_records(order_id, db=ScanHelperService._db(db), limit=limit)

    @staticmethod
    def get_user_order_reports(order_id, user_id, db=None):
        return ScanRepository.get_user_order_report(order_id, user_id, db=ScanHelperService._db(db))

    @staticmethod
    def get_process_name(process_id, db=None):
        return ScanRepository.get_process_name(process_id, db=ScanHelperService._db(db))

    @staticmethod
    def check_duplicate_normal_report(order_id, process_id, serial_no, user_id, db=None):
        return ScanRepository.find_duplicate_normal_report(
            order_id, process_id, serial_no, user_id, db=ScanHelperService._db(db)
        )

    @staticmethod
    def check_serial_duplicate_in_order(order_id, serial_no, user_id, db=None):
        """Check if a serial_no has been reported by this user on ANY process in this order."""
        return ScanRepository.has_serial_duplicate_in_order(order_id, serial_no, user_id, db=ScanHelperService._db(db))

    @staticmethod
    def check_duplicate_defect_report(order_id, process_id, user_id, report_type, db=None):
        return ScanRepository.find_duplicate_defect_report(
            order_id, process_id, user_id, report_type, db=ScanHelperService._db(db)
        )

    @staticmethod
    def check_approval_required(process_id, db=None):
        if get_setting("approval_enabled", "1") != "1":
            return None
        return ScanRepository.find_approval_config(process_id, db=ScanHelperService._db(db))

    # ======================== 报工写入操作（全部接受 db 参数，不自行 commit） ========================

    @staticmethod
    def insert_work_record(order_id, process_id, user_id, report_type, quantity, remark, work_status, serial_no, db=None):
        return ScanRepository.insert_report_work_record(
            order_id,
            process_id,
            user_id,
            report_type,
            quantity,
            remark,
            work_status,
            serial_no,
            db=ScanHelperService._db(db),
        )

    @staticmethod
    def insert_approval_record(wr_id, db=None):
        """插入审批记录，已存在 pending 记录则跳过（防止重复提交）"""
        return ScanRepository.insert_approval_record(wr_id, db=ScanHelperService._db(db))

    @staticmethod
    def update_order_process_completed(order_id, process_id, new_completed, db=None):
        ScanRepository.update_order_process_completed(
            order_id,
            process_id,
            new_completed,
            db=ScanHelperService._db(db),
        )

    @staticmethod
    def advance_product_item(item_id, next_process_id, version, db=None):
        return ScanRepository.advance_product_item(
            item_id,
            next_process_id,
            version,
            db=ScanHelperService._db(db),
        )

    @staticmethod
    def complete_product_item(item_id, version, db=None):
        return ScanRepository.complete_product_item(item_id, version, db=ScanHelperService._db(db))

    @staticmethod
    def update_order_completed(order_id, db=None):
        ScanRepository.refresh_order_completion(order_id, db=ScanHelperService._db(db))

    @staticmethod
    def count_completed_items(order_id, db=None):
        return ScanRepository.count_completed_items(order_id, db=ScanHelperService._db(db))

    @staticmethod
    def complete_order(order_id, db=None):
        ScanRepository.complete_order(order_id, db=ScanHelperService._db(db))

    # ======================== 废品/返工操作 ========================

    @staticmethod
    def insert_scrap_record(order_id, process_id, user_id, quantity, reason, db=None):
        ScanRepository.insert_scrap_record(
            order_id,
            process_id,
            user_id,
            quantity,
            reason,
            db=ScanHelperService._db(db),
        )

    @staticmethod
    def update_order_process_scrapped(order_id, process_id, new_scrapped, db=None):
        ScanRepository.update_order_process_scrapped(
            order_id,
            process_id,
            new_scrapped,
            db=ScanHelperService._db(db),
        )

    @staticmethod
    def update_order_scrapped(order_id, db=None):
        ScanRepository.refresh_order_scrapped(order_id, db=ScanHelperService._db(db))

    @staticmethod
    def insert_rework_record(order_id, process_id, user_id, quantity, reason, db=None):
        ScanRepository.insert_rework_record(
            order_id,
            process_id,
            user_id,
            quantity,
            reason,
            db=ScanHelperService._db(db),
        )

    @staticmethod
    def update_order_process_rework(order_id, process_id, new_rework, db=None):
        ScanRepository.update_order_process_rework(
            order_id,
            process_id,
            new_rework,
            db=ScanHelperService._db(db),
        )

    @staticmethod
    def update_order_rework(order_id, db=None):
        ScanRepository.refresh_order_rework(order_id, db=ScanHelperService._db(db))

    # ======================== 库存相关 ========================

    @staticmethod
    def find_inventory_by_model(product_code, db=None):
        return ScanRepository.find_inventory_by_model(product_code, db=ScanHelperService._db(db))

    @staticmethod
    def find_or_create_inventory(product_code, product_name, order_id=None, specification="", db=None):
        """Per-order inventory: each order gets its own inventory record, no merging."""
        return ScanRepository.find_or_create_inventory(
            product_code,
            product_name,
            order_id,
            specification,
            db=ScanHelperService._db(db),
        )

    @staticmethod
    def check_inventory_log_dup(order_id, serial_no=None, db=None):
        return ScanRepository.find_inbound_inventory_log(order_id, serial_no, db=ScanHelperService._db(db))

    @staticmethod
    def stock_in(inv_id, quantity, order_id, order_no, user_id, user_name, db=None):
        ScanRepository.stock_in(
            inv_id,
            quantity,
            order_id,
            order_no,
            user_id,
            user_name,
            db=ScanHelperService._db(db),
        )

    # ======================== 权限范围 ========================

    @staticmethod
    def check_order_scope(order_id, pids, db=None):
        if pids is None:
            return True
        if not pids:
            return False
        return ScanRepository.order_has_process_in_scope(order_id, pids, db=ScanHelperService._db(db))
