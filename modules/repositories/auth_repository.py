"""qr-system — AuthRepository（认证数据访问层）
All raw SQL lives here. Methods accept optional db for transaction sharing.
"""
from modules.services import BaseService


class AuthRepository:
    """Authentication database operations — queries + writes, no business logic."""

    @staticmethod
    def get_login_rate(ip, cutoff, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT COUNT(*) FROM login_attempts WHERE ip_address = ? AND created_at > ?",
            (ip, cutoff)
        ).fetchone()[0]

    @staticmethod
    def insert_login_log(username, ip, ua, success, user_id=None, fail_reason=None, db=None):
        db = db or BaseService.db()
        db.execute(
            "INSERT INTO login_logs (username, user_id, ip_address, success, fail_reason, user_agent) "
            "VALUES (?,?,?,?,?,?)",
            (username, user_id, ip, success, fail_reason, ua)
        )

    @staticmethod
    def insert_login_attempt(ip, db=None):
        db = db or BaseService.db()
        db.execute("INSERT INTO login_attempts (ip_address) VALUES (?)", (ip,))

    @staticmethod
    def find_user(username, db=None):
        db = db or BaseService.db()
        return db.execute(
            'SELECT * FROM users WHERE username = ? AND status = "active"', (username,)
        ).fetchone()

    @staticmethod
    def upgrade_password(user_id, new_hash, db=None):
        db = db or BaseService.db()
        db.execute(
            "UPDATE users SET password = ?, password_version = 2 WHERE id = ?",
            (new_hash, user_id)
        )

    @staticmethod
    def update_login_failure(user_id, fail_count, locked_until=None, db=None):
        db = db or BaseService.db()
        if locked_until:
            db.execute(
                "UPDATE users SET failed_login_count = ?, locked_until = ? WHERE id = ?",
                (fail_count, locked_until, user_id)
            )
        else:
            db.execute(
                "UPDATE users SET failed_login_count = ? WHERE id = ?", (fail_count, user_id)
            )

    @staticmethod
    def create_session_update_user(user_id, token, db=None):
        db = db or BaseService.db()
        db.execute(
            'UPDATE users SET token = ?, last_active = datetime("now","localtime"), '
            'failed_login_count = 0, locked_until = NULL WHERE id = ?',
            (token, user_id)
        )

    @staticmethod
    def create_session_insert(user_id, token, ip, ua, db=None):
        db = db or BaseService.db()
        db.execute(
            "INSERT INTO user_sessions (user_id, token, ip_address, user_agent) VALUES (?,?,?,?)",
            (user_id, token, ip, ua)
        )

    @staticmethod
    def get_user_role_code(user_id, db=None):
        db = db or BaseService.db()
        row = db.execute(
            "SELECT r.code FROM user_roles ur JOIN roles r ON ur.role_id = r.id "
            "WHERE ur.user_id = ? ORDER BY r.level LIMIT 1", (user_id,)
        ).fetchone()
        return row['code'] if row else 'worker'

    @staticmethod
    def logout_update_user(user_id, db=None):
        db = db or BaseService.db()
        db.execute("UPDATE users SET token = NULL WHERE id = ?", (user_id,))

    @staticmethod
    def logout_deactivate_session(token, db=None):
        db = db or BaseService.db()
        db.execute("UPDATE user_sessions SET is_active = 0 WHERE token = ?", (token,))

    @staticmethod
    def list_sessions(user_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT id, ip_address, user_agent, created_at, last_active, is_active "
            "FROM user_sessions WHERE user_id = ? ORDER BY created_at DESC LIMIT 50",
            (user_id,)
        ).fetchall()

    @staticmethod
    def find_session_by_id(sid, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT * FROM user_sessions WHERE id = ?", (sid,)
        ).fetchone()

    @staticmethod
    def get_session_for_user(sid, user_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT * FROM user_sessions WHERE id = ? AND user_id = ?", (sid, user_id)
        ).fetchone()

    @staticmethod
    def deactivate_session_by_id(sid, db=None):
        db = db or BaseService.db()
        db.execute("UPDATE user_sessions SET is_active = 0 WHERE id = ?", (sid,))

    @staticmethod
    def clear_user_token_by_token(token, db=None):
        db = db or BaseService.db()
        db.execute("UPDATE users SET token = NULL WHERE token = ?", (token,))

    @staticmethod
    def change_password(user_id, new_hash, db=None):
        db = db or BaseService.db()
        db.execute(
            "UPDATE users SET password = ?, password_version = 2, must_change_password = 0 WHERE id = ?",
            (new_hash, user_id)
        )
