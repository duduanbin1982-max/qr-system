"""
qr-system — 工价管理 + 工资计算路由

薄层：HTTP 解析 → 调用 Service → 格式化响应 / CSV导出。
"""
import csv, io
from datetime import datetime

from flask import request, jsonify, send_file, g

from modules.app import app
from modules.middleware.audit import audit_log
from modules.middleware.auth import check_auth, check_permission
from modules.middleware.validate import validate_json
from modules.middleware.helpers import get_json_body
from modules.services.price_service import RoutePriceService
from modules.services.wage_service import WageService

# ============================================================
# Product Route Pricing (产品路线工价)
# ============================================================

# ============================================================
# Route-level Pricing (路线级工价)
# ============================================================

@app.route('/api/route-prices', methods=['GET'])
@check_auth
@check_permission('prices:view')
def list_route_prices():
    category = request.args.get('category', '').strip()
    return jsonify(RoutePriceService.list_all(category))

@app.route('/api/route-prices/<int:route_id>', methods=['GET'])
@check_auth
@check_permission('prices:view')
def get_route_prices(route_id):
    try:
        return jsonify(RoutePriceService.get_by_route(route_id))
    except ValueError as e:
        return jsonify({'error': str(e)}), 404

@app.route('/api/route-prices/<int:route_id>', methods=['PUT'])
@check_auth
@check_permission('prices:edit')
def save_route_prices(route_id):
    data = get_json_body()
    prices = data.get('prices', {})
    if not isinstance(prices, dict):
        return jsonify({'error': 'prices必须为对象格式'}), 400
    effective_date = data.get('effective_date')
    remark = data.get('remark')
    try:
        updated, created = RoutePriceService.save_prices(
            route_id, prices, effective_date, remark)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    msg = f'保存成功（新增 {created} 条，更新 {updated} 条）'
    try:
        audit_log('save_route_prices', 'process_route', route_id, msg)
    except Exception as e:
        app.logger.warning('audit_log failed: %s', e)
    return jsonify({'message': msg, 'created': created, 'updated': updated})

# ============================================================

@app.route('/api/route-prices/<int:route_id>/history', methods=['GET'])
@check_auth
@check_permission('prices:view')
def get_route_price_history(route_id):
    """获取路线工价变更历史"""
    return jsonify(RoutePriceService.get_route_price_history(route_id))

# ============================================================
# Wage & Reports (工资统计与报表)
# ============================================================

@app.route('/api/wages', methods=['GET'])
@check_auth
@check_permission('wages:view')
def calculate_wages():
    employee_id = request.args.get('employee_id', type=int)
    # Row-level access control: non-admin users can only see their own wages
    if not g.current_user.get('_permissions') or '*' not in g.current_user.get('_permissions', []):
        if 'prices:view_all' not in g.current_user.get('_permissions', []):
            # Force to current user's own employee_id
            current_uid = g.current_user.get('id')
            current_eno = g.current_user.get('employee_no')
            if employee_id and employee_id != current_uid:
                return jsonify({'error': '无权限查看他人工资'}), 403
            employee_id = current_uid
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    export = request.args.get('export', '')
    include_pending = request.args.get('include_pending', '0') == '1'
    include_rework = request.args.get('include_rework', '0') == '1'
    hide_zero = request.args.get('hide_zero', '0') == '1'
    if export:
        result = WageService.calculate_wages(employee_id, date_from, date_to, 1, 999999, include_pending, include_rework, hide_zero)
    else:
        page = max(request.args.get('page', 1, type=int), 1)
        limit = min(max(request.args.get('limit', 200, type=int), 1), 1000)
        result = WageService.calculate_wages(employee_id, date_from, date_to, page, limit, include_pending, include_rework, hide_zero)
    wages = result['wages']

    if export in ('xlsx', 'csv'):
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['员工姓名', '工号', '总数量', '总工资',
                         '日期', '订单号', '产品名称', '工序', '数量', '单价', '工资'])
        for w in wages:
            for d in w['details']:
                writer.writerow([
                    w['employee_name'], w['employee_no'],
                    w['total_quantity'], w['total_wage'],
                    d['date'][:10] if d['date'] else '',
                    d.get('order_no', ''), d.get('product_name', ''),
                    d['process_name'], d['quantity'], d['unit_price'], d['wage']
                ])
        output.seek(0)
        return send_file(io.BytesIO(output.getvalue().encode('utf-8-sig')),
                         mimetype='text/csv; charset=utf-8-sig',
                         as_attachment=True,
                         download_name=f'wages_{date_from}_{date_to}.csv')

    return jsonify({'wages': wages, 'total': result.get('total', 0), 'page': result.get('page', 1), 'limit': result.get('limit', 200)})

@app.route('/api/daily-report', methods=['GET'])
@check_auth
@check_permission('wages:view')
def daily_report():
    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    export = request.args.get('export', '')

    result = WageService.daily_report(date)
    report = result['report']

    if export in ('xlsx', 'csv'):
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['员工姓名', '工号', '工序', '数量'])
        for r in report:
            for proc_id, p in r['processes'].items():
                writer.writerow([r['employee_name'], r['employee_no'],
                                 p['process_name'], p['quantity']])
        output.seek(0)
        return send_file(io.BytesIO(output.getvalue().encode('utf-8-sig')),
                         mimetype='text/csv; charset=utf-8-sig',
                         as_attachment=True,
                         download_name=f'daily_report_{date}.csv')

    return jsonify({'date': date, 'report': report})

@app.route('/api/production-progress', methods=['GET'])
@check_auth
@check_permission('wages:view')
def production_progress():
    page = max(request.args.get('page', 1, type=int), 1)
    limit = min(max(request.args.get('limit', 50, type=int), 1), 200)
    return jsonify(WageService.production_progress(page, limit))

@app.route('/api/wages/monthly-summary', methods=['GET'])
@check_auth
@check_permission('wages:view')
def monthly_summary():
    year_month = request.args.get('year_month', datetime.now().strftime('%Y-%m'))
    page = max(request.args.get('page', 1, type=int), 1)
    limit = min(max(request.args.get('limit', 100, type=int), 1), 500)
    return jsonify(WageService.monthly_summary(year_month, page, limit))

@app.route('/api/wages/process-summary', methods=['GET'])
@check_auth
@check_permission('wages:view')
def process_wage_summary():
    year_month = request.args.get('year_month', datetime.now().strftime('%Y-%m'))
    return jsonify(WageService.process_wage_summary(year_month))

@app.route("/api/wages/adjustments", methods=["GET"])
@check_auth
@check_permission('wages:view')
def list_wage_adjustments():
    user_id = request.args.get("user_id")
    year_month = request.args.get("year_month")
    return jsonify(WageService.list_adjustments(user_id=user_id, year_month=year_month))

@app.route("/api/wages/adjustments", methods=["POST"])
@check_auth
@check_permission('wages:edit')
def save_wage_adjustment():
    data = request.get_json()
    return jsonify(WageService.save_adjustment(
        user_id=data["user_id"], year_month=data["year_month"],
        adj_type=data["type"], amount=data["amount"],
        reason=data.get("reason", ""), created_by="system"
    ))

@app.route("/api/wages/adjustments/<int:adj_id>", methods=["DELETE"])
@check_auth
@check_permission('wages:edit')
def delete_wage_adjustment(adj_id):
    return jsonify(WageService.delete_adjustment(adj_id))

@app.route("/api/wages/adjustments-total", methods=["GET"])
@check_auth
@check_permission('wages:view')
def get_adjustments_total():
    user_id = request.args.get("user_id")
    year_month = request.args.get("year_month")
    return jsonify(WageService.get_adjustments_total(
        user_id=int(user_id) if user_id else 0, year_month=year_month or ""
    ))

@app.route("/api/wages/trends", methods=["GET"])
@check_auth
@check_permission("wages:view")
def wage_trends():
    months = request.args.get("months", 12, type=int)
    return jsonify(WageService.wage_trends(months=min(months, 36)))

@app.route("/api/wages/confirm", methods=["POST"])
@check_auth
@check_permission("wages:edit")
def confirm_wage_snapshot():
    year_month = request.args.get("year_month", "")
    if not year_month:
        return jsonify({"error": "missing year_month"}), 400
    return jsonify(WageService.confirm_snapshot(year_month, g.current_user.get("name", g.current_user.get("username", "system"))))

@app.route("/api/wages/snapshot-status", methods=["GET"])
@check_auth
@check_permission("wages:view")
def wage_snapshot_status():
    year_month = request.args.get("year_month", "")
    if not year_month:
        return jsonify({"error": "missing year_month"}), 400
    return jsonify(WageService.get_snapshot_status(year_month))

@app.route("/api/wages/snapshot", methods=["POST"])
@check_auth
@check_permission('wages:view')
def save_wage_snapshot():
    year_month = request.args.get("year_month", "")
    if not year_month:
        return jsonify({"error": "missing year_month"}), 400
    return jsonify(WageService.save_snapshot(year_month))

@app.route("/api/wages/lock", methods=["POST"])
@check_auth
@check_permission('wages:view')
def lock_wage_snapshot():
    data = request.get_json() or {}
    year_month = request.args.get("year_month", "")
    if not year_month:
        return jsonify({"error": "missing year_month"}), 400
    return jsonify(WageService.lock_snapshot(year_month, g.current_user.get("name", g.current_user.get("username", "system")), data.get("notes", "")))

@app.route("/api/wages/position-summary", methods=["GET"])
@check_auth
@check_permission("wages:view")
def position_wage_summary():
    year_month = request.args.get("year_month", "")
    if not year_month:
        from datetime import datetime
        year_month = datetime.now().strftime("%Y-%m")
    return jsonify(WageService.position_summary(year_month))

@app.route("/api/wages/prediction", methods=["GET"])
@check_auth
@check_permission("wages:view")
def wage_prediction():
    months = request.args.get("months", 6, type=int)
    return jsonify(WageService.wage_prediction(months=min(months, 24)))

