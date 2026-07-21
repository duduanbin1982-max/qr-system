"""qr-system — AuthService（认证数据访问层）
CRITICAL FIX: 所有写操作接受可选 db 参数，仅独立调用时自行 commit，事务共享时不 commit
"""
import bcrypt, secrets, hashlib
from modules.services import BaseService
from modules.repositories.auth_repository import AuthRepository


class AuthService:
    """认证数据访问 — login/logout/session/password 全部 DB 操作。"""

    @staticmethod
    def _db(db=None):
        """获取数据库连接：优先使用传入的 db（事务中），否则新建连接。"""
        return db if db is not None else BaseService.db()

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
        d = AuthService._db(db)
        AuthRepository.insert_login_log(username, ip, ua, success, user_id, fail_reason, db=d)
        if db is None:
            d.commit()

    @staticmethod
    def insert_login_attempt(ip, db=None):
        d = AuthService._db(db)
        AuthRepository.insert_login_attempt(ip, db=d)
        if db is None:
            d.commit()

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
        d = AuthService._db(db)
        AuthRepository.upgrade_password(user_id, new_hash, db=d)
        if db is None:
            d.commit()

    @staticmethod
    def update_login_failure(user_id, fail_count, locked_until=None, db=None):
        d = AuthService._db(db)
        AuthRepository.update_login_failure(user_id, fail_count, locked_until, db=d)
        if db is None:
            d.commit()

    @staticmethod
    def create_session(user_id, token, ip, ua, db=None):
        d = AuthService._db(db)
        AuthRepository.create_session_update_user(user_id, token, db=d)
        AuthRepository.create_session_insert(user_id, token, ip, ua, db=d)
        if db is None:
            d.commit()

    @staticmethod
    def get_user_role_code(user_id, db=None):
        return AuthRepository.get_user_role_code(user_id, db=db)

    @staticmethod
    def logout(user_id, token, db=None):
        d = AuthService._db(db)
        AuthRepository.logout_update_user(user_id, db=d)
        AuthRepository.logout_deactivate_session(token, db=d)
        if db is None:
            d.commit()

    @staticmethod
    def list_sessions(user_id, current_token, db=None):
        return AuthRepository.list_sessions(user_id, current_token, db=db)

    @staticmethod
    def find_session_by_id(sid, db=None):
        """根据 session ID 查找会话（不限定用户，用于管理员踢人检查）"""
        return AuthRepository.find_session_by_id(sid, db=db)

    @staticmethod
    def delete_session(sid, user_id, db=None):
        d = AuthService._db(db)
        sess = AuthRepository.get_session_for_user(sid, user_id, db=d)
        if not sess:
            return None
        AuthRepository.deactivate_session_by_id(sid, db=d)
        AuthRepository.clear_user_token_by_token(sess['token'], db=d)
        if db is None:
            d.commit()
        return sess

    @staticmethod
    def change_password(user_id, new_hash, db=None):
        d = AuthService._db(db)
        AuthRepository.change_password(user_id, new_hash, db=d)
        if db is None:
            d.commit()
