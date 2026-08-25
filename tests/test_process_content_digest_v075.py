import sqlite3

from modules.migration_process_content_digest_v075 import (
    m075_repair_process_content_digests,
)
from tests.test_pending_route_price_v074_migration import migrate_database_through


def _seed_legacy_digest_gap(db, price_status="approved"):
    process_id = db.execute(
        "INSERT INTO processes(name,description,category,seq_order,status,"
        "process_code,lifecycle_status) VALUES (?,?,?,?,?,?,?)",
        ("V075 工序", "摘要修复测试", "机加工", 10, "active", "PROC-V075", "active"),
    ).lastrowid
    process_version_id = db.execute(
        "INSERT INTO process_versions(process_id,version,process_code_snapshot,name,"
        "category,description,seq_order,status,content_digest,idempotency_key) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            process_id,
            1,
            "PROC-V075",
            "V075 工序",
            "机加工",
            "摘要修复测试",
            10,
            "published",
            "",
            "v075-process",
        ),
    ).lastrowid
    route_id = db.execute(
        "INSERT INTO process_routes(name,description,category,status,route_code,"
        "lifecycle_status) VALUES (?,?,?,?,?,?)",
        ("V075 路线", "摘要修复测试", "机加工", "active", "ROUTE-V075", "active"),
    ).lastrowid
    route_version_id = db.execute(
        "INSERT INTO process_route_versions(process_route_id,version,route_code_snapshot,"
        "name,category,description,status,content_digest,idempotency_key) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (
            route_id,
            1,
            "ROUTE-V075",
            "V075 路线",
            "机加工",
            "摘要修复测试",
            "draft",
            "",
            "v075-route",
        ),
    ).lastrowid
    db.execute(
        "INSERT INTO process_route_version_items(route_version_id,process_id,"
        "process_version_id,seq_order,is_required,required_audit) VALUES (?,?,?,?,?,?)",
        (route_version_id, process_id, process_version_id, 10, 1, 0),
    )
    db.execute(
        "UPDATE process_route_versions SET status='published' WHERE id=?",
        (route_version_id,),
    )
    price_id = db.execute(
        "INSERT INTO route_price_versions(route_id,process_id,route_version_id,"
        "process_version_id,normal_unit_price_micros,valid_from,status) "
        "VALUES (?,?,?,?,?,?,?)",
        (route_id, process_id, route_version_id, process_version_id, 100000, "2026-01-01 07:00:00", price_status),
    ).lastrowid
    db.commit()
    return process_version_id, route_version_id, price_id


def test_v075_repairs_missing_digests_and_price_snapshots_with_evidence():
    db = migrate_database_through(74)
    try:
        process_version_id, route_version_id, price_id = _seed_legacy_digest_gap(db, price_status="draft")

        m075_repair_process_content_digests(db)

        process_digest = db.execute(
            "SELECT content_digest FROM process_versions WHERE id=?",
            (process_version_id,),
        ).fetchone()[0]
        route_digest = db.execute(
            "SELECT content_digest FROM process_route_versions WHERE id=?",
            (route_version_id,),
        ).fetchone()[0]
        snapshots = db.execute(
            "SELECT route_content_digest_snapshot,process_content_digest_snapshot "
            "FROM route_price_versions WHERE id=?",
            (price_id,),
        ).fetchone()

        assert len(process_digest) == 64
        assert len(route_digest) == 64
        assert tuple(snapshots) == (route_digest, process_digest)
        assert db.execute(
            "SELECT COUNT(*) FROM process_version_events "
            "WHERE idempotency_key=?",
            (f"v075:process-content-digests:process:{process_version_id}",),
        ).fetchone()[0] == 1
        assert db.execute(
            "SELECT COUNT(*) FROM process_route_version_events "
            "WHERE idempotency_key=?",
            (f"v075:process-content-digests:route:{route_version_id}",),
        ).fetchone()[0] == 1
        assert db.execute(
            "SELECT COUNT(*) FROM payroll_events "
            "WHERE idempotency_key=?",
            (f"v075:process-content-digests:price:{price_id}",),
        ).fetchone()[0] == 1

        m075_repair_process_content_digests(db)
        assert db.execute(
            "SELECT COUNT(*) FROM process_version_events "
            "WHERE idempotency_key=?",
            (f"v075:process-content-digests:process:{process_version_id}",),
        ).fetchone()[0] == 1
        assert db.execute(
            "SELECT COUNT(*) FROM payroll_events "
            "WHERE idempotency_key=?",
            (f"v075:process-content-digests:price:{price_id}",),
        ).fetchone()[0] == 1
    finally:
        db.close()


def test_v075_does_not_replace_existing_digest_or_snapshot():
    db = migrate_database_through(74)
    try:
        process_version_id, route_version_id, price_id = _seed_legacy_digest_gap(db, price_status="draft")
        db.execute(
            "UPDATE process_versions SET content_digest='existing-process-digest' WHERE id=?",
            (process_version_id,),
        )
        db.execute(
            "UPDATE process_route_versions SET content_digest='existing-route-digest' WHERE id=?",
            (route_version_id,),
        )
        db.execute(
            "UPDATE route_price_versions SET route_content_digest_snapshot='existing-route-snapshot',"
            "process_content_digest_snapshot='existing-process-snapshot' WHERE id=?",
            (price_id,),
        )
        db.commit()

        m075_repair_process_content_digests(db)

        assert db.execute(
            "SELECT content_digest FROM process_versions WHERE id=?",
            (process_version_id,),
        ).fetchone()[0] == "existing-process-digest"
        assert db.execute(
            "SELECT content_digest FROM process_route_versions WHERE id=?",
            (route_version_id,),
        ).fetchone()[0] == "existing-route-digest"
        assert tuple(db.execute(
            "SELECT route_content_digest_snapshot,process_content_digest_snapshot "
            "FROM route_price_versions WHERE id=?",
            (price_id,),
        ).fetchone()) == ("existing-route-snapshot", "existing-process-snapshot")
    finally:
        db.close()
