"""qr-system - Order Attachments Routes (Refactored)"""
import os
from io import BytesIO

from flask import request, jsonify, g, send_file

from modules.app import app
from modules.middleware.audit import safe_audit_log
from modules.middleware.auth import check_auth, check_permission
from modules.middleware.data_scope import get_user_process_ids
from modules.services.order_attachments_service import OrderAttachmentsService
from modules.services.scan_helper_service import ScanHelperService
from werkzeug.utils import secure_filename

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
            order_id,
            secure_filename(file.filename),
            file.content_type or 'application/octet-stream',
            0,
            g.current_user.get('name', ''),
            UPLOAD_DIR
        )
        file.save(fpath)
        safe_audit_log('upload_attachment', 'order', order_id, f'attachment {aid}')
        return jsonify({'id': aid, 'message': '上传成功'})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/order-attachments/<int:attachment_id>/download', methods=['GET'])
@app.route('/api/attachments/<int:attachment_id>/download', methods=['GET'])
@check_auth
@check_permission('orders:view')
def download_attachment(attachment_id):
    pids = get_user_process_ids(g.current_user)
    if pids is not None:
        row_check = OrderAttachmentsService.get_attachment_meta(attachment_id)
        if row_check and not ScanHelperService.check_order_scope(row_check['order_id'], pids):
            return jsonify({'error': '无权限下载此附件'}), 403
    try:
        row = OrderAttachmentsService.get_attachment_file(attachment_id)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404

    file_path = row['file_path']
    if not file_path or not os.path.exists(file_path):
        return jsonify({'error': 'Attachment file not found'}), 404

    with open(file_path, 'rb') as file_obj:
        file_data = file_obj.read()

    return send_file(
        BytesIO(file_data),
        mimetype=row['file_type'] or 'application/octet-stream',
        as_attachment=True,
        download_name=row['file_name'],
    )


@app.route('/api/order-attachments/<int:attachment_id>', methods=['DELETE'])
@app.route('/api/attachments/<int:attachment_id>', methods=['DELETE'])
@check_auth
@check_permission('orders:edit')
def delete_attachment(attachment_id):
    pids = get_user_process_ids(g.current_user)
    if pids is not None:
        row_check = OrderAttachmentsService.get_attachment_meta(attachment_id)
        if row_check and not ScanHelperService.check_order_scope(row_check['order_id'], pids):
            return jsonify({'error': '无权限删除此附件'}), 403
    try:
        row = OrderAttachmentsService.delete_attachment(attachment_id)
        file_path = row['file_path']
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        safe_audit_log('delete_attachment', 'order', row['order_id'], f'deleted {attachment_id}')
        return jsonify({'message': '已删除'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
