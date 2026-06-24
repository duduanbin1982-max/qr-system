import atexit
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import uuid

import bcrypt
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRODUCTION_DB = os.path.join(PROJECT_ROOT, "data", "production.db")
TEST_DB = os.path.join(tempfile.gettempdir(), f"qr_test_{os.getpid()}.db")
TEST_TEMPLATE_DB = os.path.join(tempfile.gettempdir(), f"qr_test_template_{os.getpid()}.db")
SCRUB_USERNAMES = ("testrunner", "testworker")
SCRUB_EMPLOYEE_NO_PATTERN = "TEST-%"
SCRUB_ORDER_PREFIX = "TEST-%"
SCRUB_CROSS_MODULE_CUSTOMER = "Cross Module Customer"
SCRUB_CROSS_MODULE_PRODUCT = "Cross Module Product"
SCRUB_PROCESS_NAME_PREFIX = "Fixture %"
SCRUB_PROCESS_DESCRIPTIONS = ("pytest fixture process", "cross module fixture")
SCRUB_ROUTE_NAME_PREFIX = "Fixture Route %"
SCRUB_PRODUCT_CODE_PREFIX = "XMOD-%"
SCRUB_PRODUCT_CODES = ("TEST-CODE-001",)
SCRUB_PRODUCT_NAMES = ("Test Product", "Cross Module Product")
SCRUB_CUSTOMER_NAMES = ("Test Customer", "Test_Customer", "Cross Module Customer")

sys.path.insert(0, PROJECT_ROOT)
os.environ["SECRET_KEY"] = "test-secret-key-for-pytest"
os.environ["ENABLE_SWAGGER"] = "false"
os.environ["DB_PATH"] = TEST_DB


def _remove_sqlite_artifacts(path):
    for suffix in ("", "-wal", "-shm"):
        candidate = path + suffix if suffix else path
        if os.path.exists(candidate):
            os.remove(candidate)


def _backup_database(source_path, dest_path):
    _remove_sqlite_artifacts(dest_path)
    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    dest = sqlite3.connect(dest_path)
    try:
        source.backup(dest)
        dest.execute("PRAGMA journal_mode=DELETE")
        dest.commit()
    finally:
        dest.close()
        source.close()


def _table_columns(conn):
    tables = {}
    for (table_name,) in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ):
        tables[table_name] = {
            row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")
        }
    return tables


def _delete_where_in(conn, table_name, column_name, values):
    if not values:
        return
    placeholders = ",".join("?" for _ in values)
    conn.execute(
        f"DELETE FROM {table_name} WHERE {column_name} IN ({placeholders})",
        tuple(values),
    )


def _delete_where_like(conn, table_name, column_name, pattern):
    conn.execute(
        f"DELETE FROM {table_name} WHERE {column_name} LIKE ?",
        (pattern,),
    )


def _select_ids(conn, query, params=()):
    return [row[0] for row in conn.execute(query, params).fetchall()]


def _scrub_runtime_state(conn):
    conn.execute("DELETE FROM login_attempts")
    conn.execute("DELETE FROM login_logs")
    conn.execute("DELETE FROM user_sessions")
    conn.execute(
        "UPDATE users SET token = NULL, locked_until = NULL, failed_login_count = 0"
    )


def _scrub_fixture_artifacts(conn):
    order_rows = conn.execute(
        "SELECT id, order_no FROM orders "
        "WHERE order_no LIKE ? OR (customer = ? AND product_name = ?)",
        (
            SCRUB_ORDER_PREFIX,
            SCRUB_CROSS_MODULE_CUSTOMER,
            SCRUB_CROSS_MODULE_PRODUCT,
        ),
    ).fetchall()
    order_ids = sorted({row[0] for row in order_rows})
    order_nos = sorted({row[1] for row in order_rows})

    user_ids = sorted(
        _select_ids(
            conn,
            "SELECT id FROM users WHERE username IN (?, ?) OR employee_no LIKE ?",
            (
                SCRUB_USERNAMES[0],
                SCRUB_USERNAMES[1],
                SCRUB_EMPLOYEE_NO_PATTERN,
            ),
        )
    )

    process_ids = sorted(
        _select_ids(
            conn,
            "SELECT id FROM processes WHERE name LIKE ? OR description IN (?, ?)",
            (
                SCRUB_PROCESS_NAME_PREFIX,
                SCRUB_PROCESS_DESCRIPTIONS[0],
                SCRUB_PROCESS_DESCRIPTIONS[1],
            ),
        )
    )

    route_ids = sorted(
        _select_ids(
            conn,
            "SELECT id FROM process_routes WHERE name LIKE ? OR description = ?",
            (SCRUB_ROUTE_NAME_PREFIX, SCRUB_PROCESS_DESCRIPTIONS[1]),
        )
    )

    product_ids = sorted(
        _select_ids(
            conn,
            "SELECT id FROM products WHERE product_code IN (?) "
            "OR product_code LIKE ? OR product_name IN (?, ?)",
            (
                SCRUB_PRODUCT_CODES[0],
                SCRUB_PRODUCT_CODE_PREFIX,
                SCRUB_PRODUCT_NAMES[0],
                SCRUB_PRODUCT_NAMES[1],
            ),
        )
    )

    customer_ids = sorted(
        _select_ids(
            conn,
            "SELECT id FROM customers WHERE name IN (?, ?, ?)",
            SCRUB_CUSTOMER_NAMES,
        )
    )

    tables = _table_columns(conn)
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        for table_name, columns in tables.items():
            if "order_id" in columns:
                _delete_where_in(conn, table_name, "order_id", order_ids)
            if "order_no" in columns:
                _delete_where_in(conn, table_name, "order_no", order_nos)
            if "user_id" in columns:
                _delete_where_in(conn, table_name, "user_id", user_ids)
            if "username" in columns:
                _delete_where_in(conn, table_name, "username", SCRUB_USERNAMES)
            if "employee_no" in columns:
                _delete_where_like(
                    conn, table_name, "employee_no", SCRUB_EMPLOYEE_NO_PATTERN
                )
            if "process_id" in columns:
                _delete_where_in(conn, table_name, "process_id", process_ids)
            if "route_id" in columns:
                _delete_where_in(conn, table_name, "route_id", route_ids)
            if "product_id" in columns:
                _delete_where_in(conn, table_name, "product_id", product_ids)
            if "customer_id" in columns:
                _delete_where_in(conn, table_name, "customer_id", customer_ids)

        _delete_where_in(conn, "orders", "id", order_ids)
        _delete_where_in(conn, "users", "id", user_ids)
        _delete_where_in(conn, "processes", "id", process_ids)
        _delete_where_in(conn, "process_routes", "id", route_ids)
        _delete_where_in(conn, "products", "id", product_ids)
        _delete_where_in(conn, "customers", "id", customer_ids)
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def _prepare_template_db():
    _backup_database(PRODUCTION_DB, TEST_TEMPLATE_DB)
    conn = sqlite3.connect(TEST_TEMPLATE_DB)
    try:
        _scrub_runtime_state(conn)
        _scrub_fixture_artifacts(conn)
        conn.commit()
    finally:
        conn.close()


def _reset_test_db():
    if not os.path.exists(TEST_TEMPLATE_DB):
        _prepare_template_db()
    _remove_sqlite_artifacts(TEST_DB)
    shutil.copy2(TEST_TEMPLATE_DB, TEST_DB)


_prepare_template_db()
_reset_test_db()

from modules.app import app
from modules.db import clear_settings_cache, close_db, get_db
from modules.config import PREDEFINED_ROLES

app.teardown_appcontext(close_db)

import modules.routes.approvals
import modules.routes.audit_logs
import modules.routes.auth
import modules.routes.board
import modules.routes.customers
import modules.routes.dashboard
import modules.routes.email_reports
import modules.routes.exports
import modules.routes.imports
import modules.routes.inventory
import modules.routes.materials
import modules.routes.notifications
import modules.routes.order_attachments
import modules.routes.order_notes
import modules.routes.orders
import modules.routes.password_security
import modules.routes.permissions
import modules.routes.personal_stats
import modules.routes.positions
import modules.routes.prices
import modules.routes.process_routes
import modules.routes.processes
import modules.routes.products
import modules.routes.progress
import modules.routes.quality
import modules.routes.reports
import modules.routes.rework
import modules.routes.roles
import modules.routes.scan_qr
import modules.routes.scan_work
import modules.routes.schedule
import modules.routes.settings
import modules.routes.shipments
import modules.routes.stats
import modules.routes.trace
import modules.routes.user_roles
import modules.routes.users


TEST_USER = "testrunner"
TEST_PASS = "Test@1234"
TEST_HASH = bcrypt.hashpw(TEST_PASS.encode(), bcrypt.gensalt()).decode()

WORKER_USER = "testworker"
WORKER_PASS = "Test@1234"
WORKER_HASH = bcrypt.hashpw(WORKER_PASS.encode(), bcrypt.gensalt()).decode()


def _ensure_role(db, role_code):
    role_row = db.execute(
        "SELECT id FROM roles WHERE code = ? AND status = 'active' ORDER BY id LIMIT 1",
        (role_code,),
    ).fetchone()
    if role_row:
        return role_row["id"]

    role_def = PREDEFINED_ROLES[role_code]
    cursor = db.execute(
        "INSERT INTO roles (name, code, description, permissions, status, group_id, level) "
        "VALUES (?, ?, ?, ?, 'active', ?, ?)",
        (
            role_def["name"],
            role_def["code"],
            role_def["description"],
            json.dumps(role_def["permissions"], ensure_ascii=False),
            role_def.get("group_id"),
            role_def.get("level", 1),
        ),
    )
    return cursor.lastrowid


def _ensure_user(db, username, password_hash, name, role, employee_no, group_name=None):
    existing = db.execute(
        "SELECT id FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    if not existing:
        columns = [
            "username",
            "password",
            "name",
            "role",
            "status",
            "password_version",
            "employee_no",
        ]
        values = [username, password_hash, name, role, "active", 2, employee_no]
        if group_name is not None:
            columns.append("group_name")
            values.append(group_name)
        placeholders = ",".join("?" for _ in values)
        cursor = db.execute(
            f"INSERT INTO users ({','.join(columns)}) VALUES ({placeholders})",
            values,
        )
        user_id = cursor.lastrowid
    else:
        user_id = existing["id"]
        update_sql = (
            "UPDATE users SET password = ?, name = ?, role = ?, status = 'active', "
            "locked_until = NULL, failed_login_count = 0, password_version = 2, "
            "token = NULL, must_change_password = 0, employee_no = ?"
        )
        params = [password_hash, name, role, employee_no]
        if group_name is not None:
            update_sql += ", group_name = ?"
            params.append(group_name)
        update_sql += " WHERE id = ?"
        params.append(user_id)
        db.execute(update_sql, params)

    role_id = _ensure_role(db, role)
    db.execute("DELETE FROM user_roles WHERE user_id = ?", (user_id,))
    db.execute(
        "INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)",
        (user_id, role_id),
    )
    db.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))

    if role == "admin":
        db.execute("DELETE FROM login_attempts")
        db.execute("DELETE FROM login_logs")

    db.commit()
    return user_id


def _ensure_test_order(db):
    db.execute("INSERT OR IGNORE INTO customers (id, name) VALUES (9999, 'Test Customer')")
    db.execute(
        "INSERT OR IGNORE INTO products (id, product_name, product_code, model, spec, category) "
        "VALUES (9999, 'Test Product', 'TEST-CODE-001', 'TEST', 'Standard', 'fixture')"
    )

    process = db.execute(
        "SELECT id FROM processes WHERE status = 'active' ORDER BY seq_order, id LIMIT 1"
    ).fetchone()
    if not process:
        cursor = db.execute(
            "INSERT INTO processes (name, description, category, seq_order, status, updated_at) "
            "VALUES (?, ?, ?, 1, 'active', datetime('now','localtime'))",
            ("Fixture Process", "pytest fixture process", "fixture"),
        )
        process_id = cursor.lastrowid
    else:
        process_id = process["id"]

    order_no = f"TEST-FIXTURE-{uuid.uuid4().hex[:8].upper()}"
    cursor = db.execute(
        "INSERT INTO orders (order_no, customer, product_name, product_code, quantity, status, qr_mode) "
        "VALUES (?, 'Test Customer', 'Test Product', 'TEST-CODE-001', 10, 'pending', '')",
        (order_no,),
    )
    order_id = cursor.lastrowid
    db.execute(
        "INSERT INTO order_processes (order_id, process_id, seq_order, status, completed, scrapped, rework) "
        "VALUES (?, ?, 1, 'pending', 0, 0, 0)",
        (order_id, process_id),
    )
    db.commit()
    return order_id


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
        _ensure_user(db, TEST_USER, TEST_HASH, "Test Runner", "admin", "TEST-ADMIN-001")
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
        return _ensure_test_order(db)


@pytest.fixture
def worker_auth_token(client):
    with client.application.app_context():
        db = get_db()
        _ensure_user(
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
