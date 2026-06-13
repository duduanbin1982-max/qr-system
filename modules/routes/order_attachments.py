"""qr-system - Order Attachments Routes (Refactored)"""
import os
from flask import request, jsonify, g
from modules.app import app
from modules.middleware.auth import check_auth, check_permission, audit_log
from modules.services.order_attachments_service import OrderAttachmentsService

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'uploads', 'attachments')


@app.route('/api/orders/<int:order_id>/attachments', methods=['GET'])
@check_auth
@check_permission('orders:view')
def list_attachments(order_id):
    attachments = OrderAttachmentsService.list_attachments(order_id)
    return jsonify({'attachments': attachments})


@app.route('/api/orders/<int:order_id>/attachments', methods=['POST'])
@check_auth
@check_permission('orders:edit')
def upload_attachment(order_id):
    file = request.files.get('file')
    if not file:
        return jsonify({'error': '请选择文件'}), 400
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    try:
        aid, fpath = OrderAttachmentsService.upload_attachment(
            order_id, file.filename, file.content_type or 'application/octet-stream',
            0, g.current_user.get('name', ''), UPLOAD_DIR
        )
        file.save(fpath)
        audit_log('upload_attachment', 'order', order_id, f'attachment {aid}')
        return jsonify({'id': aid, 'message': '上传成功'})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/order-attachments/<int:attachment_id>', methods=['DELETE'])
@check_auth
@check_permission('orders:edit')
def delete_attachment(attachment_id):
    try:
        row = OrderAttachmentsService.delete_attachment(attachment_id)
        fpath = row['file_path']
        if os.path.exists(fpath):
            os.remove(fpath)
        audit_log('delete_attachment', 'order', row['order_id'], f'deleted {attachment_id}')
        return jsonify({'message': '已删除'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
