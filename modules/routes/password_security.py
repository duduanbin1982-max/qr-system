"""qr-system - Password Policy & Admin Reset（Refactored）"""
from flask import request, jsonify, g
from modules.route_decorators import (
    app,
    check_auth,
    check_permission,
    get_json_body,
    validate_json,
)
from modules.services.user_service import UserService


@app.route('/api/auth/reset-password/<int:user_id>', methods=['POST'])
@check_auth
@check_permission('users:admin')
@validate_json('change_password')
def admin_reset_password(user_id):
    data = get_json_body()
    try:
        UserService.reset_password(
            user_id,
            data.get('new_password', '').strip(),
            g.current_user.get('id'),
        )
        return jsonify({'message': '密码已重置，下次登录需修改密码'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
