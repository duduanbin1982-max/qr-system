"""qr-system - Password Policy & Admin Reset（Refactored）"""
from flask import request, jsonify, g
from modules.app import app
from modules.middleware.audit import safe_audit_log
from modules.middleware.auth import check_auth, check_permission
from modules.middleware.validate import validate_json
from modules.middleware.helpers import get_json_body
from modules.services.password_service import PasswordService


@app.route('/api/auth/reset-password/<int:user_id>', methods=['POST'])
@check_auth
@check_permission('users:edit')
@validate_json('change_password')
def admin_reset_password(user_id):
    data = get_json_body()
    try:
        username = PasswordService.admin_reset_password(
            user_id, data.get('new_password', '').strip()
        )
        safe_audit_log('reset_password', 'user', user_id,
                       f'Admin {g.current_user.get("username","")} reset password for {username}')
        return jsonify({'message': f'已重置用户 {username} 的密码，下次登录需修改密码'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
