"""V075 repair for missing immutable process/route content digests.

V060 created legacy version rows before content digests were populated.  V074
correctly made those digests mandatory for exact pending-route price requests,
which exposed the legacy gap as an empty ``expected_process_content_digest``.
This migration derives the digest from the same canonical payload used by the
version services and repairs only empty digest/snapshot fields.
"""

import json

from modules.domain.process_versioning import (
    canonical_version_payload,
    normalize_route_items,
    payload_sha256,
)
from modules.migration_helpers import MigrationInvariantError, table_exists


MIGRATION_KEY = "v075:process-content-digests"


def _process_digest(row):
    content = {
        "process_id": row["process_id"],
        "version": row["version"],
        "process_code_snapshot": row["process_code_snapshot"],
        "name": row["name"],
        "category": row["category"],
        "description": row["description"],
        "seq_order": row["seq_order"],
    }
    return payload_sha256(canonical_version_payload("process", content, ()))


def _route_digest(db, row):
    items = [
        dict(item)
        for item in db.execute(
            "SELECT process_id,process_version_id,seq_order,is_required,required_audit "
            "FROM process_route_version_items WHERE route_version_id=? "
            "ORDER BY seq_order,id",
            (row["id"],),
        ).fetchall()
    ]
    content = {
        "process_route_id": row["process_route_id"],
        "version": row["version"],
        "route_code_snapshot": row["route_code_snapshot"],
        "name": row["name"],
        "category": row["category"],
        "description": row["description"],
        "items": normalize_route_items(items),
    }
    return payload_sha256(canonical_version_payload("route", content, ()))


def _record_process_event(db, row, digest):
    if not table_exists(db, "process_version_events"):
        return
    key = f"{MIGRATION_KEY}:process:{row['id']}"
    payload = json.dumps(
        {
            "source": "v060-legacy-baseline",
            "old_content_digest": "",
            "new_content_digest": digest,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    db.execute(
        "INSERT OR IGNORE INTO process_version_events ("
        "entity_id,version_id,event_type,actor_name,actor_role,reason,"
        "impact_digest,idempotency_key,from_status,to_status,payload_json) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            row["process_id"],
            row["id"],
            "content_digest_repaired",
            "migration-v075",
            "system",
            "Repair missing canonical process version content digest",
            row["impact_digest"] or "",
            key,
            row["status"] or "",
            row["status"] or "",
            payload,
        ),
    )


def _record_route_event(db, row, digest):
    if not table_exists(db, "process_route_version_events"):
        return
    key = f"{MIGRATION_KEY}:route:{row['id']}"
    payload = json.dumps(
        {
            "source": "v060-legacy-baseline",
            "old_content_digest": "",
            "new_content_digest": digest,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    db.execute(
        "INSERT OR IGNORE INTO process_route_version_events ("
        "entity_id,version_id,event_type,actor_name,actor_role,reason,"
        "impact_digest,idempotency_key,from_status,to_status,payload_json) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            row["process_route_id"],
            row["id"],
            "content_digest_repaired",
            "migration-v075",
            "system",
            "Repair missing canonical route version content digest",
            row["impact_digest"] or "",
            key,
            row["status"] or "",
            row["status"] or "",
            payload,
        ),
    )


def _record_price_event(db, row, route_digest, process_digest):
    if not table_exists(db, "payroll_events"):
        return
    key = f"{MIGRATION_KEY}:price:{row['id']}"
    payload = json.dumps(
        {
            "source": "v074-digest-snapshot-backfill",
            "route_version_id": row["route_version_id"],
            "process_version_id": row["process_version_id"],
            "route_content_digest_snapshot": route_digest,
            "process_content_digest_snapshot": process_digest,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    db.execute(
        "INSERT INTO payroll_events (event_type,operator_name,reason,payload_json,"
        "request_id,idempotency_key) "
        "SELECT ?,?,?,?,?,? WHERE NOT EXISTS ("
        "SELECT 1 FROM payroll_events WHERE idempotency_key=?)",
        (
            "price_version_v075_digest_repaired",
            "migration-v075",
            "Repair missing exact route/process digest snapshots",
            payload,
            key,
            key,
            key,
        ),
    )


def m075_repair_process_content_digests(db):
    required = (
        "process_versions",
        "process_route_versions",
        "process_route_version_items",
        "route_price_versions",
    )
    missing = [name for name in required if not table_exists(db, name)]
    if missing:
        raise MigrationInvariantError(
            "V075 requires versioned process and route tables: " + ",".join(missing)
        )

    db.execute("SAVEPOINT process_content_digest_v075")
    try:
        process_rows = db.execute(
            "SELECT * FROM process_versions "
            "WHERE COALESCE(content_digest,'')='' ORDER BY id"
        ).fetchall()
        route_rows = db.execute(
            "SELECT * FROM process_route_versions "
            "WHERE COALESCE(content_digest,'')='' ORDER BY id"
        ).fetchall()

        for row in process_rows:
            digest = _process_digest(row)
            if len(digest) != 64:
                raise MigrationInvariantError(
                    f"V075 produced invalid process digest for version {row['id']}"
                )
            db.execute(
                "UPDATE process_versions SET content_digest=? "
                "WHERE id=? AND COALESCE(content_digest,'')=''",
                (digest, row["id"]),
            )
            _record_process_event(db, row, digest)

        route_digests = {}
        for row in route_rows:
            digest = _route_digest(db, row)
            if len(digest) != 64:
                raise MigrationInvariantError(
                    f"V075 produced invalid route digest for version {row['id']}"
                )
            route_digests[int(row["id"])] = digest
            db.execute(
                "UPDATE process_route_versions SET content_digest=? "
                "WHERE id=? AND COALESCE(content_digest,'')=''",
                (digest, row["id"]),
            )
            _record_route_event(db, row, digest)

        # V074's snapshot backfill ran before the missing legacy process digests
        # were repaired. Fill only empty snapshots, preserving every existing
        # non-empty snapshot and all price amounts/statuses.
        trigger_sql = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND name='protect_approved_price_version'"
        ).fetchone()
        if trigger_sql is not None:
            db.execute("DROP TRIGGER protect_approved_price_version")
        price_rows = db.execute(
            "SELECT price.*,route_version.content_digest AS route_digest,"
            "process_version.content_digest AS process_digest "
            "FROM route_price_versions price "
            "JOIN process_route_versions route_version "
            "ON route_version.id=price.route_version_id "
            "JOIN process_versions process_version "
            "ON process_version.id=price.process_version_id "
            "WHERE price.route_version_id IS NOT NULL "
            "AND price.process_version_id IS NOT NULL "
            "AND price.status<>'voided' "
            "AND (COALESCE(price.route_content_digest_snapshot,'')='' "
            "OR COALESCE(price.process_content_digest_snapshot,'')='') "
            "ORDER BY price.id"
        ).fetchall()
        for row in price_rows:
            route_digest = row["route_digest"] or route_digests.get(
                int(row["route_version_id"]), ""
            )
            process_digest = row["process_digest"] or ""
            if not route_digest or not process_digest:
                raise MigrationInvariantError(
                    f"V075 cannot repair price digest snapshot {row['id']}"
                )
            db.execute(
                "UPDATE route_price_versions SET "
                "route_content_digest_snapshot=CASE WHEN "
                "COALESCE(route_content_digest_snapshot,'')='' THEN ? "
                "ELSE route_content_digest_snapshot END, "
                "process_content_digest_snapshot=CASE WHEN "
                "COALESCE(process_content_digest_snapshot,'')='' THEN ? "
                "ELSE process_content_digest_snapshot END WHERE id=?",
                (route_digest, process_digest, row["id"]),
            )
            _record_price_event(db, row, route_digest, process_digest)
        if trigger_sql is not None:
            db.execute(trigger_sql[0])
    except Exception:
        db.execute("ROLLBACK TO process_content_digest_v075")
        db.execute("RELEASE process_content_digest_v075")
        raise
    db.execute("RELEASE process_content_digest_v075")


MIGRATIONS = [
    (75, "Repair missing process and route content digests", m075_repair_process_content_digests),
]
