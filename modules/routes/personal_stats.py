"""qr-system - Personal Stats (Refactored)"""
from flask import request, jsonify, g
from datetime import datetime, timedelta
from modules.app import app
from modules.middleware.auth import check_auth
from modules.services.personal_stats_service import PersonalStatsService


@app.route('/api/personal/stats', methods=['GET'])
@check_auth
def personal_stats():
    uid = g.current_user['id']
    now = datetime.now()
    today_start = now.strftime('%Y-%m-%d') + ' 00:00:00'
    week_start = (now - timedelta(days=now.weekday())).strftime('%Y-%m-%d') + ' 00:00:00'
    month_start = now.strftime('%Y-%m') + '-01 00:00:00'

    result = PersonalStatsService.get_all_stats(uid, today_start, week_start, month_start)

    return jsonify({
        'user': {
            'id': uid,
            'name': g.current_user.get('name', g.current_user.get('username', '')),
            'username': g.current_user.get('username', ''),
        },
        'today': {
            'records': result['today_sum']['total_records'],
            'quantity': result['today_sum']['total_qty'],
            'orders': result['today_sum']['order_count'],
        },
        'week': {
            'records': result['week_sum']['total_records'],
            'quantity': result['week_sum']['total_qty'],
            'orders': result['week_sum']['order_count'],
        },
        'month': {
            'records': result['month_sum']['total_records'],
            'quantity': result['month_sum']['total_qty'],
            'orders': result['month_sum']['order_count'],
        },
        'process_breakdown': [
            {'process': r['process_name'], 'count': r['count'], 'quantity': r['total_qty']}
            for r in result['process_breakdown']
        ],
        'active_orders': [
            {'id': r['id'], 'order_no': r['order_no'], 'product_name': r['product_name'],
             'status': r['status'], 'order_qty': r['quantity'], 'my_qty': r['my_qty']}
            for r in result['active_orders']
        ],
        'trend': result['trend'],
        'recent_records': [
            {'id': r['id'], 'order_id': r['order_id'], 'order_no': r['order_no'] or '',
             'product_name': r['product_name'] or '', 'process_id': r['process_id'],
             'process_name': r['process_name'] or '', 'serial_no': r['serial_no'] or '',
             'quantity': r['quantity'], 'type': r['type'] or '',
             'remark': r['remark'] or '', 'created_at': r['created_at']}
            for r in result['today_records']
        ],
    })
