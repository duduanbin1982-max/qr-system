"""
qr-system — 订单附件
"""
import json, hashlib, secrets, base64
from datetime import datetime, timedelta
from functools import wraps
from io import BytesIO

from flask import request, jsonify, send_file, g

from modules.app import app
from modules.db import get_db, get_setting
from modules.middleware.auth import check_auth, check_permission, audit_log
from modules.config import PERMISSION_DEFS, generate_product_code


@app.route('/api/orders/<int:order_id>/attachments', methods=['GET'])
@check_auth
def list_order_attachments(order_id):
    """
    获取订单附件列表
    ---
    tags:
      - Orders
    summary: 获取订单附件列表
    responses:
      200:
        description: OK
    security:
      - Bearer: []
    """
    db = get_db()
    rows = db.execute('''
        SELECT a.id, a.order_id, a.file_name, a.file_type, a.file_size, a.created_at, u.name as uploaded_by_name
        FROM order_attachments a
        LEFT JOIN users u ON a.uploaded_by = u.id
        WHERE a.order_id = ?
        ORDER BY a.created_at DESC
    ''', (order_id,)).fetchall()
    return jsonify({'attachments': [dict(r) for r in rows]})

@app.route('/api/orders/<int:order_id>/attachments', methods=['POST'])
@check_auth
def upload_order_attachment(order_id):
    """
    上传订单附件
    ---
    tags:
      - Orders
    summary: 上传订单附件
    responses:
      200:
        description: OK
    security:
      - Bearer: []
    """
    if 'file' not in request.files:
        return jsonify({'error': '没有文件'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '文件名不能为空'}), 400
    
    # 读取文件数据
    file_data = file.read()
    file_size = len(file_data)
    
    # 限制文件大小 10MB
    if file_size > 10 * 1024 * 1024:
        return jsonify({'error': '文件大小超过10MB限制'}), 400
    
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    
    # 保存到数据库
    db.execute('''
        INSERT INTO order_attachments (order_id, file_name, file_type, file_size, file_data, uploaded_by)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        order_id,
        file.filename,
        file.content_type or '',
        file_size,
        file_data,
        g.current_user['id']
    ))
    db.commit()
    
    audit_log('upload_attachment', 'order', order_id, file.filename)
    return jsonify({'message': '上传成功'})

@app.route('/api/attachments/<int:attachment_id>/download', methods=['GET'])
@check_auth
def download_attachment(attachment_id):
    """
    下载附件
    ---
    tags:
      - Orders
    summary: 下载附件
    responses:
      200:
        description: OK
    security:
      - Bearer: []
    """
    db = get_db()
    row = db.execute('SELECT * FROM order_attachments WHERE id = ?', (attachment_id,)).fetchone()
    if not row:
        return jsonify({'error': '附件不存在'}), 404
    
    return send_file(
        BytesIO(row['file_data']),
        mimetype=row['file_type'] or 'application/octet-stream',
        as_attachment=True,
        download_name=row['file_name']
    )

@app.route('/api/attachments/<int:attachment_id>', methods=['DELETE'])
@check_auth
def delete_attachment(attachment_id):
    """
    删除附件
    ---
    tags:
      - Orders
    summary: 删除附件
    responses:
      200:
        description: OK
    security:
      - Bearer: []
    """
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    row = db.execute('SELECT order_id, file_name FROM order_attachments WHERE id = ?', (attachment_id,)).fetchone()
    if not row:
        return jsonify({'error': '附件不存在'}), 404
    
    db.execute('DELETE FROM order_attachments WHERE id = ?', (attachment_id,))
    db.commit()
    
    audit_log('delete_attachment', 'order', row['order_id'], row['file_name'])
    return jsonify({'message': '删除成功'})

# ============================================================
