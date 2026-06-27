"""qr-system - Reports Routes (Refactored)"""
from datetime import datetime, timedelta
from flask import request, jsonify
from modules.app import app
from modules.middleware.auth import check_auth, check_permission
from modules.middleware.error_handler import handle_unexpected_error
from modules.services.reports_service import ReportsService
from modules.cache_utils import ttl_cache


@app.route('/api/reports/production-trend', methods=['GET'])
@check_auth
@check_permission('reports:view')
@ttl_cache(ttl_seconds=30)
def reports_production_trend():
    days = request.args.get('days', 30, type=int)
    if days <= 0:
        return jsonify({'trend': [], 'summary': {'total_output': 0, 'total_scrap': 0, 'total_rework': 0, 'scrap_rate': 0, 'rework_rate': 0, 'days': days}})
    try:
        now = datetime.now()
        end_date = now.strftime('%Y-%m-%d')
        start_date = (now - timedelta(days=days - 1)).strftime('%Y-%m-%d')
        trend_data = ReportsService.production_trend(start_date, end_date)
        total_output = sum(r['output'] for r in trend_data)
        total_scrap = sum(r['scrap'] for r in trend_data)
        total_rework = sum(r['rework'] for r in trend_data)
        total_processed = total_output + total_scrap
        return jsonify({
            'trend': trend_data,
            'summary': {
                'total_output': total_output, 'total_scrap': total_scrap,
                'total_rework': total_rework,
                'total_processed': total_processed,
                'scrap_rate': round(total_scrap / total_processed * 100, 1) if total_processed else 0,
                'rework_rate': round(total_rework / total_processed * 100, 1) if total_processed else 0,
                'days': days,
            },
        })
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/reports/worker-efficiency', methods=['GET'])
@check_auth
@check_permission('reports:view')
def reports_worker_efficiency():
    try:
        workers = ReportsService.worker_efficiency(
            start=request.args.get('start', ''),
            end=request.args.get('end', ''),
            product_code=request.args.get('product_code', ''),
        )
        return jsonify({'workers': workers})
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/reports/quality-analysis', methods=['GET'])
@check_auth
@check_permission('reports:view')
def reports_quality_analysis():
    try:
        return jsonify(ReportsService.quality_analysis(
            start=request.args.get('start', ''),
            end=request.args.get('end', ''),
            product_code=request.args.get('product_code', ''),
        ))
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/reports/order-analysis', methods=['GET'])
@check_auth
@check_permission('reports:view')
@ttl_cache(ttl_seconds=60)
def reports_order_analysis():
    try:
        return jsonify(ReportsService.order_analysis())
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/reports/product-stats', methods=['GET'])
@check_auth
@check_permission('reports:view')
@ttl_cache(ttl_seconds=30)
def reports_product_stats():
    try:
        return jsonify(ReportsService.product_stats(
            start=request.args.get('start', ''),
            product_code=request.args.get('product_code', ''),            end=request.args.get('end', ''),
        ))
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/reports/material-usage', methods=['GET'])
@check_auth
@check_permission('reports:view')
def reports_material_usage():
    try:
        return jsonify(ReportsService.material_usage(
            start=request.args.get('start', ''),
            product_code=request.args.get('product_code', ''),
            end=request.args.get('end', ''),
        ))
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/reports/shipment-stats', methods=['GET'])
@check_auth
@check_permission('reports:view')
def reports_shipment_stats():
    try:
        return jsonify(ReportsService.shipment_stats(
            start=request.args.get('start', ''),
            end=request.args.get('end', ''),
            product_code=request.args.get('product_code', ''),
        ))
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')




@app.route('/api/reports/product-process-matrix', methods=['GET'])
@check_auth
@check_permission('reports:view')
def reports_product_process_matrix():
    try:
        return jsonify(ReportsService.product_process_matrix(
            start=request.args.get('start', ''),
            end=request.args.get('end', ''),
            product_code=request.args.get('product_code', ''),
        ))
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')



@app.route('/api/reports/model-process-stats', methods=['GET'])
@check_auth
@check_permission('reports:view')
def reports_model_process_stats():
    try:
        return jsonify(ReportsService.model_process_stats(
            start=request.args.get('start', ''),
            end=request.args.get('end', ''),
        ))
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')
@app.route('/api/reports/product-process-stats', methods=['GET'])
@check_auth
@check_permission('reports:view')
def reports_product_process_stats():
    try:
        return jsonify(ReportsService.product_process_stats(
            start=request.args.get('start', ''),
            end=request.args.get('end', ''),
        ))
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/reports/dashboard-kpi', methods=['GET'])
@check_auth
@check_permission('reports:view')
@ttl_cache(ttl_seconds=30)
def reports_dashboard_kpi():
    try:
        return jsonify(ReportsService.dashboard_kpi())
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')
