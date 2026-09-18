import atexit
from functools import wraps
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
for _production_node_flag in (
    "PRODUCTION_NODE_QUERY_ENABLED",
    "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED",
    "PRODUCTION_NODE_WRITE_ENABLED",
    "PRODUCTION_NODE_ENGINE_ENABLED",
    "LEGACY_PROCESS_LINE_WRITE_BLOCKED",
):
    os.environ[_production_node_flag] = "false"

UNIT_TEST_FILES = {
    "test_approval_workflow_policy.py",
    "test_material_requirement_policy.py",
    "test_order_lifecycle_policy.py",
    "test_process_order_service.py",
    "test_process_reporting_policy.py",
    "test_quality_evaluation_policy.py",
    "test_refactor_services.py",
    "test_scan_helper.py",
    "test_service_dependency_seams.py",
    "test_work_report_command.py",
}

CONTRACT_TEST_FILES = {
    "test_api_contracts.py",
    "test_architecture_imports.py",
    "test_deployment_contracts.py",
    "test_export_contracts.py",
    "test_fixture_isolation.py",
    "test_frontend_api_facade_contracts.py",
    "test_legacy_entrypoints.py",
    "test_mobile_frontend_contracts.py",
    "test_permission_catalog_contracts.py",
    "test_quality_cutover_contracts.py",
    "test_reports_contracts.py",
    "test_stats_contracts.py",
    "test_work_time_source_contracts.py",
}


def _remove_sqlite_artifacts(path):
    for suffix in ("", "-wal", "-shm"):
        candidate = path + suffix if suffix else path
        if os.path.exists(candidate):
            os.remove(candidate)


from modules import migrations as _test_migration_module


APPROVED_CORE_PROCESSES = {
    "下料": ("原材料切割", 1),
    "铆接": ("铆接组装", 2),
    "焊接": ("焊接组装", 3),
    "抛丸": ("表面抛丸", 4),
    "打磨": ("表面打磨", 5),
    "镗孔": ("精密镗孔", 6),
    "喷漆": ("喷涂上色", 7),
}


def _seed_approved_core_process_baseline(conn):
    """Model the approved production process master data before V076."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(processes)")}
    for name, (description, seq_order) in APPROVED_CORE_PROCESSES.items():
        if "process_code" in columns:
            conn.execute(
                "INSERT OR IGNORE INTO processes "
                "(process_code,name,description,seq_order,status) "
                "VALUES (?,?,?,?, 'active')",
                (f"TEST-APPROVED-{seq_order:03d}", name, description, seq_order),
            )
        else:
            conn.execute(
                "INSERT OR IGNORE INTO processes "
                "(name,description,seq_order,status) VALUES (?,?,?,'active')",
                (name, description, seq_order),
            )
    conn.commit()


def _ensure_approved_core_process_versions(conn):
    """Complete post-V060 test roots with the real V060 baseline backfill."""
    from modules.migration_process_versioning_v060 import _backfill_legacy_v1

    approved_names = tuple(APPROVED_CORE_PROCESSES)
    placeholders = ",".join("?" for _ in approved_names)
    _backfill_legacy_v1(conn)

    rows = conn.execute(
        "SELECT id FROM processes WHERE name IN (" + placeholders + ") ORDER BY id",
        approved_names,
    ).fetchall()
    incomplete = conn.execute(
        "SELECT p.name FROM processes p "
        "LEFT JOIN process_versions v ON v.id=p.current_effective_version_id "
        "WHERE p.name IN (" + placeholders + ") "
        "AND (p.current_effective_version_id IS NULL OR v.process_id<>p.id) "
        "ORDER BY p.name",
        approved_names,
    ).fetchall()
    if len(rows) != len(approved_names) or incomplete:
        raise AssertionError(
            "approved test processes require complete effective versions: "
            + ",".join(row[0] for row in incomplete)
        )
    conn.commit()


def _install_approved_process_baseline_adapter():
    """Make every test-built V059 source carry production's approved master data."""
    catalog = []
    for version, description, migrate in _test_migration_module.MIGRATIONS:
        if version != 59:
            catalog.append((version, description, migrate))
            continue

        @wraps(migrate)
        def migrate_with_approved_processes(db, real_migrate=migrate):
            real_migrate(db)
            _seed_approved_core_process_baseline(db)

        catalog.append((version, description, migrate_with_approved_processes))
    _test_migration_module.MIGRATIONS = catalog


_install_approved_process_baseline_adapter()
_REAL_RUN_MIGRATIONS = _test_migration_module.run_migrations


def _run_test_migrations_with_approved_production_baseline(db=None):
    """Run the real catalog while modeling production's approved V075 data.

    This test-only adapter directly seeds only process root master data. It
    then lets the real V060 legacy backfill create every eligible process
    version, and lets the real V060-V087 chain build and validate the 21 legacy
    resources, nodes, and additive node fact schema.
    """
    catalog = _test_migration_module.MIGRATIONS
    versions = {version for version, _, _ in catalog}
    if db is None:
        return _REAL_RUN_MIGRATIONS(db)
    current_version = db.execute("PRAGMA user_version").fetchone()[0]
    if current_version >= 87:
        return _REAL_RUN_MIGRATIONS(db)
    if not {76, 87}.issubset(versions):
        return _REAL_RUN_MIGRATIONS(db)

    if 60 <= current_version < 76:
        _seed_approved_core_process_baseline(db)
        _ensure_approved_core_process_versions(db)
        return _REAL_RUN_MIGRATIONS(db)

    if current_version >= 76:
        return _REAL_RUN_MIGRATIONS(db)

    pre_process_versioning = [migration for migration in catalog if migration[0] < 60]
    _test_migration_module.MIGRATIONS = pre_process_versioning
    try:
        executed = _REAL_RUN_MIGRATIONS(db)
    finally:
        _test_migration_module.MIGRATIONS = catalog

    _seed_approved_core_process_baseline(db)
    return executed + _REAL_RUN_MIGRATIONS(db)


# Tests that import run_migrations receive this production-baseline adapter;
# application code remains unchanged outside the test process.
_test_migration_module.run_migrations = _run_test_migrations_with_approved_production_baseline


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
from modules.middleware.rate_limit import reset_rate_limiters
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


def pytest_collection_modifyitems(items):
    for item in items:
        filename = os.path.basename(str(item.path))
        if filename in UNIT_TEST_FILES:
            item.add_marker(pytest.mark.unit)
        elif filename in CONTRACT_TEST_FILES:
            item.add_marker(pytest.mark.contract)
        else:
            item.add_marker(pytest.mark.integration)


@pytest.fixture(autouse=True)
def isolated_test_db():
    _reset_test_db()
    clear_settings_cache()
    reset_rate_limiters()
    yield
    clear_settings_cache()
    reset_rate_limiters()


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
