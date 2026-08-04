import json
import sqlite3

import pytest

from factories import WORKER_HASH, create_order, create_process_route, ensure_process, ensure_user
from modules.db import get_db
from modules.domain.reporting_day import reporting_month_bounds
from modules.services.payroll_history_migration_service import PayrollHistoryMigrationService


def test_historical_cutover_creates_exact_v2_and_keeps_unmatched_as_exception(client):
    with client.application.app_context():
        db = get_db()
        preparer_id = ensure_user(db, "history-preparer", "hash", "历史工资制单员", "admin", "HIST-PREP")
        worker_id = ensure_user(db, "history-worker", WORKER_HASH, "历史工资员工", "worker", "HIST-WORK")
        priced_process = ensure_process(db, "历史有工价工序")
        missing_process = ensure_process(db, "历史无工价工序")
        route_id = create_process_route(db, [priced_process, missing_process], "历史工资路线")
        order_id = create_order(db, [priced_process, missing_process], quantity=10, product_code="HISTORY-PRODUCT")
        db.execute("UPDATE orders SET route_id=? WHERE id=?", (route_id, order_id))
        db.execute("DROP TRIGGER prevent_legacy_route_price_insert")
        legacy_price_id = db.execute(
            "INSERT INTO route_prices (route_id,process_id,unit_price,effective_date,status) VALUES (?,?,1.25,'2026-08-01','active')",
            (route_id, priced_process),
        ).lastrowid
        version_id = db.execute(
            """
            INSERT INTO route_price_versions (
                route_id,process_id,normal_unit_price_micros,rework_rate_basis_points,
                rework_rate_configured,valid_from,status,created_by_name,approved_by_name,
                approved_at,legacy_route_price_id
            ) VALUES (?,?,12500,0,0,'2026-08-01 00:00:00','approved','migration','migration',datetime('now'),?)
            """,
            (route_id, priced_process, legacy_price_id),
        ).lastrowid
        for process_id in (priced_process, missing_process):
            db.execute(
                "INSERT INTO work_records (order_id,process_id,user_id,type,quantity,status,created_at) VALUES (?,?,?,'normal',3,'approved','2026-07-15 08:00:00')",
                (order_id, process_id, worker_id),
            )
        start, end = reporting_month_bounds("2026-07")
        legacy_batch_id = db.execute(
            """
            INSERT INTO payroll_batches (
                payroll_month,version,period_start,period_end,status,source_cutoff_at,
                idempotency_key,legacy_imported,prepared_by_name
            ) VALUES ('2026-07',1,?,?,'locked','2026-08-01 07:00:00','legacy:test-history',1,'legacy import')
            """,
            (start, end),
        ).lastrowid
        db.commit()

        plan = PayrollHistoryMigrationService.analyze(db, "2026-07")
        assert (plan["total"], plan["resolved"], plan["unresolved"]) == (2, 1, 1)
        assert plan["reason_counts"] == {"missing_current_price": 1}
        result = PayrollHistoryMigrationService.apply(
            db, "2026-07", preparer_id, 1, 1
        )

        assert result["inserted_resolutions"] == 1
        assert result["batch"]["version"] == 2
        assert result["batch"]["supersedes_batch_id"] == legacy_batch_id
        assert result["calculation"]["status"] == "exceptions_pending"
        assert result["calculation"]["priced_record_count"] == 1
        assert result["calculation"]["exception_count"] == 1
        resolution = db.execute(
            "SELECT * FROM payroll_work_price_resolutions"
        ).fetchone()
        assert resolution["price_version_id"] == version_id
        assert resolution["policy_code"] == "current_price_migration_v1"
        manifest = result["manifest"]
        assert manifest["batch_id"] == result["batch"]["id"]
        assert manifest["manifest_sha256"] == plan["manifest_sha256"]
        manifest_records = json.loads(manifest["records_json"])
        assert [row["work_record_id"] for row in manifest_records] == sorted(
            row["work_record_id"] for row in manifest_records
        )
        assert {row["classification"] for row in manifest_records} == {
            "current_price_migration",
            "missing_current_price",
        }

        retry_plan = PayrollHistoryMigrationService.analyze(db, "2026-07")
        assert retry_plan["manifest_sha256"] == plan["manifest_sha256"]
        retry = PayrollHistoryMigrationService.apply(
            db, "2026-07", preparer_id, 1, 1
        )
        assert retry["inserted_resolutions"] == 0
        assert retry["manifest"]["id"] == manifest["id"]
        assert db.execute("SELECT COUNT(*) FROM payroll_migration_manifests").fetchone()[0] == 1

        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(
                "UPDATE payroll_migration_manifests SET records_json='[]' WHERE id=?",
                (manifest["id"],),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(
                "DELETE FROM payroll_migration_manifests WHERE id=?",
                (manifest["id"],),
            )
        db.rollback()

        db.execute(
            "INSERT INTO work_records (order_id,process_id,user_id,type,quantity,status,created_at) "
            "VALUES (?,?,?,'normal',1,'approved','2026-07-16 08:00:00')",
            (order_id, missing_process, worker_id),
        )
        db.commit()
        with pytest.raises(RuntimeError, match="迁移清单与当前数据不一致"):
            PayrollHistoryMigrationService.apply(
                db, "2026-07", preparer_id, 1, 2
            )
        assert db.execute("SELECT COUNT(*) FROM payroll_work_price_resolutions").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM payroll_migration_manifests").fetchone()[0] == 1


def test_historical_analysis_classifies_zero_current_price_as_unresolved(client):
    with client.application.app_context():
        db = get_db()
        worker_id = ensure_user(
            db, "zero-history-worker", WORKER_HASH, "零工价员工", "worker", "ZERO-HIST"
        )
        process_id = ensure_process(db, "历史零工价工序")
        route_id = create_process_route(db, [process_id], "历史零工价路线")
        order_id = create_order(
            db, [process_id], quantity=5, product_code="ZERO-HISTORY-PRODUCT"
        )
        db.execute("UPDATE orders SET route_id=? WHERE id=?", (route_id, order_id))
        db.execute("DROP TRIGGER prevent_legacy_route_price_insert")
        legacy_price_id = db.execute(
            "INSERT INTO route_prices (route_id,process_id,unit_price,effective_date,status) "
            "VALUES (?,?,0,'2026-08-01','active')",
            (route_id, process_id),
        ).lastrowid
        db.execute(
            """
            INSERT INTO route_price_versions (
                route_id,process_id,normal_unit_price_micros,rework_rate_basis_points,
                rework_rate_configured,valid_from,status,created_by_name,approved_by_name,
                approved_at,legacy_route_price_id
            ) VALUES (?,?,0,0,0,'2026-08-01 00:00:00','approved','migration','migration',datetime('now'),?)
            """,
            (route_id, process_id, legacy_price_id),
        )
        work_record_id = db.execute(
            "INSERT INTO work_records (order_id,process_id,user_id,type,quantity,status,created_at) "
            "VALUES (?,?,?,'normal',2,'approved','2026-07-20 08:00:00')",
            (order_id, process_id, worker_id),
        ).lastrowid
        db.commit()

        first = PayrollHistoryMigrationService.analyze(db, "2026-07")
        second = PayrollHistoryMigrationService.analyze(db, "2026-07")
        assert (first["total"], first["resolved"], first["unresolved"]) == (1, 0, 1)
        assert first["reason_counts"] == {"zero_current_price": 1}
        assert json.loads(first["manifest_records_json"]) == [
            {
                "classification": "zero_current_price",
                "work_record_id": work_record_id,
            }
        ]
        assert first["manifest_sha256"] == second["manifest_sha256"]


def test_historical_cutover_rolls_back_when_confirmed_counts_change(client):
    with client.application.app_context():
        db = get_db()
        preparer_id = ensure_user(db, "rollback-preparer", "hash", "回滚制单员", "admin", "ROLLBACK-PREP")
        db.commit()
        try:
            PayrollHistoryMigrationService.apply(db, "2026-07", preparer_id, 2592, 61)
        except RuntimeError as error:
            assert "历史工资基线不一致" in str(error)
        else:
            raise AssertionError("count mismatch must abort the historical cutover")
        assert db.execute("SELECT COUNT(*) FROM payroll_work_price_resolutions").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM payroll_batches WHERE idempotency_key LIKE 'payroll-history-current-price:%'").fetchone()[0] == 0
