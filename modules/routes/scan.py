"""
qr-system — 扫码报工路由 (desktop scan + mobile H5 + QR codes)
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
from modules.middleware.data_scope import get_user_process_ids
from modules.middleware.error_handler import handle_unexpected_error
from modules.middleware.helpers import get_json_body
from modules.services.inventory_service import InventoryService



# ============================================================


def auto_stock_in(db, order_id, user_id, user_name):
    """Order completion auto-inventory: match inventory.product_model = orders.product_code"""
    try:
        order_row = db.execute(
            'SELECT id, order_no, product_code, product_name, quantity FROM orders WHERE id = ?',
            (order_id,)
        ).fetchone()
        if not order_row or not order_row['product_code']:
            return
        inv = db.execute(
            'SELECT id, product_model, product_name, quantity FROM inventory WHERE product_model = ?',
            (order_row['product_code'],)
        ).fetchone()
        if not inv:
            return
        dup = db.execute(
            'SELECT id FROM inventory_logs WHERE order_id = ? AND type = "in"',
            (order_id,)
        ).fetchone()
        if dup:
            return
        db.execute(
            'UPDATE inventory SET quantity = quantity + ?, updated_at = datetime("now","localtime") WHERE id = ?',
            (order_row['quantity'], inv['id'])
        )
        db.execute(
            'INSERT INTO inventory_logs (inventory_id, type, quantity, order_id, order_no, remark, operator_id, operator_name) '
            'VALUES (?, "in", ?, ?, ?, ?, ?, ?)',
            (inv['id'], order_row['quantity'], order_id, order_row['order_no'],
             '订单完成自动入库', user_id, user_name)
        )
    except Exception:
        pass


def _execute_report_write(db, report_type, order_id, process_id, user_id, user_name,
                           quantity, remark, serial_no, need_approval, record_type='normal'):
    """共享报工写入逻辑 — 由 work_report 和 mobile_report 共用"""
    work_status = 'pending' if need_approval else 'approved'
    
    if report_type == 'normal':
        cur = db.execute(
            'INSERT INTO work_records (order_id, process_id, user_id, type, quantity, remark, status, serial_no) VALUES (?,?,?,?,?,?,?,?)',
            (order_id, process_id, user_id, record_type, quantity, remark, work_status, serial_no))
        wr_id = cur.lastrowid

        if need_approval:
            db.execute('INSERT INTO approval_records (work_record_id, status) VALUES (?, "pending")', (wr_id,))

        if work_status == 'approved':
            op = db.execute('SELECT * FROM order_processes WHERE order_id = ? AND process_id = ?',
                            (order_id, process_id)).fetchone()
            if op:
                new_completed = (op['completed'] or 0) + quantity
                db.execute('UPDATE order_processes SET completed = ? WHERE order_id = ? AND process_id = ?',
                           (new_completed, order_id, process_id))

            # 更新订单完成数：统计已完成的工件数量（而非工序累计总和）
            db.execute('UPDATE orders SET completed = (SELECT COUNT(*) FROM product_items WHERE order_id = ? AND status = "completed"), '
                       'updated_at = datetime("now","localtime"), status = "producing" WHERE id = ?',
                       (order_id, order_id))
            # 检查订单是否全部完成
            order_info = db.execute('SELECT quantity FROM orders WHERE id = ?', (order_id,)).fetchone()
            if order_info:
                completed_cnt = db.execute(
                    'SELECT COUNT(*) as cnt FROM product_items WHERE order_id = ? AND status = "completed"',
                    (order_id,)
                ).fetchone()['cnt']
                if completed_cnt >= order_info['quantity']:
                    db.execute('UPDATE orders SET status = "completed", completed_at = datetime("now","localtime") WHERE id = ?',
                               (order_id,))
                    # 自动入库：匹配 inventory.product_model = orders.product_code
                    auto_stock_in(db, order_id, user_id, user_name)

        # 更新产品序列号的当前工序（推进到下一道工序）
        if serial_no:
            current_op = db.execute('SELECT * FROM order_processes WHERE order_id = ? AND process_id = ?',
                                    (order_id, process_id)).fetchone()
            if current_op:
                item = db.execute('SELECT * FROM product_items WHERE serial_no = ?', (serial_no,)).fetchone()
                if item:
                    current_seq = current_op['seq_order']
                    next_op = db.execute(
                        'SELECT op.process_id FROM order_processes op WHERE op.order_id = ? AND op.seq_order > ? ORDER BY op.seq_order LIMIT 1',
                        (order_id, current_seq)
                    ).fetchone()
                    if next_op:
                        db.execute('UPDATE product_items SET current_process_id = ?, status = "in_progress" WHERE id = ?',
                                   (next_op['process_id'], item['id']))
                    else:
                        db.execute('UPDATE product_items SET current_process_id = NULL, status = "completed", completed_at = datetime("now","localtime") WHERE id = ?',
                                   (item['id'],))

    elif report_type == 'scrap':
        reason = remark or ''
        db.execute('INSERT INTO scrap_records (order_id, process_id, user_id, quantity, reason) VALUES (?,?,?,?,?)',
                   (order_id, process_id, user_id, quantity, reason))
        op = db.execute('SELECT * FROM order_processes WHERE order_id = ? AND process_id = ?',
                        (order_id, process_id)).fetchone()
        if op:
            new_scrapped = (op['scrapped'] or 0) + quantity
            db.execute('UPDATE order_processes SET scrapped = ? WHERE order_id = ? AND process_id = ?',
                       (new_scrapped, order_id, process_id))
        db.execute('UPDATE orders SET scrapped = (SELECT COALESCE(SUM(scrapped),0) FROM order_processes WHERE order_id = ?), '
                   'updated_at = datetime("now","localtime") WHERE id = ?', (order_id, order_id))

    elif report_type == 'rework':
        reason = remark or ''
        db.execute('INSERT INTO rework_records (order_id, process_id, user_id, quantity, reason) VALUES (?,?,?,?,?)',
                   (order_id, process_id, user_id, quantity, reason))
        op = db.execute('SELECT * FROM order_processes WHERE order_id = ? AND process_id = ?',
                        (order_id, process_id)).fetchone()
        if op:
            new_rework = (op['rework'] or 0) + quantity
            db.execute('UPDATE order_processes SET rework = ? WHERE order_id = ? AND process_id = ?',
                       (new_rework, order_id, process_id))
        db.execute('UPDATE orders SET rework = (SELECT COALESCE(SUM(rework),0) FROM order_processes WHERE order_id = ?), '
                   'updated_at = datetime("now","localtime") WHERE id = ?', (order_id, order_id))

def _check_order_scope(order_id, db=None):
    pids = get_user_process_ids(g.current_user)
    if pids is None:
        return True
    if not pids:
        return False
    if db is None:
        db = get_db()
    placeholders = ",".join("?" for _ in pids)
    row = db.execute(
        f"SELECT 1 FROM order_processes WHERE order_id = ? AND process_id IN ({placeholders})",
        [order_id] + pids
    ).fetchone()
    return row is not None

# Work Report (扫码报工)
# ============================================================
@app.route('/api/scan', methods=['POST'])
@check_auth
@check_permission('scan:view')
def scan_order():
    """扫码获取订单信息（支持订单号或产品序列号）"""
    try:
        data = get_json_body()
        code = data.get('code', '').strip()
        if not code:
            return jsonify({'error': '请扫描二维码'}), 400

        db = get_db()

        # 先当订单号查
        order = db.execute('SELECT * FROM orders WHERE order_no = ? AND deleted_at IS NULL', (code,)).fetchone()

        # 未找到，尝试解析为产品序列号
        item_info = None
        if not order:
            item = db.execute('SELECT * FROM product_items WHERE serial_no = ?', (code,)).fetchone()
            if item:
                item_info = dict(item)
                order = db.execute('SELECT * FROM orders WHERE id = ? AND deleted_at IS NULL', (item['order_id'],)).fetchone()
                if order:
                    try:
                        item_info['qr_data'] = json.loads(item['qr_content'])
                    except (json.JSONDecodeError, TypeError):
                        item_info['qr_data'] = {}

        if not order:
            return jsonify({'error': f'未找到订单或产品: {code}'}), 404

        o = dict(order)

        if not _check_order_scope(o["id"], db):
            return jsonify({"error": "您无权查看此订单"}), 403

        try:
            o['extra_fields'] = json.loads(o.get('extra_fields') or '{}')
        except (json.JSONDecodeError, TypeError):
            o['extra_fields'] = {}

        procs = db.execute('''
            SELECT op.*, p.name as process_name
            FROM order_processes op JOIN processes p ON op.process_id = p.id
            WHERE op.order_id = ? ORDER BY op.seq_order
        ''', (o['id'],)).fetchall()
        all_procs = [dict(p) for p in procs]
        # 按岗位过滤工序
        user_pids = get_user_process_ids(g.current_user)
        if user_pids is not None:
            o['processes'] = [p for p in all_procs if p['process_id'] in user_pids]
        else:
            o['processes'] = all_procs

        records = db.execute('''
            SELECT wr.*, u.name as worker_name, p.name as process_name
            FROM work_records wr
            JOIN users u ON wr.user_id = u.id
            JOIN processes p ON wr.process_id = p.id
            WHERE wr.order_id = ?
            ORDER BY wr.created_at DESC LIMIT 50
        ''', (o['id'],)).fetchall()
        o['records'] = [dict(r) for r in records]

        if item_info:
            return jsonify({'order': o, 'item': item_info})
        return jsonify({'order': o})
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')

# ============================================================
# Mobile H5 扫码报工 API
# ============================================================

@app.route('/api/mobile/decode/<code>', methods=['GET'])
@check_auth
@check_permission('scan:view')
def mobile_decode(code):
    """将数字编码的二维码还原为JSON — 透明编解码层，mobile_scan 无需改动"""
    try:
        code = code.strip()
        # 防止恶意超长输入
        if len(code) > 2048:
            return jsonify({'error': '二维码数据过长'}), 400
        # N前缀 → 强制 QR 走 Alphanumeric Mode（解决 jsQR Numeric Mode 兼容性问题），去掉
        if code.startswith('N'):
            code = code[1:]
        # 非纯数字 → 旧格式（JSON或订单号），原样返回
        if not code.isdigit():
            return jsonify({'code': code})
        
        # 数字编码格式：模式标记(1位) + order_id(6位) + position_no(5位) = 12位
        if len(code) < 12:
            return jsonify({'error': '无效的数字编码'}), 400
        
        mode = code[0]
        if mode != '2':  # '2' = 序列号模式
            return jsonify({'code': code})  # 非序列号模式原样传递
        
        try:
            order_id = int(code[1:7])
            position_no = int(code[7:12])
        except ValueError:
            return jsonify({'error': '无效的数字编码'}), 400
        
        db = get_db()
        item = db.execute(
            'SELECT * FROM product_items WHERE order_id = ? AND position_no = ?',
            (order_id, position_no)
        ).fetchone()
        
        if not item:
            return jsonify({'error': f'未找到产品: 订单{order_id} 第{position_no}件'}), 404
        
        order = db.execute('SELECT * FROM orders WHERE id = ? AND deleted_at IS NULL', (order_id,)).fetchone()
        
        decoded = json.dumps({
            't': 'pi',
            'sn': item['serial_no'],
            'oid': order_id,
            'on': order['order_no'] if order else ''
        }, ensure_ascii=False, separators=(',', ':'))
        
        return jsonify({'code': decoded})
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/mobile/scan', methods=['POST'])
@check_auth
@check_permission('scan:view')
def mobile_scan():
    """手机H5扫码 - 自动判断当前工序并返回报工确认信息"""
    try:
        data = get_json_body()
        code = data.get('code', '').strip()
        if not code:
            return jsonify({'error': '请扫描二维码'}), 400

        db = get_db()

        # 支持两种查询：1) 订单号  2) 产品序列号
        # 先当订单号查
        order = db.execute('SELECT * FROM orders WHERE order_no = ? AND deleted_at IS NULL', (code,)).fetchone()

        # 解析二维码内容（JSON格式的二维码内容）
        item_info = None
        if not order:
            try:
                qr_data = json.loads(code)
                if qr_data.get('type') == 'product_item' or qr_data.get('t') == 'pi':
                    serial_no = qr_data.get('serial_no') or qr_data.get('sn', '')
                    item_info = db.execute('SELECT * FROM product_items WHERE serial_no = ?', (serial_no,)).fetchone()
                    if item_info:
                        order = db.execute('SELECT * FROM orders WHERE id = ? AND deleted_at IS NULL', (item_info['order_id'],)).fetchone()
            except (json.JSONDecodeError, TypeError):
                pass

        if not order:
            return jsonify({'error': f'未找到订单: {code}'}), 404

        o = dict(order)

        # 数据权限检查
        if not _check_order_scope(o["id"], db):
            return jsonify({"error": "您无权查看此订单"}), 403

        try:
            o['extra_fields'] = json.loads(o.get('extra_fields') or '{}')
        except (json.JSONDecodeError, TypeError):
            o['extra_fields'] = {}
        # 工序列表（按岗位过滤）
        procs = db.execute('''
            SELECT op.*, p.name as process_name
            FROM order_processes op JOIN processes p ON op.process_id = p.id
            WHERE op.order_id = ? ORDER BY op.seq_order
        ''', (o['id'],)).fetchall()
        all_procs = [dict(p) for p in procs]
        # 按岗位过滤工序
        user_pids = get_user_process_ids(g.current_user)
        if user_pids is not None:
            o['processes'] = [p for p in all_procs if p['process_id'] in user_pids]
        else:
            o['processes'] = all_procs

        # 产品序列号信息（如果有）
        if item_info:
            o['item'] = dict(item_info)
        else:
            o['item'] = None

        # 如果是纯订单二维码模式，用第一个未完成的工序
        if not item_info and o['processes']:
            for p in o['processes']:
                if p.get('completed', 0) < order['quantity']:
                    o['current_process'] = p
                    break
            else:
                o['current_process'] = o['processes'][-1]
        elif item_info:
            # 产品序列号模式：取该产品当前工序
            current_pid = item_info['current_process_id']
            if current_pid:
                for p in o['processes']:
                    if p['process_id'] == current_pid:
                        o['current_process'] = p
                        break
            else:
                o['current_process'] = o['processes'][0] if o['processes'] else None

        return jsonify({'order': o})
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')

@app.route('/api/mobile/report', methods=['POST'])
@check_auth
@check_permission('scan:edit')
def mobile_report():
    """手机H5扫码报工"""
    data = get_json_body()
    try:
        order_id = int(data.get('order_id', 0))
        process_id = int(data.get('process_id', 0))
        quantity = int(data.get('quantity', 1))
    except (ValueError, TypeError):
        return jsonify({'error': '参数格式错误：order_id/process_id/quantity 必须为数字'}), 400
    serial_no = data.get('serial_no', '').strip() or None
    remark = data.get('remark', '')
    report_type = data.get('type') or data.get('work_status') or 'normal'  # normal / scrap / rework

    if not order_id or not process_id:
        return jsonify({'error': '参数不完整'}), 400

    db = get_db()
    user = g.current_user

    order = db.execute('SELECT * FROM orders WHERE id = ? AND deleted_at IS NULL', (order_id,)).fetchone()
    if not order:
        return jsonify({'error': '订单不存在'}), 404


    # 数据权限检查
    if not _check_order_scope(order_id, db):
        return jsonify({"error": "您无权对此订单报工"}), 403

    # ===== 工序存在性校验（所有报工类型）=====
    op_check = db.execute(
        'SELECT id FROM order_processes WHERE order_id = ? AND process_id = ?',
        (order_id, process_id)).fetchone()
    if not op_check:
        return jsonify({'error': '该工序不在订单工艺路线中'}), 400

    # ===== 序列号防重复报工 =====
    if serial_no and report_type == 'normal':
        existing = db.execute(
            'SELECT id FROM work_records WHERE order_id = ? AND process_id = ? AND serial_no = ?',
            (order_id, process_id, serial_no)
        ).fetchone()
        if existing:
            return jsonify({'error': f'序列号 {serial_no} 在此工序已报工，不可重复扫码！'}), 409

    # ===== 工艺路线防错校验（仅正常报工需要）=====
    if report_type == 'normal' and order['route_id']:
        current_op = db.execute(
            'SELECT * FROM order_processes WHERE order_id = ? AND process_id = ?',
            (order_id, process_id)).fetchone()
        if not current_op:
            return jsonify({'error': '该工序不在订单工艺路线中'}), 400
        current_seq = current_op['seq_order']

        # 顺序报工检查（process_order_mode != out_of_order）
        process_order_mode = get_setting('process_order_mode', 'sequential')
        if process_order_mode != 'out_of_order':
            prev_incomplete = db.execute('''
                SELECT op.seq_order, p.name as process_name
                FROM order_processes op
                JOIN processes p ON op.process_id = p.id
                WHERE op.order_id = ? AND op.seq_order < ? AND (op.completed IS NULL OR op.completed = 0)
                ORDER BY op.seq_order
            ''', (order_id, current_seq)).fetchall()
            if prev_incomplete:
                names = '、'.join([p['process_name'] for p in prev_incomplete])
                return jsonify({'error': f'请先完成前置工序：{names}'}), 400

        # 上道工序累计数量限制
        if get_setting('limit_by_prev_process', '1') == '1' and current_seq > 1:
            prev_op = db.execute('''
                SELECT op.*, p.name as process_name
                FROM order_processes op
                JOIN processes p ON op.process_id = p.id
                WHERE op.order_id = ? AND op.seq_order = ?
            ''', (order_id, current_seq - 1)).fetchone()
            if prev_op:
                new_completed = (current_op['completed'] or 0) + quantity
                prev_completed = prev_op['completed'] or 0
                if new_completed > prev_completed:
                    return jsonify({'error': f'报工数量不能超过上道工序({prev_op["process_name"]})的累计数量 {prev_completed}'}), 400

        # 订单数量上限限制
        if get_setting('limit_by_order_qty', '1') == '1':
            new_completed = (current_op['completed'] or 0) + quantity
            if new_completed > order['quantity']:
                return jsonify({'error': f'报工累计({new_completed})不能超过订单数量({order["quantity"]})'}), 400

    # ===== 审批检查（仅正常报工需要）=====
    need_approval = False
    if report_type == 'normal':
        approval_config = db.execute('SELECT * FROM approval_config WHERE process_id = ? AND require_approval = 1', (process_id,)).fetchone()
        if approval_config:
            need_approval = True
    
    # 记录（使用共享写入函数）
    db.execute('SAVEPOINT mobile_report_sp')
    try:
        _execute_report_write(db, report_type, order_id, process_id,
                              user['id'], user['name'], quantity, remark, serial_no,
                              need_approval, record_type='mobile')
        db.execute('RELEASE mobile_report_sp')
        db.commit()
    except Exception as e:
        db.execute('ROLLBACK TO mobile_report_sp')
        return handle_unexpected_error(e, 'database operation')

    try:
        audit_log(f'mobile_{report_type}', 'order', order_id,
                 f'process={process_id} serial={serial_no} qty={quantity}  by={user["name"]}')
    except Exception:
        pass
    return jsonify({'message': '报工成功', 'worker': dict(user)})

@app.route('/api/report', methods=['POST'])
@check_auth
@check_permission('scan:edit')
def work_report():
    """报工"""
    data = get_json_body()
    try:
        order_id = int(data.get('order_id', 0))
        process_id = int(data.get('process_id', 0))
        quantity = int(data.get('quantity', 0))
    except (ValueError, TypeError):
        return jsonify({'error': '参数格式错误：order_id/process_id/quantity 必须为数字'}), 400
    serial_no = data.get('serial_no', '').strip() or None
    report_type = data.get('type', 'normal')
    remark = data.get('remark', '')

    if not order_id or not process_id or quantity <= 0:
        return jsonify({'error': '参数不完整'}), 400

    db = get_db()
    user = g.current_user

    # ===== 工艺路线防错校验 =====
    order = db.execute('SELECT * FROM orders WHERE id = ? AND deleted_at IS NULL', (order_id,)).fetchone()
    if not order:
        return jsonify({'error': '订单不存在'}), 404

    # 数据权限检查
    if not _check_order_scope(order_id, db):
        return jsonify({"error": "您无权对此订单报工"}), 403

    # ===== 工序存在性校验（所有报工类型）=====
    op_check = db.execute(
        'SELECT id FROM order_processes WHERE order_id = ? AND process_id = ?',
        (order_id, process_id)).fetchone()
    if not op_check:
        return jsonify({'error': '该工序不在订单工艺路线中'}), 400

    # ===== 序列号防重复报工 =====
    if serial_no and report_type == 'normal':
        existing = db.execute(
            'SELECT id FROM work_records WHERE order_id = ? AND process_id = ? AND serial_no = ?',
            (order_id, process_id, serial_no)
        ).fetchone()
        if existing:
            return jsonify({'error': f'序列号 {serial_no} 在此工序已报工，不可重复扫码！'}), 409

    current_op = db.execute(
        'SELECT * FROM order_processes WHERE order_id = ? AND process_id = ?',
        (order_id, process_id)).fetchone()
    if order['route_id'] and not current_op:
        return jsonify({'error': '该工序不在订单工艺路线中'}), 400
    current_seq = current_op['seq_order'] if current_op else 0

    # 顺序报工检查（process_order_mode != out_of_order）
    process_order_mode = get_setting('process_order_mode', 'sequential')
    if process_order_mode != 'out_of_order':
        prev_incomplete = db.execute('''
            SELECT op.seq_order, p.name as process_name
            FROM order_processes op
            JOIN processes p ON op.process_id = p.id
            WHERE op.order_id = ? AND op.seq_order < ? AND (op.completed IS NULL OR op.completed = 0)
            ORDER BY op.seq_order
        ''', (order_id, current_seq)).fetchall()
        if prev_incomplete:
            names = '、'.join([p['process_name'] for p in prev_incomplete])
            return jsonify({'error': f'请先完成前置工序：{names}'}), 400

    # 上道工序累计数量限制
    if get_setting('limit_by_prev_process', '1') == '1' and current_seq > 1:
        prev_op = db.execute('''
            SELECT op.*, p.name as process_name
            FROM order_processes op
            JOIN processes p ON op.process_id = p.id
            WHERE op.order_id = ? AND op.seq_order = ?
        ''', (order_id, current_seq - 1)).fetchone()
        if prev_op:
            new_completed = (current_op['completed'] or 0) + quantity
            prev_completed = prev_op['completed'] or 0
            if new_completed > prev_completed:
                return jsonify({'error': f'报工数量不能超过上道工序({prev_op["process_name"]})的累计数量 {prev_completed}'}), 400

    # 订单数量上限限制
    if get_setting('limit_by_order_qty', '1') == '1':
        new_completed = (current_op['completed'] or 0) + quantity
        if new_completed > order['quantity']:
            return jsonify({'error': f'报工累计({new_completed})不能超过订单数量({order["quantity"]})'}), 400

    # ===== 审批检查 =====
    need_approval = False
    approval_config = db.execute(
        'SELECT * FROM approval_config WHERE process_id = ? AND require_approval = 1',
        (process_id,)).fetchone()
    if approval_config:
        need_approval = True

    work_status = 'pending' if need_approval else 'approved'

    # ===== 正常报工 =====
    db.execute('SAVEPOINT report_sp')
    try:
        if report_type == 'normal':
            cur = db.execute('INSERT INTO work_records (order_id, process_id, user_id, type, quantity, remark, status, serial_no) VALUES (?,?,?,?,?,?,?,?)',
                       (order_id, process_id, user['id'], 'normal', quantity, remark, work_status, serial_no))
            wr_id = cur.lastrowid
            # 写入待审批记录
            if need_approval:
                db.execute('INSERT INTO approval_records (work_record_id, status) VALUES (?, "pending")', (wr_id,))
            # 审批通过的报工才更新计数
            if work_status == 'approved':
                op = db.execute('SELECT * FROM order_processes WHERE order_id = ? AND process_id = ?',
                                (order_id, process_id)).fetchone()
                if op:
                    new_completed = (op['completed'] or 0) + quantity
                    db.execute('UPDATE order_processes SET completed = ? WHERE order_id = ? AND process_id = ?',
                               (new_completed, order_id, process_id))
                # 更新订单完成数：统计已完成的工件数量（而非工序累计总和）
                db.execute('UPDATE orders SET completed = (SELECT COUNT(*) FROM product_items WHERE order_id = ? AND status = "completed"), '
                           'updated_at = datetime("now","localtime"), status = "producing" WHERE id = ?',
                           (order_id, order_id))
                # 检查订单是否全部完成
                order_info = db.execute('SELECT quantity FROM orders WHERE id = ?', (order_id,)).fetchone()
                if order_info:
                    completed_cnt = db.execute(
                        'SELECT COUNT(*) as cnt FROM product_items WHERE order_id = ? AND status = "completed"',
                        (order_id,)
                    ).fetchone()['cnt']
                    if completed_cnt >= order_info['quantity']:
                        db.execute('UPDATE orders SET status = "completed", completed_at = datetime("now","localtime") WHERE id = ?',
                                   (order_id,))
                        auto_stock_in(db, order_id, user['id'], user['name'])

            # 推进工件当前工序
            if serial_no and current_op:
                item = db.execute('SELECT * FROM product_items WHERE serial_no = ?', (serial_no,)).fetchone()
                if item:
                    current_seq = current_op['seq_order']
                    next_op = db.execute(
                        'SELECT op.process_id FROM order_processes op WHERE op.order_id = ? AND op.seq_order > ? ORDER BY op.seq_order LIMIT 1',
                        (order_id, current_seq)
                    ).fetchone()
                    if next_op:
                        db.execute('UPDATE product_items SET current_process_id = ?, status = "in_progress" WHERE id = ?',
                                   (next_op['process_id'], item['id']))
                    else:
                        db.execute('UPDATE product_items SET current_process_id = NULL, status = "completed", completed_at = datetime("now","localtime") WHERE id = ?',
                                   (item['id'],))

        elif report_type == 'scrap':
            reason = data.get('reason', '')
            db.execute('INSERT INTO scrap_records (order_id, process_id, user_id, quantity, reason) VALUES (?,?,?,?,?)',
                       (order_id, process_id, user['id'], quantity, reason))
            op = db.execute('SELECT * FROM order_processes WHERE order_id = ? AND process_id = ?',
                            (order_id, process_id)).fetchone()
            if op:
                new_scrapped = (op['scrapped'] or 0) + quantity
                db.execute('UPDATE order_processes SET scrapped = ? WHERE order_id = ? AND process_id = ?',
                           (new_scrapped, order_id, process_id))
            db.execute('UPDATE orders SET scrapped = (SELECT COALESCE(SUM(scrapped),0) FROM order_processes WHERE order_id = ?), '
                       'updated_at = datetime("now","localtime") WHERE id = ?', (order_id, order_id))

        elif report_type == 'rework':
            reason = data.get('reason', '')
            db.execute('INSERT INTO rework_records (order_id, process_id, user_id, quantity, reason) VALUES (?,?,?,?,?)',
                       (order_id, process_id, user['id'], quantity, reason))
            op = db.execute('SELECT * FROM order_processes WHERE order_id = ? AND process_id = ?',
                            (order_id, process_id)).fetchone()
            if op:
                new_rework = (op['rework'] or 0) + quantity
                db.execute('UPDATE order_processes SET rework = ? WHERE order_id = ? AND process_id = ?',
                           (new_rework, order_id, process_id))
            db.execute('UPDATE orders SET rework = (SELECT COALESCE(SUM(rework),0) FROM order_processes WHERE order_id = ?), '
                       'updated_at = datetime("now","localtime") WHERE id = ?', (order_id, order_id))

        db.execute('RELEASE report_sp')
        db.commit()
    except Exception as e:
        db.execute('ROLLBACK TO report_sp')
        return handle_unexpected_error(e, 'database operation')

    try:
        audit_log(f'report_{report_type}', 'order', order_id,
                  f'process={process_id} qty={quantity} type={report_type}')
    except Exception:
        pass
    return jsonify({'message': '报工成功'})

# ============================================================
# QR Code Generation
# ============================================================
@app.route('/api/qrcode/<order_no>', methods=['GET'])
@check_auth
@check_permission('scan:view')
def get_qrcode(order_no):
    try:
        db = get_db()
        order = db.execute('SELECT * FROM orders WHERE order_no = ? AND deleted_at IS NULL', (order_no,)).fetchone()
        if not order:
            return jsonify({'error': '订单不存在'}), 404

        # QR content: order_no
        qr_data = order_no

        qr = qrcode.QRCode(version=2, box_size=10, border=4)
        qr.add_data(qr_data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        buf = BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        return send_file(buf, mimetype='image/png')
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')

@app.route('/api/qrcode/batch', methods=['POST'])
@check_auth
@check_permission('orders:create')
def batch_qrcode():
    """批量生成二维码标签 - 支持订单模式和产品序列号模式"""
    try:
        data = get_json_body()
        order_ids = data.get('order_ids', [])
        mode = data.get('mode', 'order')  # 'order' 或 'serial'
        
        if not order_ids:
            return jsonify({'error': '请选择订单'}), 400

        db = get_db()
        codes = []
        
        for oid in order_ids:
            order = db.execute('SELECT * FROM orders WHERE id = ? AND deleted_at IS NULL', (oid,)).fetchone()
            if not order:
                continue
            
            if mode == 'serial':
                # 产品序列号模式：为每件产品生成标签
                items = db.execute(
                    'SELECT * FROM product_items WHERE order_id = ? ORDER BY position_no',
                    (oid,)
                ).fetchall()
                
                if not items:
                    # 如果还没生成序列号，自动生成
                    db.execute('BEGIN IMMEDIATE')
                    try:
                        for i in range(1, order['quantity'] + 1):
                            serial_no = f"{order['order_no']}-{i:03d}"
                            qr_content = json.dumps({
                                't': 'pi',
                                'sn': serial_no,
                                'oid': order['id'],
                                'on': order['order_no']
                            }, ensure_ascii=False)
                            
                            db.execute('''
                                INSERT INTO product_items 
                                (serial_no, order_id, position_no, qr_content, status, created_at)
                                VALUES (?, ?, ?, ?, 'pending', datetime('now', 'localtime'))
                            ''', (serial_no, oid, i, qr_content))
                        db.commit()
                    except Exception:
                        db.execute('ROLLBACK')
                        raise
                    
                    items = db.execute(
                        'SELECT * FROM product_items WHERE order_id = ? ORDER BY position_no',
                        (oid,)
                    ).fetchall()
                
                # 为每个序列号生成二维码（优先使用订单中的 product_code 字段）
                product_code = (order['product_code'] or '').strip()
                if not product_code:
                    product = db.execute('SELECT product_code FROM products WHERE product_name = ? LIMIT 1', (order['product_name'],)).fetchone()
                    product_code = product['product_code'] if product else ''
                for item in items:
                    qr_data = f"N2{order['id']:06d}{item['position_no']:05d}"
                    qr = qrcode.QRCode(version=2, box_size=8, border=1)
                    qr.add_data(qr_data)
                    qr.make(fit=True)
                    img = qr.make_image(fill_color="black", back_color="white")
                    buf = BytesIO()
                    img.save(buf, format='PNG')
                    buf.seek(0)
                    b64 = base64.b64encode(buf.read()).decode()
                    codes.append({
                        'serial_no': item['serial_no'],
                        'order_no': order['order_no'],
                        'customer': order['customer'],
                        'product_name': order['product_name'],
                        'product_code': product_code,
                        'position': item['position_no'],
                        'qrcode': f'data:image/png;base64,{b64}'
                    })
            else:
                # 订单模式：每个订单一个二维码
                qr = qrcode.QRCode(version=2, box_size=8, border=1)
                qr.add_data(order['order_no'])
                qr.make(fit=True)
                img = qr.make_image(fill_color="black", back_color="white")
                buf = BytesIO()
                img.save(buf, format='PNG')
                buf.seek(0)
                b64 = base64.b64encode(buf.read()).decode()
                product_code = (order['product_code'] or '').strip()
                if not product_code:
                    product = db.execute('SELECT product_code FROM products WHERE product_name = ? LIMIT 1', (order['product_name'],)).fetchone()
                    product_code = product['product_code'] if product else ''
                codes.append({
                    'order_no': order['order_no'],
                    'customer': order['customer'],
                    'product_name': order['product_name'],
                    'product_code': product_code,
                    'quantity': order['quantity'],
                    'qrcode': f'data:image/png;base64,{b64}'
                })

        return jsonify({'codes': codes})
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')