"""Authentication and session data migrations."""

from modules.migration_helpers import add_column_if_missing


def m031_align_single_token_sessions(db):
    db.execute(
        "UPDATE user_sessions SET is_active = 0 "
        "WHERE is_active = 1 AND NOT EXISTS ("
        "SELECT 1 FROM users u "
        "WHERE u.id = user_sessions.user_id "
        "AND u.status = 'active' "
        "AND u.token = user_sessions.token"
        ")"
    )
    db.commit()


def m046_add_active_position_to_sessions(db):
    add_column_if_missing(db, "user_sessions", "active_position_id", "INTEGER")
    db.execute(
        "UPDATE user_sessions SET active_position_id = ("
        "SELECT u.position_id FROM users u WHERE u.id = user_sessions.user_id"
        ") WHERE active_position_id IS NULL"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_us_active_position "
        "ON user_sessions(active_position_id)"
    )
    db.commit()


MIGRATIONS = [
    (31, "Align active sessions with the current single-login token", m031_align_single_token_sessions),
    (46, "Add session-level active production position", m046_add_active_position_to_sessions),
]
