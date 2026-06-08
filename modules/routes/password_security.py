"""qr-system - Password Policy & Admin Reset"""
import re
from flask import request, jsonify, g
from modules.app import app
from modules.db import get_db
from modules.middleware.auth import check_auth, check_permission, audit_log
from modules.middleware.validate import validate_json
from modules.middleware.helpers import get_json_body
import bcrypt


def validate_password_strength(password):
    """Validate password meets complexity requirements.
    Returns (True, '') or (False, error_message).
    """
    if len(password) < 8:
        return False, '密码至少需要8个字符'
    if not re.search(r'[A-Z]', password) and not re.search(r'[a-z]', password):
        return False, '密码需包含至少一个字母'
    if not re.search(r'[0-9]', password):
        return False, '密码需包含至少一个数字'
    return True, ''


@app.route('/api/auth/reset-password/<int:user_id>', methods=['POST'])
@check_auth
@check_permission('users:edit')
@validate_json('change_password')
def admin_reset_password(user_id):
    """Admin resets a user password."""
    data = get_json_body()
    new_password = data.get('new_password', '').strip()
    
    valid, msg = validate_password_strength(new_password)
    if not valid:
        return jsonify({'error': msg}), 400
    
    db = get_db()
    user = db.execute('SELECT id, username, status FROM users WHERE id = ?', (user_id,)).fetchone()
    if not user:
        return jsonify({'error': '用户不存在'}), 404
    if user['status'] != 'active':
        return jsonify({'error': '用户已禁用'}), 400
    
    hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    db.execute(
        'UPDATE users SET password = ?, password_version = 2, must_change_password = 1, locked_until = NULL, failed_login_count = 0 WHERE id = ?',
        (hashed, user_id)
    )
    db.commit()
    
    audit_log('reset_password', 'user', user_id,
              f'Admin {g.current_user.get("username","")} reset password for {user["username"]}')
    
    return jsonify({'message': f'已重置用户 {user["username"]} 的密码，下次登录需修改密码'})
