import pytest

from modules.db import get_db
from factory_auth import WORKER_HASH, WORKER_PASS, WORKER_USER, ensure_user
from factory_production import ensure_process


def _seed_position_user(client):
    with client.application.app_context():
        db = get_db()
        user_id = ensure_user(
            db,
            WORKER_USER,
            WORKER_HASH,
            "Position Worker",
            "worker",
            "TEST-POSITION-001",
            "worker-group",
        )
        primary_process_id = ensure_process(db, "Position Primary Process", 1)
        secondary_process_id = ensure_process(db, "Position Secondary Process", 2)
        unavailable_process_id = ensure_process(db, "Position Unavailable Process", 3)
        primary_position_id = db.execute(
            "INSERT INTO positions (name, description, status) "
            "VALUES ('Primary Position', '', 'active')"
        ).lastrowid
        secondary_position_id = db.execute(
            "INSERT INTO positions (name, description, status) "
            "VALUES ('Secondary Position', '', 'active')"
        ).lastrowid
        unavailable_position_id = db.execute(
            "INSERT INTO positions (name, description, status) "
            "VALUES ('Unavailable Position', '', 'active')"
        ).lastrowid
        db.executemany(
            "INSERT INTO position_processes (position_id, process_id) VALUES (?, ?)",
            [
                (primary_position_id, primary_process_id),
                (secondary_position_id, secondary_process_id),
                (unavailable_position_id, unavailable_process_id),
            ],
        )
        db.execute(
            "UPDATE users SET position_id = ? WHERE id = ?",
            (primary_position_id, user_id),
        )
        db.execute(
            "INSERT INTO user_processes (user_id, process_id) VALUES (?, ?)",
            (user_id, secondary_process_id),
        )
        db.commit()
    return user_id, primary_position_id, secondary_position_id, unavailable_position_id


def _login(client):
    response = client.post(
        "/api/auth/login",
        json={"username": WORKER_USER, "password": WORKER_PASS},
    )
    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    token = payload["user"]["token"]
    return payload, {"Authorization": f"Bearer {token}"}, token


@pytest.mark.integration
def test_login_defaults_active_position_to_primary_and_lists_authorized_positions(client):
    _, primary_position_id, secondary_position_id, unavailable_position_id = (
        _seed_position_user(client)
    )

    payload, headers, _ = _login(client)

    user = payload["user"]
    assert user["active_position_id"] == primary_position_id
    assert user["position_id"] == primary_position_id
    assert {position["id"] for position in user["available_positions"]} == {
        primary_position_id,
        secondary_position_id,
    }
    assert unavailable_position_id not in {
        position["id"] for position in user["available_positions"]
    }
    context = client.get("/api/auth/active-position", headers=headers).get_json()
    assert context["active_position"]["id"] == primary_position_id


@pytest.mark.integration
def test_switching_active_position_updates_only_current_session(client):
    user_id, primary_position_id, secondary_position_id, _ = _seed_position_user(client)
    _, headers, token = _login(client)

    response = client.put(
        "/api/auth/active-position",
        headers=headers,
        json={"position_id": secondary_position_id},
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["active_position"]["id"] == secondary_position_id
    with client.application.app_context():
        db = get_db()
        assert db.execute(
            "SELECT position_id FROM users WHERE id = ?", (user_id,)
        ).fetchone()["position_id"] == primary_position_id
        assert db.execute(
            "SELECT active_position_id FROM user_sessions WHERE token = ?", (token,)
        ).fetchone()["active_position_id"] == secondary_position_id

    info = client.get("/api/auth/info", headers=headers).get_json()["user"]
    assert info["position_id"] == primary_position_id
    assert info["active_position_id"] == secondary_position_id


@pytest.mark.integration
def test_switching_to_position_outside_effective_process_scope_is_rejected(client):
    _, primary_position_id, _, unavailable_position_id = _seed_position_user(client)
    _, headers, token = _login(client)

    response = client.put(
        "/api/auth/active-position",
        headers=headers,
        json={"position_id": unavailable_position_id},
    )

    assert response.status_code == 400
    assert "可用岗位范围" in response.get_json()["error"]
    with client.application.app_context():
        active_position_id = get_db().execute(
            "SELECT active_position_id FROM user_sessions WHERE token = ?", (token,)
        ).fetchone()["active_position_id"]
    assert active_position_id == primary_position_id
