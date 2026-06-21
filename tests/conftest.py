import os
import re
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
    """Create in-memory SQLite DB from production schema for fast testing."""
    schema_file = '/tmp/qr_schema.sql'
    # Regenerate schema dump if stale (>1 hour or missing)
    prod_db = '/home/dubin/qr-system/data/production.db'
    if not os.path.exists(schema_file) or (os.path.exists(prod_db) and os.path.getmtime(prod_db) > os.path.getmtime(schema_file)):
        import subprocess
        subprocess.run(['sqlite3', prod_db, '.schema'], stdout=open(schema_file, 'w'), check=True)
    
    # Use shared in-memory DB: all connections share the same memory DB
    db_uri = 'file:qrtest?mode=memory&cache=shared'
    conn = sqlite3.connect(db_uri, uri=True)
    with open(schema_file, 'r') as f:
        schema_sql = f.read()
    # Filter out internal SQLite tables that cannot be created explicitly
    schema_sql = re.sub(r'CREATE TABLE sqlite_\w+[^;]*;', '', schema_sql)
    # Also filter CREATE INDEX on sqlite_* and sqlite_stat* tables
    schema_sql = re.sub(r'CREATE.*INDEX.*ON sqlite_\w+[^;]*;', '', schema_sql)
    conn.executescript(schema_sql)
    conn.commit()
    conn.close()
    return db_uri


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


def _ensure_user(db, username, password_hash, name, role, employee_no, group_name=None):
    """Create or update a test user with role assignment. Parameterized to avoid duplication."""
    existing = db.execute(
        "SELECT id FROM users WHERE username = ?", (username,)
    ).fetchone()
    if not existing:
        cols = "username, password, name, role, status, password_version, employee_no"
        vals = "?, ?, ?, ?, ?, 2, ?"
        params = [username, password_hash, name, role, "active", employee_no]
        if group_name:
            cols += ", group_name"
            vals += ", ?"
            params.append(group_name)
        cursor = db.execute(
            f"INSERT INTO users ({cols}) VALUES ({vals})", params
        )
        user_id = cursor.lastrowid
    else:
        db.execute(
            "UPDATE users SET password = ?, status = 'active', role = ?, locked_until = NULL, failed_login_count = 0, password_version = 2 WHERE username = ?",
            (password_hash, role, username)
        )
        user_id = existing["id"]
    # Ensure role assignment in user_roles table (needed by has_permission)
    role_row = db.execute("SELECT id FROM roles WHERE code = ? AND status = 'active'", (role,)).fetchone()
    if role_row:
        existing_role = db.execute(
            "SELECT id FROM user_roles WHERE user_id = ? AND role_id = ?",
            (user_id, role_row["id"])
        ).fetchone()
        if not existing_role:
            db.execute(
                "INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)",
                (user_id, role_row["id"])
            )
    # Clear login attempts for admin users (not needed for workers)
    if role == "admin":
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
        _ensure_user(db, TEST_USER, TEST_HASH, "Test Runner", "admin", "TEST-ADMIN-001")
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


@pytest.fixture
def worker_auth_token(client):
    with client.application.app_context():
        from modules.db import get_db
        db = get_db()
        _ensure_user(db, WORKER_USER, WORKER_HASH, "Test Worker", "worker", "TEST-WORKER-001", "员工组")
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
