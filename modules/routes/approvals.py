"""
qr-system — 审批管理
"""
import json, hashlib, secrets, base64
from datetime import datetime, timedelta
from functools import wraps
from io import BytesIO

from flask import request, jsonify, send_file, g

from modules.app import app
from modules.db import get_db, get_setting, get_page_size
from modules.middleware.auth import check_auth, check_permission, audit_log
from modules.config import PERMISSION_DEFS, generate_product_code


@app.route('/api/approvals/pending', methods=['GET'])
@check_auth
@check_permission('approvals:view')
def get_pending_approvals():
    """
    获取待审批记录
    ---
    tags:
      - Approvals
    summary: 获取待审批记录
    responses:
      200:
        description: OK
    security:
      - Bearer: []
    """
    db = get_db()
    rows = db.execute('''
        SELECT ar.*, o.order_no, p.name as process_name, u.name as worker_name, wr.quantity
        FROM approval_records ar
        LEFT JOIN work_records wr ON ar.work_record_id = wr.id
        LEFT JOIN orders o ON wr.order_id = o.id
        LEFT JOIN processes p ON wr.process_id = p.id
        LEFT JOIN users u ON wr.user_id = u.id
        WHERE ar.status = 'pending' AND (o.deleted_at IS NULL OR o.id IS NULL)
        ORDER BY ar.created_at DESC
    ''').fetchall()
    return jsonify({'approvals': [dict(r) for r in rows]})

@app.route('/api/approvals/history', methods=['GET'])
@check_auth
@check_permission('approvals:view')
def get_approval_history():
    """
    获取已处理的审批记录（非 pending）
    ---
    tags:
      - Approvals
    summary: 获取已处理的审批记录（非 pending）
    responses:
      200:
        description: OK
    security:
      - Bearer: []
    """
    db = get_db()
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', get_page_size(), type=int)
    rows = db.execute('''
        SELECT ar.*, o.order_no, p.name as process_name, u.name as worker_name, wr.quantity
        FROM approval_records ar
        LEFT JOIN work_records wr ON ar.work_record_id = wr.id
        LEFT JOIN orders o ON wr.order_id = o.id
        LEFT JOIN processes p ON wr.process_id = p.id
        LEFT JOIN users u ON wr.user_id = u.id
        WHERE ar.status != 'pending' AND (o.deleted_at IS NULL OR o.id IS NULL)
        ORDER BY ar.created_at DESC
        LIMIT ? OFFSET ?
    ''', (limit, (page - 1) * limit)).fetchall()
    total = db.execute('''
        SELECT COUNT(*) FROM approval_records ar
        LEFT JOIN work_records wr ON ar.work_record_id = wr.id
        LEFT JOIN orders o ON wr.order_id = o.id
        WHERE ar.status != 'pending' AND (o.deleted_at IS NULL OR o.id IS NULL)
    ''').fetchone()[0]
    return jsonify({'approvals': [dict(r) for r in rows], 'total': total, 'page': page, 'limit': limit})

@app.route('/api/approvals/<int:record_id>/<action>', methods=['POST'])
@check_auth
@check_permission('approvals:edit')
def handle_approval(record_id, action):
    """
    审批通过或拒绝（SAVEPOINT 原子操作）
    ---
    tags:
      - Approvals
    summary: 审批通过或拒绝（SAVEPOINT 原子操作）
    responses:
      200:
        description: OK
    security:
      - Bearer: []
    """
    if action not in ('approve', 'reject'):
        return jsonify({'error': '无效的操作'}), 400
    db = get_db()
    record = db.execute('SELECT * FROM approval_records WHERE id = ?', (record_id,)).fetchone()
    if not record:
        return jsonify({'error': '审批记录不存在'}), 404
    if record['status'] != 'pending':
        return jsonify({'error': '该记录已被处理'}), 409
    data = request.get_json(force=True, silent=True) or {}
    status = 'approved' if action == 'approve' else 'rejected'

    db.execute('SAVEPOINT approval_handle')
    try:
        db.execute(
            'UPDATE approval_records SET status = ?, approver_id = ?, approver_name = ?, comment = ? WHERE id = ?',
            (status, g.current_user['id'], g.current_user['name'], data.get('comment', ''), record_id)
        )
        if action == 'approve':
            # 先读取 work_record — 防止重复审批
            wr = db.execute(
                'SELECT quantity, order_id, status FROM work_records WHERE id = ?',
                (record['work_record_id'],)
            ).fetchone()
            if not wr:
                db.execute('ROLLBACK TO approval_handle')
                return jsonify({'error': '工序记录不存在'}), 404
            if wr['status'] == 'approved':
                db.execute('ROLLBACK TO approval_handle')
                return jsonify({'error': '该工序记录已被审批通过，不能重复审批'}), 409
            # 检查订单是否已被软删除
            order = db.execute(
                'SELECT quantity, completed, deleted_at FROM orders WHERE id = ?',
                (wr['order_id'],)
            ).fetchone()
            if not order or order['deleted_at'] is not None:
                db.execute('ROLLBACK TO approval_handle')
                return jsonify({'error': '关联订单已删除'}), 400
            # 检查数量上限
            if order['completed'] + wr['quantity'] > order['quantity']:
                db.execute('ROLLBACK TO approval_handle')
                return jsonify({'error': f'审批通过将使完成数({order["completed"]}+{wr["quantity"]})超过订单总量({order["quantity"]})'}), 400
            db.execute(
                'UPDATE work_records SET status = ? WHERE id = ?',
                ('approved', record['work_record_id'])
            )
            db.execute(
                'UPDATE orders SET completed = completed + ? WHERE id = ?',
                (wr['quantity'], wr['order_id'])
            )
        else:
            db.execute(
                'UPDATE work_records SET status = ? WHERE id = ?',
                ('rejected', record['work_record_id'])
            )
        db.execute('RELEASE approval_handle')
    except Exception as e:
        db.execute('ROLLBACK TO approval_handle')
        return jsonify({'error': f'审批异常: {str(e)}'}), 500

    db.commit()
    audit_log('approve_' + action, 'approval', record_id,
              f'{g.current_user["name"]} {action} work_record {record["work_record_id"]}')
    return jsonify({'message': '操作成功'})

# ============================================================
