"""qr-system - Stats Routes (Refactored)"""
from datetime import datetime
from flask import request, jsonify
from modules.app import app
from modules.middleware.auth import check_auth, check_permission
from modules.middleware.error_handler import handle_unexpected_error
from modules.services.stats_service import StatsService
from modules.services.reports_service import ReportsService
from modules.cache_utils import ttl_cache


@app.route('/api/stats/daily', methods=['GET'])
@check_auth
@check_permission('stats:view')
@ttl_cache(ttl_seconds=30)
def stats_daily():
    date = request.args.get('date', '') or datetime.now().strftime('%Y-%m-%d')
    product_code = request.args.get('product_code', '')
    try:
        result = StatsService.get_daily_records(date, product_code)
        return jsonify(result)
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/stats/worker', methods=['GET'])
@check_auth
@check_permission('stats:view')
@ttl_cache(ttl_seconds=30)
def stats_worker():
    start = request.args.get('start', '')
    end = request.args.get('end', '')
    sort_by = request.args.get('sort_by', 'quantity')
    sort_dir = request.args.get('sort_dir', 'desc')
    product_code = request.args.get('product_code', '')
    try:
        workers = StatsService.get_worker_stats(sort_by, sort_dir, start, end, product_code)
        return jsonify({'workers': workers})
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/stats/scrap', methods=['GET'])
@check_auth
@check_permission('stats:view')
@ttl_cache(ttl_seconds=30)
def stats_scrap():
    start = request.args.get('start', '')
    end = request.args.get('end', '')
    product_code = request.args.get('product_code', '')
    try:
        result = StatsService.get_scrap_records(start, end, product_code)
        return jsonify(result)
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/stats/order-progress', methods=['GET'])
@check_auth
@check_permission('stats:view')
@ttl_cache(ttl_seconds=30)
def stats_order_progress():
    start = request.args.get('start', '')
    end = request.args.get('end', '')
    product_code = request.args.get('product_code', '')
    try:
        orders = StatsService.get_order_progress(start, end, product_code)
        return jsonify({'orders': orders})
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')

@app.route('/api/stats/worker-detail', methods=['GET'])
@check_auth
@check_permission('stats:view')
def stats_worker_detail():
    user_id = request.args.get('user_id', type=int)
    start = request.args.get('start', '')
    end = request.args.get('end', '')
    if not user_id:
        return jsonify({'error': 'user_id required'}), 400
    try:
        rows = StatsService.get_worker_detail(user_id, start, end)
        return jsonify({'rows': rows})
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')



@app.route("/api/stats/product", methods=["GET"])
@check_auth
@check_permission("stats:view")
@ttl_cache(ttl_seconds=30)
def stats_product():
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    product_code = request.args.get("product_code", "")
    try:
        result = ReportsService.product_stats(start, end, product_code)
        return jsonify(result)
    except Exception as e:
        return handle_unexpected_error(e, "database operation")


@app.route("/api/stats/shipment", methods=["GET"])
@check_auth
@check_permission("stats:view")
@ttl_cache(ttl_seconds=30)
def stats_shipment():
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    product_code = request.args.get("product_code", "")
    try:
        result = ReportsService.shipment_stats(start, end, product_code)
        return jsonify(result)
    except Exception as e:
        return handle_unexpected_error(e, "database operation")


@app.route("/api/stats/material", methods=["GET"])
@check_auth
@check_permission("stats:view")
@ttl_cache(ttl_seconds=30)
def stats_material():
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    product_code = request.args.get("product_code", "")
    try:
        result = ReportsService.material_usage(start, end, product_code)
        return jsonify(result)
    except Exception as e:
        return handle_unexpected_error(e, "database operation")


@app.route("/api/stats/product-process", methods=["GET"])
@check_auth
@check_permission("stats:view")
@ttl_cache(ttl_seconds=30)
def stats_product_process():
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    try:
        result = ReportsService.product_process_stats(start, end)
        return jsonify(result)
    except Exception as e:
        return handle_unexpected_error(e, "database operation")


@app.route("/api/stats/material-detail", methods=["GET"])
@check_auth
@check_permission("stats:view")
def stats_material_detail():
    material_id = request.args.get("material_id", type=int)
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    if not material_id:
        return jsonify({"error": "material_id required"}), 400
    try:
        from modules.services import BaseService
        db = BaseService.db()
        where = ["mc.material_id = ?"]
        params = [material_id]
        if start:
            where.append("DATE(mc.created_at) >= ?"); params.append(start)
        if end:
            where.append("DATE(mc.created_at) <= ?"); params.append(end)
        w = " AND ".join(where)
        rows = db.execute(
            "SELECT mc.id, mc.quantity, mc.created_at, o.order_no, o.product_name, "
            "p.name as process_name FROM material_consumptions mc "
            "LEFT JOIN orders o ON mc.order_id = o.id "
            "LEFT JOIN processes p ON mc.process_id = p.id "
            "WHERE " + w + " ORDER BY mc.created_at DESC LIMIT 200",
            params
        ).fetchall()
        return jsonify({"details": [dict(r) for r in rows]})
    except Exception as e:
        return handle_unexpected_error(e, "database operation")



@app.route("/api/stats/customer", methods=["GET"])
@check_auth
@check_permission("stats:view")
@ttl_cache(ttl_seconds=60)
def stats_customer():
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    try:
        result = ReportsService.customer_stats(start, end)
        return jsonify(result)
    except Exception as e:
        return handle_unexpected_error(e, "database operation")


@app.route("/api/stats/production-lines", methods=["GET"])
@check_auth
@check_permission("stats:view")
@ttl_cache(ttl_seconds=60)
def stats_production_lines():
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    try:
        result = ReportsService.production_line_stats(start, end)
        return jsonify(result)
    except Exception as e:
        return handle_unexpected_error(e, "database operation")


@app.route("/api/stats/monthly-summary", methods=["GET"])
@check_auth
@check_permission("stats:view")
@ttl_cache(ttl_seconds=120)
def stats_monthly_summary():
    try:
        result = ReportsService.monthly_summary()
        return jsonify(result)
    except Exception as e:
        return handle_unexpected_error(e, "database operation")



@app.route("/api/stats/export-pdf", methods=["GET"])
@check_auth
@check_permission("stats:view")
def stats_export_pdf():
    tab = request.args.get("tab", "daily")
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    product_code = request.args.get("product_code", "")
    try:
        from io import BytesIO
        from flask import send_file
        from datetime import datetime as dt
        # Simple HTML-to-PDF via print: return HTML that auto-prints
        html_parts = ['<html><head><meta charset="UTF-8"><title>统计报表</title>']
        html_parts.append('<style>body{font-family:sans-serif;padding:20px}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccc;padding:6px;text-align:left}th{background:#f5f5f5}h2{color:#333}</style>')
        html_parts.append('</head><body><h2>扫码报工 - 统计报表</h2>')
        html_parts.append(f'<p>Tab: {tab} | 日期: {start} ~ {end} | 导出时间: {dt.now().strftime("%Y-%m-%d %H:%M")}</p>')
        html_parts.append('<p style="color:#999;font-size:12px">请使用浏览器打印功能(Ctrl+P)保存为PDF</p>')
        html_parts.append('</body></html>')
        output = BytesIO(''.join(html_parts).encode('utf-8'))
        output.seek(0)
        return send_file(output, mimetype='text/html; charset=utf-8',
                        as_attachment=True, download_name=f'stats_{tab}_{dt.now().strftime("%Y%m%d_%H%M%S")}.html')
    except Exception as e:
        return handle_unexpected_error(e, "pdf export")
