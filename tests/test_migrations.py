import ast
import sqlite3
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_run_migrations_uses_supplied_connection():
    from modules import migrations

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        executed = migrations.run_migrations(db)
        assert executed == len(migrations.MIGRATIONS)
        assert db.execute("PRAGMA user_version").fetchone()[0] == migrations.LATEST_VERSION

        table_names = {
            row["name"]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "users" in table_names
        assert "board_sessions" in table_names
        assert "product_bom" in table_names
        assert "order_materials" in table_names
        assert "process_quality_evaluation_tasks" in table_names
        assert "process_quality_evaluations" in table_names
        assert "process_quality_evaluation_reviews" in table_names
        assert "process_quality_evaluation_templates" in table_names
        assert "process_quality_evaluation_appeals" in table_names
        assert "quality_standards" in table_names
        assert "quality_inspection_plans" in table_names
        assert "quality_inspection_tasks" in table_names
        assert "quality_nonconformances" in table_names
        assert "quality_capa_records" in table_names
        assert "quality_supplier_inspections" in table_names
        assert "quality_gauges" in table_names
        order_columns = {
            row["name"] for row in db.execute("PRAGMA table_info(orders)").fetchall()
        }
        assert {
            "qr_printed_at",
            "qr_print_count",
            "qr_printed_by",
            "qr_printed_by_name",
            "product_id",
            "completed_at",
        }.issubset(order_columns)
        assert "product_code_aliases" in table_names
        assert "order_product_links" in {
            row["name"]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='view'"
            ).fetchall()
        }
        session_columns = {
            row["name"]
            for row in db.execute("PRAGMA table_info(user_sessions)").fetchall()
        }
        assert "active_position_id" in session_columns
        assert "idx_us_active_position" in {
            row["name"]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
    finally:
        db.close()

def test_latest_version_matches_highest_registered_migration():
    from modules import migrations

    assert migrations.LATEST_VERSION == max(version for version, _, _ in migrations.MIGRATIONS)


def test_migration_registry_is_split_by_domain_without_duplicate_versions():
    from modules import migrations

    versions = [version for version, _, _ in migrations.MIGRATIONS]
    assert versions == [1, *range(13, migrations.LATEST_VERSION + 1)]
    assert len(versions) == len(set(versions))
    assert {migration_fn.__module__ for _, _, migration_fn in migrations.MIGRATIONS} == {
        "modules.migration_baseline",
        "modules.migration_auth",
        "modules.migration_core",
        "modules.migration_performance",
        "modules.migration_work_time",
        "modules.migration_order_completion",
        "modules.migration_order_qr_print",
            "modules.migration_process_quality",
            "modules.migration_process_management",
            "modules.migration_quality_management",
        "modules.migration_materials",
            "modules.migration_approval_workflow",
            "modules.migration_serial_backfill",
            "modules.migration_product_identity",
            "modules.migration_inventory_ledger",
            "modules.migration_shipment_lifecycle",
            "modules.migration_reporting",
        }
    assert len((PROJECT_ROOT / "modules" / "migrations.py").read_text(encoding="utf-8").splitlines()) < 100


def test_position_aware_backfill_migration_is_idempotent_and_preserves_history():
    from modules.migration_serial_backfill import (
        MIGRATIONS,
        m048_position_aware_serial_backfill,
    )

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        db.executescript(
            """
            CREATE TABLE work_records (
                id INTEGER PRIMARY KEY,
                report_source TEXT NOT NULL DEFAULT 'standard',
                actual_completed_at TEXT,
                backfill_reason TEXT NOT NULL DEFAULT ''
            );
            INSERT INTO work_records (
                id, report_source, actual_completed_at, backfill_reason
            ) VALUES (
                1, 'serial_backfill', '2026-07-01 09:30:00', '历史漏扫补报'
            );
            """
        )

        m048_position_aware_serial_backfill(db)
        m048_position_aware_serial_backfill(db)

        columns = {
            row["name"]: row
            for row in db.execute("PRAGMA table_info(work_records)").fetchall()
        }
        assert MIGRATIONS[-1][0] == 48
        assert columns["submit_position_id"]["type"] == "INTEGER"
        assert columns["submit_position_name"]["type"] == "TEXT"
        assert columns["submit_position_name"]["notnull"] == 1
        assert columns["submit_position_name"]["dflt_value"] == "''"

        history = db.execute(
            "SELECT report_source, actual_completed_at, backfill_reason, "
            "submit_position_id, submit_position_name FROM work_records WHERE id = 1"
        ).fetchone()
        assert tuple(history) == (
            "serial_backfill",
            "2026-07-01 09:30:00",
            "历史漏扫补报",
            None,
            "",
        )
        assert db.execute("SELECT COUNT(*) FROM work_records").fetchone()[0] == 1
    finally:
        db.close()


def test_stable_product_identity_migration_backfills_current_code_and_snapshot():
    from modules.migration_product_identity import m050_stable_order_product_identity

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        db.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE products (
                id INTEGER PRIMARY KEY,
                product_name TEXT NOT NULL,
                product_code TEXT NOT NULL,
                model TEXT,
                spec TEXT,
                category TEXT
            );
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                product_name TEXT NOT NULL DEFAULT '',
                product_code TEXT NOT NULL DEFAULT ''
            );
            INSERT INTO products (id, product_name, product_code, model, spec, category)
            VALUES (7, '测试产品', 'TEST-CURRENT', 'M7', 'S7', '结构件');
            INSERT INTO orders (id, product_name, product_code)
            VALUES (9, '', 'TEST-CURRENT');
            """
        )

        m050_stable_order_product_identity(db)
        m050_stable_order_product_identity(db)

        order = db.execute(
            "SELECT product_id, product_name FROM orders WHERE id = 9"
        ).fetchone()
        assert tuple(order) == (7, "测试产品")
        alias = db.execute(
            "SELECT product_id, source FROM product_code_aliases WHERE product_code='TEST-CURRENT'"
        ).fetchone()
        assert tuple(alias) == (7, "current")
        assert db.execute(
            "SELECT product_id FROM order_product_links WHERE order_id=9"
        ).fetchone()[0] == 7
    finally:
        db.close()


def test_stable_product_identity_triggers_preserve_aliases_on_direct_code_update():
    from modules.migration_product_identity import m050_stable_order_product_identity

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        db.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE products (
                id INTEGER PRIMARY KEY,
                product_name TEXT NOT NULL,
                product_code TEXT NOT NULL,
                model TEXT,
                spec TEXT,
                category TEXT
            );
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                product_name TEXT NOT NULL DEFAULT '',
                product_code TEXT NOT NULL DEFAULT ''
            );
            INSERT INTO products (id, product_name, product_code)
            VALUES (7, '测试产品', 'TEST-OLD');
            INSERT INTO orders (id, product_name, product_code)
            VALUES (9, '订单快照', 'TEST-OLD');
            """
        )

        m050_stable_order_product_identity(db)
        db.execute("UPDATE products SET product_code = 'TEST-NEW' WHERE id = 7")
        db.execute(
            "INSERT INTO orders (id, product_name, product_code) "
            "VALUES (10, '历史导入', 'TEST-OLD')"
        )
        db.execute("UPDATE products SET product_code = 'TEST-FINAL' WHERE id = 7")

        aliases = {
            row["product_code"]: row["product_id"]
            for row in db.execute(
                "SELECT product_code, product_id FROM product_code_aliases"
            ).fetchall()
        }
        orders = db.execute(
            "SELECT id, product_id, product_code, product_name FROM orders ORDER BY id"
        ).fetchall()

        assert aliases == {"TEST-OLD": 7, "TEST-NEW": 7, "TEST-FINAL": 7}
        assert tuple(orders[0]) == (9, 7, "TEST-OLD", "订单快照")
        assert tuple(orders[1]) == (10, 7, "TEST-OLD", "历史导入")

        with pytest.raises(sqlite3.IntegrityError, match="historical alias"):
            db.execute(
                "INSERT INTO products (id, product_name, product_code) "
                "VALUES (8, '错误复用', 'TEST-OLD')"
            )
    finally:
        db.close()


def test_inventory_ledger_migration_reconciles_and_protects_history():
    from modules.migration_inventory_ledger import m051_inventory_ledger

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        db.executescript(
            """
            CREATE TABLE users (id INTEGER PRIMARY KEY);
            CREATE TABLE inventory (
                id INTEGER PRIMARY KEY, quantity REAL DEFAULT 0,
                product_model TEXT, product_name TEXT, reserved REAL DEFAULT 0,
                updated_at TEXT, last_count_date TEXT
            );
            CREATE TABLE inventory_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                inventory_id INTEGER NOT NULL, type TEXT NOT NULL,
                quantity REAL NOT NULL, order_id INTEGER, order_no TEXT DEFAULT '',
                remark TEXT DEFAULT '', operator_id INTEGER,
                operator_name TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO inventory (id, quantity, product_model, product_name)
            VALUES (1, 5, 'M-1', 'Product 1');
            INSERT INTO inventory_logs (inventory_id, type, quantity)
            VALUES (1, 'in', 3);
            """
        )

        m051_inventory_ledger(db)
        db.commit()
        m051_inventory_ledger(db)
        db.commit()

        logs = db.execute(
            "SELECT qty_delta, balance_before, balance_after, source_type "
            "FROM inventory_logs ORDER BY id"
        ).fetchall()
        assert [tuple(row) for row in logs] == [
            (3, 0, 3, "legacy"),
            (2, 3, 5, "migration"),
        ]
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE inventory_logs SET remark='changed' WHERE id=1")
        db.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="archive"):
            db.execute("DELETE FROM inventory WHERE id=1")
    finally:
        db.close()


def test_session_migration_deactivates_tokens_that_cannot_authenticate():
    from modules.migration_auth import m031_align_single_token_sessions

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        db.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, status TEXT, token TEXT)"
        )
        db.execute(
            "CREATE TABLE user_sessions (id INTEGER PRIMARY KEY, user_id INTEGER, token TEXT, is_active INTEGER)"
        )
        db.execute("INSERT INTO users VALUES (1, 'active', 'current-token')")
        db.executemany(
            "INSERT INTO user_sessions VALUES (?, 1, ?, ?)",
            [
                (1, "current-token", 1),
                (2, "stale-token", 1),
                (3, "old-inactive-token", 0),
            ],
        )

        m031_align_single_token_sessions(db)
        m031_align_single_token_sessions(db)

        assert [
            row["is_active"]
            for row in db.execute("SELECT is_active FROM user_sessions ORDER BY id").fetchall()
        ] == [1, 0, 0]
    finally:
        db.close()


def test_order_completion_migration_removes_only_legacy_extra_status():
    from modules.migration_order_completion import m032_remove_legacy_order_status_from_extra_fields

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        db.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, extra_fields TEXT)")
        db.executemany(
            "INSERT INTO orders (id, extra_fields) VALUES (?, ?)",
            [
                (1, '{"status":"pending","model":"A"}'),
                (2, '{"model":"B"}'),
                (3, 'invalid-json'),
            ],
        )

        m032_remove_legacy_order_status_from_extra_fields(db)
        m032_remove_legacy_order_status_from_extra_fields(db)

        values = [
            row["extra_fields"]
            for row in db.execute("SELECT extra_fields FROM orders ORDER BY id").fetchall()
        ]
        assert values == ['{"model":"A"}', '{"model":"B"}', 'invalid-json']
    finally:
        db.close()


def test_database_at_version_29_runs_all_pending_migrations():
    from modules import migrations

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        for version, _, migration_fn in sorted(migrations.MIGRATIONS):
            if version > 29:
                continue
            migration_fn(db)
            db.execute(f"PRAGMA user_version = {version}")
        db.execute("DROP INDEX IF EXISTS idx_wt_records_route_process")
        db.execute("DROP INDEX IF EXISTS idx_wt_records_standard_missing")
        db.execute("PRAGMA user_version = 29")
        db.commit()

        assert migrations.run_migrations(db) == len([
            version for version, _, _ in migrations.MIGRATIONS if version > 29
        ])
        assert db.execute("PRAGMA user_version").fetchone()[0] == migrations.LATEST_VERSION
        index_names = {
            row["name"]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert "idx_wt_records_route_process" in index_names
        assert "idx_wt_records_standard_missing" in index_names
    finally:
        db.close()


def test_material_stock_ledger_migration_creates_one_baseline_per_material():
    from modules.migration_materials import m042_material_stock_ledger

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        db.executescript(
            """
            CREATE TABLE materials (
                id INTEGER PRIMARY KEY,
                quantity REAL DEFAULT 0
            );
            CREATE TABLE material_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                material_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                quantity REAL NOT NULL,
                remark TEXT DEFAULT '',
                operator_id INTEGER,
                operator_name TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE material_consumptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                material_id INTEGER NOT NULL,
                quantity REAL NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO materials (id, quantity) VALUES (1, 12.5), (2, 0);
            """
        )

        m042_material_stock_ledger(db)
        m042_material_stock_ledger(db)

        rows = db.execute(
            "SELECT material_id, type, quantity, balance_before, balance_after "
            "FROM material_logs ORDER BY material_id"
        ).fetchall()
        assert [tuple(row) for row in rows] == [
            (1, "baseline", 12.5, 12.5, 12.5),
            (2, "baseline", 0.0, 0.0, 0.0),
        ]
        consumption_columns = {
            row[1] for row in db.execute("PRAGMA table_info(material_consumptions)")
        }
        assert {"status", "reversed_at", "reversed_by", "reversal_reason", "reversal_log_id"} <= consumption_columns
    finally:
        db.close()


def test_material_consumption_work_source_migration_is_idempotent_and_unique():
    from modules.migration_materials import m043_link_material_consumptions_to_work_reports

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        db.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE work_records (id INTEGER PRIMARY KEY);
            CREATE TABLE materials (id INTEGER PRIMARY KEY);
            CREATE TABLE material_consumptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                material_id INTEGER NOT NULL
            );
            """
        )

        m043_link_material_consumptions_to_work_reports(db)
        m043_link_material_consumptions_to_work_reports(db)
        columns = {
            row["name"]
            for row in db.execute("PRAGMA table_info(material_consumptions)").fetchall()
        }
        assert "source_work_record_id" in columns
        db.execute("INSERT INTO work_records (id) VALUES (8)")
        db.execute("INSERT INTO material_consumptions (material_id, source_work_record_id) VALUES (1, 8)")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO material_consumptions (material_id, source_work_record_id) VALUES (1, 8)")
        db.execute("INSERT INTO material_consumptions (material_id, source_work_record_id) VALUES (2, 8)")
    finally:
        db.close()


def test_process_quality_remediation_migration_repairs_invariants():
    from modules.migration_process_quality import m037_process_quality_review_remediation

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        db.executescript(
            """
            CREATE TABLE system_settings (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE process_quality_evaluations (
                id INTEGER PRIMARY KEY,
                total_score REAL,
                issue_tags_json TEXT,
                template_snapshot_json TEXT,
                severity TEXT,
                status TEXT
            );
            CREATE TABLE quality_inspection_tasks (
                id INTEGER PRIMARY KEY,
                source_evaluation_id INTEGER,
                status TEXT,
                completed_at TEXT DEFAULT '',
                updated_at TEXT DEFAULT ''
            );
            CREATE TABLE process_quality_evaluation_templates (
                id INTEGER PRIMARY KEY,
                process_id INTEGER,
                route_id INTEGER,
                status TEXT,
                updated_at TEXT DEFAULT ''
            );
            """
        )
        db.execute(
            "INSERT INTO system_settings VALUES (?, ?)",
            (
                "process_quality_evaluation_rules",
                '{"low_score_threshold":60,"critical_score_threshold":40}',
            ),
        )
        db.execute(
            "INSERT INTO process_quality_evaluations VALUES (1, 75, ?, ?, 'normal', 'rejected')",
            ('["严重尺寸超差"]', '{"critical_issue_tags":["严重尺寸超差"]}'),
        )
        db.execute(
            "INSERT INTO quality_inspection_tasks "
            "(id, source_evaluation_id, status) VALUES (1, 1, 'failed')"
        )
        db.executemany(
            "INSERT INTO process_quality_evaluation_templates "
            "(id, process_id, route_id, status) VALUES (?, 10, NULL, 'active')",
            [(1,), (2,)],
        )

        m037_process_quality_review_remediation(db)
        m037_process_quality_review_remediation(db)

        evaluation = db.execute(
            "SELECT severity FROM process_quality_evaluations WHERE id = 1"
        ).fetchone()
        task = db.execute(
            "SELECT status, cancel_reason, cancelled_at FROM quality_inspection_tasks WHERE id = 1"
        ).fetchone()
        templates = db.execute(
            "SELECT id, status FROM process_quality_evaluation_templates ORDER BY id"
        ).fetchall()
        indexes = {
            row["name"]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
        assert evaluation["severity"] == "critical"
        assert task["status"] == "cancelled"
        assert task["cancel_reason"] == "关联评价已被驳回"
        assert task["cancelled_at"]
        assert [(row["id"], row["status"]) for row in templates] == [
            (1, "inactive"),
            (2, "active"),
        ]
        assert "idx_pqe_templates_active_general" in indexes
        assert "idx_pqe_templates_active_route" in indexes
    finally:
        db.close()


def test_legacy_handoff_cutover_migration_uses_evaluation_status_as_authority():
    from modules.migration_process_quality import m038_converge_legacy_handoff_status

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        db.executescript(
            """
            CREATE TABLE process_handoff_reviews (
                id INTEGER PRIMARY KEY,
                status TEXT,
                confirmed_by INTEGER,
                confirm_note TEXT,
                confirmed_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE process_quality_evaluations (
                id INTEGER PRIMARY KEY,
                source_handoff_review_id INTEGER,
                status TEXT,
                reviewed_by INTEGER,
                review_note TEXT,
                reviewed_at TEXT
            );
            INSERT INTO process_handoff_reviews VALUES (1, 'pending', NULL, '', NULL, '2026-01-01');
            INSERT INTO process_quality_evaluations VALUES (10, 1, 'confirmed', 7, 'verified', '2026-01-02');
            """
        )

        m038_converge_legacy_handoff_status(db)
        m038_converge_legacy_handoff_status(db)

        row = db.execute("SELECT * FROM process_handoff_reviews WHERE id = 1").fetchone()
        assert row["status"] == "confirmed"
        assert row["confirmed_by"] == 7
        assert row["confirm_note"] == "verified"
        assert row["confirmed_at"] == "2026-01-02"
    finally:
        db.close()


def test_init_db_always_delegates_to_migration_runner(tmp_path, monkeypatch):
    from modules import db as db_module

    db_path = tmp_path / "version-30.db"
    db = sqlite3.connect(db_path)
    db.execute("PRAGMA user_version = 30")
    db.close()
    observed_versions = []

    def record_version(connection):
        observed_versions.append(
            connection.execute("PRAGMA user_version").fetchone()[0]
        )

    monkeypatch.setattr(db_module, "DB_PATH", str(db_path))
    monkeypatch.setattr(db_module, "run_migrations", record_version)

    db_module.init_db()

    assert observed_versions == [30]

def test_schema_compat_helper_creates_expected_compat_tables():
    from modules.migration_schema_compat import ensure_current_schema_compat

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        ensure_current_schema_compat(db)
        table_names = {
            row["name"]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "departments" in table_names
        assert "wage_snapshots" in table_names
        assert any(row[1] == "deleted_at" for row in db.execute("PRAGMA table_info(users)"))
    finally:
        db.close()

def test_material_migration_helper_creates_material_planning_tables():
    from modules.migration_materials import ensure_material_planning_tables

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        ensure_material_planning_tables(db)
        table_names = {
            row["name"]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "product_bom" in table_names
        assert "order_materials" in table_names
        index_names = {
            row["name"]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert "idx_product_bom_product" in index_names
        assert "idx_order_materials_order" in index_names
    finally:
        db.close()


def test_add_column_helper_is_explicit_and_idempotent():
    from modules.migration_helpers import add_column_if_missing

    db = sqlite3.connect(":memory:")
    try:
        assert add_column_if_missing(db, "missing", "value", "TEXT") is False
        db.execute("CREATE TABLE example (id INTEGER PRIMARY KEY)")
        assert add_column_if_missing(db, "example", "value", "TEXT DEFAULT ''") is True
        assert add_column_if_missing(db, "example", "value", "TEXT DEFAULT ''") is False
    finally:
        db.close()


def test_unique_index_failure_reports_existing_duplicate_data():
    from modules.migration_helpers import MigrationInvariantError, create_unique_index

    db = sqlite3.connect(":memory:")
    try:
        db.execute("CREATE TABLE example (id INTEGER PRIMARY KEY, code TEXT)")
        db.executemany("INSERT INTO example (code) VALUES (?)", [("DUP",), ("DUP",)])

        with pytest.raises(MigrationInvariantError, match=r"duplicate example\(code\) data"):
            create_unique_index(db, "idx_example_code", "example", "code")
    finally:
        db.close()


def test_failed_migration_does_not_advance_database_version(monkeypatch):
    from modules import migrations

    def broken_migration(db):
        db.execute("SELECT * FROM table_that_does_not_exist")

    monkeypatch.setattr(migrations, "MIGRATIONS", [(1, "intentional failure", broken_migration)])
    db = sqlite3.connect(":memory:")
    try:
        with pytest.raises(sqlite3.OperationalError, match="table_that_does_not_exist"):
            migrations.run_migrations(db)
        assert db.execute("PRAGMA user_version").fetchone()[0] == 0
    finally:
        db.close()


def test_migration_modules_do_not_silently_swallow_exceptions():
    violations = []
    for path in sorted((PROJECT_ROOT / "modules").glob("migration*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                violations.append(f"{path.name}:{node.lineno}")
            if isinstance(node.type, ast.Name) and node.type.id == "Exception":
                if not any(isinstance(child, ast.Raise) for child in ast.walk(node)):
                    violations.append(f"{path.name}:{node.lineno}")

    assert violations == []
