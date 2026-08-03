"""qr-system - Stats Routes (Refactored)"""
from datetime import datetime
from html import escape
from flask import request, jsonify, send_file
from modules.route_decorators import (
    app, check_auth, check_permission, validate_reporting_range,
)
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
    try:
        page = int(request.args.get('page', '1'))
        per_page = int(request.args.get('per_page', '500'))
    except (TypeError, ValueError):
        return jsonify({'error': 'page 和 per_page 必须是整数'}), 400
    if page < 1:
        return jsonify({'error': 'page 必须是不小于 1 的整数'}), 400
    if per_page < 1:
        return jsonify({'error': 'per_page 必须是不小于 1 的整数'}), 400
    per_page = min(per_page, 5000)
    try:
        result = StatsService.get_daily_records(date, product_code, page, per_page)
    except ValueError:
        return jsonify({'error': '日期格式无效，请使用 YYYY-MM-DD'}), 400
    return jsonify(result)


@app.route('/api/stats/worker', methods=['GET'])
@check_auth
@check_permission('stats:view')
@validate_reporting_range
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
@validate_reporting_range
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
@validate_reporting_range
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
@validate_reporting_range
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
@validate_reporting_range
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
@validate_reporting_range
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
@validate_reporting_range
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
@validate_reporting_range
@ttl_cache(ttl_seconds=30)
def stats_product_process():
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    result = ReportsService.product_process_stats(start, end)
    return jsonify(result)


@app.route("/api/stats/material-detail", methods=["GET"])
@check_auth
@check_permission("stats:view")
@validate_reporting_range
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
@validate_reporting_range
@ttl_cache(ttl_seconds=60)
def stats_customer():
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    result = ReportsService.customer_stats(start, end)
    return jsonify(result)


@app.route("/api/stats/production-lines", methods=["GET"])
@check_auth
@check_permission("stats:view")
@validate_reporting_range
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
@validate_reporting_range
def stats_export_pdf():
    tab = request.args.get("tab", "daily")
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    product_code = request.args.get("product_code", "")
    report_builders = {
        "daily": lambda: (
            "生产日报明细",
            ["时间", "订单号", "产品编码", "产品名称", "工序", "员工", "数量", "类型"],
            [
                [
                    row.get("created_at"), row.get("display_order_no"),
                    row.get("product_code"), row.get("product_name"),
                    row.get("process_name"), row.get("worker_name"),
                    row.get("quantity"), row.get("type"),
                ]
                for row in StatsService.get_daily_records(
                    end or start or current_reporting_day(), product_code, 1, 5000
                )["records"]
            ],
        ),
        "worker": lambda: (
            "员工计件",
            ["姓名", "工号", "报工次数", "正常数量", "报废数量", "返修数量"],
            [
                [row.get("name"), row.get("employee_no"), row.get("record_count"),
                 row.get("total_output"), row.get("total_scrap"), row.get("total_rework")]
                for row in StatsService.get_worker_stats(
                    "quantity", "desc", start, end, product_code
                )
            ],
        ),
        "scrap": lambda: (
            "报废记录",
            ["时间", "订单号", "产品", "工序", "员工", "数量", "原因"],
            [
                [row.get("created_at"), row.get("order_no"), row.get("product_name"),
                 row.get("process_name"), row.get("worker_name"), row.get("quantity"),
                 row.get("reason")]
                for row in StatsService.get_scrap_records(start, end, product_code)["records"]
            ],
        ),
        "progress": lambda: (
            "订单进度",
            ["订单号", "产品", "客户", "计划数量", "完成数量", "状态", "计划结束"],
            [
                [row.get("order_no"), row.get("product_name"), row.get("customer"),
                 row.get("quantity"), row.get("completed"), row.get("status"), row.get("plan_end")]
                for row in StatsService.get_order_progress(start, end, product_code)
            ],
        ),
        "product": lambda: (
            "产品统计",
            ["产品编码", "产品名称", "型号", "订单数量", "产量", "报废", "返修", "订单数"],
            [
                [row.get("product_code"), row.get("product_name"), row.get("model"),
                 row.get("order_qty"), row.get("output"), row.get("scrap"),
                 row.get("rework"), row.get("order_count")]
                for row in ReportsService.product_stats(start, end, product_code)["by_product"]
            ],
        ),
        "shipment": lambda: (
            "发货统计（按客户）",
            ["客户", "发货单数", "发货数量"],
            [
                [row.get("customer"), row.get("shipment_count"), row.get("total_qty")]
                for row in ReportsService.shipment_stats(start, end, product_code)["by_customer"]
            ],
        ),
        "material": lambda: (
            "物料消耗",
            ["物料", "规格", "类型", "单位", "消耗量", "订单数"],
            [
                [row.get("name"), row.get("spec"), row.get("material_type"),
                 row.get("unit"), row.get("total_used"), row.get("order_count")]
                for row in ReportsService.material_usage(start, end, product_code)["by_material"]
            ],
        ),
        "matrix": lambda: (
            "产品工序统计",
            ["产品编码", "产品名称", "型号", "合计"],
            [
                [row.get("product_code"), row.get("product_name"), row.get("model"), row.get("total")]
                for row in ReportsService.product_process_stats(start, end)["products"]
            ],
        ),
        "customer": lambda: (
            "客户统计",
            ["客户", "订单数", "订单数量", "完成数量", "在产订单"],
            [
                [row.get("customer_name"), row.get("order_count"), row.get("total_qty"),
                 row.get("completed_qty"), row.get("active_orders")]
                for row in ReportsService.customer_stats(start, end)
            ],
        ),
    }
    if tab not in report_builders:
        return jsonify({"error": "不支持的报表类型"}), 400

    title, headers, rows = report_builders[tab]()
    from io import BytesIO
    html_parts = ['<html><head><meta charset="UTF-8"><title>统计报表</title>']
    html_parts.append('<style>@page{size:A4 landscape;margin:12mm}body{font-family:sans-serif;padding:8px;color:#222}table{border-collapse:collapse;width:100%;font-size:11px}th,td{border:1px solid #bbb;padding:5px;text-align:left;word-break:break-word}th{background:#eee}h2{margin:0 0 8px}.meta{color:#555;font-size:12px;margin-bottom:12px}@media print{.hint{display:none}}</style>')
    html_parts.append(f'</head><body><h2>{escape(title)}</h2>')
    html_parts.append(f'<div class="meta">统计日: {escape(start or "-")} 至 {escape(end or "-")} | 生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M")} | 共 {len(rows)} 行</div>')
    html_parts.append('<div class="hint">请使用浏览器打印功能保存为 PDF</div><table><thead><tr>')
    html_parts.extend(f'<th>{escape(str(header))}</th>' for header in headers)
    html_parts.append('</tr></thead><tbody>')
    if rows:
        for row in rows:
            html_parts.append('<tr>')
            html_parts.extend(f'<td>{escape(str(value if value is not None else ""))}</td>' for value in row)
            html_parts.append('</tr>')
    else:
        html_parts.append(f'<tr><td colspan="{len(headers)}">无符合条件的数据</td></tr>')
    html_parts.append('</tbody></table><script>window.addEventListener("load",()=>window.print())</script>')
    html_parts.append('</body></html>')
    output = BytesIO(''.join(html_parts).encode('utf-8'))
    output.seek(0)
    return send_file(output, mimetype='text/html; charset=utf-8',
                    as_attachment=False, download_name=f'stats_{tab}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.html')
