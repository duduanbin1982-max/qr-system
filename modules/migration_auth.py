"""Authentication and session data migrations."""


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


MIGRATIONS = [
    (31, "Align active sessions with the current single-login token", m031_align_single_token_sessions),
]
