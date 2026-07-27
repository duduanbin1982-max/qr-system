"""
qr-system - Order Remark History Routes（Refactored）
"""
from flask import request, jsonify, g
from modules.route_decorators import app, check_auth, check_order_data_scope, check_permission
from modules.services.setting_service import SettingsService
from modules.services.order_notes_service import OrderNotesService


@app.route('/api/orders/<int:oid>/remarks', methods=['GET'])
@check_auth
@check_permission('orders:view')
def get_order_remarks(oid):
    if not check_order_data_scope(oid, g.current_user):
        return jsonify({'error': '无权限访问此订单'}), 403
    try:
        page = max(request.args.get('page', 1, type=int), 1)
        limit = min(max(request.args.get('limit', int(SettingsService.get_value('page_size', '20') or 20), type=int), 1), 100)
        return jsonify(OrderNotesService.get_remarks(oid, page, limit))
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
