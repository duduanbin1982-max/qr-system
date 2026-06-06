"""
qr-system — 用户管理

薄层：HTTP 解析 → 调用 UserService → 格式化响应。
"""
from flask import request, jsonify, g

from modules.app import app
from modules.db import get_setting
from modules.middleware.auth import check_auth, check_permission, audit_log
from modules.middleware.validate import validate_json
from modules.middleware.helpers import get_json_body
from modules.services.user_service import UserService


@app.route('/api/users', methods=['GET'])
@check_auth
@check_permission('users:view')
def list_users():
    page = max(request.args.get('page', 1, type=int), 1)
    limit_raw = request.args.get('limit', get_setting('page_size', '20'), type=int)
    limit = min(max(int(limit_raw or 20), 1), 200)
    role_filter = request.args.get('role', '').strip()
    keyword = request.args.get('keyword', '').strip()
    status = request.args.get('status', '').strip()
    return jsonify(UserService.list_users(page, limit, role_filter, keyword, status))


@app.route('/api/users', methods=['POST'])
@check_auth
@check_permission('users:create')
@validate_json('create_user')
def create_user():
    data = get_json_body()
    try:
        uid, password = UserService.create_user(data)
    except ValueError as e:
        code = 409 if '已存在' in str(e) else 400
        return jsonify({'error': str(e)}), code
    audit_log('create_user', 'user', uid, f'{data.get("username")}/{data.get("name")}')
    return jsonify({'message': '添加成功', 'id': uid})


@app.route('/api/users/<int:uid>', methods=['PUT'])
@check_auth
@check_permission('users:edit')
def update_user(uid):
    data = get_json_body()
    try:
        UserService.update_user(uid, data)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404 if '不存在' in str(e) else 400
    safe_data = {k: v for k, v in data.items() if k not in ('password', 'token')}
    audit_log('update_user', 'user', uid, str(safe_data))
    return jsonify({'message': '更新成功'})


@app.route('/api/users/<int:uid>', methods=['DELETE'])
@check_auth
@check_permission('users:delete')
def delete_user(uid):
    try:
        UserService.delete_user(uid, g.current_user['id'])
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    audit_log('delete_user', 'user', uid)
    return jsonify({'message': '删除成功'})


@app.route('/api/users/<int:uid>/reset-password', methods=['POST'])
@check_auth
@check_permission('users:edit')
def reset_password(uid):
    data = get_json_body()
    try:
        new_pw = UserService.reset_password(uid, data.get('password'))
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    audit_log('reset_password', 'user', uid)
    return jsonify({'message': '密码已重置'})


@app.route('/api/users/<int:uid>/unlock', methods=['POST'])
@check_auth
@check_permission('users:edit')
def unlock_user(uid):
    try:
        UserService.unlock_user(uid)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    audit_log('unlock_user', 'user', uid)
    return jsonify({'message': '账户已解锁'})
