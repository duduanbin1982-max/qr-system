import atexit
import os
import shutil
import sqlite3
import sys
import tempfile

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_DB = os.path.join(tempfile.gettempdir(), f"qr_test_{os.getpid()}.db")
TEST_TEMPLATE_DB = os.path.join(tempfile.gettempdir(), f"qr_test_template_{os.getpid()}.db")

sys.path.insert(0, PROJECT_ROOT)
os.environ["SECRET_KEY"] = "test-secret-key-for-pytest"
os.environ["ENABLE_SWAGGER"] = "false"
os.environ["DB_PATH"] = TEST_DB


def _remove_sqlite_artifacts(path):
    for suffix in ("", "-wal", "-shm"):
        candidate = path + suffix if suffix else path
        if os.path.exists(candidate):
            os.remove(candidate)


def _create_schema_database(dest_path):
    _remove_sqlite_artifacts(dest_path)
    from modules.migrations import run_migrations

    conn = sqlite3.connect(dest_path)
    conn.row_factory = sqlite3.Row
    try:
        run_migrations(conn)
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.commit()
    finally:
        conn.close()


def _prepare_template_db():
    _create_schema_database(TEST_TEMPLATE_DB)


def _reset_test_db():
    if not os.path.exists(TEST_TEMPLATE_DB):
        _prepare_template_db()
    _remove_sqlite_artifacts(TEST_DB)
    shutil.copy2(TEST_TEMPLATE_DB, TEST_DB)


_prepare_template_db()
_reset_test_db()

from modules.app import app
from modules.db import clear_settings_cache, close_db, get_db
from factories import (
    TEST_HASH,
    TEST_PASS,
    TEST_USER,
    WORKER_HASH,
    WORKER_PASS,
    WORKER_USER,
    ensure_test_order,
    ensure_user,
)

app.teardown_appcontext(close_db)

from modules.routes.registry import register_routes

register_routes()


@pytest.fixture(autouse=True)
def isolated_test_db():
    _reset_test_db()
    clear_settings_cache()
    yield
    clear_settings_cache()


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key"
    with app.app_context():
        db = get_db()
        ensure_user(db, TEST_USER, TEST_HASH, "Test Runner", "admin", "TEST-ADMIN-001")
    with app.test_client() as test_client:
        yield test_client


@pytest.fixture
def auth_token(client):
    response = client.post(
        "/api/auth/login",
        json={"username": TEST_USER, "password": TEST_PASS},
    )
    data = response.get_json() or {}
    if "user" in data:
        return data["user"].get("token", "")
    return data.get("token", "")


@pytest.fixture
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture
def test_order_id(client):
    with client.application.app_context():
        db = get_db()
        return ensure_test_order(db)


@pytest.fixture
def worker_auth_token(client):
    with client.application.app_context():
        db = get_db()
        ensure_user(
            db,
            WORKER_USER,
            WORKER_HASH,
            "Test Worker",
            "worker",
            "TEST-WORKER-001",
            "worker-group",
        )
    response = client.post(
        "/api/auth/login",
        json={"username": WORKER_USER, "password": WORKER_PASS},
    )
    data = response.get_json() or {}
    if "user" in data:
        return data["user"].get("token", "")
    return data.get("token", "")


@pytest.fixture
def worker_auth_headers(worker_auth_token):
    return {"Authorization": f"Bearer {worker_auth_token}"}


@atexit.register
def _cleanup_test_db():
    _remove_sqlite_artifacts(TEST_DB)
    _remove_sqlite_artifacts(TEST_TEMPLATE_DB)
