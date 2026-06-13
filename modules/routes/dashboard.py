"""qr-system - Dashboard Routes (Refactored)"""
from flask import jsonify, request
from modules.app import app
from modules.middleware.auth import check_auth, check_permission
from modules.services.dashboard_service import DashboardService


@app.route('/api/dashboard/stats', methods=['GET'])
@check_auth
@check_permission('dashboard:view')
def dashboard_stats():
    return jsonify(DashboardService.get_stats())


@app.route('/api/dashboard/trend', methods=['GET'])
@check_auth
@check_permission('dashboard:view')
def dashboard_trend():
    days = request.args.get('days', 30, type=int)
    return jsonify({'trend': DashboardService.get_trend(days)})

@app.route('/api/dashboard', methods=['GET'])
@check_auth
@check_permission('dashboard:view')
def dashboard_index():
    """Aggregated dashboard endpoint for the workbench page"""
    return jsonify(DashboardService.get_dashboard())
