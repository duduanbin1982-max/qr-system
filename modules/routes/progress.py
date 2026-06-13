"""qr-system - Progress Routes (Refactored)"""
from flask import jsonify
from modules.app import app
from modules.middleware.auth import check_auth, check_permission
from modules.middleware.error_handler import handle_unexpected_error
from modules.services.progress_service import ProgressService


@app.route('/api/progress/<int:order_id>', methods=['GET'])
@check_auth
@check_permission('orders:view')
def get_order_progress(order_id):
    try:
        return jsonify(ProgressService.get_order_progress(order_id))
    except ValueError as e:
        return jsonify({'error': str(e)}), 404


@app.route('/api/progress/delivery-alerts', methods=['GET'])
@check_auth
@check_permission('orders:view')
def get_delivery_alerts():
    return jsonify(ProgressService.get_delivery_alerts())
