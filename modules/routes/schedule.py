"""
qr-system — 生产排程路由（Refactored: SQL → ScheduleService）
"""
from flask import jsonify
from modules.app import app
from modules.middleware.auth import check_auth, check_permission
from modules.middleware.error_handler import handle_unexpected_error
from modules.services.schedule_service import ScheduleService


@app.route('/api/schedule/gantt', methods=['GET'])
@check_auth
@check_permission('schedule:view')
def schedule_gantt():
    try:
        return jsonify(ScheduleService.get_gantt_data())
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')
