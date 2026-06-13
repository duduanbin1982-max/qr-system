"""
qr-system - Order Remark History Routes（Refactored）
"""
from flask import request, jsonify
from modules.app import app
from modules.db import get_page_size
from modules.middleware.auth import check_auth, check_permission
from modules.services.order_notes_service import OrderNotesService


@app.route('/api/orders/<int:oid>/remarks', methods=['GET'])
@check_auth
@check_permission('orders:view')
def get_order_remarks(oid):
    try:
        page = max(request.args.get('page', 1, type=int), 1)
        limit = min(max(request.args.get('limit', get_page_size(), type=int), 1), 100)
        return jsonify(OrderNotesService.get_remarks(oid, page, limit))
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
