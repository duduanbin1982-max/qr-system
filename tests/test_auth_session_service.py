from datetime import datetime, timedelta

import pytest

from modules.db import get_db


def _timestamp(value):
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _set_session_times(client, auth_headers, created_at, last_active):
    token = auth_headers["Authorization"].removeprefix("Bearer ")
    with client.application.app_context():
        db = get_db()
        user = db.execute("SELECT id FROM users WHERE token = ?", (token,)).fetchone()
        db.execute(
            "UPDATE users SET last_active = ? WHERE id = ?",
            (last_active, user["id"]),
        )
        db.execute(
            "UPDATE user_sessions SET created_at = ?, last_active = ? WHERE token = ?",
            (created_at, last_active, token),
        )
        db.commit()
    return token


def _get_session_times(client, token):
    with client.application.app_context():
        db = get_db()
        user_last_active = db.execute(
            "SELECT last_active FROM users WHERE token = ?",
            (token,),
        ).fetchone()["last_active"]
        session = db.execute(
            "SELECT last_active, is_active FROM user_sessions WHERE token = ?",
            (token,),
        ).fetchone()
        return user_last_active, session["last_active"], session["is_active"]


@pytest.mark.integration
def test_auth_session_activity_writes_are_throttled(client, auth_headers):
    now = datetime.now()
    recent = _timestamp(now - timedelta(minutes=1))
    token = _set_session_times(client, auth_headers, _timestamp(now), recent)

    response = client.get("/api/auth/info", headers=auth_headers)

    assert response.status_code == 200
    assert _get_session_times(client, token) == (recent, recent, 1)


@pytest.mark.integration
def test_auth_session_activity_is_touched_after_interval(client, auth_headers):
    now = datetime.now()
    stale = _timestamp(now - timedelta(minutes=6))
    token = _set_session_times(client, auth_headers, _timestamp(now), stale)

    response = client.get("/api/auth/info", headers=auth_headers)
    user_last_active, session_last_active, is_active = _get_session_times(client, token)

    assert response.status_code == 200
    assert user_last_active > stale
    assert session_last_active == user_last_active
    assert is_active == 1


@pytest.mark.integration
def test_auth_session_absolute_timeout_invalidates_token(client, auth_headers):
    now = datetime.now()
    created_at = _timestamp(now - timedelta(hours=9))
    last_active = _timestamp(now - timedelta(minutes=1))
    token = _set_session_times(client, auth_headers, created_at, last_active)

    response = client.get("/api/auth/info", headers=auth_headers)

    assert response.status_code == 401
    assert response.get_json() == {"error": "登录已过期，请重新登录"}
    with client.application.app_context():
        db = get_db()
        assert db.execute("SELECT token FROM users WHERE username = 'testrunner'").fetchone()["token"] is None
        assert db.execute(
            "SELECT is_active FROM user_sessions WHERE token = ?",
            (token,),
        ).fetchone()["is_active"] == 0


@pytest.mark.integration
def test_session_list_marks_current_session_without_exposing_token(client, auth_headers):
    response = client.get("/api/auth/sessions", headers=auth_headers)
    sessions = response.get_json()["sessions"]

    assert response.status_code == 200
    assert any(session["is_current"] == 1 for session in sessions)
    assert all("token" not in session for session in sessions)
