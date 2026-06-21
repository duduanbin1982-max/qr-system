"""qr-system - PasswordService"""
import bcrypt
from modules.services import BaseService
from modules.repositories.password_repository import PasswordRepository


class PasswordService:
    @staticmethod
    def admin_reset_password(user_id, new_password):
        """Admin reset user password. Raises ValueError on failure."""
        import re
        if len(new_password) < 8:
            raise ValueError('Password must be at least 8 characters')
        if not re.search(r'[A-Z]', new_password) and not re.search(r'[a-z]', new_password):
            raise ValueError('Password must contain at least one letter')
        if not re.search(r'[0-9]', new_password):
            raise ValueError('Password must contain at least one digit')

        user = PasswordRepository.find_active_user(user_id)
        if not user:
            raise ValueError('User not found')
        if user['status'] != 'active':
            raise ValueError('User is disabled')

        hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
        with BaseService.transaction() as txn:
            PasswordRepository.reset_password_txn(user_id, hashed, db=txn)
        return user['username']
