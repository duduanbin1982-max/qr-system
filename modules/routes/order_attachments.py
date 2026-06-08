"""qr-system - Order attachments (filesystem storage)"""
import os, hashlib
from datetime import datetime
from flask import request, jsonify, send_file, g

from modules.app import app
from modules.config import ALLOWED_UPLOAD_EXTENSIONS
from werkzeug.utils import secure_filename
from modules.db import get_db
from modules.middleware.auth import check_auth, has_permission, check_permission, audit_log

ATTACH_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "attachments")
os.makedirs(ATTACH_DIR, exist_ok=True)

def _get_file_path(order_id, attachment_id, filename):
    order_dir = os.path.join(ATTACH_DIR, str(order_id))
    os.makedirs(order_dir, exist_ok=True)
    return os.path.join(order_dir, f"{attachment_id}_{filename}")

@app.route('/api/orders/<int:order_id>/attachments', methods=['GET'])
@check_auth
@check_permission('orders:view')
def list_order_attachments(order_id):
    db = get_db()
    rows = db.execute('''
        SELECT a.id, a.order_id, a.file_name, a.file_type, a.file_size, a.file_path, a.created_at,
               u.name as uploaded_by_name
        FROM order_attachments a
        LEFT JOIN users u ON a.uploaded_by = u.id
        WHERE a.order_id = ?
        ORDER BY a.created_at DESC
    ''', (order_id,)).fetchall()
    items = []
    for r in rows:
        d = dict(r)
        d.pop('file_data', None)
        items.append(d)
    return jsonify({'attachments': items})

@app.route('/api/orders/<int:order_id>/attachments', methods=['POST'])
@check_auth
@check_permission('orders:edit')
def upload_order_attachment(order_id):
    if 'file' not in request.files:
        return jsonify({'error': 'no file'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'filename required'}), 400
    safe_name = secure_filename(file.filename)
    ext = '.' + safe_name.rsplit('.', 1)[-1].lower() if '.' in safe_name else ''
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        return jsonify({'error': f'File type {ext} not allowed'}), 400
    filedata = file.read()
    fsize = len(filedata)
    if fsize > 10 * 1024 * 1024:
        return jsonify({'error': 'file too large'}), 400
    db = get_db()
    order = db.execute('SELECT id FROM orders WHERE id = ? AND deleted_at IS NULL', (order_id,)).fetchone()
    if not order:
        return jsonify({'error': 'order not found'}), 404
    db.execute("BEGIN IMMEDIATE")
    cur = db.execute('INSERT INTO order_attachments (order_id, file_name, file_type, file_size, uploaded_by) VALUES (?,?,?,?,?)',
                     (order_id, file.filename, file.content_type or '', fsize, g.current_user['id']))
    aid = cur.lastrowid
    fpath = _get_file_path(order_id, aid, file.filename)
    with open(fpath, 'wb') as f:
        f.write(filedata)
    db.execute('UPDATE order_attachments SET file_path = ? WHERE id = ?', (fpath, aid))
    db.commit()
    audit_log('upload_attachment', 'order', order_id, file.filename)
    return jsonify({'message': 'uploaded', 'id': aid})

@app.route('/api/attachments/<int:attachment_id>/download', methods=['GET'])
@check_auth
def download_attachment(attachment_id):
    if not has_permission(g.current_user, 'orders:view'):
        return jsonify({'error': 'Forbidden'}), 403
    db = get_db()
    row = db.execute('SELECT * FROM order_attachments WHERE id = ?', (attachment_id,)).fetchone()
    if not row:
        return jsonify({'error': 'not found'}), 404
    fpath = row['file_path']
    if fpath and os.path.exists(fpath):
        return send_file(fpath, mimetype=row['file_type'] or 'application/octet-stream', as_attachment=True, download_name=row['file_name'])
    if row['file_data']:
        from io import BytesIO
        return send_file(BytesIO(row['file_data']), mimetype=row['file_type'] or 'application/octet-stream', as_attachment=True, download_name=row['file_name'])
    return jsonify({'error': 'file not found'}), 404

@app.route('/api/attachments/<int:attachment_id>', methods=['DELETE'])
@check_auth
@check_permission('orders:edit')
def delete_attachment(attachment_id):
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    row = db.execute('SELECT order_id, file_name, file_path FROM order_attachments WHERE id = ?', (attachment_id,)).fetchone()
    if not row:
        return jsonify({'error': 'not found'}), 404
    if row['file_path'] and os.path.exists(row['file_path']):
        os.remove(row['file_path'])
    db.execute('DELETE FROM order_attachments WHERE id = ?', (attachment_id,))
    db.commit()
    audit_log('delete_attachment', 'order', row['order_id'], row['file_name'])
    return jsonify({'message': 'deleted'})
