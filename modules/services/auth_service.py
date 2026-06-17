"""qr-system — AuthService（认证数据访问层）
CRITICAL FIX: 所有写操作接受可选 db 参数，仅独立调用时自行 commit，事务共享时不 commit
"""
import bcrypt, secrets, hashlib
from modules.services import BaseService


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
        return AuthService._db(db).execute(
            "SELECT COUNT(*) FROM login_attempts WHERE ip_address = ? AND created_at > ?",
            (ip, cutoff)
        ).fetchone()[0]

    @staticmethod
    def insert_login_log(username, ip, ua, success, user_id=None, fail_reason=None, db=None):
        d = AuthService._db(db)
        d.execute(
            "INSERT INTO login_logs (username, user_id, ip_address, success, fail_reason, user_agent) "
            "VALUES (?,?,?,?,?,?)",
            (username, user_id, ip, success, fail_reason, ua)
        )
        if db is None:
            d.commit()

    @staticmethod
    def insert_login_attempt(ip, db=None):
        d = AuthService._db(db)
        d.execute("INSERT INTO login_attempts (ip_address) VALUES (?)", (ip,))
        if db is None:
            d.commit()

    @staticmethod
    def find_user(username, db=None):
        return AuthService._db(db).execute(
            'SELECT * FROM users WHERE username = ? AND status = "active"', (username,)
        ).fetchone()

    @staticmethod
    def check_password(user, password):
        stored = user['password']
        if stored.startswith('$2b$') or stored.startswith('$2a$'):
            return bcrypt.checkpw(password.encode(), stored.encode())
        return hashlib.sha256(password.encode()).hexdigest() == stored

    @staticmethod
    def upgrade_password(user_id, new_hash, db=None):
        d = AuthService._db(db)
        d.execute(
            "UPDATE users SET password = ?, password_version = 2 WHERE id = ?",
            (new_hash, user_id)
        )
        if db is None:
            d.commit()

    @staticmethod
    def update_login_failure(user_id, fail_count, locked_until=None, db=None):
        d = AuthService._db(db)
        if locked_until:
            d.execute(
                "UPDATE users SET failed_login_count = ?, locked_until = ? WHERE id = ?",
                (fail_count, locked_until, user_id)
            )
        else:
            d.execute(
                "UPDATE users SET failed_login_count = ? WHERE id = ?", (fail_count, user_id)
            )
        if db is None:
            d.commit()

    @staticmethod
    def create_session(user_id, token, ip, ua, db=None):
        d = AuthService._db(db)
        d.execute(
            'UPDATE users SET token = ?, last_active = datetime("now","localtime"), '
            'failed_login_count = 0, locked_until = NULL WHERE id = ?',
            (token, user_id)
        )
        d.execute(
            "INSERT INTO user_sessions (user_id, token, ip_address, user_agent) VALUES (?,?,?,?)",
            (user_id, token, ip, ua)
        )
        if db is None:
            d.commit()

    @staticmethod
    def get_user_role_code(user_id, db=None):
        row = AuthService._db(db).execute(
            "SELECT r.code FROM user_roles ur JOIN roles r ON ur.role_id = r.id "
            "WHERE ur.user_id = ? ORDER BY r.level LIMIT 1", (user_id,)
        ).fetchone()
        return row['code'] if row else 'worker'

    @staticmethod
    def logout(user_id, token, db=None):
        d = AuthService._db(db)
        d.execute("UPDATE users SET token = NULL WHERE id = ?", (user_id,))
        d.execute("UPDATE user_sessions SET is_active = 0 WHERE token = ?", (token,))
        if db is None:
            d.commit()

    @staticmethod
    def list_sessions(user_id, db=None):
        return AuthService._db(db).execute(
            "SELECT id, ip_address, user_agent, created_at, last_active, is_active "
            "FROM user_sessions WHERE user_id = ? ORDER BY created_at DESC LIMIT 50",
            (user_id,)
        ).fetchall()

    @staticmethod
    def find_session_by_id(sid, db=None):
        """根据 session ID 查找会话（不限定用户，用于管理员踢人检查）"""
        return AuthService._db(db).execute(
            "SELECT * FROM user_sessions WHERE id = ?", (sid,)
        ).fetchone()

    @staticmethod
    def delete_session(sid, user_id, db=None):
        d = AuthService._db(db)
        sess = d.execute(
            "SELECT * FROM user_sessions WHERE id = ? AND user_id = ?", (sid, user_id)
        ).fetchone()
        if not sess:
            return None
        d.execute("UPDATE user_sessions SET is_active = 0 WHERE id = ?", (sid,))
        d.execute("UPDATE users SET token = NULL WHERE token = ?", (sess['token'],))
        if db is None:
            d.commit()
        return sess

    @staticmethod
    def change_password(user_id, new_hash, db=None):
        d = AuthService._db(db)
        d.execute(
            "UPDATE users SET password = ?, password_version = 2, must_change_password = 0 WHERE id = ?",
            (new_hash, user_id)
        )
        if db is None:
            d.commit()
