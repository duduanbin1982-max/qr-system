"""
qr-system — 客户管理（路由层）

薄层：HTTP 解析 → 调用 CustomerService → 格式化响应。
注：Swagger docstring 仅供文档参考。
"""
from flask import request, jsonify

from modules.app import app
from modules.middleware.auth import check_auth, check_permission, audit_log
from modules.middleware.helpers import get_json_body
from modules.services.customer_service import CustomerService


@app.route('/api/customers', methods=['GET'])
@check_auth
@check_permission('customers:view')
def list_customers():
    """
    客户列表
    ---
    tags: [Customers]
    summary: 客户列表
    description: 获取所有客户列表，支持关键词搜索。
    parameters:
      - name: keyword
        in: query
        type: string
        description: 搜索客户名称
    responses:
      200:
        description: 客户列表
    security:
      - Bearer: []
    """
    keyword = request.args.get('keyword', '').strip()
    return jsonify(CustomerService.list_customers(keyword))


@app.route('/api/customers', methods=['POST'])
@check_auth
@check_permission('customers:create')
def create_customer():
    """
    创建客户
    ---
    tags: [Customers]
    summary: 创建客户
    description: 创建新客户。名称不可重复。
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required: [name]
          properties:
            name:
              type: string
              description: 客户名称
            contact:
              type: string
              description: 联系人
            phone:
              type: string
              description: 电话
            address:
              type: string
              description: 地址
            remark:
              type: string
              description: 备注
    responses:
      200:
        description: 创建成功
      409:
        description: 客户名称已存在
    security:
      - Bearer: []
    """
    data = get_json_body()
    try:
        cid = CustomerService.create_customer(data)
    except ValueError as e:
        return jsonify({'error': str(e)}), 409 if '已存在' in str(e) else 400
    try:
        audit_log('create_customer', 'customer', cid, data.get('name', ''))
    except Exception:
        pass
    return jsonify({'message': '创建成功', 'id': cid})


@app.route('/api/customers/<int:cid>', methods=['PUT'])
@check_auth
@check_permission('customers:edit')
def update_customer(cid):
    """
    更新客户
    ---
    tags: [Customers]
    summary: 更新客户
    description: 更新客户信息。
    parameters:
      - name: cid
        in: path
        type: integer
        required: true
        description: 客户ID
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            name:
              type: string
            contact:
              type: string
            phone:
              type: string
            address:
              type: string
            remark:
              type: string
    responses:
      200:
        description: 更新成功
      400:
        description: 参数错误
      409:
        description: 名称冲突
    security:
      - Bearer: []
    """
    data = get_json_body()
    try:
        CustomerService.update_customer(cid, data)
    except ValueError as e:
        return jsonify({'error': str(e)}), 409 if '已存在' in str(e) else 400
    try:
        audit_log('update_customer', 'customer', cid, str(data))
    except Exception:
        pass
    return jsonify({'message': '更新成功'})


@app.route('/api/customers/<int:cid>', methods=['DELETE'])
@check_auth
@check_permission('customers:delete')
def delete_customer(cid):
    """
    删除客户
    ---
    tags: [Customers]
    summary: 删除客户
    description: 删除客户。如果有订单关联该客户，将因 FK RESTRICT 而失败。
    parameters:
      - name: cid
        in: path
        type: integer
        required: true
        description: 客户ID
    responses:
      200:
        description: 删除成功
      400:
        description: 有订单关联，无法删除
    security:
      - Bearer: []
    """
    try:
        CustomerService.delete_customer(cid)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    try:
        audit_log('delete_customer', 'customer', cid)
    except Exception:
        pass
    return jsonify({'message': '删除成功'})


@app.route('/api/customers/<int:cid>/orders', methods=['GET'])
@check_auth
@check_permission('customers:view')
def customer_orders(cid):
    """
    客户订单历史
    ---
    tags: [Customers]
    summary: 客户订单历史
    description: 查询指定客户的所有订单记录。
    parameters:
      - name: cid
        in: path
        type: integer
        required: true
        description: 客户ID
    responses:
      200:
        description: 订单列表
    security:
      - Bearer: []
    """
    return jsonify(CustomerService.get_customer_orders(cid))
