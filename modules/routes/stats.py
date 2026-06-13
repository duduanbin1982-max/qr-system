"""qr-system - Stats Routes (Refactored)"""
from datetime import datetime
from flask import request, jsonify
from modules.app import app
from modules.middleware.auth import check_auth, check_permission
from modules.middleware.error_handler import handle_unexpected_error
from modules.services.stats_service import StatsService


@app.route('/api/stats/daily', methods=['GET'])
@check_auth
@check_permission('stats:view')
def stats_daily():
    date = request.args.get('date', '') or datetime.now().strftime('%Y-%m-%d')
    try:
        result = StatsService.get_daily_records(date)
        return jsonify(result)
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/stats/worker', methods=['GET'])
@check_auth
@check_permission('stats:view')
def stats_worker():
    start = request.args.get('start', '')
    end = request.args.get('end', '')
    sort_by = request.args.get('sort_by', 'quantity')
    sort_dir = request.args.get('sort_dir', 'desc')
    try:
        workers = StatsService.get_worker_stats(sort_by, sort_dir, start, end)
        return jsonify({'workers': workers})
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/stats/scrap', methods=['GET'])
@check_auth
@check_permission('stats:view')
def stats_scrap():
    start = request.args.get('start', '')
    end = request.args.get('end', '')
    try:
        records = StatsService.get_scrap_records(start, end)
        return jsonify({'records': records})
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/stats/order-progress', methods=['GET'])
@check_auth
@check_permission('stats:view')
def stats_order_progress():
    try:
        orders = StatsService.get_order_progress()
        return jsonify({'orders': orders})
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')
