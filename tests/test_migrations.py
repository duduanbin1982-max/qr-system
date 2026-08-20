import ast
import json
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
        user_columns = {
            row["name"] for row in db.execute("PRAGMA table_info(users)").fetchall()
        }
        assert {"purged_at", "purged_by", "purge_reason"}.issubset(user_columns)
        assert "idx_users_employee_no_normalized" in {
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


def test_user_management_migration_blocks_normalized_employee_number_duplicates():
    from modules.migration_user_management import (
        m059_harden_user_identity_and_retention,
    )

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        db.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL,
                employee_no TEXT DEFAULT ''
            );
            INSERT INTO users VALUES (1, 'first', ' STAFF-01 ');
            INSERT INTO users VALUES (2, 'second', 'staff-01');
            """
        )
        with pytest.raises(RuntimeError, match="1:first.*2:second"):
            m059_harden_user_identity_and_retention(db)
        assert db.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='index' AND name='idx_users_employee_no_normalized'"
        ).fetchone() is None
    finally:
        db.close()


def test_process_quality_state_migration_records_anomalies_and_locks_terminal_states():
    from modules.migration_process_quality import m058_harden_process_quality_state_transitions

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        db.executescript(
            """
            CREATE TABLE process_quality_evaluations (
                id INTEGER PRIMARY KEY,
                status TEXT
            );
            CREATE TABLE process_quality_evaluation_appeals (
                id INTEGER PRIMARY KEY,
                evaluation_id INTEGER,
                status TEXT
            );
            INSERT INTO process_quality_evaluations VALUES (1, 'confirmed');
            INSERT INTO process_quality_evaluations VALUES (2, 'legacy_unknown');
            INSERT INTO process_quality_evaluation_appeals VALUES (10, 1, 'pending');
            """
        )

        m058_harden_process_quality_state_transitions(db)

        issue = db.execute(
            "SELECT issue_code, observed_status FROM process_quality_state_issues "
            "WHERE entity_type = 'evaluation' AND entity_id = 2"
        ).fetchone()
        assert dict(issue) == {
            "issue_code": "invalid_status",
            "observed_status": "legacy_unknown",
        }
        db.execute("UPDATE process_quality_evaluations SET status = 'rejected' WHERE id = 1")
        db.execute("UPDATE process_quality_evaluation_appeals SET status = 'accepted' WHERE id = 10")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE process_quality_evaluations SET status = 'confirmed' WHERE id = 1")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE process_quality_evaluation_appeals SET status = 'rejected' WHERE id = 10")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO process_quality_evaluations VALUES (3, 'invalid')")
    finally:
        db.close()


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
            "modules.migration_payroll_ledger",
            "modules.migration_performance_department",
            "modules.migration_user_management",
            "modules.migration_process_versioning",
            "modules.migration_product_integrity",
            "modules.migration_company_profile",
            "modules.migration_audit",
        "modules.migration_process_config",
            "modules.migration_role_group_permissions",
            "modules.migration_role_management",
            "modules.migration_position_versioning",
        }
    assert len((PROJECT_ROOT / "modules" / "migrations.py").read_text(encoding="utf-8").splitlines()) < 100


def test_audit_event_and_process_config_migration_versions_are_stable():
    from modules import migrations

    by_version = {
        version: migration_fn.__module__
        for version, _, migration_fn in migrations.MIGRATIONS
    }
    assert by_version[66] == "modules.migration_audit"
    assert by_version[67] == "modules.migration_process_config"
    assert by_version[68] == "modules.migration_role_group_permissions"
    assert by_version[69] == "modules.migration_role_management"
    assert by_version[70] == "modules.migration_position_versioning"
    assert migrations.LATEST_VERSION == 70


def test_payroll_ledger_migration_rounds_legacy_adjustments_and_locks_legacy_tables():
    from modules import migrations
    from modules.migration_payroll_ledger import m055_versioned_payroll_ledger

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        for version, _, migrate in migrations.MIGRATIONS:
            if version >= 55:
                break
            migrate(db)

        db.execute(
            "INSERT INTO users (id,username,password,name,role,employee_no,status) "
            "VALUES (9001,'payroll-migration-worker','hash','迁移员工','worker','PAY-9001','active')"
        )
        db.execute(
            "INSERT INTO route_prices (id,route_id,process_id,unit_price,effective_date,status) "
            "VALUES (9001,9001,9001,12.3456,'2026-07-01','active')"
        )
        db.execute(
            "INSERT INTO wage_snapshots "
            "(id,employee_id,employee_name,employee_no,year_month,total_quantity,total_wage,rework_wage,status) "
            "VALUES (9001,9001,'迁移员工','PAY-9001','2026-07',3,12.345,1.005,'confirmed')"
        )
        db.execute(
            "INSERT INTO wage_adjustments "
            "(id,user_id,year_month,type,amount,reason,created_by) "
            "VALUES (9001,9001,'2026-07','bonus',1.005,'历史四舍五入','migration-test')"
        )

        m055_versioned_payroll_ledger(db)

        assert db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='payroll_migration_manifests'"
        ).fetchone()

        adjustment = db.execute(
            "SELECT amount_cents FROM payroll_adjustments WHERE legacy_wage_adjustment_id=9001"
        ).fetchone()
        assert adjustment["amount_cents"] == 101

        locked_operations = [
            (
                "INSERT INTO route_prices (route_id,process_id,unit_price) VALUES (9002,9002,1)",
                (),
            ),
            ("UPDATE route_prices SET unit_price=99 WHERE id=9001", ()),
            ("DELETE FROM route_prices WHERE id=9001", ()),
            (
                "INSERT INTO wage_snapshots (employee_id,year_month) VALUES (9001,'2026-08')",
                (),
            ),
            ("UPDATE wage_snapshots SET total_wage=99 WHERE id=9001", ()),
            ("DELETE FROM wage_snapshots WHERE id=9001", ()),
            (
                "INSERT INTO wage_adjustments (user_id,year_month,type,amount,reason) "
                "VALUES (9001,'2026-08','bonus',1,'blocked')",
                (),
            ),
            ("UPDATE wage_adjustments SET amount=99 WHERE id=9001", ()),
            ("DELETE FROM wage_adjustments WHERE id=9001", ()),
        ]
        for statement, parameters in locked_operations:
            with pytest.raises(sqlite3.IntegrityError, match="read-only"):
                db.execute(statement, parameters)

        assert db.execute("SELECT unit_price FROM route_prices WHERE id=9001").fetchone()[0] == 12.3456
        assert db.execute("SELECT total_wage FROM wage_snapshots WHERE id=9001").fetchone()[0] == 12.345
        assert db.execute("SELECT amount FROM wage_adjustments WHERE id=9001").fetchone()[0] == 1.005
    finally:
        db.close()


def test_versioned_performance_ledger_migration_imports_legacy_and_enforces_invariants():
    from modules import migrations
    from modules.migration_performance import m056_versioned_performance_ledger

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        for version, _, migrate in migrations.MIGRATIONS:
            if version >= 56:
                break
            migrate(db)

        db.execute(
            "INSERT INTO users (id,username,password,name,role,employee_no,status) "
            "VALUES (9301,'performance-migration-worker','hash','绩效迁移员工','worker','PERF-9301','active')"
        )
        db.execute(
            "INSERT INTO users (id,username,password,name,role,employee_no,status) "
            "VALUES (9302,'performance-missing-position','hash','缺岗位员工','worker','PERF-9302','inactive')"
        )
        db.execute(
            "INSERT INTO performance_scores ("
            "id,user_id,year_month,output_qty,report_count,work_days,output_score,quality_score,"
            "delivery_score,discipline_score,improvement_score,total_score,rank_no,rank_total,"
            "warning_level,warning_reason,status,generated_at,updated_at,score_details"
            ") VALUES (9301,9301,'2026-07',10,2,2,35,30,2,10,8,85,1,2,'green','历史评分','generated',"
            "'2026-08-01 08:00:00','2026-08-02 08:00:00',?)",
            (json.dumps({"position_id": 71, "position_name": "历史焊接岗位"}, ensure_ascii=False),),
        )
        db.execute(
            "INSERT INTO performance_scores ("
            "id,user_id,year_month,output_qty,total_score,warning_level,status,generated_at,updated_at,score_details"
            ") VALUES (9302,9302,'2026-07',0,85,'green','generated',"
            "'2026-08-01 08:00:00','2026-08-01 08:00:00','{}')"
        )
        db.execute(
            "INSERT INTO performance_reviews ("
            "id,user_id,year_month,discipline_deduction,discipline_reason,manual_score,manual_comment,"
            "reviewed_by,created_at,updated_at"
            ") VALUES (9301,9301,'2026-07',2,'历史纪律扣分',8,'历史主管意见',1,"
            "'2026-08-01 09:00:00','2026-08-01 09:00:00')"
        )
        db.execute(
            "INSERT INTO performance_improvement_plans ("
            "id,score_id,user_id,year_month,reason,goal,actions,owner_id,due_date,status,"
            "review_result,review_notes,created_by,created_at,updated_at,closed_at"
            ") VALUES (9301,9301,9301,'2026-07','历史问题','历史目标','历史措施',1,'2026-08-31',"
            "'closed','passed','历史复评',1,'2026-08-01 10:00:00','2026-08-10 10:00:00','2026-08-10 10:00:00')"
        )
        legacy_permissions = [
            "page:performance",
            "performance:view",
            "performance:create",
            "performance:edit",
        ]
        db.execute(
            "INSERT INTO roles (id,name,code,permissions) VALUES (9301,'旧绩效角色','legacy-performance',?)",
            (json.dumps(legacy_permissions),),
        )
        db.execute(
            "INSERT INTO user_roles (user_id,role_id) VALUES (9301,9301)"
        )

        m056_versioned_performance_ledger(db)

        expected_tables = {
            "performance_rule_versions",
            "performance_position_target_versions",
            "performance_batches",
            "performance_score_revisions",
            "performance_source_facts",
            "performance_reviews_v2",
            "performance_batch_events",
            "performance_data_exceptions",
            "performance_quality_events",
            "performance_quality_event_sources",
            "performance_assignment_history",
            "performance_department_scopes",
            "performance_improvement_plans_v2",
            "performance_plan_events",
            "performance_plan_evidence",
            "performance_plan_reassessments",
            "performance_permission_migration_report",
            "performance_migration_manifests",
        }
        table_names = {
            row["name"]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert expected_tables <= table_names

        def unique_index_columns(table_name):
            indexes = db.execute(f"PRAGMA index_list({table_name})").fetchall()
            return {
                tuple(
                    item["name"]
                    for item in db.execute(f"PRAGMA index_info({index['name']})").fetchall()
                )
                for index in indexes
                if index["unique"]
            }

        assert ("production_month", "version") in unique_index_columns("performance_batches")
        assert ("batch_id", "user_id", "revision") in unique_index_columns(
            "performance_score_revisions"
        )
        assert ("source_type", "source_id") in unique_index_columns(
            "performance_quality_event_sources"
        )
        assert ("user_id", "department_id") in unique_index_columns(
            "performance_department_scopes"
        )
        assert ("batch_id", "fact_type", "canonical_event_id") in unique_index_columns(
            "performance_source_facts"
        )

        legacy_batch = dict(db.execute(
            "SELECT * FROM performance_batches WHERE production_month='2026-07'"
        ).fetchone())
        assert legacy_batch["version"] == 1
        assert legacy_batch["status"] == "approved"
        assert legacy_batch["legacy_imported"] == 1
        assert legacy_batch["rule_version_id"] is None

        revisions = {
            row["legacy_score_id"]: dict(row)
            for row in db.execute(
                "SELECT * FROM performance_score_revisions WHERE batch_id=? ORDER BY legacy_score_id",
                (legacy_batch["id"],),
            ).fetchall()
        }
        assert set(revisions) == {9301, 9302}
        assert revisions[9301]["position_id_snapshot"] == 71
        assert revisions[9301]["position_name_snapshot"] == "历史焊接岗位"
        assert revisions[9301]["prior_revisions_unavailable"] == 1
        assert revisions[9302]["position_id_snapshot"] is None
        assert db.execute(
            "SELECT COUNT(*) FROM performance_data_exceptions "
            "WHERE exception_type='missing_position_snapshot' AND user_id=9302"
        ).fetchone()[0] == 1
        assert db.execute(
            "SELECT COUNT(*) FROM performance_reviews_v2 WHERE legacy_review_id=9301"
        ).fetchone()[0] == 1
        imported_plan = db.execute(
            "SELECT status,legacy_plan_id FROM performance_improvement_plans_v2 WHERE legacy_plan_id=9301"
        ).fetchone()
        assert tuple(imported_plan) == ("closed", 9301)

        migrated_permissions = json.loads(db.execute(
            "SELECT permissions FROM roles WHERE id=9301"
        ).fetchone()[0])
        assert "page:performance" in migrated_permissions
        assert "performance:view_self" in migrated_permissions
        assert not {
            "performance:view",
            "performance:create",
            "performance:edit",
            "performance:view_all",
            "performance:prepare",
            "performance:approve",
        } & set(migrated_permissions)
        permission_report = db.execute(
            "SELECT * FROM performance_permission_migration_report WHERE role_id=9301"
        ).fetchone()
        assert permission_report["assigned_user_count"] == 1
        assert json.loads(permission_report["old_permissions_json"]) == legacy_permissions

        with pytest.raises(sqlite3.IntegrityError, match="invalid performance batch status transition"):
            db.execute(
                "UPDATE performance_batches SET status='draft' WHERE id=?",
                (legacy_batch["id"],),
            )
        with pytest.raises(sqlite3.IntegrityError, match="initial status must be draft"):
            db.execute(
                "INSERT INTO performance_batches ("
                "production_month,version,period_start,period_end,status,idempotency_key"
                ") VALUES ('2026-09',1,'2026-09-01 07:00:00','2026-10-01 07:00:00',"
                "'approved','test:performance:direct-approved')"
            )
        draft_batch_id = db.execute(
            "INSERT INTO performance_batches ("
            "production_month,version,period_start,period_end,status,idempotency_key,"
            "prepared_by,prepared_by_name"
            ") VALUES ('2026-08',1,'2026-08-01 07:00:00','2026-09-01 07:00:00',"
            "'draft','test:performance:draft',1,'pytest')"
        ).lastrowid
        with pytest.raises(sqlite3.IntegrityError, match="invalid performance batch status transition"):
            db.execute(
                "UPDATE performance_batches SET status='approved' WHERE id=?",
                (draft_batch_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="approved performance batches are immutable"):
            db.execute(
                "INSERT INTO performance_score_revisions (batch_id,user_id,revision) VALUES (?,?,2)",
                (legacy_batch["id"], 9301),
            )

        fact_id = db.execute(
            "INSERT INTO performance_source_facts ("
            "batch_id,fact_type,source_type,source_id,source_digest"
            ") VALUES (?,?,?,?,?)",
            (draft_batch_id, "work", "work_records", 1, "fact-digest"),
        ).lastrowid
        with pytest.raises(sqlite3.IntegrityError, match="performance source facts are immutable"):
            db.execute(
                "UPDATE performance_source_facts SET source_digest='changed' WHERE id=?",
                (fact_id,),
            )

        db.execute(
            "UPDATE performance_batches SET status='supervisor_review' WHERE id=?",
            (draft_batch_id,),
        )
        db.execute(
            "UPDATE performance_batches SET status='approval_pending' WHERE id=?",
            (draft_batch_id,),
        )
        with pytest.raises(sqlite3.IntegrityError, match="performance approver is required"):
            db.execute(
                "UPDATE performance_batches SET status='approved' WHERE id=?",
                (draft_batch_id,),
            )
        db.execute(
            "UPDATE performance_batches SET approved_by=1 WHERE id=?",
            (draft_batch_id,),
        )
        with pytest.raises(sqlite3.IntegrityError, match="preparer and approver must differ"):
            db.execute(
                "UPDATE performance_batches SET status='approved' WHERE id=?",
                (draft_batch_id,),
            )

        with pytest.raises(sqlite3.IntegrityError, match="final performance batches are immutable"):
            db.execute(
                "UPDATE performance_batches SET approved_by_name='tampered' WHERE id=?",
                (legacy_batch["id"],),
            )
        with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
            db.execute("DELETE FROM performance_batches WHERE id=?", (legacy_batch["id"],))

        immutable_ledger_operations = [
            "UPDATE performance_score_revisions SET total_score=0 WHERE legacy_score_id=9301",
            "DELETE FROM performance_reviews_v2 WHERE legacy_review_id=9301",
            "UPDATE performance_batch_events SET reason='tampered' WHERE batch_id=%d"
            % legacy_batch["id"],
            "DELETE FROM performance_migration_manifests WHERE production_month='2026-07'",
        ]
        for statement in immutable_ledger_operations:
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                db.execute(statement)

        legacy_locked_operations = [
            (
                "INSERT INTO performance_scores (user_id,year_month) VALUES (9301,'2026-08')",
                (),
            ),
            ("UPDATE performance_reviews SET manual_score=1 WHERE id=9301", ()),
            ("DELETE FROM performance_improvement_plans WHERE id=9301", ()),
        ]
        for statement, parameters in legacy_locked_operations:
            with pytest.raises(sqlite3.IntegrityError, match="read-only"):
                db.execute(statement, parameters)

        score_count = db.execute("SELECT COUNT(*) FROM performance_scores").fetchone()[0]
        revision_count = db.execute("SELECT COUNT(*) FROM performance_score_revisions").fetchone()[0]
        m056_versioned_performance_ledger(db)
        assert db.execute("SELECT COUNT(*) FROM performance_scores").fetchone()[0] == score_count
        assert db.execute("SELECT COUNT(*) FROM performance_score_revisions").fetchone()[0] == revision_count
        assert db.execute(
            "SELECT COUNT(*) FROM performance_migration_manifests WHERE production_month='2026-07'"
        ).fetchone()[0] == 1
    finally:
        db.close()


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
