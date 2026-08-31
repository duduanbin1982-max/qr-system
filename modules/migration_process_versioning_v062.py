"""V062 route-price version binding and controlled resolution migration."""

import json

from modules.migration_helpers import (
    MigrationInvariantError,
    add_column_if_missing,
    column_exists,
    table_exists,
)
from modules.migration_process_versioning_common import (
    PRICE_BINDING_MIGRATION_KEY,
    _create_exception_table,
    _required_columns,
)
from modules.migration_process_versioning_v061 import (
    _route_version_topology_sha256,
)


PRICE_VERSION_MUTATION_TRIGGERS = (
    "prevent_price_version_overlap_insert",
    "prevent_price_version_overlap_update",
    "protect_approved_price_version",
    "validate_price_version_binding_insert",
    "validate_price_version_binding_update",
    "validate_approved_price_version_insert",
    "validate_approved_price_version_update",
    "validate_legacy_unbound_price_insert",
    "validate_legacy_unbound_price_update",
    "reject_unbound_payroll_price_insert",
    "reject_unbound_payroll_price_update",
    "reject_unbound_price_resolution_insert",
    "reject_unbound_price_resolution_update",
)


def _price_resolution_manifest():
    from modules.process_v2_price_resolution_manifest import (
        load_price_binding_resolution_manifest,
    )

    return load_price_binding_resolution_manifest()


def _manifest_price_actions():
    manifest = _price_resolution_manifest()
    fanout = {
        int(item["source_price_version_id"]): ("fanout", item)
        for item in manifest.get("fanout_prices", [])
    }
    retired = {
        int(item["price_version_id"]): ("retire_unbound", item)
        for item in manifest.get("retire_unbound_prices", [])
    }
    overlap = set(fanout) & set(retired)
    if overlap:
        raise MigrationInvariantError(
            "Process V2 price resolution manifest has conflicting actions: "
            + ",".join(str(value) for value in sorted(overlap))
        )
    return {**fanout, **retired}


def _price_reference_metrics(db, price_id):
    price_ids = (
        sorted({int(value) for value in price_id})
        if isinstance(price_id, (list, tuple, set))
        else [int(price_id)]
    )
    placeholders = ",".join("?" for _ in price_ids)
    details = {"count": 0, "amount_cents": 0}
    if table_exists(db, "payroll_detail_lines"):
        row = db.execute(
            "SELECT COUNT(*),COALESCE(SUM(amount_cents),0) "
            f"FROM payroll_detail_lines WHERE price_version_id IN ({placeholders})",
            price_ids,
        ).fetchone()
        details = {"count": int(row[0]), "amount_cents": int(row[1])}
    resolutions = 0
    if table_exists(db, "payroll_work_price_resolutions"):
        resolutions = int(
            db.execute(
                "SELECT COUNT(*) FROM payroll_work_price_resolutions "
                f"WHERE price_version_id IN ({placeholders})",
                price_ids,
            ).fetchone()[0]
        )
    return {"details": details, "resolutions": resolutions}


def _route_versions_by_topology(db, route_id):
    versions = {}
    for row in db.execute(
        "SELECT id FROM process_route_versions WHERE process_route_id=? "
        "ORDER BY version,id",
        (route_id,),
    ).fetchall():
        digest = _route_version_topology_sha256(db, row[0])
        if digest in versions:
            raise MigrationInvariantError(
                f"Migration v62 found duplicate route topology for route {route_id}"
            )
        versions[digest] = int(row[0])
    return versions


def _validate_manifest_price_action(db, price_row, action, spec):
    price_id = int(price_row["id"])
    if action == "retire_unbound":
        if (
            int(price_row["route_id"]) != int(spec["route_id"])
            or int(price_row["process_id"]) != int(spec["process_id"])
        ):
            return {
                "reason_code": "authorized_retirement_source_mismatch",
                "summary": {
                    "route_id": price_row["route_id"],
                    "process_id": price_row["process_id"],
                },
            }
        references = _price_reference_metrics(db, price_id)
        if references["details"]["count"] or references["resolutions"]:
            return {
                "reason_code": "authorized_retirement_has_business_references",
                "summary": references,
            }
        return None

    expected = spec["expected"]
    observed = {
        "route_id": int(price_row["route_id"]),
        "process_id": int(price_row["process_id"]),
        "normal_unit_price_micros": int(price_row["normal_unit_price_micros"]),
        "valid_from": price_row["valid_from"],
        "status": price_row["status"],
    }
    for key in observed:
        if observed[key] != expected[key]:
            return {
                "reason_code": "authorized_fanout_source_mismatch",
                "summary": {"field": key, "expected": expected[key], "actual": observed[key]},
            }
    family_ids = [price_id]
    if table_exists(db, "process_price_binding_migration_events"):
        family_ids.extend(
            int(row[0])
            for row in db.execute(
                "SELECT result_price_version_id "
                "FROM process_price_binding_migration_events "
                "WHERE source_price_version_id=?",
                (price_id,),
            ).fetchall()
        )
    references = _price_reference_metrics(db, family_ids)
    expected_references = {
        "details": {
            "count": int(expected["payroll_detail_count"]),
            "amount_cents": int(expected["payroll_amount_cents"]),
        },
        "resolutions": int(expected["price_resolution_count"]),
    }
    if references != expected_references:
        return {
            "reason_code": "authorized_fanout_reference_mismatch",
            "summary": {"expected": expected_references, "actual": references},
        }
    versions = _route_versions_by_topology(db, observed["route_id"])
    missing = [
        digest
        for digest in spec["target_topology_sha256"]
        if digest not in versions
    ]
    if missing:
        return {
            "reason_code": "authorized_fanout_route_snapshot_missing",
            "summary": {"missing_topology_sha256": missing},
        }
    if spec["primary_topology_sha256"] not in spec["target_topology_sha256"]:
        return {
            "reason_code": "authorized_fanout_primary_not_in_targets",
            "summary": {"primary": spec["primary_topology_sha256"]},
        }
    return None


def _legacy_price_binding_resolution(db, price_id, route_id, process_id):
    """Resolve one legacy root-scoped price to the strongest exact route revision.

    V1 remains the default when it still contains the process.  When the
    process was removed, actual payroll-order usage outranks other historical
    orders; a unique order-backed revision outranks an otherwise unreferenced
    reconstructed revision.  Ambiguity is returned as a blocking issue instead
    of being guessed.
    """

    def candidate(version_id):
        if version_id is None:
            return None
        return db.execute(
            "SELECT version.id AS route_version_id,item.process_version_id "
            "FROM process_route_versions version "
            "JOIN process_route_version_items item ON item.route_version_id=version.id "
            "WHERE version.id=? AND version.process_route_id=? "
            "AND item.process_id=?",
            (version_id, route_id, process_id),
        ).fetchone()

    v1 = db.execute(
        "SELECT version.id AS route_version_id,item.process_version_id "
        "FROM process_route_versions version "
        "JOIN process_route_version_items item ON item.route_version_id=version.id "
        "WHERE version.process_route_id=? AND version.version=1 "
        "AND item.process_id=?",
        (route_id, process_id),
    ).fetchone()
    if v1 is not None:
        return dict(v1), None

    order_columns = (
        {row[1] for row in db.execute("PRAGMA table_info(orders)")}
        if table_exists(db, "orders")
        else set()
    )
    detail_columns = (
        {row[1] for row in db.execute("PRAGMA table_info(payroll_detail_lines)")}
        if table_exists(db, "payroll_detail_lines")
        else set()
    )
    payroll_versions = []
    if {"id", "route_id", "route_version_id"} <= order_columns and {
        "price_version_id",
        "order_id",
    } <= detail_columns:
        payroll_versions = [
            int(row[0])
            for row in db.execute(
                "SELECT DISTINCT order_row.route_version_id "
                "FROM payroll_detail_lines detail JOIN orders order_row "
                "ON order_row.id=detail.order_id "
                "JOIN process_route_version_items item "
                "ON item.route_version_id=order_row.route_version_id "
                "AND item.process_id=? "
                "WHERE detail.price_version_id=? AND order_row.route_id=? "
                "AND order_row.route_version_id IS NOT NULL "
                "ORDER BY order_row.route_version_id",
                (process_id, price_id, route_id),
            ).fetchall()
        ]
    if len(payroll_versions) == 1:
        return dict(candidate(payroll_versions[0])), None
    if len(payroll_versions) > 1:
        return None, {
            "reason_code": "price_used_by_multiple_route_revisions",
            "summary": {
                "route_id": route_id,
                "process_id": process_id,
                "route_version_ids": payroll_versions,
            },
        }

    order_versions = []
    if {"id", "route_id", "route_version_id"} <= order_columns:
        order_versions = [
            int(row[0])
            for row in db.execute(
                "SELECT DISTINCT order_row.route_version_id FROM orders order_row "
                "JOIN process_route_version_items item "
                "ON item.route_version_id=order_row.route_version_id "
                "AND item.process_id=? WHERE order_row.route_id=? "
                "AND order_row.route_version_id IS NOT NULL "
                "ORDER BY order_row.route_version_id",
                (process_id, route_id),
            ).fetchall()
        ]
    if len(order_versions) == 1:
        return dict(candidate(order_versions[0])), None
    if len(order_versions) > 1:
        return None, {
            "reason_code": "multiple_historical_route_candidates",
            "summary": {
                "route_id": route_id,
                "process_id": process_id,
                "route_version_ids": order_versions,
            },
        }

    all_versions = db.execute(
        "SELECT version.id AS route_version_id,item.process_version_id "
        "FROM process_route_versions version "
        "JOIN process_route_version_items item ON item.route_version_id=version.id "
        "WHERE version.process_route_id=? AND item.process_id=? "
        "ORDER BY version.version,version.id",
        (route_id, process_id),
    ).fetchall()
    if len(all_versions) == 1:
        return dict(all_versions[0]), None
    return None, {
        "reason_code": (
            "multiple_unreferenced_route_candidates"
            if len(all_versions) > 1
            else "missing_historical_route_candidate"
        ),
        "summary": {
            "route_id": route_id,
            "process_id": process_id,
            "route_version_ids": [int(row[0]) for row in all_versions],
        },
    }


def _collect_price_binding_issues(db):
    issues = []
    required = (
        ("route_price_versions", ("id", "route_id", "process_id")),
        ("payroll_detail_lines", ("id", "amount_cents")),
        ("process_route_versions", ("id", "process_route_id", "version")),
        (
            "process_route_version_items",
            ("id", "route_version_id", "process_id", "process_version_id"),
        ),
    )
    if not all(_required_columns(db, table, columns, issues) for table, columns in required):
        return issues
    exact_columns_exist = column_exists(
        db, "route_price_versions", "route_version_id"
    ) and column_exists(db, "route_price_versions", "process_version_id")
    legacy_filter = (
        "AND (price.route_version_id IS NULL OR price.process_version_id IS NULL) "
        if exact_columns_exist
        else ""
    )
    rows = db.execute(
        "SELECT price.* FROM route_price_versions price "
        "WHERE 1=1 " + legacy_filter + "ORDER BY price.id"
    ).fetchall()
    explicit_actions = _manifest_price_actions()
    for row in rows:
        explicit = explicit_actions.get(int(row["id"]))
        if explicit is not None:
            issue = _validate_manifest_price_action(db, row, explicit[0], explicit[1])
            if issue is not None:
                issues.append(
                    {
                        "entity_type": "route_price_version",
                        "legacy_id": row["id"],
                        **issue,
                    }
                )
            continue
        _, issue = _legacy_price_binding_resolution(
            db, int(row["id"]), int(row["route_id"]), int(row["process_id"])
        )
        if issue is not None:
            issues.append(
                {
                    "entity_type": "route_price_version",
                    "legacy_id": row["id"],
                    **issue,
                }
            )
    if exact_columns_exist:
        for row in db.execute(
            "SELECT price.id,price.route_id,price.process_id,"
            "price.route_version_id,price.process_version_id "
            "FROM route_price_versions price "
            "LEFT JOIN process_route_versions route_version "
            "ON route_version.id=price.route_version_id "
            "LEFT JOIN process_versions process_version "
            "ON process_version.id=price.process_version_id "
            "LEFT JOIN process_route_version_items item "
            "ON item.route_version_id=price.route_version_id "
            "AND item.process_id=price.process_id "
            "AND item.process_version_id=price.process_version_id "
            "WHERE price.route_version_id IS NOT NULL "
            "AND price.process_version_id IS NOT NULL "
            "AND (route_version.id IS NULL OR process_version.id IS NULL "
            "OR route_version.process_route_id<>price.route_id "
            "OR process_version.process_id<>price.process_id OR item.id IS NULL) "
            "ORDER BY price.id"
        ).fetchall():
            issues.append(
                {
                    "entity_type": "route_price_version",
                    "legacy_id": row[0],
                    "reason_code": "invalid_exact_version_binding",
                    "summary": {
                        "route_id": row[1],
                        "process_id": row[2],
                        "route_version_id": row[3],
                        "process_version_id": row[4],
                    },
                }
            )
    return issues


def _record_price_binding_issues(db, issues):
    for issue in issues:
        db.execute(
            "INSERT OR IGNORE INTO process_version_migration_exceptions "
            "(migration_key,entity_type,legacy_id,reason_code,blocking,source_summary_json) "
            "VALUES (?,?,?,?,1,?)",
            (
                PRICE_BINDING_MIGRATION_KEY,
                issue["entity_type"],
                issue["legacy_id"],
                issue["reason_code"],
                json.dumps(issue["summary"], ensure_ascii=False, sort_keys=True),
            ),
        )


def _price_binding_metrics(db):
    metrics = {
        "prices": db.execute(
            "SELECT COUNT(*) FROM route_price_versions"
        ).fetchone()[0],
        "price_micros": db.execute(
            "SELECT COALESCE(SUM(normal_unit_price_micros),0) "
            "FROM route_price_versions"
        ).fetchone()[0],
        "payroll_details": db.execute(
            "SELECT COUNT(*) FROM payroll_detail_lines"
        ).fetchone()[0],
        "payroll_amount_cents": db.execute(
            "SELECT COALESCE(SUM(amount_cents),0) FROM payroll_detail_lines"
        ).fetchone()[0],
    }
    metrics["price_resolutions"] = (
        db.execute("SELECT COUNT(*) FROM payroll_work_price_resolutions").fetchone()[0]
        if table_exists(db, "payroll_work_price_resolutions")
        else 0
    )
    return metrics


def _drop_price_version_mutation_triggers(db):
    for name in PRICE_VERSION_MUTATION_TRIGGERS:
        db.execute("DROP TRIGGER IF EXISTS " + name)


def _saved_price_reference_update_triggers(db):
    names = ("protect_payroll_detail_update", "prevent_payroll_resolution_update")
    placeholders = ",".join("?" for _ in names)
    return [
        (row["name"], row["sql"])
        for row in db.execute(
            "SELECT name,sql FROM sqlite_master WHERE type='trigger' "
            f"AND name IN ({placeholders}) ORDER BY name",
            names,
        ).fetchall()
        if row["sql"]
    ]


def _drop_named_triggers(db, triggers):
    for name, _ in triggers:
        quoted = name.replace('"', '""')
        db.execute(f'DROP TRIGGER "{quoted}"')


def _restore_named_triggers(db, triggers):
    existing = {
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
    }
    for name, sql in triggers:
        if name not in existing:
            db.execute(sql)


def _add_price_binding_columns(db):
    add_column_if_missing(
        db,
        "route_price_versions",
        "route_version_id",
        "INTEGER REFERENCES process_route_versions(id) ON DELETE RESTRICT",
    )
    add_column_if_missing(
        db,
        "route_price_versions",
        "process_version_id",
        "INTEGER REFERENCES process_versions(id) ON DELETE RESTRICT",
    )
    add_column_if_missing(
        db,
        "payroll_detail_lines",
        "route_version_id",
        "INTEGER REFERENCES process_route_versions(id) ON DELETE RESTRICT",
    )
    add_column_if_missing(
        db,
        "payroll_detail_lines",
        "process_version_id",
        "INTEGER REFERENCES process_versions(id) ON DELETE RESTRICT",
    )
    add_column_if_missing(
        db,
        "route_price_versions",
        "legacy_binding_unavailable",
        "INTEGER NOT NULL DEFAULT 0 CHECK(legacy_binding_unavailable IN (0,1))",
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS process_price_binding_migration_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL CHECK(action IN ('bind_primary','clone_binding','retire_unbound')),
            source_price_version_id INTEGER NOT NULL,
            result_price_version_id INTEGER NOT NULL,
            route_version_id INTEGER,
            process_version_id INTEGER,
            topology_sha256 TEXT NOT NULL DEFAULT '',
            approved_by_name TEXT NOT NULL,
            approved_at TEXT NOT NULL,
            reason TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            idempotency_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(source_price_version_id)
                REFERENCES route_price_versions(id) ON DELETE RESTRICT,
            FOREIGN KEY(result_price_version_id)
                REFERENCES route_price_versions(id) ON DELETE RESTRICT,
            FOREIGN KEY(route_version_id)
                REFERENCES process_route_versions(id) ON DELETE RESTRICT,
            FOREIGN KEY(process_version_id)
                REFERENCES process_versions(id) ON DELETE RESTRICT
        )
        """
    )


def _explicit_price_clone_expectation(db):
    manifest = _price_resolution_manifest()
    event_table_exists = table_exists(db, "process_price_binding_migration_events")
    expected = {"prices": 0, "price_micros": 0}
    for spec in manifest.get("fanout_prices", []):
        price = db.execute(
            "SELECT normal_unit_price_micros FROM route_price_versions WHERE id=?",
            (spec["source_price_version_id"],),
        ).fetchone()
        if price is None:
            continue
        for digest in spec["target_topology_sha256"]:
            if digest == spec["primary_topology_sha256"]:
                continue
            key = f"v062:price:{spec['source_price_version_id']}:topology:{digest}"
            existing = (
                db.execute(
                    "SELECT 1 FROM process_price_binding_migration_events "
                    "WHERE idempotency_key=?",
                    (key,),
                ).fetchone()
                if event_table_exists
                else None
            )
            if existing is None:
                expected["prices"] += 1
                expected["price_micros"] += int(price[0])
    return expected


def _record_price_binding_event(
    db,
    *,
    action,
    source_price_id,
    result_price_id,
    route_version_id,
    process_version_id,
    topology_digest,
    reason,
    payload,
    idempotency_key,
):
    authorization = _price_resolution_manifest()["authorization"]
    db.execute(
        "INSERT OR IGNORE INTO process_price_binding_migration_events ("
        "action,source_price_version_id,result_price_version_id,route_version_id,"
        "process_version_id,topology_sha256,approved_by_name,approved_at,reason,"
        "payload_json,idempotency_key) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            action,
            source_price_id,
            result_price_id,
            route_version_id,
            process_version_id,
            topology_digest,
            authorization["approved_by"],
            authorization["approved_at"],
            reason,
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            idempotency_key,
        ),
    )


def _binding_for_topology(db, route_id, process_id, topology_digest):
    versions = _route_versions_by_topology(db, route_id)
    route_version_id = versions.get(topology_digest)
    if route_version_id is None:
        raise MigrationInvariantError(
            "Migration v62 lost an authorized route topology: " + topology_digest
        )
    item = db.execute(
        "SELECT process_version_id FROM process_route_version_items "
        "WHERE route_version_id=? AND process_id=?",
        (route_version_id, process_id),
    ).fetchone()
    if item is None:
        raise MigrationInvariantError(
            "Migration v62 authorized topology omits price process: "
            + topology_digest
        )
    return route_version_id, int(item[0])


def _clone_price_for_binding(
    db, source_price_id, route_version_id, process_version_id, reason
):
    return db.execute(
        "INSERT INTO route_price_versions ("
        "route_id,process_id,normal_unit_price_micros,rework_rate_basis_points,"
        "rework_rate_configured,valid_from,valid_to,status,created_by,created_by_name,"
        "created_at,approved_by,approved_by_name,approved_at,remark,"
        "legacy_route_price_id,row_version,route_version_id,process_version_id,"
        "legacy_binding_unavailable) "
        "SELECT route_id,process_id,normal_unit_price_micros,rework_rate_basis_points,"
        "rework_rate_configured,valid_from,valid_to,status,created_by,created_by_name,"
        "created_at,approved_by,approved_by_name,approved_at,"
        "CASE WHEN COALESCE(remark,'')='' THEN ? ELSE remark||'; '||? END,"
        "NULL,row_version,?,?,0 FROM route_price_versions WHERE id=?",
        (
            "Exact-route migration clone: " + reason,
            "Exact-route migration clone: " + reason,
            route_version_id,
            process_version_id,
            source_price_id,
        ),
    ).lastrowid


def _rebind_price_references(db, source_price_id, target_prices):
    price_ids = sorted(set(target_prices.values()) | {source_price_id})
    placeholders = ",".join("?" for _ in price_ids)
    detail_updates = 0
    if table_exists(db, "payroll_detail_lines"):
        rows = db.execute(
            "SELECT detail.id,detail.price_version_id,"
            "COALESCE(order_row.route_version_id,work.route_version_id,"
            "work_order.route_version_id) AS route_version_id "
            "FROM payroll_detail_lines detail "
            "LEFT JOIN orders order_row ON order_row.id=detail.order_id "
            "LEFT JOIN work_records work ON work.id=detail.work_record_id "
            "LEFT JOIN orders work_order ON work_order.id=work.order_id "
            f"WHERE detail.price_version_id IN ({placeholders}) ORDER BY detail.id",
            price_ids,
        ).fetchall()
        for row in rows:
            expected_price = target_prices.get(row["route_version_id"])
            if expected_price is None:
                raise MigrationInvariantError(
                    "Migration v62 cannot route payroll detail to an authorized price: "
                    + str(row["id"])
                )
            if int(row["price_version_id"]) != expected_price:
                db.execute(
                    "UPDATE payroll_detail_lines SET price_version_id=? WHERE id=?",
                    (expected_price, row["id"]),
                )
                detail_updates += 1

    resolution_updates = 0
    if table_exists(db, "payroll_work_price_resolutions"):
        rows = db.execute(
            "SELECT resolution.id,resolution.price_version_id,"
            "COALESCE(work.route_version_id,order_row.route_version_id) AS route_version_id "
            "FROM payroll_work_price_resolutions resolution "
            "JOIN work_records work ON work.id=resolution.work_record_id "
            "LEFT JOIN orders order_row ON order_row.id=work.order_id "
            f"WHERE resolution.price_version_id IN ({placeholders}) "
            "ORDER BY resolution.id",
            price_ids,
        ).fetchall()
        for row in rows:
            expected_price = target_prices.get(row["route_version_id"])
            if expected_price is None:
                raise MigrationInvariantError(
                    "Migration v62 cannot route payroll resolution to an authorized price: "
                    + str(row["id"])
                )
            if int(row["price_version_id"]) != expected_price:
                db.execute(
                    "UPDATE payroll_work_price_resolutions SET price_version_id=? WHERE id=?",
                    (expected_price, row["id"]),
                )
                resolution_updates += 1
    return {"payroll_detail_updates": detail_updates, "price_resolution_updates": resolution_updates}


def _apply_explicit_price_resolutions(db):
    manifest = _price_resolution_manifest()
    retirement_time = manifest["retire_effective_at"]
    for spec in manifest.get("retire_unbound_prices", []):
        price_id = int(spec["price_version_id"])
        row = db.execute(
            "SELECT * FROM route_price_versions WHERE id=?", (price_id,)
        ).fetchone()
        if row is None:
            continue
        issue = _validate_manifest_price_action(db, row, "retire_unbound", spec)
        if issue is not None:
            raise MigrationInvariantError(
                f"Migration v62 retirement authorization mismatch at price {price_id}: "
                + issue["reason_code"]
            )
        if not (
            row["status"] == "retired"
            and int(row["legacy_binding_unavailable"] or 0) == 1
        ):
            db.execute(
                "UPDATE route_price_versions SET status='retired',valid_to=?,"
                "route_version_id=NULL,process_version_id=NULL,"
                "legacy_binding_unavailable=1,row_version=row_version+1 WHERE id=?",
                (retirement_time, price_id),
            )
        key = f"v062:price:{price_id}:retire-unbound"
        _record_price_binding_event(
            db,
            action="retire_unbound",
            source_price_id=price_id,
            result_price_id=price_id,
            route_version_id=None,
            process_version_id=None,
            topology_digest="",
            reason="No order, payroll, work record, or backup route evidence; retired without inventing topology.",
            payload={"route_id": spec["route_id"], "process_id": spec["process_id"]},
            idempotency_key=key,
        )

    for spec in manifest.get("fanout_prices", []):
        source_price_id = int(spec["source_price_version_id"])
        source = db.execute(
            "SELECT * FROM route_price_versions WHERE id=?", (source_price_id,)
        ).fetchone()
        if source is None:
            continue
        issue = _validate_manifest_price_action(db, source, "fanout", spec)
        if issue is not None:
            raise MigrationInvariantError(
                f"Migration v62 fanout authorization mismatch at price {source_price_id}: "
                + issue["reason_code"]
            )
        bindings = {}
        for digest in spec["target_topology_sha256"]:
            bindings[digest] = _binding_for_topology(
                db, int(source["route_id"]), int(source["process_id"]), digest
            )
        primary_digest = spec["primary_topology_sha256"]
        primary_binding = bindings[primary_digest]
        db.execute(
            "UPDATE route_price_versions SET route_version_id=?,process_version_id=?,"
            "legacy_binding_unavailable=0 WHERE id=?",
            (*primary_binding, source_price_id),
        )
        target_prices = {primary_binding[0]: source_price_id}
        primary_key = f"v062:price:{source_price_id}:primary:{primary_digest}"
        _record_price_binding_event(
            db,
            action="bind_primary",
            source_price_id=source_price_id,
            result_price_id=source_price_id,
            route_version_id=primary_binding[0],
            process_version_id=primary_binding[1],
            topology_digest=primary_digest,
            reason=spec["reason"],
            payload={"primary": True},
            idempotency_key=primary_key,
        )
        for digest, binding in bindings.items():
            if digest == primary_digest:
                continue
            key = f"v062:price:{source_price_id}:topology:{digest}"
            event = db.execute(
                "SELECT result_price_version_id FROM process_price_binding_migration_events "
                "WHERE idempotency_key=?",
                (key,),
            ).fetchone()
            if event is None:
                result_price_id = _clone_price_for_binding(
                    db, source_price_id, binding[0], binding[1], spec["reason"]
                )
                _record_price_binding_event(
                    db,
                    action="clone_binding",
                    source_price_id=source_price_id,
                    result_price_id=result_price_id,
                    route_version_id=binding[0],
                    process_version_id=binding[1],
                    topology_digest=digest,
                    reason=spec["reason"],
                    payload={"primary": False},
                    idempotency_key=key,
                )
            else:
                result_price_id = int(event[0])
                clone = db.execute(
                    "SELECT route_version_id,process_version_id FROM route_price_versions "
                    "WHERE id=?",
                    (result_price_id,),
                ).fetchone()
                if clone is None or tuple(clone) != binding:
                    raise MigrationInvariantError(
                        "Migration v62 existing price clone does not match its event: "
                        + str(result_price_id)
                    )
            target_prices[binding[0]] = result_price_id
        updates = _rebind_price_references(db, source_price_id, target_prices)
        db.execute(
            "UPDATE process_price_binding_migration_events SET payload_json=? "
            "WHERE idempotency_key=?",
            (
                json.dumps(
                    {"primary": True, **updates},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                primary_key,
            ),
        )


def _backfill_price_version_bindings(db):
    rows = db.execute(
        "SELECT id,route_id,process_id FROM route_price_versions "
        "WHERE (route_version_id IS NULL OR process_version_id IS NULL) "
        "AND COALESCE(legacy_binding_unavailable,0)=0 ORDER BY id"
    ).fetchall()
    for row in rows:
        binding, issue = _legacy_price_binding_resolution(
            db, int(row[0]), int(row[1]), int(row[2])
        )
        if issue is not None:
            raise MigrationInvariantError(
                "Migration v62 lost a preflight price resolution at legacy id "
                f"{row[0]}: {issue['reason_code']}"
            )
        db.execute(
            "UPDATE route_price_versions SET route_version_id=?,process_version_id=? "
            "WHERE id=?",
            (
                binding["route_version_id"],
                binding["process_version_id"],
                row[0],
            ),
        )


def _create_price_binding_indexes(db):
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_price_versions_exact_lookup "
        "ON route_price_versions("
        "route_version_id,process_version_id,status,valid_from,valid_to)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_payroll_detail_route_version "
        "ON payroll_detail_lines(route_version_id)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_payroll_detail_process_version "
        "ON payroll_detail_lines(process_version_id)"
    )


def _create_price_binding_triggers(db):
    statements = [
        """
        CREATE TRIGGER validate_price_version_binding_insert
        BEFORE INSERT ON route_price_versions
        WHEN NOT (
            NEW.status='retired' AND NEW.legacy_binding_unavailable=1
            AND NEW.route_version_id IS NULL AND NEW.process_version_id IS NULL
        ) AND (
          NEW.route_version_id IS NULL OR NEW.process_version_id IS NULL
          OR NOT EXISTS (
            SELECT 1 FROM process_route_versions route_version
            JOIN process_versions process_version
              ON process_version.id=NEW.process_version_id
            JOIN process_route_version_items item
              ON item.route_version_id=route_version.id
             AND item.process_id=NEW.process_id
             AND item.process_version_id=NEW.process_version_id
            WHERE route_version.id=NEW.route_version_id
              AND route_version.process_route_id=NEW.route_id
              AND process_version.process_id=NEW.process_id
          )
        )
        BEGIN SELECT RAISE(ABORT,'price version binding is invalid'); END
        """,
        """
        CREATE TRIGGER validate_price_version_binding_update
        BEFORE UPDATE OF route_id,process_id,route_version_id,process_version_id
        ON route_price_versions
        WHEN NOT (
            NEW.status='retired' AND NEW.legacy_binding_unavailable=1
            AND NEW.route_version_id IS NULL AND NEW.process_version_id IS NULL
        ) AND (
          NEW.route_version_id IS NULL OR NEW.process_version_id IS NULL
          OR NOT EXISTS (
            SELECT 1 FROM process_route_versions route_version
            JOIN process_versions process_version
              ON process_version.id=NEW.process_version_id
            JOIN process_route_version_items item
              ON item.route_version_id=route_version.id
             AND item.process_id=NEW.process_id
             AND item.process_version_id=NEW.process_version_id
            WHERE route_version.id=NEW.route_version_id
              AND route_version.process_route_id=NEW.route_id
              AND process_version.process_id=NEW.process_id
          )
        )
        BEGIN SELECT RAISE(ABORT,'price version binding is invalid'); END
        """,
        """
        CREATE TRIGGER validate_legacy_unbound_price_insert
        BEFORE INSERT ON route_price_versions
        WHEN NEW.legacy_binding_unavailable=1 AND NOT (
            NEW.status='retired' AND NEW.route_version_id IS NULL
            AND NEW.process_version_id IS NULL
        )
        BEGIN SELECT RAISE(ABORT,'legacy unbound price must remain retired and unbound'); END
        """,
        """
        CREATE TRIGGER validate_legacy_unbound_price_update
        BEFORE UPDATE ON route_price_versions
        WHEN NEW.legacy_binding_unavailable=1 AND NOT (
            NEW.status='retired' AND NEW.route_version_id IS NULL
            AND NEW.process_version_id IS NULL
        )
        BEGIN SELECT RAISE(ABORT,'legacy unbound price must remain retired and unbound'); END
        """,
        """
        CREATE TRIGGER validate_approved_price_version_insert
        BEFORE INSERT ON route_price_versions
        WHEN NEW.status='approved' AND NOT EXISTS (
            SELECT 1 FROM process_route_versions route_version
            JOIN process_versions process_version
              ON process_version.id=NEW.process_version_id
            WHERE route_version.id=NEW.route_version_id
              AND route_version.status='published'
              AND process_version.status='published'
        )
        BEGIN SELECT RAISE(ABORT,'approved price requires published versions'); END
        """,
        """
        CREATE TRIGGER validate_approved_price_version_update
        BEFORE UPDATE OF status ON route_price_versions
        WHEN OLD.status<>'approved' AND NEW.status='approved' AND NOT EXISTS (
            SELECT 1 FROM process_route_versions route_version
            JOIN process_versions process_version
              ON process_version.id=NEW.process_version_id
            WHERE route_version.id=NEW.route_version_id
              AND route_version.status='published'
              AND process_version.status='published'
        )
        BEGIN SELECT RAISE(ABORT,'approved price requires published versions'); END
        """,
        """
        CREATE TRIGGER prevent_price_version_overlap_insert
        BEFORE INSERT ON route_price_versions
        WHEN NEW.status='approved' AND EXISTS (
            SELECT 1 FROM route_price_versions current
            WHERE current.route_version_id=NEW.route_version_id
              AND current.process_version_id=NEW.process_version_id
              AND current.status='approved'
              AND COALESCE(current.valid_to,'9999-12-31 23:59:59') > NEW.valid_from
              AND COALESCE(NEW.valid_to,'9999-12-31 23:59:59') > current.valid_from
        )
        BEGIN SELECT RAISE(ABORT,'approved price version intervals overlap'); END
        """,
        """
        CREATE TRIGGER prevent_price_version_overlap_update
        BEFORE UPDATE ON route_price_versions
        WHEN NEW.status='approved' AND EXISTS (
            SELECT 1 FROM route_price_versions current
            WHERE current.id<>NEW.id
              AND current.route_version_id=NEW.route_version_id
              AND current.process_version_id=NEW.process_version_id
              AND current.status='approved'
              AND COALESCE(current.valid_to,'9999-12-31 23:59:59') > NEW.valid_from
              AND COALESCE(NEW.valid_to,'9999-12-31 23:59:59') > current.valid_from
        )
        BEGIN SELECT RAISE(ABORT,'approved price version intervals overlap'); END
        """,
        """
        CREATE TRIGGER protect_approved_price_version
        BEFORE UPDATE ON route_price_versions
        WHEN OLD.status IN ('approved','retired') AND NOT (
            OLD.status='approved' AND NEW.status='approved'
            AND OLD.route_id=NEW.route_id AND OLD.process_id=NEW.process_id
            AND OLD.route_version_id=NEW.route_version_id
            AND OLD.process_version_id=NEW.process_version_id
            AND OLD.normal_unit_price_micros=NEW.normal_unit_price_micros
            AND OLD.rework_rate_basis_points=NEW.rework_rate_basis_points
            AND OLD.rework_rate_configured=NEW.rework_rate_configured
            AND OLD.valid_from=NEW.valid_from
            AND COALESCE(OLD.valid_to,'')=''
            AND COALESCE(NEW.valid_to,'')<>''
        )
        BEGIN SELECT RAISE(ABORT,'approved price versions are immutable'); END
        """,
    ]
    if table_exists(db, "payroll_detail_lines"):
        statements.extend(
            [
                """
                CREATE TRIGGER reject_unbound_payroll_price_insert
                BEFORE INSERT ON payroll_detail_lines
                WHEN NEW.price_version_id IS NOT NULL AND EXISTS (
                    SELECT 1 FROM route_price_versions price
                    WHERE price.id=NEW.price_version_id
                      AND price.legacy_binding_unavailable=1
                )
                BEGIN SELECT RAISE(ABORT,'legacy unbound price cannot be used by payroll'); END
                """,
                """
                CREATE TRIGGER reject_unbound_payroll_price_update
                BEFORE UPDATE OF price_version_id ON payroll_detail_lines
                WHEN NEW.price_version_id IS NOT NULL AND EXISTS (
                    SELECT 1 FROM route_price_versions price
                    WHERE price.id=NEW.price_version_id
                      AND price.legacy_binding_unavailable=1
                )
                BEGIN SELECT RAISE(ABORT,'legacy unbound price cannot be used by payroll'); END
                """,
            ]
        )
    if table_exists(db, "payroll_work_price_resolutions"):
        statements.extend(
            [
                """
                CREATE TRIGGER reject_unbound_price_resolution_insert
                BEFORE INSERT ON payroll_work_price_resolutions
                WHEN NEW.price_version_id IS NOT NULL AND EXISTS (
                    SELECT 1 FROM route_price_versions price
                    WHERE price.id=NEW.price_version_id
                      AND price.legacy_binding_unavailable=1
                )
                BEGIN SELECT RAISE(ABORT,'legacy unbound price cannot be resolved'); END
                """,
                """
                CREATE TRIGGER reject_unbound_price_resolution_update
                BEFORE UPDATE OF price_version_id ON payroll_work_price_resolutions
                WHEN NEW.price_version_id IS NOT NULL AND EXISTS (
                    SELECT 1 FROM route_price_versions price
                    WHERE price.id=NEW.price_version_id
                      AND price.legacy_binding_unavailable=1
                )
                BEGIN SELECT RAISE(ABORT,'legacy unbound price cannot be resolved'); END
                """,
            ]
        )
    for statement in statements:
        db.execute(statement)


def _validate_price_version_bindings(db, before, expected_clones):
    after = _price_binding_metrics(db)
    expected_after = dict(before)
    expected_after["prices"] += expected_clones["prices"]
    expected_after["price_micros"] += expected_clones["price_micros"]
    if after != expected_after:
        raise MigrationInvariantError(
            "Migration v62 changed protected payroll totals outside the authorized "
            f"price clones: {before} -> {after}, expected {expected_after}"
        )
    invalid = db.execute(
        "SELECT price.id FROM route_price_versions price "
        "LEFT JOIN process_route_versions route_version "
        "ON route_version.id=price.route_version_id "
        "LEFT JOIN process_versions process_version "
        "ON process_version.id=price.process_version_id "
        "LEFT JOIN process_route_version_items item "
        "ON item.route_version_id=price.route_version_id "
        "AND item.process_id=price.process_id "
        "AND item.process_version_id=price.process_version_id "
        "WHERE NOT (price.status='retired' AND price.legacy_binding_unavailable=1 "
        "AND price.route_version_id IS NULL AND price.process_version_id IS NULL) "
        "AND (route_version.id IS NULL OR process_version.id IS NULL "
        "OR route_version.process_route_id<>price.route_id "
        "OR process_version.process_id<>price.process_id OR item.id IS NULL) LIMIT 1"
    ).fetchone()
    if invalid is not None:
        raise MigrationInvariantError(
            f"Migration v62 blocked: invalid price binding at legacy id {invalid[0]}"
        )
    invalid_unbound = db.execute(
        "SELECT price.id FROM route_price_versions price "
        "WHERE price.legacy_binding_unavailable=1 AND (price.status<>'retired' "
        "OR price.route_version_id IS NOT NULL OR price.process_version_id IS NOT NULL "
        "OR EXISTS (SELECT 1 FROM payroll_detail_lines detail "
        "WHERE detail.price_version_id=price.id) "
        + (
            "OR EXISTS (SELECT 1 FROM payroll_work_price_resolutions resolution "
            "WHERE resolution.price_version_id=price.id) "
            if table_exists(db, "payroll_work_price_resolutions")
            else ""
        )
        + ") LIMIT 1"
    ).fetchone()
    if invalid_unbound is not None:
        raise MigrationInvariantError(
            "Migration v62 left an invalid retired legacy price at id "
            + str(invalid_unbound[0])
        )
    trigger_names = {
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
    }
    required_triggers = set(PRICE_VERSION_MUTATION_TRIGGERS)
    if not table_exists(db, "payroll_detail_lines"):
        required_triggers -= {
            "reject_unbound_payroll_price_insert",
            "reject_unbound_payroll_price_update",
        }
    if not table_exists(db, "payroll_work_price_resolutions"):
        required_triggers -= {
            "reject_unbound_price_resolution_insert",
            "reject_unbound_price_resolution_update",
        }
    missing = required_triggers - trigger_names
    if missing:
        raise MigrationInvariantError(
            "Migration v62 failed to restore price guards: "
            + ", ".join(sorted(missing))
        )


def m062_bind_price_versions(db):
    """Bind legacy prices and new payroll details to exact master-data versions."""
    _create_exception_table(db)
    issues = _collect_price_binding_issues(db)
    if issues:
        _record_price_binding_issues(db, issues)
        db.commit()
        sample = ", ".join(
            f"{issue['entity_type']}:{issue['legacy_id']}:{issue['reason_code']}"
            for issue in issues[:5]
        )
        raise MigrationInvariantError(
            f"Migration v62 blocked by {len(issues)} price binding exception(s): {sample}"
        )

    before = _price_binding_metrics(db)
    expected_clones = _explicit_price_clone_expectation(db)
    saved_reference_triggers = _saved_price_reference_update_triggers(db)
    db.execute("SAVEPOINT process_price_v062")
    try:
        _drop_price_version_mutation_triggers(db)
        _drop_named_triggers(db, saved_reference_triggers)
        _add_price_binding_columns(db)
        _apply_explicit_price_resolutions(db)
        _backfill_price_version_bindings(db)
        _create_price_binding_indexes(db)
        _create_price_binding_triggers(db)
        _restore_named_triggers(db, saved_reference_triggers)
        _validate_price_version_bindings(db, before, expected_clones)
    except Exception:
        db.execute("ROLLBACK TO process_price_v062")
        db.execute("RELEASE process_price_v062")
        raise
    db.execute("RELEASE process_price_v062")
