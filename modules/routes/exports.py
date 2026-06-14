"""qr-system - Export API Routes（Refactored）"""
from flask import request, jsonify, send_file
from modules.app import app
from modules.middleware.auth import check_auth
from modules.export_utils import export_orders_to_excel, export_work_records_to_excel
from modules.services.export_service import ExportService
import io
@app.route('/api/export/orders', methods=['GET'])
@check_auth
def export_orders():
    orders = ExportService.get_orders_export()
    output = export_orders_to_excel(orders)
    return send_file(output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True, download_name='orders_export.xlsx')
@app.route('/api/export/work-records', methods=['GET'])
@check_auth
def export_work_records():
    records = ExportService.get_work_records_export(
        order_id=request.args.get('order_id'),
        date_from=request.args.get('date_from'),
        date_to=request.args.get('date_to'),
    )
    output = export_work_records_to_excel(records)
    return send_file(output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True, download_name='work_records_export.xlsx')
