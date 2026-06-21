"""qr-system — AuthService（认证业务逻辑层）
Repository pattern: all SQL lives in AuthRepository. Service handles business logic only.
"""
import bcrypt, secrets, hashlib
from modules.services import BaseService
from modules.repositories.auth_repository import AuthRepository


class AuthService:
    """Authentication business logic — login/logout/session/password workflows."""

    @staticmethod
    def lock_minutes(fail_count):
        """Progressive lockout duration in minutes."""
        thresholds = [(20, 1440), (15, 120), (10, 30), (5, 5)]
        for threshold, minutes in thresholds:
            if fail_count >= threshold:
                return minutes
        return 5

    @staticmethod
    def get_login_rate(ip, cutoff, db=None):
        return AuthRepository.get_login_rate(ip, cutoff, db=db)

    @staticmethod
    def insert_login_log(username, ip, ua, success, user_id=None, fail_reason=None, db=None):
        AuthRepository.insert_login_log(username, ip, ua, success, user_id, fail_reason, db=db)
        if db is None:
            BaseService.db().commit()

    @staticmethod
    def insert_login_attempt(ip, db=None):
        AuthRepository.insert_login_attempt(ip, db=db)
        if db is None:
            BaseService.db().commit()

    @staticmethod
    def find_user(username, db=None):
        return AuthRepository.find_user(username, db=db)

    @staticmethod
    def check_password(user, password):
        stored = user['password']
        if stored.startswith('$2b$') or stored.startswith('$2a$'):
            return bcrypt.checkpw(password.encode(), stored.encode())
        return hashlib.sha256(password.encode()).hexdigest() == stored

    @staticmethod
    def upgrade_password(user_id, new_hash, db=None):
        AuthRepository.upgrade_password(user_id, new_hash, db=db)
        if db is None:
            BaseService.db().commit()

    @staticmethod
    def update_login_failure(user_id, fail_count, locked_until=None, db=None):
        AuthRepository.update_login_failure(user_id, fail_count, locked_until, db=db)
        if db is None:
            BaseService.db().commit()

    @staticmethod
    def create_session(user_id, token, ip, ua, db=None):
        AuthRepository.create_session_update_user(user_id, token, db=db)
        AuthRepository.create_session_insert(user_id, token, ip, ua, db=db)
        if db is None:
            BaseService.db().commit()

    @staticmethod
    def get_user_role_code(user_id, db=None):
        return AuthRepository.get_user_role_code(user_id, db=db)

    @staticmethod
    def logout(user_id, token, db=None):
        AuthRepository.logout_update_user(user_id, db=db)
        AuthRepository.logout_deactivate_session(token, db=db)
        if db is None:
            BaseService.db().commit()

    @staticmethod
    def list_sessions(user_id, db=None):
        return AuthRepository.list_sessions(user_id, db=db)

    @staticmethod
    def find_session_by_id(sid, db=None):
        """根据 session ID 查找会话（不限定用户，用于管理员踢人检查）"""
        return AuthRepository.find_session_by_id(sid, db=db)

    @staticmethod
    def delete_session(sid, user_id, db=None):
        sess = AuthRepository.get_session_for_user(sid, user_id, db=db)
        if not sess:
            return None
        AuthRepository.deactivate_session_by_id(sid, db=db)
        AuthRepository.clear_user_token_by_token(sess['token'], db=db)
        if db is None:
            BaseService.db().commit()
        return sess

    @staticmethod
    def change_password(user_id, new_hash, db=None):
        AuthRepository.change_password(user_id, new_hash, db=db)
        if db is None:
            BaseService.db().commit()
