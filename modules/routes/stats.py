"""qr-system - Stats Routes (Refactored)"""
from datetime import datetime
from flask import request, jsonify, send_file
from modules.route_decorators import app, check_auth, check_permission
from modules.services.stats_service import StatsService
from modules.services.reports_service import ReportsService
from modules.cache_utils import ttl_cache
from modules.domain.reporting_day import current_reporting_day


@app.route('/api/stats/daily', methods=['GET'])
@check_auth
@check_permission('stats:view')
@ttl_cache(ttl_seconds=30)
def stats_daily():
    date = request.args.get('date', '') or current_reporting_day()
    product_code = request.args.get('product_code', '')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 500, type=int)
    try:
        result = StatsService.get_daily_records(date, product_code, page, per_page)
    except ValueError:
        return jsonify({'error': '日期格式无效，请使用 YYYY-MM-DD'}), 400
    return jsonify(result)


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
    workers = StatsService.get_worker_stats(sort_by, sort_dir, start, end, product_code)
    return jsonify({'workers': workers})


@app.route('/api/stats/scrap', methods=['GET'])
@check_auth
@check_permission('stats:view')
@ttl_cache(ttl_seconds=30)
def stats_scrap():
    start = request.args.get('start', '')
    end = request.args.get('end', '')
    product_code = request.args.get('product_code', '')
    result = StatsService.get_scrap_records(start, end, product_code)
    return jsonify(result)


@app.route('/api/stats/order-progress', methods=['GET'])
@check_auth
@check_permission('stats:view')
@ttl_cache(ttl_seconds=30)
def stats_order_progress():
    start = request.args.get('start', '')
    end = request.args.get('end', '')
    product_code = request.args.get('product_code', '')
    orders = StatsService.get_order_progress(start, end, product_code)
    return jsonify({'orders': orders})

@app.route('/api/stats/worker-detail', methods=['GET'])
@check_auth
@check_permission('stats:view')
def stats_worker_detail():
    user_id = request.args.get('user_id', type=int)
    start = request.args.get('start', '')
    end = request.args.get('end', '')
    if not user_id:
        return jsonify({'error': 'user_id required'}), 400
    rows = StatsService.get_worker_detail(user_id, start, end)
    return jsonify({'rows': rows})



@app.route("/api/stats/product", methods=["GET"])
@check_auth
@check_permission("stats:view")
@ttl_cache(ttl_seconds=30)
def stats_product():
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    product_code = request.args.get("product_code", "")
    result = ReportsService.product_stats(start, end, product_code)
    return jsonify(result)


@app.route("/api/stats/shipment", methods=["GET"])
@check_auth
@check_permission("stats:view")
@ttl_cache(ttl_seconds=30)
def stats_shipment():
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    product_code = request.args.get("product_code", "")
    result = ReportsService.shipment_stats(start, end, product_code)
    return jsonify(result)


@app.route("/api/stats/material", methods=["GET"])
@check_auth
@check_permission("stats:view")
@ttl_cache(ttl_seconds=30)
def stats_material():
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    product_code = request.args.get("product_code", "")
    result = ReportsService.material_usage(start, end, product_code)
    return jsonify(result)


@app.route("/api/stats/product-process", methods=["GET"])
@check_auth
@check_permission("stats:view")
@ttl_cache(ttl_seconds=30)
def stats_product_process():
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    result = ReportsService.product_process_stats(start, end)
    return jsonify(result)


@app.route("/api/stats/material-detail", methods=["GET"])
@check_auth
@check_permission("stats:view")
def stats_material_detail():
    material_id = request.args.get("material_id", type=int)
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    if not material_id:
        return jsonify({"error": "material_id required"}), 400
    details = StatsService.get_material_detail(material_id, start, end)
    return jsonify({"details": details})

@app.route("/api/stats/customer", methods=["GET"])
@check_auth
@check_permission("stats:view")
@ttl_cache(ttl_seconds=60)
def stats_customer():
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    result = ReportsService.customer_stats(start, end)
    return jsonify(result)


@app.route("/api/stats/production-lines", methods=["GET"])
@check_auth
@check_permission("stats:view")
@ttl_cache(ttl_seconds=60)
def stats_production_lines():
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    result = ReportsService.production_line_stats(start, end)
    return jsonify(result)


@app.route("/api/stats/monthly-summary", methods=["GET"])
@check_auth
@check_permission("stats:view")
@ttl_cache(ttl_seconds=120)
def stats_monthly_summary():
    result = ReportsService.monthly_summary()
    return jsonify(result)



@app.route("/api/stats/export-pdf", methods=["GET"])
@check_auth
@check_permission("stats:view")
def stats_export_pdf():
    tab = request.args.get("tab", "daily")
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    product_code = request.args.get("product_code", "")
    from io import BytesIO
    # Simple HTML-to-PDF via print: return HTML that auto-prints
    html_parts = ['<html><head><meta charset="UTF-8"><title>统计报表</title>']
    html_parts.append('<style>body{font-family:sans-serif;padding:20px}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccc;padding:6px;text-align:left}th{background:#f5f5f5}h2{color:#333}</style>')
    html_parts.append('</head><body><h2>扫码报工 - 统计报表</h2>')
    html_parts.append(f'<p>Tab: {tab} | 日期: {start} ~ {end} | 导出时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}</p>')
    html_parts.append('<p style="color:#999;font-size:12px">请使用浏览器打印功能(Ctrl+P)保存为PDF</p>')
    html_parts.append('</body></html>')
    output = BytesIO(''.join(html_parts).encode('utf-8'))
    output.seek(0)
    return send_file(output, mimetype='text/html; charset=utf-8',
                    as_attachment=True, download_name=f'stats_{tab}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.html')
