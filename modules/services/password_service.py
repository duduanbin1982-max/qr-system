"""
qr-system — PasswordService（密码策略）
"""
import bcrypt
from modules.services import BaseService


class PasswordService:
    @staticmethod
    def admin_reset_password(user_id, new_password):
        """管理员重置用户密码。Raises ValueError on failure."""
        import re
        if len(new_password) < 8:
            raise ValueError('密码至少需要8个字符')
        if not re.search(r'[A-Z]', new_password) and not re.search(r'[a-z]', new_password):
            raise ValueError('密码需包含至少一个字母')
        if not re.search(r'[0-9]', new_password):
            raise ValueError('密码需包含至少一个数字')

        db = BaseService.db()
        user = db.execute(
            'SELECT id, username, status FROM users WHERE id = ?', (user_id,)
        ).fetchone()
        if not user:
            raise ValueError('用户不存在')
        if user['status'] != 'active':
            raise ValueError('用户已禁用')

        hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
        with BaseService.transaction() as txn:
            txn.execute(
                'UPDATE users SET password = ?, password_version = 2, '
                'must_change_password = 1, locked_until = NULL, '
                'failed_login_count = 0 WHERE id = ?',
                (hashed, user_id)
            )
        return user['username']
