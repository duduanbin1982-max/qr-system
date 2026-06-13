import os
import sys
import pytest
import bcrypt

sys.path.insert(0, "/home/dubin/qr-system")
os.environ["SECRET_KEY"] = "test-secret-key-for-pytest"
os.environ["ENABLE_SWAGGER"] = "false"

from modules.app import app
from modules.db import get_db, close_db

app.teardown_appcontext(close_db)

import modules.routes.auth
import modules.routes.orders
import modules.routes.products
import modules.routes.processes
import modules.routes.scan
import modules.routes.scan_helpers
import modules.routes.scan_work
import modules.routes.scan_qr
import modules.routes.customers
import modules.routes.users
import modules.routes.settings
import modules.routes.dashboard
import modules.routes.board

TEST_USER = "testrunner"
TEST_PASS = "Test@1234"
TEST_HASH = bcrypt.hashpw(TEST_PASS.encode(), bcrypt.gensalt()).decode()


def _ensure_test_user(db):
    """Create or update test user with full admin permissions."""
    existing = db.execute(
        "SELECT id FROM users WHERE username = ?", (TEST_USER,)
    ).fetchone()
    if not existing:
        cursor = db.execute(
            "INSERT INTO users (username, password, name, role, status, password_version) VALUES (?, ?, ?, ?, ?, 2)",
            (TEST_USER, TEST_HASH, "Test Runner", "admin", "active")
        )
        user_id = cursor.lastrowid
    else:
        db.execute(
            "UPDATE users SET password = ?, status = 'active', role = 'admin', locked_until = NULL, failed_login_count = 0, password_version = 2 WHERE username = ?",
            (TEST_HASH, TEST_USER)
        )
        user_id = existing["id"]
    db.execute("DELETE FROM login_attempts")
    db.execute("DELETE FROM login_logs")
    db.commit()
    return user_id


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key"
    with app.app_context():
        db = get_db()
        _ensure_test_user(db)
    return app.test_client()


@pytest.fixture
def auth_token(client):
    resp = client.post("/api/auth/login", json={
        "username": TEST_USER,
        "password": TEST_PASS
    })
    data = resp.get_json()
    if data and "user" in data:
        return data["user"].get("token", "")
    return data.get("token", "") if data else ""


@pytest.fixture
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}