import sqlite3

import pytest

from modules.master_data_references import find_unregistered_reference_columns
from modules.migration_helpers import MigrationInvariantError


FACT_PROCESS_ROLES = {
    "work_records": ("process",),
    "material_consumptions": ("process",),
    "order_completion_focus_events": ("process",),
    "process_handoff_reviews": ("from_process", "to_process"),
    "process_quality_evaluation_tasks": ("target_process", "evaluator_process"),
    "process_quality_evaluation_task_audits": (
        "target_process",
        "evaluator_process",
    ),
    "process_quality_evaluations": ("target_process", "evaluator_process"),
    "quality_inspection_tasks": ("process",),
    "quality_inspections": ("process",),
    "quality_nonconformances": ("process", "responsible_process"),
    "rework_records": ("process",),
    "scrap_records": ("process",),
    "work_time_records": ("process",),
    "work_time_standards": ("process",),
    "payroll_detail_lines": ("process",),
    "performance_quality_events": ("process",),
    "performance_source_facts": ("process",),
}


def _columns(db, table):
    return {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}


def _triggers(db, tables):
    placeholders = ",".join("?" for _ in tables)
    return {
        row["name"]: row["sql"]
        for row in db.execute(
            "SELECT name,sql FROM sqlite_master WHERE type='trigger' "
            f"AND tbl_name IN ({placeholders}) ORDER BY name",
            tuple(tables),
        ).fetchall()
    }


def _v062_fact_db():
    from modules import migrations

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    for version, _, migrate in migrations.MIGRATIONS:
        if version >= 60:
            break
        migrate(db)

    process_ids = [
        row["id"]
        for row in db.execute("SELECT id FROM processes ORDER BY id LIMIT 2").fetchall()
    ]
    route_id = db.execute(
        "INSERT INTO process_routes(name,description,category,status) "
        "VALUES ('v063测试路线','','结构件','active')"
    ).lastrowid
    for seq_order, process_id in enumerate(process_ids, 1):
        db.execute(
            "INSERT INTO process_route_items(route_id,process_id,seq_order,is_required,required_audit) "
            "VALUES (?,?,?,1,0)",
            (route_id, process_id, seq_order),
        )

    for version, _, migrate in migrations.MIGRATIONS:
        if 60 <= version < 63:
            migrate(db)

    route_version = db.execute(
        "SELECT id,name FROM process_route_versions "
        "WHERE process_route_id=? AND version=1",
        (route_id,),
    ).fetchone()
    process_versions = {
        row["process_id"]: row
        for row in db.execute(
            "SELECT id,process_id,process_code_snapshot,name,category "
            "FROM process_versions WHERE process_id IN (?,?) AND version=1",
            tuple(process_ids),
        ).fetchall()
    }
    user_id = db.execute(
        "SELECT id FROM users WHERE role='worker' ORDER BY id LIMIT 1"
    ).fetchone()["id"]
    order_id = db.execute(
        "INSERT INTO orders(order_no,product_name,product_code,quantity,route_id,"
        "route_version_id,route_name_snapshot) VALUES "
        "('V063-ORDER','版本事实产品','V063-PRODUCT',10,?,?,?)",
        (route_id, route_version["id"], route_version["name"]),
    ).lastrowid
    work_record_id = db.execute(
        "INSERT INTO work_records(order_id,process_id,user_id,type,status,quantity,created_at) "
        "VALUES (?,?,?,'normal','approved',7,'2026-08-01 08:00:00')",
        (order_id, process_ids[0], user_id),
    ).lastrowid
    handoff_id = db.execute(
        "INSERT INTO process_handoff_reviews("
        "order_id,from_process_id,to_process_id,from_user_id,evaluator_user_id,"
        "source_work_record_id,quantity,rating,status,created_at) "
        "VALUES (?,?,?,?,?,?,7,4,'confirmed','2026-08-01 09:00:00')",
        (
            order_id,
            process_ids[0],
            process_ids[1],
            user_id,
            user_id,
            work_record_id,
        ),
    ).lastrowid

    payroll_batch_id = db.execute(
        "INSERT INTO payroll_batches("
        "payroll_month,version,period_start,period_end,status,source_cutoff_at,idempotency_key) "
        "VALUES ('2026-08',1,'2026-08-01 07:00:00','2026-09-01 07:00:00',"
        "'confirmed','2026-09-01 07:00:00','v063-payroll')"
    ).lastrowid
    employee_line_id = db.execute(
        "INSERT INTO payroll_employee_lines("
        "batch_id,employee_id,employee_name_snapshot,normal_quantity,normal_wage_cents,"
        "payable_wage_cents) VALUES (?,?, '迁移员工',7,875,875)",
        (payroll_batch_id, user_id),
    ).lastrowid
    payroll_detail_id = db.execute(
        "INSERT INTO payroll_detail_lines("
        "batch_id,employee_line_id,source_type,source_id,work_record_id,work_recorded_at,"
        "order_id,route_id,route_name_snapshot,process_id,process_name_snapshot,quantity,"
        "unit_price_micros,amount_cents) VALUES "
        "(?,?,'normal_work',?,?, '2026-08-01 08:00:00',?,?, '',?, '',7,125000,875)",
        (
            payroll_batch_id,
            employee_line_id,
            work_record_id,
            work_record_id,
            order_id,
            route_id,
            process_ids[0],
        ),
    ).lastrowid

    quality_event_id = db.execute(
        "INSERT INTO performance_quality_events("
        "event_type,quantity,order_id,process_id,user_id,business_at,snapshot_json,event_digest) "
        "VALUES ('scrap',2,?,?,?,'2026-08-01 10:00:00','{\"score\": 88}','v063-event')",
        (order_id, process_ids[0], user_id),
    ).lastrowid
    performance_batch_id = db.execute(
        "INSERT INTO performance_batches("
        "production_month,version,period_start,period_end,idempotency_key,status) "
        "VALUES ('2026-08',1,'2026-08-01 07:00:00','2026-09-01 07:00:00',"
        "'v063-performance','draft')"
    ).lastrowid
    source_fact_id = db.execute(
        "INSERT INTO performance_source_facts("
        "batch_id,fact_type,source_type,source_id,canonical_event_id,business_at,user_id,"
        "order_id,process_id,process_name_snapshot,quantity,payload_json,source_digest) "
        "VALUES (?,'quality','quality_event',?,?, '2026-08-01 10:00:00',?,?,?, '',2,"
        "'{\"score\": 88}','v063-fact')",
        (
            performance_batch_id,
            quality_event_id,
            quality_event_id,
            user_id,
            order_id,
            process_ids[0],
        ),
    ).lastrowid

    db.execute("UPDATE processes SET name='根工序名称已变化' WHERE id=?", (process_ids[0],))
    db.execute("UPDATE process_routes SET name='根路线名称已变化' WHERE id=?", (route_id,))
    db.execute("PRAGMA user_version=62")
    db.commit()
    return db, {
        "process_ids": process_ids,
        "process_versions": process_versions,
        "route_id": route_id,
        "route_version": route_version,
        "order_id": order_id,
        "user_id": user_id,
        "work_record_id": work_record_id,
        "handoff_id": handoff_id,
        "payroll_detail_id": payroll_detail_id,
        "quality_event_id": quality_event_id,
        "source_fact_id": source_fact_id,
    }


def test_v063_adds_exact_version_and_snapshot_columns_to_all_business_facts():
    from modules.migration_process_versioning import m063_version_process_facts

    db, _ = _v062_fact_db()
    try:
        m063_version_process_facts(db)
        for table, roles in FACT_PROCESS_ROLES.items():
            columns = _columns(db, table)
            assert {
                "route_id",
                "route_version_id",
                "route_name_snapshot",
                "version_binding_source",
            } <= columns
            for role in roles:
                assert {
                    f"{role}_version_id",
                    f"{role}_code_snapshot",
                    f"{role}_name_snapshot",
                    f"{role}_category_snapshot",
                } <= columns
        assert find_unregistered_reference_columns(db) == []
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        db.close()


def test_v063_backfills_v1_snapshots_for_single_and_multi_process_facts():
    from modules.migration_process_versioning import m063_version_process_facts

    db, ids = _v062_fact_db()
    try:
        expected_process = ids["process_versions"][ids["process_ids"][0]]
        expected_evaluator = ids["process_versions"][ids["process_ids"][1]]
        m063_version_process_facts(db)

        work = db.execute(
            "SELECT process_version_id,process_code_snapshot,process_name_snapshot,"
            "process_category_snapshot,route_id,route_version_id,route_name_snapshot,"
            "version_binding_source FROM work_records WHERE id=?",
            (ids["work_record_id"],),
        ).fetchone()
        assert tuple(work) == (
            expected_process["id"],
            expected_process["process_code_snapshot"],
            expected_process["name"],
            expected_process["category"],
            ids["route_id"],
            ids["route_version"]["id"],
            ids["route_version"]["name"],
            "legacy_v1",
        )
        assert work["process_name_snapshot"] != "根工序名称已变化"
        assert work["route_name_snapshot"] != "根路线名称已变化"

        handoff = db.execute(
            "SELECT from_process_version_id,from_process_name_snapshot,"
            "to_process_version_id,to_process_name_snapshot,route_version_id,"
            "version_binding_source FROM process_handoff_reviews WHERE id=?",
            (ids["handoff_id"],),
        ).fetchone()
        assert tuple(handoff) == (
            expected_process["id"],
            expected_process["name"],
            expected_evaluator["id"],
            expected_evaluator["name"],
            ids["route_version"]["id"],
            "legacy_v1",
        )
    finally:
        db.close()


def test_v063_preserves_locked_business_values_and_restores_immutable_guards():
    from modules.migration_process_versioning import m063_version_process_facts

    db, ids = _v062_fact_db()
    protected_tables = (
        "payroll_detail_lines",
        "performance_quality_events",
        "performance_source_facts",
    )
    try:
        triggers_before = _triggers(db, protected_tables)
        payroll_before = tuple(
            db.execute(
                "SELECT id,quantity,unit_price_micros,amount_cents,source_snapshot_json "
                "FROM payroll_detail_lines WHERE id=?",
                (ids["payroll_detail_id"],),
            ).fetchone()
        )
        event_before = tuple(
            db.execute(
                "SELECT id,quantity,snapshot_json,event_digest "
                "FROM performance_quality_events WHERE id=?",
                (ids["quality_event_id"],),
            ).fetchone()
        )
        fact_before = tuple(
            db.execute(
                "SELECT id,quantity,payload_json,source_digest "
                "FROM performance_source_facts WHERE id=?",
                (ids["source_fact_id"],),
            ).fetchone()
        )

        m063_version_process_facts(db)

        assert _triggers(db, protected_tables) == triggers_before
        assert tuple(
            db.execute(
                "SELECT id,quantity,unit_price_micros,amount_cents,source_snapshot_json "
                "FROM payroll_detail_lines WHERE id=?",
                (ids["payroll_detail_id"],),
            ).fetchone()
        ) == payroll_before
        assert tuple(
            db.execute(
                "SELECT id,quantity,snapshot_json,event_digest "
                "FROM performance_quality_events WHERE id=?",
                (ids["quality_event_id"],),
            ).fetchone()
        ) == event_before
        assert tuple(
            db.execute(
                "SELECT id,quantity,payload_json,source_digest "
                "FROM performance_source_facts WHERE id=?",
                (ids["source_fact_id"],),
            ).fetchone()
        ) == fact_before

        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(
                "UPDATE payroll_detail_lines SET amount_cents=999 WHERE id=?",
                (ids["payroll_detail_id"],),
            )
        db.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(
                "UPDATE performance_source_facts SET quantity=9 WHERE id=?",
                (ids["source_fact_id"],),
            )
    finally:
        db.close()


def test_v063_keeps_existing_v2_fact_binding_when_reapplied():
    from modules.migration_process_versioning import m063_version_process_facts

    db, ids = _v062_fact_db()
    try:
        m063_version_process_facts(db)
        process_id = ids["process_ids"][0]
        process_v2_id = db.execute(
            "INSERT INTO process_versions("
            "process_id,version,process_code_snapshot,name,category,status) "
            "SELECT process_id,2,process_code_snapshot,'V2工序名称',category,'draft' "
            "FROM process_versions WHERE process_id=? AND version=1",
            (process_id,),
        ).lastrowid
        route_v2_id = db.execute(
            "INSERT INTO process_route_versions("
            "process_route_id,version,route_code_snapshot,name,category,status) "
            "SELECT process_route_id,2,route_code_snapshot,'V2路线名称',category,'draft' "
            "FROM process_route_versions WHERE process_route_id=? AND version=1",
            (ids["route_id"],),
        ).lastrowid
        db.execute(
            "INSERT INTO process_route_version_items("
            "route_version_id,process_id,process_version_id,seq_order) VALUES (?,?,?,1)",
            (route_v2_id, process_id, process_v2_id),
        )
        v2_fact_id = db.execute(
            "INSERT INTO work_records("
            "order_id,process_id,process_version_id,process_code_snapshot,"
            "process_name_snapshot,process_category_snapshot,user_id,type,status,quantity,"
            "route_id,route_version_id,route_name_snapshot,version_binding_source,created_at) "
            "SELECT ?,?,process_version.id,process_version.process_code_snapshot,"
            "process_version.name,process_version.category,?,'normal','approved',1,?,?,"
            "route_version.name,'captured','2026-08-02 08:00:00' "
            "FROM process_versions process_version,process_route_versions route_version "
            "WHERE process_version.id=? AND route_version.id=?",
            (
                ids["order_id"],
                process_id,
                ids["user_id"],
                ids["route_id"],
                route_v2_id,
                process_v2_id,
                route_v2_id,
            ),
        ).lastrowid
        before = tuple(
            db.execute(
                "SELECT process_version_id,process_name_snapshot,route_version_id,"
                "route_name_snapshot,version_binding_source FROM work_records WHERE id=?",
                (v2_fact_id,),
            ).fetchone()
        )

        m063_version_process_facts(db)

        assert tuple(
            db.execute(
                "SELECT process_version_id,process_name_snapshot,route_version_id,"
                "route_name_snapshot,version_binding_source FROM work_records WHERE id=?",
                (v2_fact_id,),
            ).fetchone()
        ) == before == (
            process_v2_id,
            "V2工序名称",
            route_v2_id,
            "V2路线名称",
            "captured",
        )
    finally:
        db.close()


def test_v063_records_unmapped_process_and_blocks_migration():
    from modules.migration_process_versioning import (
        PROCESS_FACT_MIGRATION_KEY,
        m063_version_process_facts,
    )

    db, ids = _v062_fact_db()
    try:
        orphan_process_id = db.execute(
            "INSERT INTO processes("
            "name,description,category,seq_order,status,process_code,lifecycle_status) "
            "VALUES ('无版本工序','','结构件',99,'active','PROC-9999','active')"
        ).lastrowid
        orphan_fact_id = db.execute(
            "INSERT INTO work_records(order_id,process_id,user_id,quantity) VALUES (?,?,?,1)",
            (ids["order_id"], orphan_process_id, ids["user_id"]),
        ).lastrowid
        db.commit()

        with pytest.raises(MigrationInvariantError, match="fact binding exception"):
            m063_version_process_facts(db)

        issue = db.execute(
            "SELECT entity_type,legacy_id,reason_code,blocking,resolution_status "
            "FROM process_version_migration_exceptions "
            "WHERE migration_key=? AND legacy_id=?",
            (PROCESS_FACT_MIGRATION_KEY, orphan_fact_id),
        ).fetchone()
        assert tuple(issue) == (
            "work_records.process",
            orphan_fact_id,
            "missing_process_v1",
            1,
            "open",
        )
        assert "version_binding_source" not in _columns(db, "work_records")
    finally:
        db.close()


def test_v063_indexes_and_reference_guards_cover_fact_versions():
    from modules.migration_process_versioning import m063_version_process_facts

    db, ids = _v062_fact_db()
    try:
        m063_version_process_facts(db)
        indexes = {
            row["name"]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert {
            "idx_v63_work_records_process_version",
            "idx_v63_work_records_route_version",
            "idx_v63_work_records_order_route",
            "idx_v63_work_records_user_time",
            "idx_v63_handoff_from_process_version",
            "idx_v63_handoff_to_process_version",
            "idx_v63_payroll_detail_process_version",
            "idx_v63_performance_fact_process_version",
        } <= indexes

        process_version_id = db.execute(
            "SELECT process_version_id FROM work_records WHERE id=?",
            (ids["work_record_id"],),
        ).fetchone()["process_version_id"]
        route_version_id = db.execute(
            "SELECT route_version_id FROM work_records WHERE id=?",
            (ids["work_record_id"],),
        ).fetchone()["route_version_id"]
        with pytest.raises(sqlite3.IntegrityError, match="process version is referenced"):
            db.execute("DELETE FROM process_versions WHERE id=?", (process_version_id,))
        db.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="route version is referenced"):
            db.execute("DELETE FROM process_route_versions WHERE id=?", (route_version_id,))
    finally:
        db.close()
