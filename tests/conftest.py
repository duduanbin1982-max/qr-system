import os
import sys
import pytest
import bcrypt
import atexit

sys.path.insert(0, "/home/dubin/qr-system")
os.environ["SECRET_KEY"] = "test-secret-key-for-pytest"
os.environ["ENABLE_SWAGGER"] = "false"

import tempfile, sqlite3, shutil

# Test DB isolation: copy production schema to temp DB
_TEST_DB = os.path.join(tempfile.gettempdir(), 'qr_test_' + str(os.getpid()) + '.db')

def _setup_test_db():
    """Copy production DB schema (not data) to temp DB for safe testing."""
    prod_db = '/home/dubin/qr-system/data/production.db'
    if os.path.exists(prod_db):
        shutil.copy2(prod_db, _TEST_DB)
        # Clear all data but keep schema
        conn = sqlite3.connect(_TEST_DB)
        conn.execute("PRAGMA foreign_keys = OFF")
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        for (tname,) in tables:
            if tname not in ('sqlite_sequence',):
                conn.execute(f"DELETE FROM {tname}")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.commit()
        conn.close()
    return _TEST_DB


_setup_test_db()
os.environ["DB_PATH"] = _TEST_DB
from modules.app import app
from modules.db import get_db, close_db

app.teardown_appcontext(close_db)

import modules.routes.auth
import modules.routes.orders
import modules.routes.products
import modules.routes.processes
import modules.routes.scan_work
import modules.routes.scan_qr
import modules.routes.customers
import modules.routes.users
import modules.routes.settings
import modules.routes.dashboard
import modules.routes.board

import modules.routes.prices        # wages API
import modules.routes.materials     # materials CRUD
import modules.routes.inventory     # inventory CRUD
import modules.routes.trace         # order trace
import modules.routes.stats         # stats endpoints
import modules.routes.reports       # reports endpoints
import modules.routes.shipments     # shipments API
import modules.routes.rework        # rework API
import modules.routes.quality       # quality API
import modules.routes.schedule      # schedule API
import modules.routes.approvals     # approvals API
import modules.routes.permissions   # permissions API
import modules.routes.roles         # roles API
import modules.routes.positions     # positions API
import modules.routes.process_routes # process routes API
import modules.routes.audit_logs    # audit logs API
import modules.routes.user_roles    # user roles API
import modules.routes.notifications # notifications API
import modules.routes.personal_stats # personal stats API
import modules.routes.progress      # progress API
import modules.routes.password_security # password security API
import modules.routes.email_reports # email reports API
import modules.routes.exports       # exports API
import modules.routes.imports       # imports API
import modules.routes.order_attachments # order attachments API
import modules.routes.order_notes   # order notes API


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
            "INSERT INTO users (username, password, name, role, status, password_version, employee_no) VALUES (?, ?, ?, ?, ?, 2, ?)",
            (TEST_USER, TEST_HASH, "Test Runner", "admin", "active", "TEST-ADMIN-001")
        )
        user_id = cursor.lastrowid
    else:
        db.execute(
            "UPDATE users SET password = ?, status = 'active', role = 'admin', locked_until = NULL, failed_login_count = 0, password_version = 2 WHERE username = ?",
            (TEST_HASH, TEST_USER)
        )
        user_id = existing["id"]
    # Ensure test user has admin role in user_roles table (needed by has_permission)
    admin_role = db.execute("SELECT id FROM roles WHERE code = 'admin' AND status = 'active'").fetchone()
    if admin_role:
        existing_role = db.execute(
            "SELECT id FROM user_roles WHERE user_id = ? AND role_id = ?",
            (user_id, admin_role["id"])
        ).fetchone()
        if not existing_role:
            db.execute(
                "INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)",
                (user_id, admin_role["id"])
            )

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



def _ensure_test_order(db, user_id):
    """Create a test order if none exists."""
    existing = db.execute("SELECT id FROM orders LIMIT 1").fetchone()
    if existing:
        return existing["id"]
    # Create test customer
    db.execute("INSERT OR IGNORE INTO customers (id, name) VALUES (9999, 'Test_Customer')")
    # Create test product
    db.execute(
        "INSERT OR IGNORE INTO products (id, product_name, product_code, model, spec, category) "
        "VALUES (9999, 'Test_Product', 'TEST-CODE-001', 'TEST', 'Standard', '结构件')"
    )
    cursor = db.execute(
        "INSERT INTO orders (order_no, customer, product_name, product_code, quantity, status) "
        "VALUES ('TEST-FIXTURE-001', 'Test_Customer', 'Test_Product', 'TEST-CODE-001', 10, 'pending')"
    )
    db.commit()
    return cursor.lastrowid


@pytest.fixture
def test_order_id(client):
    """Fixture: ensures a test order exists and returns its ID."""
    with client.application.app_context():
        from modules.db import get_db
        db = get_db()
        return _ensure_test_order(db, None)


@pytest.fixture
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}

# Worker account for reporting tests (admin can't do normal reporting)
WORKER_USER = "testworker"
WORKER_PASS = "Test@1234"
WORKER_HASH = bcrypt.hashpw(WORKER_PASS.encode(), bcrypt.gensalt()).decode()

def _ensure_worker_user(db):
    existing = db.execute("SELECT id FROM users WHERE username = ?", (WORKER_USER,)).fetchone()
    if not existing:
        cursor = db.execute(
            "INSERT INTO users (username, password, name, role, status, password_version, group_name, employee_no) VALUES (?, ?, ?, ?, ?, 2, ?, ?)",
            (WORKER_USER, WORKER_HASH, "Test Worker", "worker", "active", "员工组", "TEST-WORKER-001")
        )
        user_id = cursor.lastrowid
    else:
        db.execute(
            "UPDATE users SET password = ?, status = 'active', role = 'worker', locked_until = NULL, failed_login_count = 0, password_version = 2 WHERE username = ?",
            (WORKER_HASH, WORKER_USER)
        )
        user_id = existing["id"]
    # Ensure worker role
    worker_role = db.execute("SELECT id FROM roles WHERE code = 'worker' AND status = 'active'").fetchone()
    if worker_role:
        existing_role = db.execute(
            "SELECT id FROM user_roles WHERE user_id = ? AND role_id = ?",
            (user_id, worker_role["id"])
        ).fetchone()
        if not existing_role:
            db.execute(
                "INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)",
                (user_id, worker_role["id"])
            )
    db.commit()
    return user_id

@pytest.fixture
def worker_auth_token(client):
    with client.application.app_context():
        from modules.db import get_db
        db = get_db()
        _ensure_worker_user(db)
    resp = client.post("/api/auth/login", json={
        "username": WORKER_USER,
        "password": WORKER_PASS
    })
    data = resp.get_json()
    if data and "user" in data:
        return data["user"].get("token", "")
    return data.get("token", "") if data else ""

@pytest.fixture
def worker_auth_headers(worker_auth_token):
    return {"Authorization": f"Bearer {worker_auth_token}"}

@atexit.register
def _cleanup_test_db():
    """Remove temp test database after test run."""
    if os.path.exists(_TEST_DB):
        try:
            os.remove(_TEST_DB)
        except OSError:
            pass
