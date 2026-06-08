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
from modules.db import get_page_size
from modules.middleware.auth import check_auth, check_permission, audit_log
from modules.config import ALLOWED_UPLOAD_EXTENSIONS
from werkzeug.utils import secure_filename
from modules.middleware.helpers import get_json_body
from modules.services.product_service import ProductService


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
    return jsonify(ProductService.list_products(keyword, category))


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
    try:
        audit_log('create_product', 'product', pid, data.get('product_name', ''))
    except Exception:
        pass
    return jsonify({'message': '创建成功', 'id': pid, 'product_code': product_code})


@app.route('/api/products/<int:pid>', methods=['PUT'])
@check_auth
@check_permission('products:edit')
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
    try:
        audit_log('update_product', 'product', pid, str(data))
    except Exception:
        pass
    return jsonify({'message': '更新成功', 'product_code': product_code})


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
    except Exception:
        pass
    return jsonify({'message': '删除成功'})


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
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
    try:
        file.save(tmp.name)
        tmp.close()
        result = ProductService.import_products(tmp.name)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    finally:
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)
    try:
        audit_log('import_products', 'product', 0, f'imported {result["success"]}')
    except Exception:
        pass
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
    try:
        audit_log('upload_attachment', 'product', product_id, file.filename)
    except Exception:
        pass
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
    try:
        audit_log('delete_attachment', 'product', attachment_id, row['file_name'])
    except Exception:
        pass
    return jsonify({'message': '删除成功'})
