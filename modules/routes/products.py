"""
qr-system — 产品管理（路由层）

注：docstring 中的 Swagger 标记仅供文档参考，项目未集成 Flask-RESTX。
"""
import json
from urllib.parse import quote
import os        # for import_products temp file cleanup
import tempfile  # for import_products temp file
from io import BytesIO  # for attachment download
from flask import request, jsonify, send_file, make_response, g
from modules.app import app
from modules.db import get_page_size, get_db
from modules.middleware.audit import audit_log
from modules.middleware.auth import check_auth, check_permission
from modules.config import ALLOWED_UPLOAD_EXTENSIONS
from werkzeug.utils import secure_filename
from modules.middleware.helpers import get_json_body
from modules.middleware.validate import validate_json
from modules.services.product_service import ProductService



def _safe_audit_log(action, resource_type, resource_id, detail=''):
    """安全审计日志 失败不中断主流程。"""
    try:
        audit_log(action, resource_type, resource_id, detail)
    except Exception as e:
        app.logger.warning('audit_log failed: %s', e)

@app.route('/api/products', methods=['GET'])
@check_auth
@check_permission('products:view')
def list_products():
    """
    产品列表
    ---
    tags: [Products]
    summary: 产品列表
    parameters:
      - name: keyword
        in: query
        type: string
      - name: category
        in: query
        type: string
    responses:
      200:
        description: 产品列表
    security: [{Bearer: []}]
    """
    keyword = request.args.get('keyword', '').strip()
    category = request.args.get('category', '').strip()
    page = max(request.args.get('page', 1, type=int), 1)
    limit = min(max(request.args.get("limit", 500, type=int), 1), 500)
    deleted = request.args.get('deleted', '0').strip() in ('1', 'true', 'True')
    return jsonify(ProductService.list_products(keyword, category, page, limit, deleted=deleted))


@app.route('/api/products/search', methods=['GET'])
@check_auth
@check_permission('products:view')
def search_products():
    """
    快速搜索
    ---
    tags: [Products]
    summary: 快速搜索产品
    parameters:
      - name: q
        in: query
        type: string
      - name: limit
        in: query
        type: integer
        default: 20
    responses:
      200:
        description: 搜索结果
    security: [{Bearer: []}]
    """
    q = request.args.get('q', '').strip()
    limit = request.args.get('limit', get_page_size(), type=int)
    return jsonify(ProductService.search_products(q, limit))


@app.route('/api/products', methods=['POST'])
@check_auth
@check_permission('products:create')
@validate_json('create_product')
def create_product():
    """
    创建产品
    ---
    tags: [Products]
    summary: 创建产品
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required: [product_name]
          properties:
            product_name:
              type: string
            category:
              type: string
            spec:
              type: string
            unit:
              type: string
            remark:
              type: string
    responses:
      200:
        description: 创建成功
      409:
        description: 产品编码重复
    security: [{Bearer: []}]
    """
    data = get_json_body()
    try:
        pid, product_code = ProductService.create_product(data)
    except ValueError as e:
        return jsonify({'error': str(e)}), 409 if '重复' in str(e) else 400
    _safe_audit_log('create_product', 'product', pid, data.get('product_name', ''))
    return jsonify({'message': '创建成功', 'id': pid, 'product_code': product_code})


@app.route('/api/products/<int:pid>', methods=['PUT'])
@check_auth
@check_permission('products:edit')
@validate_json('update_product')
def update_product(pid):
    """
    更新产品
    ---
    tags: [Products]
    summary: 更新产品
    parameters:
      - name: pid
        in: path
        type: integer
        required: true
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            product_name:
              type: string
            category:
              type: string
            spec:
              type: string
            unit:
              type: string
            remark:
              type: string
    responses:
      200:
        description: 更新成功
      404:
        description: 产品不存在
    security: [{Bearer: []}]
    """
    data = get_json_body()
    try:
        product_code = ProductService.update_product(pid, data)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404 if '不存在' in str(e) else 400
    _safe_audit_log('update_product', 'product', pid, str(data))
    return jsonify({'message': '更新成功', 'product_code': product_code})


@app.route('/api/products/<int:pid>/impact', methods=['GET'])
@check_auth
@check_permission('products:view')
def product_impact(pid):
    try:
        return jsonify(ProductService.check_product_impact(pid))
    except ValueError as e:
        return jsonify({"error": str(e)}), 404




@app.route('/api/products/<int:pid>/restore', methods=['PUT'])
@check_auth
@check_permission('products:edit')
def restore_product(pid):
    """恢复已软删除的产品"""
    try:
        ProductService.restore_product(pid)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    _safe_audit_log('restore_product', 'product', pid)
    return jsonify({'message': '恢复成功'})


@app.route('/api/products/<int:pid>', methods=['DELETE'])
@check_auth
@check_permission('products:delete')
def delete_product(pid):
    """
    删除产品
    ---
    tags: [Products]
    summary: 删除产品
    parameters:
      - name: pid
        in: path
        type: integer
        required: true
    responses:
      200:
        description: 删除成功
    security: [{Bearer: []}]
    """
    try:
        ProductService.delete_product(pid)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404 if '不存在' in str(e) else 400
    try:
        audit_log('delete_product', 'product', pid)
    except Exception as e:
        app.logger.warning('audit_log failed: %s', e)
    return jsonify({'message': '删除成功'})




@app.route('/api/products/<int:pid>/purge', methods=['DELETE'])
@check_auth
@check_permission('products:delete')
def purge_product(pid):
    """物理删除产品及关联数据"""
    try:
        ProductService.purge_product(pid)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    _safe_audit_log('purge_product', 'product', pid)
    return jsonify({'message': '彻底删除成功'})


@app.route('/api/products/import', methods=['POST'])
@check_auth
@check_permission('products:create')
def import_products():
    """
    Excel批量导入
    ---
    tags: [Products]
    summary: Excel批量导入产品
    parameters:
      - name: file
        in: formData
        type: file
        required: true
        description: .xlsx文件
    responses:
      200:
        description: 导入结果
    security: [{Bearer: []}]
    """
    if 'file' not in request.files:
        return jsonify({'error': '请选择Excel文件'}), 400
    file = request.files['file']
    if not file.filename or not file.filename.lower().endswith('.xlsx'):
        return jsonify({'error': '仅支持.xlsx格式'}), 400
    if file.content_type and file.content_type not in (
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/octet-stream'
    ):
        return jsonify({'error': '文件类型不符，请上传.xlsx文件'}), 400
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
    debug_path = os.path.join(os.path.dirname(tmp.name), 'last_product_import.xlsx')
    try:
        file.save(tmp.name)
        tmp.close()
        # Save a copy for debugging
        import shutil
        shutil.copy2(tmp.name, debug_path)
        result = ProductService.import_products(tmp.name)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    finally:
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)
        if os.path.exists(debug_path):
            os.unlink(debug_path)
    try:
        audit_log('import_products', 'product', 0, f'imported success={result["success"]} skipped={result.get("skipped",0)} errors={result.get("error_summary","")}')
    except Exception as e:
        app.logger.warning('audit_log failed: %s', e)
    return jsonify(result)


@app.route('/api/products/<int:product_id>/attachments', methods=['GET'])
@check_auth
@check_permission('products:view')
def list_product_attachments(product_id):
    """
    产品附件列表
    ---
    tags: [Products]
    summary: 产品附件列表
    parameters:
      - name: product_id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: 附件列表
    security: [{Bearer: []}]
    """
    return jsonify(ProductService.list_attachments(product_id))


@app.route('/api/products/<int:product_id>/attachments', methods=['POST'])
@check_auth
@check_permission('products:create')
def upload_product_attachment(product_id):
    """
    上传产品附件
    ---
    tags: [Products]
    summary: 上传产品附件
    consumes: [multipart/form-data]
    parameters:
      - name: product_id
        in: path
        type: integer
        required: true
      - name: file
        in: formData
        type: file
        required: true
    responses:
      200:
        description: 上传成功
    security: [{Bearer: []}]
    """
    if 'file' not in request.files:
        return jsonify({'error': '没有文件'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Filename cannot be empty'}), 400
    safe_name = secure_filename(file.filename)
    ext = '.' + safe_name.rsplit('.', 1)[-1].lower() if '.' in safe_name else ''
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        return jsonify({'error': f'File type {ext} not allowed'}), 400
    file_data = file.read()
    try:
        ProductService.upload_attachment(product_id, file.filename, file.content_type or '', file_data, g.current_user['id'])
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    _safe_audit_log('upload_attachment', 'product', product_id, file.filename)
    return jsonify({'message': '上传成功'})


@app.route('/api/product-attachments/<int:attachment_id>/view', methods=['GET'])
@check_auth
@check_permission('products:view')
def product_attachment_view(attachment_id):
    """
    查看附件
    ---
    tags: [Products]
    summary: 在线查看附件（图片等）
    parameters:
      - name: attachment_id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: 文件内容
    security: [{Bearer: []}]
    """
    row = ProductService.get_attachment(attachment_id)
    if not row:
        return '', 404
    resp = make_response(row['file_data'])
    resp.content_type = row['file_type'] or 'application/octet-stream'
    resp.headers['Content-Disposition'] = f"inline; filename*=UTF-8''{quote(row['file_name'])}"
    return resp


@app.route('/api/product-attachments/<int:attachment_id>/thumbnail', methods=['GET'])
@check_auth
@check_permission('products:view')
def product_thumbnail(attachment_id):
    """
    附件缩略图
    ---
    tags: [Products]
    summary: 附件缩略图
    parameters:
      - name: attachment_id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: 图片内容
    security: [{Bearer: []}]
    """
    row = ProductService.get_attachment(attachment_id)
    if not row:
        return '', 404
    resp = make_response(row['file_data'])
    resp.content_type = row['file_type'] or 'image/jpeg'
    return resp


@app.route('/api/product-attachments/<int:attachment_id>/download', methods=['GET'])
@check_auth
@check_permission('products:view')
def download_product_attachment(attachment_id):
    """
    下载附件
    ---
    tags: [Products]
    summary: 下载附件
    parameters:
      - name: attachment_id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: 文件下载
    security: [{Bearer: []}]
    """
    row = ProductService.get_attachment(attachment_id)
    if not row:
        return jsonify({'error': '附件不存在'}), 404
    return send_file(BytesIO(row['file_data']), mimetype=row['file_type'] or 'application/octet-stream', as_attachment=True, download_name=row['file_name'])


@app.route('/api/product-attachments/<int:attachment_id>', methods=['DELETE'])
@check_auth
@check_permission('products:delete')
def delete_product_attachment(attachment_id):
    """
    删除附件
    ---
    tags: [Products]
    summary: 删除产品附件
    parameters:
      - name: attachment_id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: 删除成功
    security: [{Bearer: []}]
    """
    try:
        row = ProductService.delete_attachment(attachment_id)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    _safe_audit_log('delete_attachment', 'product', attachment_id, row['file_name'])
    return jsonify({'message': '删除成功'})

# ============================================================
# Product BOM (物料配方)
# ============================================================

@app.route("/api/products/<int:product_id>/bom", methods=["GET"])
@check_auth
@check_permission("products:view")
def list_product_bom(product_id):
    """获取产品物料配方"""
    db = get_db()
    rows = db.execute("""
        SELECT pb.*, m.name as material_name, m.spec as material_spec, m.material_type,
               p.name as process_name
        FROM product_bom pb
        LEFT JOIN materials m ON pb.material_id = m.id
        LEFT JOIN processes p ON pb.process_id = p.id
        WHERE pb.product_id = ?
        ORDER BY pb.id
    """, (product_id,)).fetchall()
    return jsonify({"bom": [dict(r) for r in rows]})


@app.route("/api/products/<int:product_id>/bom", methods=["POST"])
@check_auth
@check_permission("products:edit")
def add_product_bom(product_id):
    """添加物料配方项"""
    data = request.get_json(silent=True) or {}
    material_id = data.get("material_id")
    quantity = data.get("quantity_per_unit", data.get("quantity", 1))
    process_id = data.get("process_id") or None

    if not material_id:
        return jsonify({"error": "请选择物料"}), 400

    db = get_db()
    # Check product exists
    prod = db.execute("SELECT id FROM products WHERE id = ? AND deleted_at IS NULL", (product_id,)).fetchone()
    if not prod:
        return jsonify({"error": "产品不存在"}), 404

    try:
        db.execute(
            "INSERT INTO product_bom (product_id, material_id, quantity_per_unit, process_id) VALUES (?,?,?,?)",
            (product_id, material_id, float(quantity), process_id)
        )
        db.commit()
        new_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        row = db.execute("""
            SELECT pb.*, m.name as material_name, m.spec as material_spec, m.material_type,
                   p.name as process_name
            FROM product_bom pb
            LEFT JOIN materials m ON pb.material_id = m.id
            LEFT JOIN processes p ON pb.process_id = p.id
            WHERE pb.id = ?
        """, (new_id,)).fetchone()
        return jsonify({"bom": dict(row)}), 201
    except Exception as e:
        if "UNIQUE" in str(e).upper():
            return jsonify({"error": "该物料+工序组合已存在"}), 409
        raise


@app.route("/api/products/<int:product_id>/bom/<int:bom_id>", methods=["DELETE"])
@check_auth
@check_permission("products:edit")
def delete_product_bom(product_id, bom_id):
    """删除物料配方项"""
    db = get_db()
    row = db.execute("SELECT id FROM product_bom WHERE id = ? AND product_id = ?", (bom_id, product_id)).fetchone()
    if not row:
        return jsonify({"error": "配方项不存在"}), 404
    db.execute("DELETE FROM product_bom WHERE id = ?", (bom_id,))
    db.commit()
    return jsonify({"message": "已删除"})
