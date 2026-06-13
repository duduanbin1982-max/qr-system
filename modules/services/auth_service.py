"""qr-system — AuthService（认证数据访问层）
CRITICAL: 所有认证相关 DB 操作集中管理，路由仅做 HTTP 解析。
"""
import bcrypt, secrets, hashlib
from modules.services import BaseService


class AuthService:
    """认证数据访问 — login/logout/session/password 全部 DB 操作。"""

    @staticmethod
    def get_login_rate(ip, cutoff):
        db = BaseService.db()
        return db.execute(
            "SELECT COUNT(*) FROM login_attempts WHERE ip_address = ? AND created_at > ?",
            (ip, cutoff)
        ).fetchone()[0]

    @staticmethod
    def insert_login_log(username, ip, ua, success, user_id=None, fail_reason=None):
        db = BaseService.db()
        db.execute(
            "INSERT INTO login_logs (username, user_id, ip_address, success, fail_reason, user_agent) "
            "VALUES (?,?,?,?,?,?)",
            (username, user_id, ip, success, fail_reason, ua)
        )
        db.commit()

    @staticmethod
    def insert_login_attempt(ip):
        db = BaseService.db()
        db.execute("INSERT INTO login_attempts (ip_address) VALUES (?)", (ip,))
        db.commit()

    @staticmethod
    def find_user(username):
        db = BaseService.db()
        return db.execute(
            'SELECT * FROM users WHERE username = ? AND status = "active"', (username,)
        ).fetchone()

    @staticmethod
    def check_password(user, password):
        stored = user['password']
        if stored.startswith('$2b$') or stored.startswith('$2a$'):
            return bcrypt.checkpw(password.encode(), stored.encode())
        return hashlib.sha256(password.encode()).hexdigest() == stored

    @staticmethod
    def upgrade_password(user_id, new_hash):
        with BaseService.transaction() as txn:
            txn.execute(
                "UPDATE users SET password = ?, password_version = 2 WHERE id = ?",
                (new_hash, user_id)
            )

    @staticmethod
    def update_login_failure(user_id, fail_count, locked_until=None):
        db = BaseService.db()
        if locked_until:
            db.execute(
                "UPDATE users SET failed_login_count = ?, locked_until = ? WHERE id = ?",
                (fail_count, locked_until, user_id)
            )
        else:
            db.execute(
                "UPDATE users SET failed_login_count = ? WHERE id = ?", (fail_count, user_id)
            )
        db.commit()

    @staticmethod
    def create_session(user_id, token, ip, ua):
        db = BaseService.db()
        db.execute(
            'UPDATE users SET token = ?, last_active = datetime("now","localtime"), '
            'failed_login_count = 0, locked_until = NULL WHERE id = ?',
            (token, user_id)
        )
        db.execute(
            "INSERT INTO user_sessions (user_id, token, ip_address, user_agent) VALUES (?,?,?,?)",
            (user_id, token, ip, ua)
        )
        db.commit()

    @staticmethod
    def get_user_role_code(user_id):
        db = BaseService.db()
        row = db.execute(
            "SELECT r.code FROM user_roles ur JOIN roles r ON ur.role_id = r.id "
            "WHERE ur.user_id = ? ORDER BY r.level LIMIT 1", (user_id,)
        ).fetchone()
        return row['code'] if row else 'worker'

    @staticmethod
    def logout(user_id, token):
        db = BaseService.db()
        db.execute("UPDATE users SET token = NULL WHERE id = ?", (user_id,))
        db.execute("UPDATE user_sessions SET is_active = 0 WHERE token = ?", (token,))
        db.commit()

    @staticmethod
    def list_sessions(user_id):
        db = BaseService.db()
        return db.execute(
            "SELECT id, ip_address, user_agent, created_at, last_active, is_active "
            "FROM user_sessions WHERE user_id = ? ORDER BY created_at DESC LIMIT 50",
            (user_id,)
        ).fetchall()


    @staticmethod
    def find_session_by_id(sid):
        """根据 session ID 查找会话（不限定用户，用于管理员踢人检查）"""
        db = BaseService.db()
        return db.execute(
            "SELECT * FROM user_sessions WHERE id = ?", (sid,)
        ).fetchone()

    @staticmethod
    def delete_session(sid, user_id):
        db = BaseService.db()
        sess = db.execute(
            "SELECT * FROM user_sessions WHERE id = ? AND user_id = ?", (sid, user_id)
        ).fetchone()
        if not sess:
            return None
        db.execute("UPDATE user_sessions SET is_active = 0 WHERE id = ?", (sid,))
        db.execute("UPDATE users SET token = NULL WHERE token = ?", (sess['token'],))
        db.commit()
        return sess

    @staticmethod
    def change_password(user_id, new_hash):
        with BaseService.transaction() as txn:
            txn.execute(
                "UPDATE users SET password = ?, password_version = 2, must_change_password = 0 WHERE id = ?",
                (new_hash, user_id)
            )
