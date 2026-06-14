# DEPRECATED — Use ScanHelperService in modules/services/scan_helper_service.py instead
# Kept for reference only; do not add new code here.
"""
qr-system - Scan helpers (extracted from scan.py)
"""
import base64
import json
from io import BytesIO

import qrcode
from datetime import datetime, timedelta
from functools import wraps

from flask import request, jsonify, g, send_file

from modules.app import app
from modules.db import get_db, get_setting, get_page_size
from modules.middleware.auth import check_auth, check_permission, audit_log
from modules.middleware.validate import validate_json
from modules.middleware.data_scope import get_user_process_ids
from modules.middleware.error_handler import handle_unexpected_error
from modules.middleware.helpers import get_json_body
from modules.services.inventory_service import InventoryService
from modules.services.scan_helper_service import ScanHelperService



# ============================================================


def _auto_inbound_for_item(order_id, user_id, user_name, serial_no=None):
    """Per-item auto-inbound: triggered when a piece completes its last process."""
    try:
        order_row = ScanHelperService.get_order_for_stock(order_id)
        if not order_row or not order_row['product_code']:
            app.logger.info('auto_inbound: order %s has no product_code, skip', order_id)
            return

        product_code = order_row['product_code']
        product_name = order_row['product_name'] or product_code

        # Auto-create inventory if not exists
        inv_id = ScanHelperService.find_or_create_inventory(product_code, product_name)

        # Dedup: per serial_no or per order
        dup = ScanHelperService.check_inventory_log_dup(order_id, serial_no)
        if dup:
            app.logger.info('auto_inbound: order %s serial %s already inbounded, skip', order_id, serial_no)
            return

        qty = 1 if serial_no else (order_row['quantity'] or 0)
        remark = 'Auto inbound'
        if serial_no:
            remark = 'Auto inbound - SN:' + serial_no

        ScanHelperService.stock_in(inv_id, qty, order_id, order_row['order_no'], user_id, user_name)
        app.logger.info('auto_inbound: order %s serial %s qty %s -> inventory %s',
                        order_id, serial_no, qty, product_code)
    except Exception as e:
        app.logger.warning('auto_inbound failed: %s', e)


def auto_stock_in(db, order_id, user_id, user_name):
    """DEPRECATED: Legacy function, use ScanHelperService.auto_inbound_for_item instead."""
    raise NotImplementedError('auto_stock_in is deprecated, use ScanHelperService')


def _execute_report_write(db, report_type, order_id, process_id, user_id, user_name,
                           quantity, remark, serial_no, need_approval, record_type='normal'):
    """共享报工写入逻辑 — work_records.type 使用 report_type (normal/scrap/rework)。"""
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

            # Order mode (no serial): check if this is the last process
            if not serial_no and op:
                if ScanHelperService.is_last_process(order_id, process_id):
                    _auto_inbound_for_item(order_id, user_id, user_name, serial_no=None)

        # 更新产品序列号的当前工序（必须在 orders.completed 更新之前）
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
                        # Per-item auto inbound on last process completion
                        _auto_inbound_for_item(order_id, user_id, user_name, serial_no)

            # 更新订单完成数：必须在 product_items.status 更新之后
            ScanHelperService.update_order_completed(order_id)
            # 检查订单是否全部完成
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

def _check_order_scope(order_id, db=None):
    pids = get_user_process_ids(g.current_user)
    if pids is None:
        return True
    if not pids:
        return False
    return ScanHelperService.check_order_scope(order_id, pids)

# Work Report (扫码报工)
# ============================================================
