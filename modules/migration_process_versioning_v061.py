"""V061 order, route, and order-process version binding migration."""

import hashlib
import json

from modules.migration_helpers import (
    MigrationInvariantError,
    add_column_if_missing,
    column_exists,
    create_unique_index,
)
from modules.migration_process_versioning_common import (
    ORDER_BINDING_MIGRATION_KEY,
    _create_exception_table,
    _required_columns,
)


def _append_order_binding_issue(
    issues, entity_type, legacy_id, reason_code, **summary
):
    issues.append(
        {
            "entity_type": entity_type,
            "legacy_id": legacy_id,
            "reason_code": reason_code,
            "summary": summary,
        }
    )


def _collect_order_binding_issues(db):
    issues = []
    order_ready = _required_columns(
        db,
        "orders",
        ("id", "route_id", "completed"),
        issues,
    )
    order_process_ready = _required_columns(
        db,
        "order_processes",
        (
            "id",
            "order_id",
            "process_id",
            "seq_order",
            "required_audit",
            "completed",
        ),
        issues,
    )
    process_version_ready = _required_columns(
        db,
        "process_versions",
        ("id", "process_id", "version", "process_code_snapshot", "name", "category"),
        issues,
    )
    route_version_ready = _required_columns(
        db,
        "process_route_versions",
        ("id", "process_route_id", "version", "name"),
        issues,
    )
    _required_columns(
        db,
        "process_route_version_items",
        ("id", "route_version_id", "process_id", "process_version_id"),
        issues,
    )
    _required_columns(db, "process_route_items", ("id",), issues)
    _required_columns(db, "work_records", ("id", "quantity"), issues)

    if order_process_ready and order_ready:
        for row in db.execute(
            "SELECT op.id,op.order_id,op.process_id FROM order_processes op "
            "LEFT JOIN orders order_row ON order_row.id=op.order_id "
            "WHERE order_row.id IS NULL ORDER BY op.id"
        ).fetchall():
            _append_order_binding_issue(
                issues,
                "order_process",
                row[0],
                "missing_order",
                order_id=row[1],
                process_id=row[2],
            )

    route_needs_binding = "1=1"
    if order_ready and column_exists(db, "orders", "route_version_id"):
        route_needs_binding = "order_row.route_version_id IS NULL"
    if order_ready and route_version_ready:
        for row in db.execute(
            "SELECT order_row.id,order_row.route_id FROM orders order_row "
            "LEFT JOIN process_route_versions version "
            "ON version.process_route_id=order_row.route_id AND version.version=1 "
            "WHERE order_row.route_id IS NOT NULL AND "
            + route_needs_binding
            + " AND version.id IS NULL ORDER BY order_row.id"
        ).fetchall():
            _append_order_binding_issue(
                issues,
                "order",
                row[0],
                "missing_route_v1",
                route_id=row[1],
            )

    process_needs_binding = "1=1"
    if order_process_ready and column_exists(
        db, "order_processes", "process_version_id"
    ):
        process_needs_binding = "op.process_version_id IS NULL"
    if order_process_ready and process_version_ready:
        for row in db.execute(
            "SELECT op.id,op.order_id,op.process_id FROM order_processes op "
            "LEFT JOIN process_versions version "
            "ON version.process_id=op.process_id AND version.version=1 "
            "WHERE "
            + process_needs_binding
            + " AND version.id IS NULL ORDER BY op.id"
        ).fetchall():
            _append_order_binding_issue(
                issues,
                "order_process",
                row[0],
                "missing_process_v1",
                order_id=row[1],
                process_id=row[2],
            )

    return issues


def _record_order_binding_issues(db, issues):
    for issue in issues:
        db.execute(
            "INSERT OR IGNORE INTO process_version_migration_exceptions "
            "(migration_key,entity_type,legacy_id,reason_code,blocking,source_summary_json) "
            "VALUES (?,?,?,?,1,?)",
            (
                ORDER_BINDING_MIGRATION_KEY,
                issue["entity_type"],
                issue["legacy_id"],
                issue["reason_code"],
                json.dumps(issue["summary"], ensure_ascii=False, sort_keys=True),
            ),
        )


def _add_order_binding_columns(db):
    add_column_if_missing(
        db,
        "orders",
        "route_version_id",
        "INTEGER REFERENCES process_route_versions(id) ON DELETE RESTRICT",
    )
    add_column_if_missing(
        db,
        "orders",
        "route_name_snapshot",
        "TEXT NOT NULL DEFAULT ''",
    )
    add_column_if_missing(
        db,
        "order_processes",
        "process_version_id",
        "INTEGER REFERENCES process_versions(id) ON DELETE RESTRICT",
    )
    add_column_if_missing(
        db,
        "order_processes",
        "process_code_snapshot",
        "TEXT NOT NULL DEFAULT ''",
    )
    add_column_if_missing(
        db,
        "order_processes",
        "process_name_snapshot",
        "TEXT NOT NULL DEFAULT ''",
    )
    add_column_if_missing(
        db,
        "order_processes",
        "process_category_snapshot",
        "TEXT NOT NULL DEFAULT ''",
    )
    add_column_if_missing(
        db,
        "work_records",
        "process_version_id",
        "INTEGER REFERENCES process_versions(id) ON DELETE RESTRICT",
    )
    add_column_if_missing(
        db,
        "work_records",
        "process_code_snapshot",
        "TEXT NOT NULL DEFAULT ''",
    )
    add_column_if_missing(
        db,
        "work_records",
        "process_name_snapshot",
        "TEXT NOT NULL DEFAULT ''",
    )
    add_column_if_missing(
        db,
        "work_records",
        "process_category_snapshot",
        "TEXT NOT NULL DEFAULT ''",
    )
    add_column_if_missing(
        db,
        "work_records",
        "route_id",
        "INTEGER REFERENCES process_routes(id) ON DELETE RESTRICT",
    )
    add_column_if_missing(
        db,
        "work_records",
        "route_version_id",
        "INTEGER REFERENCES process_route_versions(id) ON DELETE RESTRICT",
    )
    add_column_if_missing(
        db,
        "work_records",
        "route_name_snapshot",
        "TEXT NOT NULL DEFAULT ''",
    )


def _historical_route_snapshot_groups(db):
    """Collect exact legacy order-route snapshots which differ from current V1.

    Legacy order_processes rows are the authoritative copy made when an order was
    created. Some old rows contain duplicate numeric seq_order values, so the
    immutable route revision uses their stable `(seq_order, id)` order and dense
    sequence numbers while retaining the original values in its evidence event.
    """
    route_nodes = {}
    for row in db.execute(
        "SELECT version.process_route_id,item.process_id,item.process_version_id,"
        "item.seq_order,item.is_required,item.required_audit,item.id "
        "FROM process_route_versions version "
        "JOIN process_route_version_items item ON item.route_version_id=version.id "
        "WHERE version.version=1 "
        "ORDER BY version.process_route_id,item.seq_order,item.id"
    ).fetchall():
        route_nodes.setdefault(row["process_route_id"], []).append(
            (
                int(row["process_id"]),
                int(row["is_required"]),
                int(row["required_audit"]),
            )
        )

    needs_binding = ""
    if column_exists(db, "orders", "route_version_id"):
        needs_binding = " AND order_row.route_version_id IS NULL"

    groups = {}
    orders = db.execute(
        "SELECT order_row.id,order_row.route_id FROM orders order_row "
        "WHERE order_row.route_id IS NOT NULL"
        + needs_binding
        + " ORDER BY order_row.id"
    ).fetchall()
    for order in orders:
        rows = db.execute(
            "SELECT op.id,op.process_id,op.seq_order,COALESCE(op.required_audit,0) "
            "AS required_audit,version.id AS process_version_id "
            "FROM order_processes op "
            "JOIN process_versions version ON version.process_id=op.process_id "
            "AND version.version=1 "
            "WHERE op.order_id=? ORDER BY op.seq_order,op.id",
            (order["id"],),
        ).fetchall()
        if not rows:
            continue

        topology = [
            (int(row["process_id"]), 1, int(row["required_audit"])) for row in rows
        ]
        if topology == route_nodes.get(order["route_id"], []):
            continue

        source_nodes = [
            {
                "source_seq_order": int(row["seq_order"] or 0),
                "process_id": int(row["process_id"]),
                "process_version_id": int(row["process_version_id"]),
                "is_required": 1,
                "required_audit": int(row["required_audit"]),
            }
            for row in rows
        ]
        signature_nodes = [
            {
                "source_seq_order": node["source_seq_order"],
                "process_id": node["process_id"],
                "is_required": node["is_required"],
                "required_audit": node["required_audit"],
            }
            for node in source_nodes
        ]
        signature_json = json.dumps(
            {
                "process_route_id": int(order["route_id"]),
                "source_nodes": signature_nodes,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        signature_sha256 = hashlib.sha256(signature_json.encode("utf-8")).hexdigest()
        key = (int(order["route_id"]), signature_sha256)
        group = groups.setdefault(
            key,
            {
                "process_route_id": int(order["route_id"]),
                "signature_sha256": signature_sha256,
                "signature_json": signature_json,
                "source_nodes": source_nodes,
                "order_ids": [],
            },
        )
        if group["signature_json"] != signature_json:
            raise MigrationInvariantError(
                "Migration v61 historical route snapshot digest collision"
            )
        group["order_ids"].append(int(order["id"]))

    return sorted(
        groups.values(),
        key=lambda group: (
            group["process_route_id"],
            min(group["order_ids"]),
            group["signature_sha256"],
        ),
    )


def _historical_route_items(group):
    return [
        {
            "process_id": node["process_id"],
            "process_version_id": node["process_version_id"],
            "seq_order": position,
            "is_required": 1,
            "required_audit": node["required_audit"],
        }
        for position, node in enumerate(group["source_nodes"], start=1)
    ]


def _validate_existing_historical_route_snapshot(db, version, expected_items):
    if version["status"] != "superseded":
        raise MigrationInvariantError(
            "Migration v61 historical route snapshot is not immutable"
        )
    actual = [
        tuple(row)
        for row in db.execute(
            "SELECT process_id,process_version_id,seq_order,is_required,required_audit "
            "FROM process_route_version_items WHERE route_version_id=? "
            "ORDER BY seq_order,id",
            (version["id"],),
        ).fetchall()
    ]
    expected = [
        (
            item["process_id"],
            item["process_version_id"],
            item["seq_order"],
            item["is_required"],
            item["required_audit"],
        )
        for item in expected_items
    ]
    if actual != expected:
        raise MigrationInvariantError(
            "Migration v61 historical route snapshot content mismatch"
        )


def _route_version_topology_sha256(db, route_version_id):
    from modules.process_v2_price_resolution_manifest import topology_sha256

    row = db.execute(
        "SELECT process_route_id FROM process_route_versions WHERE id=?",
        (route_version_id,),
    ).fetchone()
    if row is None:
        return ""
    nodes = [
        {
            "process_id": int(item["process_id"]),
            "is_required": int(item["is_required"]),
            "required_audit": int(item["required_audit"]),
        }
        for item in db.execute(
            "SELECT process_id,is_required,required_audit "
            "FROM process_route_version_items WHERE route_version_id=? "
            "ORDER BY seq_order,id",
            (route_version_id,),
        ).fetchall()
    ]
    return topology_sha256(int(row[0]), nodes)


def _reconstruct_manifest_route_snapshots(db):
    from modules.process_v2_price_resolution_manifest import (
        load_price_binding_resolution_manifest,
        topology_sha256,
    )

    manifest = load_price_binding_resolution_manifest()
    authorization = manifest["authorization"]
    revisions = sorted(
        manifest.get("backup_route_revisions", []),
        key=lambda item: (item["route_id"], item["observed_from"], item["topology_sha256"]),
    )
    for spec in revisions:
        source_prices = []
        for price_id in spec["required_price_version_ids"]:
            row = db.execute(
                "SELECT id,route_id,process_id FROM route_price_versions WHERE id=?",
                (price_id,),
            ).fetchone()
            if row is not None:
                source_prices.append(row)
        if not source_prices:
            continue
        expected_processes = {int(node["process_id"]) for node in spec["nodes"]}
        for price in source_prices:
            if int(price["route_id"]) != int(spec["route_id"]):
                raise MigrationInvariantError(
                    "Migration v61 backup route evidence price root mismatch at "
                    f"price {price['id']}"
                )
            if int(price["process_id"]) not in expected_processes:
                raise MigrationInvariantError(
                    "Migration v61 backup route evidence omits price process at "
                    f"price {price['id']}"
                )
        actual_digest = topology_sha256(spec["route_id"], spec["nodes"])
        if actual_digest != spec["topology_sha256"]:
            raise MigrationInvariantError(
                f"Migration v61 backup topology digest mismatch for route {spec['route_id']}"
            )
        expected_items = []
        for position, node in enumerate(spec["nodes"], start=1):
            process_version = db.execute(
                "SELECT id FROM process_versions WHERE process_id=? AND version=1",
                (node["process_id"],),
            ).fetchone()
            if process_version is None:
                raise MigrationInvariantError(
                    "Migration v61 backup route references a missing process V1: "
                    + str(node["process_id"])
                )
            expected_items.append(
                {
                    "process_id": int(node["process_id"]),
                    "process_version_id": int(process_version[0]),
                    "seq_order": position,
                    "is_required": int(node.get("is_required", 1)),
                    "required_audit": int(node.get("required_audit", 0)),
                }
            )

        idempotency_key = (
            f"v061:route:{spec['route_id']}:backup-snapshot:{actual_digest}"
        )
        version = db.execute(
            "SELECT * FROM process_route_versions WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        if version is None:
            for candidate in db.execute(
                "SELECT * FROM process_route_versions WHERE process_route_id=? "
                "ORDER BY version,id",
                (spec["route_id"],),
            ).fetchall():
                if _route_version_topology_sha256(db, candidate["id"]) == actual_digest:
                    version = candidate
                    break
        if version is None:
            baseline = db.execute(
                "SELECT * FROM process_route_versions "
                "WHERE process_route_id=? AND version=1",
                (spec["route_id"],),
            ).fetchone()
            if baseline is None:
                raise MigrationInvariantError(
                    "Migration v61 missing route V1 for backup evidence route "
                    + str(spec["route_id"])
                )
            next_version = db.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM process_route_versions "
                "WHERE process_route_id=?",
                (spec["route_id"],),
            ).fetchone()[0]
            reason = (
                "Reconstructed from a verified production backup route snapshot; "
                "prior revision metadata unavailable"
            )
            version_id = db.execute(
                "INSERT INTO process_route_versions ("
                "process_route_id,version,route_code_snapshot,name,category,description,"
                "status,effective_from,effective_to,supersedes_version_id,revision_reason,"
                "impact_digest,content_digest,legacy_baseline,prior_revision_unavailable,"
                "created_by,created_by_name,approved_by,approved_by_name,approved_at,"
                "published_at,idempotency_key,row_version) "
                "VALUES (?,?,?,?,?,?,'draft','','',NULL,?,?,?,1,1,NULL,'System migration',"
                "NULL,?,'','',?,0)",
                (
                    spec["route_id"],
                    next_version,
                    baseline["route_code_snapshot"],
                    baseline["name"],
                    baseline["category"],
                    baseline["description"],
                    reason,
                    actual_digest,
                    actual_digest,
                    authorization["approved_by"],
                    idempotency_key,
                ),
            ).lastrowid
            for item in expected_items:
                db.execute(
                    "INSERT INTO process_route_version_items ("
                    "route_version_id,process_id,process_version_id,seq_order,is_required,"
                    "required_audit,legacy_route_item_id) VALUES (?,?,?,?,?,?,NULL)",
                    (
                        version_id,
                        item["process_id"],
                        item["process_version_id"],
                        item["seq_order"],
                        item["is_required"],
                        item["required_audit"],
                    ),
                )
            db.execute(
                "UPDATE process_route_versions SET status='superseded',row_version=1 "
                "WHERE id=? AND status='draft'",
                (version_id,),
            )
            event_payload = json.dumps(
                {
                    "authorization": authorization,
                    "source": "verified_production_backup",
                    "observed_from": spec["observed_from"],
                    "observed_to": spec["observed_to"],
                    "representative_backup": spec["representative_backup"],
                    "representative_backup_sha256": spec[
                        "representative_backup_sha256"
                    ],
                    "required_price_version_ids": spec[
                        "required_price_version_ids"
                    ],
                    "source_topology_sha256": actual_digest,
                    "source_nodes": spec["nodes"],
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            db.execute(
                "INSERT OR IGNORE INTO process_route_version_events ("
                "entity_id,version_id,event_type,actor_name,actor_role,reason,impact_digest,"
                "idempotency_key,from_status,to_status,payload_json) "
                "VALUES (?,?,'legacy_baseline_created',?,'migration_approver',?,?,?,"
                "'','superseded',?)",
                (
                    spec["route_id"],
                    version_id,
                    authorization["approved_by"],
                    reason,
                    actual_digest,
                    idempotency_key + ":event",
                    event_payload,
                ),
            )
            version = db.execute(
                "SELECT * FROM process_route_versions WHERE id=?", (version_id,)
            ).fetchone()
        _validate_existing_historical_route_snapshot(db, version, expected_items)


def _reconstruct_historical_route_snapshots(db):
    """Create immutable superseded revisions and bind matching legacy orders."""
    groups = _historical_route_snapshot_groups(db)
    for group in groups:
        route_id = group["process_route_id"]
        snapshot_digest = group["signature_sha256"]
        idempotency_key = f"v061:route:{route_id}:order-snapshot:{snapshot_digest}"
        expected_items = _historical_route_items(group)
        version = db.execute(
            "SELECT * FROM process_route_versions WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        if version is None:
            baseline = db.execute(
                "SELECT * FROM process_route_versions "
                "WHERE process_route_id=? AND version=1",
                (route_id,),
            ).fetchone()
            if baseline is None:
                raise MigrationInvariantError(
                    f"Migration v61 missing route V1 for historical route {route_id}"
                )
            next_version = db.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM process_route_versions "
                "WHERE process_route_id=?",
                (route_id,),
            ).fetchone()[0]
            reason = (
                "Reconstructed from exact legacy order-process snapshot; "
                "prior route revision metadata unavailable"
            )
            cursor = db.execute(
                "INSERT INTO process_route_versions ("
                "process_route_id,version,route_code_snapshot,name,category,description,"
                "status,effective_from,effective_to,supersedes_version_id,revision_reason,"
                "impact_digest,content_digest,legacy_baseline,prior_revision_unavailable,"
                "created_by,created_by_name,approved_by,approved_by_name,approved_at,"
                "published_at,idempotency_key,row_version) "
                "VALUES (?,?,?,?,?,?,'draft','','',NULL,?,?,?,1,1,NULL,'System migration',"
                "NULL,'System migration','','',?,0)",
                (
                    route_id,
                    next_version,
                    baseline["route_code_snapshot"],
                    baseline["name"],
                    baseline["category"],
                    baseline["description"],
                    reason,
                    snapshot_digest,
                    snapshot_digest,
                    idempotency_key,
                ),
            )
            version_id = cursor.lastrowid
            for item in expected_items:
                db.execute(
                    "INSERT INTO process_route_version_items ("
                    "route_version_id,process_id,process_version_id,seq_order,is_required,"
                    "required_audit,legacy_route_item_id) VALUES (?,?,?,?,?,?,NULL)",
                    (
                        version_id,
                        item["process_id"],
                        item["process_version_id"],
                        item["seq_order"],
                        item["is_required"],
                        item["required_audit"],
                    ),
                )
            db.execute(
                "UPDATE process_route_versions SET status='superseded',row_version=1 "
                "WHERE id=? AND status='draft'",
                (version_id,),
            )
            event_payload = json.dumps(
                {
                    "legacy_baseline": 1,
                    "prior_revision_unavailable": 1,
                    "source": "order_processes",
                    "source_order_ids": group["order_ids"],
                    "source_signature_sha256": snapshot_digest,
                    "source_nodes": group["source_nodes"],
                    "sequence_normalization": "dense order by seq_order then order_process_id",
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            db.execute(
                "INSERT OR IGNORE INTO process_route_version_events ("
                "entity_id,version_id,event_type,actor_name,actor_role,reason,impact_digest,"
                "idempotency_key,from_status,to_status,payload_json) "
                "VALUES (?,?,'legacy_baseline_created','System migration','system',?,?,?,"
                "'','superseded',?)",
                (
                    route_id,
                    version_id,
                    reason,
                    snapshot_digest,
                    idempotency_key + ":event",
                    event_payload,
                ),
            )
            version = db.execute(
                "SELECT * FROM process_route_versions WHERE id=?", (version_id,)
            ).fetchone()

        if int(version["process_route_id"]) != route_id:
            raise MigrationInvariantError(
                "Migration v61 historical route snapshot root mismatch"
            )
        _validate_existing_historical_route_snapshot(db, version, expected_items)
        placeholders = ",".join("?" for _ in group["order_ids"])
        db.execute(
            "UPDATE orders SET route_version_id=?,route_name_snapshot=? "
            f"WHERE id IN ({placeholders}) AND route_id=? AND route_version_id IS NULL",
            (
                version["id"],
                version["name"],
                *group["order_ids"],
                route_id,
            ),
        )


def _backfill_order_version_bindings(db):
    db.execute(
        "UPDATE orders SET route_version_id=("
        "SELECT version.id FROM process_route_versions version "
        "WHERE version.process_route_id=orders.route_id AND version.version=1),"
        "route_name_snapshot=("
        "SELECT version.name FROM process_route_versions version "
        "WHERE version.process_route_id=orders.route_id AND version.version=1) "
        "WHERE route_id IS NOT NULL AND route_version_id IS NULL"
    )
    db.execute(
        "UPDATE orders SET route_name_snapshot=("
        "SELECT version.name FROM process_route_versions version "
        "WHERE version.id=orders.route_version_id) "
        "WHERE route_version_id IS NOT NULL AND COALESCE(route_name_snapshot,'')=''"
    )

    db.execute(
        "UPDATE order_processes SET process_version_id=("
        "SELECT item.process_version_id FROM orders order_row "
        "JOIN process_route_version_items item "
        "ON item.route_version_id=order_row.route_version_id "
        "AND item.process_id=order_processes.process_id "
        "WHERE order_row.id=order_processes.order_id) "
        "WHERE process_version_id IS NULL AND EXISTS ("
        "SELECT 1 FROM orders order_row "
        "WHERE order_row.id=order_processes.order_id "
        "AND order_row.route_version_id IS NOT NULL)"
    )
    db.execute(
        "UPDATE order_processes SET process_version_id=("
        "SELECT version.id FROM process_versions version "
        "WHERE version.process_id=order_processes.process_id AND version.version=1) "
        "WHERE process_version_id IS NULL AND EXISTS ("
        "SELECT 1 FROM orders order_row "
        "WHERE order_row.id=order_processes.order_id "
        "AND order_row.route_version_id IS NULL)"
    )
    db.execute(
        "UPDATE order_processes SET "
        "process_code_snapshot=CASE WHEN COALESCE(process_code_snapshot,'')='' "
        "THEN (SELECT version.process_code_snapshot FROM process_versions version "
        "WHERE version.id=order_processes.process_version_id) "
        "ELSE process_code_snapshot END,"
        "process_name_snapshot=CASE WHEN COALESCE(process_name_snapshot,'')='' "
        "THEN (SELECT version.name FROM process_versions version "
        "WHERE version.id=order_processes.process_version_id) "
        "ELSE process_name_snapshot END,"
        "process_category_snapshot=CASE WHEN COALESCE(process_category_snapshot,'')='' "
        "THEN (SELECT version.category FROM process_versions version "
        "WHERE version.id=order_processes.process_version_id) "
        "ELSE process_category_snapshot END "
        "WHERE process_version_id IS NOT NULL"
    )


def _create_order_binding_indexes(db):
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_orders_route_version "
        "ON orders(route_version_id)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_order_processes_process_version "
        "ON order_processes(process_version_id)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_work_records_process_version "
        "ON work_records(process_version_id)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_work_records_route_version "
        "ON work_records(route_version_id)"
    )
    create_unique_index(
        db,
        "idx_order_processes_order_process_version",
        "order_processes",
        "order_id,process_version_id",
    )


def _create_order_binding_triggers(db):
    statements = (
        """
        CREATE TRIGGER IF NOT EXISTS validate_order_route_version_insert
        BEFORE INSERT ON orders
        WHEN NEW.route_version_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM process_route_versions version
            WHERE version.id=NEW.route_version_id
                AND version.process_route_id=NEW.route_id
        )
        BEGIN SELECT RAISE(ABORT,'order route version does not belong to route'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS validate_order_route_version_update
        BEFORE UPDATE OF route_id,route_version_id ON orders
        WHEN NEW.route_version_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM process_route_versions version
            WHERE version.id=NEW.route_version_id
                AND version.process_route_id=NEW.route_id
        )
        BEGIN SELECT RAISE(ABORT,'order route version does not belong to route'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS validate_order_process_version_insert
        BEFORE INSERT ON order_processes
        WHEN NEW.process_version_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM process_versions version
            WHERE version.id=NEW.process_version_id
                AND version.process_id=NEW.process_id
        )
        BEGIN SELECT RAISE(ABORT,'order process version does not belong to process'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS validate_order_process_version_update
        BEFORE UPDATE OF process_id,process_version_id ON order_processes
        WHEN NEW.process_version_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM process_versions version
            WHERE version.id=NEW.process_version_id
                AND version.process_id=NEW.process_id
        )
        BEGIN SELECT RAISE(ABORT,'order process version does not belong to process'); END
        """,
    )
    for statement in statements:
        db.execute(statement)


def _order_binding_metrics(db):
    return {
        "orders": db.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
        "route_nodes": db.execute(
            "SELECT COUNT(*) FROM process_route_items"
        ).fetchone()[0],
        "order_processes": db.execute(
            "SELECT COUNT(*) FROM order_processes"
        ).fetchone()[0],
        "order_completed": db.execute(
            "SELECT COALESCE(SUM(completed),0) FROM orders"
        ).fetchone()[0],
        "process_completed": db.execute(
            "SELECT COALESCE(SUM(completed),0) FROM order_processes"
        ).fetchone()[0],
        "work_records": db.execute(
            "SELECT COUNT(*) FROM work_records"
        ).fetchone()[0],
        "reported_quantity": db.execute(
            "SELECT COALESCE(SUM(quantity),0) FROM work_records"
        ).fetchone()[0],
        "route_effective_bindings": [
            tuple(row)
            for row in db.execute(
                "SELECT id,current_effective_version_id FROM process_routes ORDER BY id"
            ).fetchall()
        ],
    }


def _validate_order_version_bindings(db, before):
    after = _order_binding_metrics(db)
    if after != before:
        raise MigrationInvariantError(
            f"Migration v61 changed protected business totals: {before} -> {after}"
        )
    checks = (
        (
            "order route version binding",
            "SELECT order_row.id FROM orders order_row "
            "LEFT JOIN process_route_versions version "
            "ON version.id=order_row.route_version_id "
            "WHERE (order_row.route_id IS NULL AND order_row.route_version_id IS NOT NULL) "
            "OR (order_row.route_id IS NOT NULL AND (version.id IS NULL "
            "OR version.process_route_id<>order_row.route_id "
            "OR order_row.route_name_snapshot<>version.name)) LIMIT 1",
        ),
        (
            "order process version binding",
            "SELECT op.id FROM order_processes op "
            "LEFT JOIN process_versions version ON version.id=op.process_version_id "
            "WHERE version.id IS NULL OR version.process_id<>op.process_id "
            "OR op.process_code_snapshot<>version.process_code_snapshot "
            "OR op.process_name_snapshot<>version.name "
            "OR op.process_category_snapshot<>version.category LIMIT 1",
        ),
        (
            "order route node binding",
            "SELECT op.id FROM order_processes op "
            "JOIN orders order_row ON order_row.id=op.order_id "
            "LEFT JOIN process_route_version_items item "
            "ON item.route_version_id=order_row.route_version_id "
            "AND item.process_id=op.process_id "
            "AND item.process_version_id=op.process_version_id "
            "WHERE order_row.route_version_id IS NOT NULL AND (item.id IS NULL "
            "OR item.required_audit<>COALESCE(op.required_audit,0)) LIMIT 1",
        ),
    )
    for label, sql in checks:
        row = db.execute(sql).fetchone()
        if row is not None:
            raise MigrationInvariantError(
                f"Migration v61 blocked: {label} at legacy id {row[0]}"
            )


def m061_bind_order_versions(db):
    """Bind legacy orders and copied process rows to immutable V1 master data."""
    _create_exception_table(db)
    issues = _collect_order_binding_issues(db)
    if issues:
        _record_order_binding_issues(db, issues)
        db.commit()
        sample = ", ".join(
            f"{issue['entity_type']}:{issue['legacy_id']}:{issue['reason_code']}"
            for issue in issues[:5]
        )
        raise MigrationInvariantError(
            f"Migration v61 blocked by {len(issues)} order binding exception(s): {sample}"
        )

    before = _order_binding_metrics(db)
    db.execute("SAVEPOINT process_order_v061")
    try:
        _add_order_binding_columns(db)
        _reconstruct_historical_route_snapshots(db)
        _reconstruct_manifest_route_snapshots(db)
        _backfill_order_version_bindings(db)
        _create_order_binding_indexes(db)
        _create_order_binding_triggers(db)
        from modules.migration_process_management import (
            rebuild_master_data_reference_guards,
        )

        rebuild_master_data_reference_guards(db)
        _validate_order_version_bindings(db, before)
    except Exception:
        db.execute("ROLLBACK TO process_order_v061")
        db.execute("RELEASE process_order_v061")
        raise
    db.execute("RELEASE process_order_v061")
