"""qr-system - Dashboard Routes (Refactored)"""
from flask import jsonify, request, g
from modules.app import app
from modules.middleware.auth import check_auth, check_permission
from modules.services.dashboard_service import DashboardService


@app.route('/api/dashboard', methods=['GET'])
@check_auth
@check_permission('dashboard:view')
def dashboard_index():
    """Aggregated dashboard endpoint for the workbench page"""
    user = dict(g.current_user) if hasattr(g, "current_user") else None
    return jsonify(DashboardService.get_dashboard(user))
