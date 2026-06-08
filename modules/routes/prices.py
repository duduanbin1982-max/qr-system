"""
qr-system — 工价管理 + 工资计算路由

薄层：HTTP 解析 → 调用 Service → 格式化响应 / CSV导出。
"""
import csv, io
from datetime import datetime

from flask import request, jsonify, send_file

from modules.app import app
from modules.middleware.auth import check_auth, check_permission, audit_log
from modules.middleware.validate import validate_json
from modules.middleware.helpers import get_json_body
from modules.services.price_service import ProcessPriceService, RoutePriceService, WageService


# ============================================================
# Process Prices CRUD (产品工序工价)
# ============================================================

@app.route('/api/process-prices', methods=['GET'])
@check_auth
@check_permission('prices:view')
def list_process_prices():
    product_id = request.args.get('product_id', '').strip()
    category = request.args.get('category', '').strip()
    page = max(request.args.get('page', 1, type=int), 1)
    limit = min(max(request.args.get('limit', 100, type=int), 1), 500)
    return jsonify(ProcessPriceService.list_prices(product_id, category, page, limit))


@app.route('/api/process-prices', methods=['POST'])
@check_auth
@check_permission('prices:create')
@validate_json('process_price')
def create_process_price():
    data = get_json_body()
    try:
        pid = ProcessPriceService.create_price(data)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    try:
        audit_log('create_process_price', 'process_price', pid, str(data))
    except Exception as e:
        app.logger.warning('audit_log failed: %s', e)
    return jsonify({'message': '创建成功', 'id': pid})


@app.route('/api/process-prices/<int:pid>', methods=['PUT'])
@check_auth
@check_permission('prices:edit')
@validate_json('process_price')
def update_process_price(pid):
    data = get_json_body()
    try:
        ProcessPriceService.update_price(pid, data)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404 if '不存在' in str(e) else 400
    try:
        audit_log('update_process_price', 'process_price', pid, str(data))
    except Exception as e:
        app.logger.warning('audit_log failed: %s', e)
    return jsonify({'message': '更新成功'})


@app.route('/api/process-prices/<int:pid>', methods=['DELETE'])
@check_auth
@check_permission('prices:delete')
def delete_process_price(pid):
    try:
        ProcessPriceService.delete_price(pid)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404 if '不存在' in str(e) else 400
    try:
        audit_log('delete_process_price', 'process_price', pid)
    except Exception as e:
        app.logger.warning('audit_log failed: %s', e)
    return jsonify({'message': '删除成功'})


# ============================================================
# Product Route Pricing (产品路线工价)
# ============================================================

@app.route('/api/products/<int:product_id>/route-pricing', methods=['GET'])
@check_auth
@check_permission('prices:view')
def get_product_route_pricing(product_id):
    try:
        return jsonify(ProcessPriceService.get_product_route_pricing(product_id))
    except ValueError as e:
        return jsonify({'error': str(e)}), 404


@app.route('/api/products/<int:product_id>/route-pricing', methods=['POST'])
@check_auth
@check_permission('prices:edit')
def save_product_route_pricing(product_id):
    data = get_json_body()
    prices = data.get('prices', {})
    effective_date = data.get('effective_date', '')
    remark = data.get('remark', '')
    route_id = data.get('route_id')
    try:
        updated, created = ProcessPriceService.save_product_route_pricing(
            product_id, prices, effective_date, remark, route_id)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    msg = f'保存成功（新增 {created} 条，更新 {updated} 条）'
    try:
        audit_log('batch_save_prices', 'product', product_id, msg)
    except Exception as e:
        app.logger.warning('audit_log failed: %s', e)
    return jsonify({'message': msg, 'created': created, 'updated': updated})


# ============================================================
# Copy & Defaults
# ============================================================

@app.route('/api/process-prices/copy', methods=['POST'])
@check_auth
@check_permission('prices:create')
def copy_process_prices():
    data = get_json_body()
    from_id = data.get('from_product_id')
    to_id = data.get('to_product_id')
    if not from_id or not to_id:
        return jsonify({'error': '缺少源/目标产品ID'}), 400
    try:
        copied, skipped = ProcessPriceService.copy_prices(
            from_id, to_id, data.get('overwrite', True))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    msg = f'成功从源产品复制 {copied} 条工价' + (f'（跳过 {skipped} 条已存在）' if skipped else '')
    try:
        audit_log('copy_prices', 'product', to_id, f'from {from_id}, {copied} copied, {skipped} skipped')
    except Exception as e:
        app.logger.warning('audit_log failed: %s', e)
    return jsonify({'message': msg, 'copied': copied, 'skipped': skipped})


@app.route('/api/process-prices/defaults', methods=['GET'])
@check_auth
@check_permission('prices:view')
def get_default_prices():
    category = request.args.get('category', '')
    return jsonify(ProcessPriceService.get_defaults(category))


@app.route('/api/process-prices/defaults', methods=['POST'])
@check_auth
@check_permission('prices:edit')
def save_default_prices():
    data = get_json_body()
    prices = data.get('prices', {})
    try:
        updated, created = ProcessPriceService.save_defaults(prices)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    msg = f'默认工价保存成功（新增 {created}，更新 {updated}）'
    try:
        audit_log('save_default_prices', 'process_price', 0, msg)
    except Exception as e:
        app.logger.warning('audit_log failed: %s', e)
    return jsonify({'message': msg})


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
# Wage & Reports (工资统计与报表)
# ============================================================

@app.route('/api/wages', methods=['GET'])
@check_auth
@check_permission('prices:view')
def calculate_wages():
    employee_id = request.args.get('employee_id')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    export = request.args.get('export', '')
    include_pending = request.args.get('include_pending', '0') == '1'
    if export:
        result = WageService.calculate_wages(employee_id, date_from, date_to, 1, 999999, include_pending)
    else:
        page = max(request.args.get('page', 1, type=int), 1)
        limit = min(max(request.args.get('limit', 200, type=int), 1), 1000)
        result = WageService.calculate_wages(employee_id, date_from, date_to, page, limit, include_pending)
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

    return jsonify({'wages': wages})


@app.route('/api/daily-report', methods=['GET'])
@check_auth
@check_permission('prices:view')
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
@check_permission('prices:view')
def production_progress():
    page = max(request.args.get('page', 1, type=int), 1)
    limit = min(max(request.args.get('limit', 50, type=int), 1), 200)
    return jsonify(WageService.production_progress(page, limit))

@app.route('/api/wages/monthly-summary', methods=['GET'])
@check_auth
@check_permission('prices:view')
def monthly_summary():
    year_month = request.args.get('year_month', datetime.now().strftime('%Y-%m'))
    return jsonify(WageService.monthly_summary(year_month))

