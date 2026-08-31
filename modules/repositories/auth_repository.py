"""qr-system — AuthRepository（认证数据访问层）
All raw SQL lives here. Methods accept optional db for transaction sharing.
"""
from modules.repositories.context import resolve_db


class AuthRepository:
    """Authentication database operations — queries + writes, no business logic."""

    @staticmethod
    def get_login_rate(ip, cutoff, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) FROM login_attempts WHERE ip_address = ? AND created_at > ?",
            (ip, cutoff)
        ).fetchone()[0]

    @staticmethod
    def insert_login_log(username, ip, ua, success, user_id=None, fail_reason=None, db=None):
        db = resolve_db(db)
        db.execute(
            "INSERT INTO login_logs (username, user_id, ip_address, success, fail_reason, user_agent) "
            "VALUES (?,?,?,?,?,?)",
            (username, user_id, ip, success, fail_reason, ua)
        )

    @staticmethod
    def insert_login_attempt(ip, db=None):
        db = resolve_db(db)
        db.execute("INSERT INTO login_attempts (ip_address) VALUES (?)", (ip,))

    @staticmethod
    def find_user(username, db=None):
        db = resolve_db(db)
        return db.execute(
            'SELECT * FROM users WHERE username = ? AND status = "active"', (username,)
        ).fetchone()

    @staticmethod
    def find_active_user_by_token(token, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT u.*, s.created_at AS _session_created_at, "
            "s.last_active AS _session_last_active, "
            "s.active_position_id AS _active_position_id "
            "FROM users u "
            "LEFT JOIN user_sessions s ON s.user_id = u.id AND s.token = u.token AND s.is_active = 1 "
            "WHERE u.token = ? AND u.status = 'active' "
            "ORDER BY s.id DESC LIMIT 1",
            (token,),
        ).fetchone()

    @staticmethod
    def touch_session(user_id, token, active_at, db=None):
        db = resolve_db(db)
        db.execute(
            "UPDATE users SET last_active = ? WHERE id = ? AND token = ?",
            (active_at, user_id, token),
        )
        db.execute(
            "UPDATE user_sessions SET last_active = ? "
            "WHERE user_id = ? AND token = ? AND is_active = 1",
            (active_at, user_id, token),
        )

    @staticmethod
    def expire_session(user_id, token, db=None):
        db = resolve_db(db)
        db.execute(
            "UPDATE users SET token = NULL WHERE id = ? AND token = ?",
            (user_id, token),
        )
        db.execute(
            "UPDATE user_sessions SET is_active = 0 WHERE user_id = ? AND token = ?",
            (user_id, token),
        )

    @staticmethod
    def upgrade_password(user_id, new_hash, db=None):
        db = resolve_db(db)
        db.execute(
            "UPDATE users SET password = ?, password_version = 2 WHERE id = ?",
            (new_hash, user_id)
        )

    @staticmethod
    def update_login_failure(user_id, fail_count, locked_until=None, db=None):
        db = resolve_db(db)
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
        db = resolve_db(db)
        db.execute(
            'UPDATE users SET token = ?, last_active = datetime("now","localtime"), '
            'failed_login_count = 0, locked_until = NULL WHERE id = ?',
            (token, user_id)
        )

    @staticmethod
    def deactivate_user_sessions(user_id, db=None):
        db = resolve_db(db)
        db.execute(
            "UPDATE user_sessions SET is_active = 0 WHERE user_id = ? AND is_active = 1",
            (user_id,),
        )

    @staticmethod
    def create_session_insert(user_id, token, ip, ua, active_position_id=None, db=None):
        db = resolve_db(db)
        db.execute(
            "INSERT INTO user_sessions "
            "(user_id, token, ip_address, user_agent, active_position_id) "
            "VALUES (?,?,?,?,?)",
            (user_id, token, ip, ua, active_position_id)
        )

    @staticmethod
    def update_session_active_position(user_id, token, position_id, db=None):
        db = resolve_db(db)
        cursor = db.execute(
            "UPDATE user_sessions SET active_position_id = ?, "
            "last_active = datetime('now','localtime') "
            "WHERE user_id = ? AND token = ? AND is_active = 1",
            (position_id, user_id, token),
        )
        return cursor.rowcount

    @staticmethod
    def get_user_role_code(user_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT r.code FROM user_roles ur JOIN roles r ON ur.role_id = r.id "
            "WHERE ur.user_id = ? AND r.status = 'active' "
            "ORDER BY CASE WHEN r.code = 'admin' THEN 0 WHEN r.code <> 'worker' THEN 1 ELSE 2 END, r.level, r.id "
            "LIMIT 1",
            (user_id,)
        ).fetchone()
        if row:
            return row['code']
        fallback = db.execute(
            "SELECT u.role FROM users u JOIN roles r ON r.code = u.role "
            "WHERE u.id = ? AND r.status = 'active' LIMIT 1",
            (user_id,)
        ).fetchone()
        return fallback['role'] if fallback else 'worker'

    @staticmethod
    def get_user_role_codes(user_id, db=None):
        """Return every active role code assigned to a user."""
        db = resolve_db(db)
        rows = db.execute(
            "SELECT r.code FROM user_roles ur JOIN roles r ON ur.role_id=r.id "
            "WHERE ur.user_id=? AND r.status='active' ORDER BY r.level,r.id",
            (user_id,),
        ).fetchall()
        codes = [row["code"] for row in rows if row["code"]]
        if codes:
            return codes
        fallback = db.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
        return [fallback["role"]] if fallback and fallback["role"] else ["worker"]

    @staticmethod
    def logout_update_user(user_id, db=None):
        db = resolve_db(db)
        db.execute("UPDATE users SET token = NULL WHERE id = ?", (user_id,))

    @staticmethod
    def logout_deactivate_session(token, db=None):
        db = resolve_db(db)
        db.execute("UPDATE user_sessions SET is_active = 0 WHERE token = ?", (token,))

    @staticmethod
    def list_sessions(user_id, current_token, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id, ip_address, user_agent, created_at, last_active, "
            "CASE WHEN token = ? AND is_active = 1 THEN 1 ELSE 0 END AS is_active, "
            "CASE WHEN token = ? THEN 1 ELSE 0 END AS is_current "
            "FROM user_sessions WHERE user_id = ? ORDER BY created_at DESC LIMIT 50",
            (current_token, current_token, user_id),
        ).fetchall()

    @staticmethod
    def find_session_by_id(sid, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM user_sessions WHERE id = ?", (sid,)
        ).fetchone()

    @staticmethod
    def get_session_for_user(sid, user_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM user_sessions WHERE id = ? AND user_id = ?", (sid, user_id)
        ).fetchone()

    @staticmethod
    def deactivate_session_by_id(sid, db=None):
        db = resolve_db(db)
        db.execute("UPDATE user_sessions SET is_active = 0 WHERE id = ?", (sid,))

    @staticmethod
    def clear_user_token_by_token(token, db=None):
        db = resolve_db(db)
        db.execute("UPDATE users SET token = NULL WHERE token = ?", (token,))

    @staticmethod
    def change_password(user_id, new_hash, db=None):
        db = resolve_db(db)
        db.execute(
            "UPDATE users SET password = ?, password_version = 2, must_change_password = 0 WHERE id = ?",
            (new_hash, user_id)
        )
