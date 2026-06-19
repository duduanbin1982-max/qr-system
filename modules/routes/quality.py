"""qr-system ? ???????Refactored: all SQL ? QualityService?"""
from flask import request, jsonify, g, send_file
from modules.db import get_db
from modules.app import app
from modules.middleware.audit import audit_log
from modules.middleware.auth import check_auth, check_permission
from modules.middleware.error_handler import handle_unexpected_error
from modules.middleware.helpers import get_json_body
from modules.middleware.validate import validate_json
from modules.services.quality_service import QualityService


def _safe_int(val, default):
    try: return int(val)
    except (ValueError, TypeError): return default


@app.route('/api/quality/inspections', methods=['GET'])
@check_auth
@check_permission('quality:view')
def quality_list():
    try:
        return jsonify(QualityService.list_inspections(
            order_id=request.args.get('order_id', type=int),
            process_id=request.args.get('process_id', type=int),
            inspection_type=request.args.get('type', ''),
            result=request.args.get('result', ''),
            search=request.args.get('search', request.args.get('keyword', '')),
            date_from=request.args.get('from', ''),
            date_to=request.args.get('to', ''),
            page=_safe_int(request.args.get('page', '1'), 1),
            per_page=_safe_int(request.args.get('limit') or request.args.get('per_page', '20'), 20),
        ))
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/quality/inspections', methods=['POST'])
@check_auth
@check_permission('quality:edit')
@validate_json('quality_inspection')
def quality_create():
    data = get_json_body()
    order_id = data.get('order_id')
    if not order_id or not data.get('process_id'):
        return jsonify({'error': '订单和工序必填'}), 400

    try:
        QualityService.check_order_exists(order_id)
        inspection_id = QualityService.create_inspection(data, g.current_user.get('id'))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    try:
        audit_log('quality_create', 'quality_inspection', inspection_id, 'created')
    except Exception:
        pass
    return jsonify({'ok': True, 'id': inspection_id})


@app.route('/api/quality/inspections/<int:inspection_id>', methods=['PUT'])
@check_auth
@check_permission('quality:edit')
@validate_json('quality_update')
def quality_update(inspection_id):
    data = get_json_body()
    try:
        result = QualityService.update_inspection(inspection_id, data)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404 if '不存在' in str(e) else 400
    try:
        audit_log('quality_edit', 'quality_inspection', inspection_id, f'result={result}')
    except Exception:
        pass
    return jsonify({'ok': True, 'message': '已更新'})


@app.route('/api/quality/inspections/<int:inspection_id>', methods=['DELETE'])
@check_auth
@check_permission('quality:delete')
def quality_delete(inspection_id):
    try:
        QualityService.delete_inspection(inspection_id)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    try:
        audit_log('quality_delete', 'quality_inspection', inspection_id, 'deleted')
    except Exception:
        pass
    return jsonify({'ok': True, 'message': '已删除'})


@app.route('/api/quality/inspections/stats', methods=['GET'])
@check_auth
@check_permission('quality:view')
def quality_stats():
    try:
        return jsonify(QualityService.get_stats())
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')



@app.route('/api/quality/inspections/export', methods=['GET'])
@check_auth
@check_permission('quality:view')
def quality_export():
    try:
        output = QualityService.export_inspections(
            order_id=request.args.get('order_id', type=int),
            process_id=request.args.get('process_id', type=int),
            inspection_type=request.args.get('type', ''),
            result=request.args.get('result', ''),
            search=request.args.get('search', request.args.get('keyword', '')),
            date_from=request.args.get('from', ''),
            date_to=request.args.get('to', ''),
        )
        from flask import send_file
        from datetime import datetime as dt
        output.seek(0)
        return send_file(
            output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True, download_name=f'quality_inspections_{dt.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
        )
    except Exception as e:
        return handle_unexpected_error(e, 'export operation')


@app.route('/api/quality/spc-p-chart', methods=['GET'])
@check_auth
@check_permission('quality:view')
def quality_spc():
    try:
        return jsonify(QualityService.spc_p_chart(
            order_id=request.args.get('order_id', type=int),
            process_id=request.args.get('process_id', type=int),
            limit=request.args.get('limit', 20, type=int),
        ))
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/quality/inspector-performance', methods=['GET'])
@check_auth
@check_permission('quality:view')
def quality_inspector_perf():
    try:
        return jsonify(QualityService.inspector_performance())
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/quality/supplier-quality', methods=['GET'])
@check_auth
@check_permission('quality:view')
def quality_supplier():
    try:
        return jsonify(QualityService.supplier_quality())
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/quality/pass-rate-trend', methods=['GET'])
@check_auth
@check_permission('quality:view')
def quality_pass_rate_trend():
    try:
        weeks = request.args.get('weeks', 6, type=int)
        return jsonify({'ok': True, 'data': QualityService.pass_rate_trend(weeks)})
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/quality/inspection-templates', methods=['GET'])
@check_auth
@check_permission('quality:view')
def quality_templates():
    return jsonify({'ok': True, 'templates': QualityService.get_templates()})


@app.route('/api/quality/inspections/batch', methods=['POST'])
@check_auth
@check_permission('quality:edit')
def quality_batch_create():
    data = get_json_body()
    items = data.get('items', [])
    if not items:
        return jsonify({'error': '请提供检验项目列表'}), 400
    try:
        result = QualityService.batch_create_inspections(items, g.current_user.get('id'))
        audit_log('quality_batch', 'quality_inspection', 0, f'created {result["created"]} items')
        return jsonify({'ok': True, **result})
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/quality/defect-categories', methods=['GET'])
@check_auth
@check_permission('quality:view')
def quality_defect_categories():
    from modules.services.quality_service import DEFECT_CATEGORIES
    return jsonify({'ok': True, 'categories': DEFECT_CATEGORIES})

@app.route('/api/quality/inspections/<int:inspection_id>/attachments', methods=['GET'])
@check_auth
@check_permission('quality:view')
def quality_attachments_list(inspection_id):
    try:
        db = get_db()
        rows = db.execute(
            'SELECT id, file_name, file_type, file_size, uploaded_by, created_at FROM quality_attachments WHERE inspection_id = ? ORDER BY id DESC',
            (inspection_id,)
        ).fetchall()
        return jsonify({'ok': True, 'attachments': [dict(r) for r in rows]})
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/quality/inspections/<int:inspection_id>/attachments', methods=['POST'])
@check_auth
@check_permission('quality:edit')
def quality_attachment_upload(inspection_id):
    try:
        if 'file' not in request.files:
            return jsonify({'error': '请选择文件'}), 400
        file = request.files['file']
        if not file.filename:
            return jsonify({'error': '文件名为空'}), 400
        file_data = file.read()
        import mimetypes
        mime = mimetypes.guess_type(file.filename)[0] or ''
        db = get_db()
        db.execute(
            'INSERT INTO quality_attachments (inspection_id, file_name, file_type, file_size, file_data, uploaded_by, created_at) VALUES (?,?,?,?,?,?,datetime("now","localtime"))',
            (inspection_id, file.filename, mime, len(file_data), file_data, g.current_user.get('id'))
        )
        db.commit()
        return jsonify({'ok': True, 'message': '上传成功'})
    except Exception as e:
        return handle_unexpected_error(e, 'file upload')


@app.route('/api/quality/attachments/<int:att_id>', methods=['GET'])
@check_auth
@check_permission('quality:view')
def quality_attachment_download(att_id):
    try:
        db = get_db()
        row = db.execute('SELECT * FROM quality_attachments WHERE id = ?', (att_id,)).fetchone()
        if not row:
            return jsonify({'error': '附件不存在'}), 404
        from flask import send_file
        from io import BytesIO
        return send_file(BytesIO(row['file_data']), mimetype=row['file_type'] or 'application/octet-stream',
                         as_attachment=True, download_name=row['file_name'])
    except Exception as e:
        return handle_unexpected_error(e, 'file download')


@app.route('/api/quality/attachments/<int:att_id>', methods=['DELETE'])
@check_auth
@check_permission('quality:edit')
def quality_attachment_delete(att_id):
    try:
        db = get_db()
        db.execute('DELETE FROM quality_attachments WHERE id = ?', (att_id,))
        db.commit()
        return jsonify({'ok': True, 'message': '已删除'})
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/quality/defect-pareto', methods=['GET'])
@check_auth
@check_permission('quality:view')
def quality_defect_pareto():
    try:
        return jsonify(QualityService.defect_pareto(
            date_from=request.args.get('from', ''),
            date_to=request.args.get('to', ''),
        ))
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')

# ═══════════════════════════════════════
#  Mobile Inspection Routes (merged from inspection.py)
# ═══════════════════════════════════════

@app.route("/api/inspection/submit", methods=["POST"])
@check_auth
@check_permission("quality:edit")
def inspection_submit():
    """Submit inspection result from mobile scan (redirected here)"""
    data = get_json_body()
    try:
        QualityService.submit_inspection(data, g.current_user.get("id"), g.current_user.get("name", ""))
        audit_log("create", "inspection", 0, "qc " + data.get("result", "") + " " + data.get("process_name", ""))
        return jsonify({"message": "ok"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/inspection", methods=["GET"])
@check_auth
@check_permission("quality:view")
def inspection_list():
    """Simple inspection list (used by InspectionList page)"""
    keyword = request.args.get("keyword", "")
    result = request.args.get("result", "")
    page = _safe_int(request.args.get("page", "1"), 1)
    limit = _safe_int(request.args.get("limit", "20"), 20)
    return jsonify(QualityService.list_inspections_simple(keyword, page, limit, result))

@app.route("/api/inspection/stats", methods=["GET"])
@check_auth
@check_permission("quality:view")
def inspection_stats():
    """Simple inspection stats"""
    return jsonify(QualityService.get_inspection_stats())
