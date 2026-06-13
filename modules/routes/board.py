"""qr-system - Board Routes (Refactored)"""
from datetime import datetime
from flask import request, jsonify
from modules.app import app
from modules.cache_utils import ttl_cache
from modules.db import get_setting
from modules.services.board_service import BoardService


@app.route('/api/dashboard/board', methods=['GET'])
def dashboard_board():
    board_token = get_setting('board_token', '')
    has_cookie = request.cookies.get('qr_token', '')
    if board_token and not has_cookie:
        provided = request.args.get('token', '')
        if provided != board_token:
            return jsonify({'error': 'Unauthorized'}), 401

    category = request.args.get('category', '').strip()
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    data = BoardService.get_board_data(category)

    return jsonify({
        'now': now_str,
        'update_time': now_str,
        'stats': {
            'total_orders': data['total_orders'],
            'producing_orders': data['producing_orders'],
            'completed_orders': data['completed_orders'],
        },
        'today': {
            'today_output': data['today_output'],
            'today_scrap': data['today_scrap'],
            'today_reports': data.get('today_reports', 0),
            'today_rework': data.get('today_rework', 0),
        },
        'orders': data['orders_in_progress'],
        'overdue_orders': data.get('overdue_orders', []),
        'process_stats': data['process_efficiency'],
        'worker_stats': data.get('worker_stats', []),
        'recent_reports': data['recent_work'],
        'monthly_completion': data['monthly_completion'],
    })
