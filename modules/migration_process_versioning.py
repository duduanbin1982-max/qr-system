"""Versioned process and route master-data schema migration."""

import hashlib
import json

from modules.migration_helpers import (
    MigrationInvariantError,
    add_column_if_missing,
    column_exists,
    create_unique_index,
    table_exists,
)


MIGRATION_KEY = "v060:legacy-baseline"
ORDER_BINDING_MIGRATION_KEY = "v061:order-version-bindings"
TERMINAL_VERSION_STATUSES = ("published", "superseded", "retired")


def _create_exception_table(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS process_version_migration_exceptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            migration_key TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            legacy_id INTEGER NOT NULL DEFAULT 0,
            reason_code TEXT NOT NULL,
            blocking INTEGER NOT NULL DEFAULT 1 CHECK(blocking IN (0,1)),
            source_summary_json TEXT NOT NULL DEFAULT '{}',
            resolution_status TEXT NOT NULL DEFAULT 'open'
                CHECK(resolution_status IN ('open','resolved','accepted')),
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(migration_key,entity_type,legacy_id,reason_code)
        )
        """
    )


def _required_columns(db, table, columns, issues):
    if not table_exists(db, table):
        issues.append(
            {
                "entity_type": "schema",
                "legacy_id": 0,
                "reason_code": "missing_required_table_" + table,
                "summary": {"table": table},
            }
        )
        return False
    missing = [column for column in columns if not column_exists(db, table, column)]
    for column in missing:
        issues.append(
            {
                "entity_type": "schema",
                "legacy_id": 0,
                "reason_code": f"missing_required_column_{table}_{column}",
                "summary": {"table": table, "column": column},
            }
        )
    return not missing


def _collect_preflight_issues(db):
    issues = []
    process_ready = _required_columns(
        db,
        "processes",
        ("id", "name", "description", "category", "seq_order", "status", "created_at"),
        issues,
    )
    route_ready = _required_columns(
        db,
        "process_routes",
        ("id", "name", "description", "category", "status", "created_at"),
        issues,
    )
    item_ready = _required_columns(
        db,
        "process_route_items",
        ("id", "route_id", "process_id", "seq_order", "is_required", "required_audit"),
        issues,
    )
    _required_columns(db, "users", ("id",), issues)
    _required_columns(db, "route_price_versions", ("id",), issues)

    if process_ready:
        for row in db.execute(
            "SELECT id,status FROM processes "
            "WHERE COALESCE(status,'') NOT IN ('active','inactive') ORDER BY id"
        ).fetchall():
            issues.append(
                {
                    "entity_type": "process",
                    "legacy_id": row[0],
                    "reason_code": "invalid_lifecycle_status",
                    "summary": {"status": row[1]},
                }
            )
        if column_exists(db, "processes", "process_code"):
            for row in db.execute(
                "SELECT id,process_code FROM processes "
                "WHERE COALESCE(process_code,'')<>'' "
                "AND process_code<>printf('PROC-%04d',id) ORDER BY id"
            ).fetchall():
                issues.append(
                    {
                        "entity_type": "process",
                        "legacy_id": row[0],
                        "reason_code": "stable_code_conflict",
                        "summary": {
                            "observed": row[1],
                            "expected": f"PROC-{row[0]:04d}",
                        },
                    }
                )

    if route_ready:
        for row in db.execute(
            "SELECT id,status FROM process_routes "
            "WHERE COALESCE(status,'') NOT IN ('active','inactive') ORDER BY id"
        ).fetchall():
            issues.append(
                {
                    "entity_type": "process_route",
                    "legacy_id": row[0],
                    "reason_code": "invalid_lifecycle_status",
                    "summary": {"status": row[1]},
                }
            )
        if column_exists(db, "process_routes", "route_code"):
            for row in db.execute(
                "SELECT id,route_code FROM process_routes "
                "WHERE COALESCE(route_code,'')<>'' "
                "AND route_code<>printf('ROUTE-%04d',id) ORDER BY id"
            ).fetchall():
                issues.append(
                    {
                        "entity_type": "process_route",
                        "legacy_id": row[0],
                        "reason_code": "stable_code_conflict",
                        "summary": {
                            "observed": row[1],
                            "expected": f"ROUTE-{row[0]:04d}",
                        },
                    }
                )

    if process_ready and route_ready and item_ready:
        queries = (
            (
                "missing_route_root",
                "SELECT item.id,item.route_id,item.process_id,item.seq_order "
                "FROM process_route_items item "
                "LEFT JOIN process_routes route ON route.id=item.route_id "
                "WHERE route.id IS NULL ORDER BY item.id",
            ),
            (
                "missing_process_root",
                "SELECT item.id,item.route_id,item.process_id,item.seq_order "
                "FROM process_route_items item "
                "LEFT JOIN processes process ON process.id=item.process_id "
                "WHERE process.id IS NULL ORDER BY item.id",
            ),
            (
                "duplicate_route_sequence",
                "SELECT item.id,item.route_id,item.process_id,item.seq_order "
                "FROM process_route_items item WHERE EXISTS ("
                "SELECT 1 FROM process_route_items earlier "
                "WHERE earlier.route_id=item.route_id AND earlier.seq_order=item.seq_order "
                "AND earlier.id<item.id) ORDER BY item.id",
            ),
            (
                "duplicate_route_process",
                "SELECT item.id,item.route_id,item.process_id,item.seq_order "
                "FROM process_route_items item WHERE EXISTS ("
                "SELECT 1 FROM process_route_items earlier "
                "WHERE earlier.route_id=item.route_id AND earlier.process_id=item.process_id "
                "AND earlier.id<item.id) ORDER BY item.id",
            ),
            (
                "route_process_category_mismatch",
                "SELECT item.id,item.route_id,item.process_id,item.seq_order "
                "FROM process_route_items item "
                "JOIN process_routes route ON route.id=item.route_id "
                "JOIN processes process ON process.id=item.process_id "
                "WHERE COALESCE(route.category,'')<>COALESCE(process.category,'') "
                "ORDER BY item.id",
            ),
        )
        for reason_code, sql in queries:
            for row in db.execute(sql).fetchall():
                issues.append(
                    {
                        "entity_type": "process_route_item",
                        "legacy_id": row[0],
                        "reason_code": reason_code,
                        "summary": {
                            "route_id": row[1],
                            "process_id": row[2],
                            "seq_order": row[3],
                        },
                    }
                )
    return issues


def _record_blocking_issues(db, issues):
    for issue in issues:
        db.execute(
            "INSERT OR IGNORE INTO process_version_migration_exceptions "
            "(migration_key,entity_type,legacy_id,reason_code,blocking,source_summary_json) "
            "VALUES (?,?,?,?,1,?)",
            (
                MIGRATION_KEY,
                issue["entity_type"],
                issue["legacy_id"],
                issue["reason_code"],
                json.dumps(issue["summary"], ensure_ascii=False, sort_keys=True),
            ),
        )


def _add_root_columns(db):
    add_column_if_missing(db, "processes", "process_code", "TEXT DEFAULT ''")
    add_column_if_missing(
        db,
        "processes",
        "lifecycle_status",
        "TEXT NOT NULL DEFAULT 'active' CHECK(lifecycle_status IN ('active','retired'))",
    )
    add_column_if_missing(
        db,
        "processes",
        "current_effective_version_id",
        "INTEGER REFERENCES process_versions(id) ON DELETE RESTRICT",
    )
    add_column_if_missing(db, "processes", "row_version", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(
        db,
        "processes",
        "created_by",
        "INTEGER REFERENCES users(id) ON DELETE SET NULL",
    )

    add_column_if_missing(db, "process_routes", "route_code", "TEXT DEFAULT ''")
    add_column_if_missing(
        db,
        "process_routes",
        "lifecycle_status",
        "TEXT NOT NULL DEFAULT 'active' CHECK(lifecycle_status IN ('active','retired'))",
    )
    add_column_if_missing(
        db,
        "process_routes",
        "current_effective_version_id",
        "INTEGER REFERENCES process_route_versions(id) ON DELETE RESTRICT",
    )
    add_column_if_missing(db, "process_routes", "row_version", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(
        db,
        "process_routes",
        "created_by",
        "INTEGER REFERENCES users(id) ON DELETE SET NULL",
    )


def _create_version_tables(db):
    statements = (
        """
        CREATE TABLE IF NOT EXISTS process_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            process_id INTEGER NOT NULL,
            version INTEGER NOT NULL CHECK(version>0),
            process_code_snapshot TEXT NOT NULL,
            name TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            seq_order INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK(status IN ('draft','pending_approval','published','superseded',
                    'rejected','cancelled','retired')),
            effective_from TEXT NOT NULL DEFAULT '',
            effective_to TEXT NOT NULL DEFAULT '',
            supersedes_version_id INTEGER,
            revision_reason TEXT NOT NULL DEFAULT '',
            impact_digest TEXT NOT NULL DEFAULT '',
            content_digest TEXT NOT NULL DEFAULT '',
            legacy_baseline INTEGER NOT NULL DEFAULT 0 CHECK(legacy_baseline IN (0,1)),
            prior_revision_unavailable INTEGER NOT NULL DEFAULT 0
                CHECK(prior_revision_unavailable IN (0,1)),
            created_by INTEGER,
            created_by_name TEXT NOT NULL DEFAULT '',
            approved_by INTEGER,
            approved_by_name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            approved_at TEXT NOT NULL DEFAULT '',
            published_at TEXT NOT NULL DEFAULT '',
            idempotency_key TEXT NOT NULL DEFAULT '',
            row_version INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(process_id) REFERENCES processes(id) ON DELETE RESTRICT,
            FOREIGN KEY(supersedes_version_id) REFERENCES process_versions(id) ON DELETE RESTRICT,
            FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(approved_by) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS process_route_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            process_route_id INTEGER NOT NULL,
            version INTEGER NOT NULL CHECK(version>0),
            route_code_snapshot TEXT NOT NULL,
            name TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK(status IN ('draft','pending_approval','published','superseded',
                    'rejected','cancelled','retired')),
            effective_from TEXT NOT NULL DEFAULT '',
            effective_to TEXT NOT NULL DEFAULT '',
            supersedes_version_id INTEGER,
            revision_reason TEXT NOT NULL DEFAULT '',
            impact_digest TEXT NOT NULL DEFAULT '',
            content_digest TEXT NOT NULL DEFAULT '',
            legacy_baseline INTEGER NOT NULL DEFAULT 0 CHECK(legacy_baseline IN (0,1)),
            prior_revision_unavailable INTEGER NOT NULL DEFAULT 0
                CHECK(prior_revision_unavailable IN (0,1)),
            created_by INTEGER,
            created_by_name TEXT NOT NULL DEFAULT '',
            approved_by INTEGER,
            approved_by_name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            approved_at TEXT NOT NULL DEFAULT '',
            published_at TEXT NOT NULL DEFAULT '',
            idempotency_key TEXT NOT NULL DEFAULT '',
            row_version INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(process_route_id) REFERENCES process_routes(id) ON DELETE RESTRICT,
            FOREIGN KEY(supersedes_version_id) REFERENCES process_route_versions(id) ON DELETE RESTRICT,
            FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(approved_by) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS process_route_version_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            route_version_id INTEGER NOT NULL,
            process_id INTEGER NOT NULL,
            process_version_id INTEGER NOT NULL,
            seq_order INTEGER NOT NULL DEFAULT 0,
            is_required INTEGER NOT NULL DEFAULT 1 CHECK(is_required IN (0,1)),
            required_audit INTEGER NOT NULL DEFAULT 0 CHECK(required_audit IN (0,1)),
            legacy_route_item_id INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(route_version_id) REFERENCES process_route_versions(id) ON DELETE RESTRICT,
            FOREIGN KEY(process_id) REFERENCES processes(id) ON DELETE RESTRICT,
            FOREIGN KEY(process_version_id) REFERENCES process_versions(id) ON DELETE RESTRICT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS process_version_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id INTEGER NOT NULL,
            version_id INTEGER,
            event_type TEXT NOT NULL,
            actor_id INTEGER,
            actor_name TEXT NOT NULL DEFAULT '',
            actor_role TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT '',
            impact_digest TEXT NOT NULL DEFAULT '',
            idempotency_key TEXT NOT NULL DEFAULT '',
            from_status TEXT NOT NULL DEFAULT '',
            to_status TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(entity_id) REFERENCES processes(id) ON DELETE RESTRICT,
            FOREIGN KEY(version_id) REFERENCES process_versions(id) ON DELETE RESTRICT,
            FOREIGN KEY(actor_id) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS process_route_version_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id INTEGER NOT NULL,
            version_id INTEGER,
            event_type TEXT NOT NULL,
            actor_id INTEGER,
            actor_name TEXT NOT NULL DEFAULT '',
            actor_role TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT '',
            impact_digest TEXT NOT NULL DEFAULT '',
            idempotency_key TEXT NOT NULL DEFAULT '',
            from_status TEXT NOT NULL DEFAULT '',
            to_status TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(entity_id) REFERENCES process_routes(id) ON DELETE RESTRICT,
            FOREIGN KEY(version_id) REFERENCES process_route_versions(id) ON DELETE RESTRICT,
            FOREIGN KEY(actor_id) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
    )
    for statement in statements:
        db.execute(statement)


def _create_workflow_tables(db):
    statements = (
        """
        CREATE TABLE IF NOT EXISTS process_lifecycle_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            process_id INTEGER NOT NULL,
            action TEXT NOT NULL CHECK(action IN ('retire','reactivate')),
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending','approved','rejected','cancelled')),
            reason TEXT NOT NULL,
            requested_by INTEGER,
            requested_by_name TEXT NOT NULL DEFAULT '',
            approved_by INTEGER,
            approved_by_name TEXT NOT NULL DEFAULT '',
            idempotency_key TEXT NOT NULL DEFAULT '',
            row_version INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            resolved_at TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(process_id) REFERENCES processes(id) ON DELETE RESTRICT,
            FOREIGN KEY(requested_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(approved_by) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS process_route_lifecycle_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            process_route_id INTEGER NOT NULL,
            action TEXT NOT NULL CHECK(action IN ('retire','reactivate')),
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending','approved','rejected','cancelled')),
            reason TEXT NOT NULL,
            requested_by INTEGER,
            requested_by_name TEXT NOT NULL DEFAULT '',
            approved_by INTEGER,
            approved_by_name TEXT NOT NULL DEFAULT '',
            idempotency_key TEXT NOT NULL DEFAULT '',
            row_version INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            resolved_at TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(process_route_id) REFERENCES process_routes(id) ON DELETE RESTRICT,
            FOREIGN KEY(requested_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(approved_by) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS master_data_release_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            release_no TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK(status IN ('draft','pending_approval','published','rejected','cancelled')),
            revision_reason TEXT NOT NULL,
            impact_digest TEXT NOT NULL DEFAULT '',
            created_by INTEGER,
            created_by_name TEXT NOT NULL DEFAULT '',
            approved_by INTEGER,
            approved_by_name TEXT NOT NULL DEFAULT '',
            idempotency_key TEXT NOT NULL DEFAULT '',
            row_version INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            approved_at TEXT NOT NULL DEFAULT '',
            published_at TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(approved_by) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS master_data_release_process_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL,
            process_version_id INTEGER NOT NULL,
            FOREIGN KEY(batch_id) REFERENCES master_data_release_batches(id) ON DELETE RESTRICT,
            FOREIGN KEY(process_version_id) REFERENCES process_versions(id) ON DELETE RESTRICT,
            UNIQUE(batch_id,process_version_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS master_data_release_route_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL,
            route_version_id INTEGER NOT NULL,
            FOREIGN KEY(batch_id) REFERENCES master_data_release_batches(id) ON DELETE RESTRICT,
            FOREIGN KEY(route_version_id) REFERENCES process_route_versions(id) ON DELETE RESTRICT,
            UNIQUE(batch_id,route_version_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS master_data_release_price_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL,
            price_version_id INTEGER NOT NULL,
            FOREIGN KEY(batch_id) REFERENCES master_data_release_batches(id) ON DELETE RESTRICT,
            FOREIGN KEY(price_version_id) REFERENCES route_price_versions(id) ON DELETE RESTRICT,
            UNIQUE(batch_id,price_version_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS master_data_release_exceptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL,
            route_version_id INTEGER NOT NULL,
            retained_process_version_id INTEGER NOT NULL,
            replacement_process_version_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            approved_by INTEGER NOT NULL,
            approved_by_name TEXT NOT NULL DEFAULT '',
            valid_from TEXT NOT NULL,
            valid_to TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(batch_id) REFERENCES master_data_release_batches(id) ON DELETE RESTRICT,
            FOREIGN KEY(route_version_id) REFERENCES process_route_versions(id) ON DELETE RESTRICT,
            FOREIGN KEY(retained_process_version_id) REFERENCES process_versions(id) ON DELETE RESTRICT,
            FOREIGN KEY(replacement_process_version_id) REFERENCES process_versions(id) ON DELETE RESTRICT,
            FOREIGN KEY(approved_by) REFERENCES users(id) ON DELETE RESTRICT,
            UNIQUE(batch_id,route_version_id,replacement_process_version_id),
            CHECK(valid_to>valid_from)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS process_version_migration_manifests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            migration_key TEXT NOT NULL,
            source_process_count INTEGER NOT NULL CHECK(source_process_count>=0),
            source_route_count INTEGER NOT NULL CHECK(source_route_count>=0),
            source_route_item_count INTEGER NOT NULL CHECK(source_route_item_count>=0),
            migrated_process_version_count INTEGER NOT NULL
                CHECK(migrated_process_version_count>=0),
            migrated_route_version_count INTEGER NOT NULL
                CHECK(migrated_route_version_count>=0),
            migrated_route_item_count INTEGER NOT NULL CHECK(migrated_route_item_count>=0),
            manifest_sha256 TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(migration_key),
            UNIQUE(manifest_sha256)
        )
        """,
    )
    for statement in statements:
        db.execute(statement)


def _create_indexes(db):
    statements = (
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_processes_process_code "
        "ON processes(process_code) WHERE process_code<>''",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_routes_route_code "
        "ON process_routes(route_code) WHERE route_code<>''",
        "CREATE INDEX IF NOT EXISTS idx_processes_effective_version "
        "ON processes(current_effective_version_id)",
        "CREATE INDEX IF NOT EXISTS idx_routes_effective_version "
        "ON process_routes(current_effective_version_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_process_versions_root_version "
        "ON process_versions(process_id,version)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_process_versions_one_published "
        "ON process_versions(process_id) WHERE status='published'",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_process_versions_one_open "
        "ON process_versions(process_id) WHERE status IN ('draft','pending_approval')",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_process_versions_idempotency "
        "ON process_versions(idempotency_key) WHERE idempotency_key<>''",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_route_versions_root_version "
        "ON process_route_versions(process_route_id,version)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_route_versions_one_published "
        "ON process_route_versions(process_route_id) WHERE status='published'",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_route_versions_one_open "
        "ON process_route_versions(process_route_id) WHERE status IN ('draft','pending_approval')",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_route_versions_idempotency "
        "ON process_route_versions(idempotency_key) WHERE idempotency_key<>''",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_route_version_items_process "
        "ON process_route_version_items(route_version_id,process_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_route_version_items_sequence "
        "ON process_route_version_items(route_version_id,seq_order)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_route_version_items_legacy "
        "ON process_route_version_items(legacy_route_item_id) "
        "WHERE legacy_route_item_id IS NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_process_version_events_idempotency "
        "ON process_version_events(idempotency_key) WHERE idempotency_key<>''",
        "CREATE INDEX IF NOT EXISTS idx_process_version_events_entity "
        "ON process_version_events(entity_id,created_at,id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_route_version_events_idempotency "
        "ON process_route_version_events(idempotency_key) WHERE idempotency_key<>''",
        "CREATE INDEX IF NOT EXISTS idx_route_version_events_entity "
        "ON process_route_version_events(entity_id,created_at,id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_process_lifecycle_one_pending "
        "ON process_lifecycle_requests(process_id) WHERE status='pending'",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_process_lifecycle_idempotency "
        "ON process_lifecycle_requests(idempotency_key) WHERE idempotency_key<>''",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_route_lifecycle_one_pending "
        "ON process_route_lifecycle_requests(process_route_id) WHERE status='pending'",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_route_lifecycle_idempotency "
        "ON process_route_lifecycle_requests(idempotency_key) WHERE idempotency_key<>''",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_master_data_release_no "
        "ON master_data_release_batches(release_no)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_master_data_release_idempotency "
        "ON master_data_release_batches(idempotency_key) WHERE idempotency_key<>''",
        "CREATE INDEX IF NOT EXISTS idx_master_data_release_exception_batch "
        "ON master_data_release_exceptions(batch_id,route_version_id)",
    )
    for statement in statements:
        db.execute(statement)


def _backfill_legacy_v1(db):
    db.execute(
        "UPDATE processes SET process_code=printf('PROC-%04d',id) "
        "WHERE COALESCE(process_code,'')=''"
    )
    db.execute(
        "UPDATE processes SET lifecycle_status="
        "CASE WHEN status='active' THEN 'active' ELSE 'retired' END "
        "WHERE current_effective_version_id IS NULL"
    )
    db.execute(
        "UPDATE process_routes SET route_code=printf('ROUTE-%04d',id) "
        "WHERE COALESCE(route_code,'')=''"
    )
    db.execute(
        "UPDATE process_routes SET lifecycle_status="
        "CASE WHEN status='active' THEN 'active' ELSE 'retired' END "
        "WHERE current_effective_version_id IS NULL"
    )

    db.execute(
        """
        INSERT INTO process_versions (
            process_id,version,process_code_snapshot,name,category,description,seq_order,
            status,effective_from,revision_reason,legacy_baseline,
            prior_revision_unavailable,created_by,created_at,published_at,
            idempotency_key,row_version
        )
        SELECT process.id,1,process.process_code,process.name,COALESCE(process.category,''),
            COALESCE(process.description,''),COALESCE(process.seq_order,0),
            CASE WHEN process.status='active' THEN 'published' ELSE 'retired' END,
            COALESCE(NULLIF(process.created_at,''),datetime('now','localtime')),
            'Legacy V1 baseline; prior revision unavailable',1,1,process.created_by,
            COALESCE(NULLIF(process.created_at,''),datetime('now','localtime')),
            COALESCE(NULLIF(process.created_at,''),datetime('now','localtime')),
            'v060:process:' || process.id || ':v1',0
        FROM processes process
        WHERE NOT EXISTS (
            SELECT 1 FROM process_versions version
            WHERE version.process_id=process.id AND version.version=1
        )
        """
    )
    db.execute(
        "UPDATE processes SET current_effective_version_id=("
        "SELECT version.id FROM process_versions version "
        "WHERE version.process_id=processes.id AND version.version=1) "
        "WHERE current_effective_version_id IS NULL"
    )

    db.execute(
        """
        INSERT INTO process_route_versions (
            process_route_id,version,route_code_snapshot,name,category,description,status,
            effective_from,revision_reason,legacy_baseline,prior_revision_unavailable,
            created_by,created_at,published_at,idempotency_key,row_version
        )
        SELECT route.id,1,route.route_code,route.name,COALESCE(route.category,''),
            COALESCE(route.description,''),
            CASE WHEN route.status='active' THEN 'published' ELSE 'retired' END,
            COALESCE(NULLIF(route.created_at,''),datetime('now','localtime')),
            'Legacy V1 baseline; prior revision unavailable',1,1,route.created_by,
            COALESCE(NULLIF(route.created_at,''),datetime('now','localtime')),
            COALESCE(NULLIF(route.created_at,''),datetime('now','localtime')),
            'v060:route:' || route.id || ':v1',0
        FROM process_routes route
        WHERE NOT EXISTS (
            SELECT 1 FROM process_route_versions version
            WHERE version.process_route_id=route.id AND version.version=1
        )
        """
    )
    db.execute(
        "UPDATE process_routes SET current_effective_version_id=("
        "SELECT version.id FROM process_route_versions version "
        "WHERE version.process_route_id=process_routes.id AND version.version=1) "
        "WHERE current_effective_version_id IS NULL"
    )

    db.execute(
        """
        INSERT INTO process_route_version_items (
            route_version_id,process_id,process_version_id,seq_order,is_required,
            required_audit,legacy_route_item_id
        )
        SELECT route_version.id,item.process_id,process_version.id,item.seq_order,
            COALESCE(item.is_required,1),COALESCE(item.required_audit,0),item.id
        FROM process_route_items item
        JOIN process_route_versions route_version
            ON route_version.process_route_id=item.route_id AND route_version.version=1
        JOIN process_versions process_version
            ON process_version.process_id=item.process_id AND process_version.version=1
        WHERE NOT EXISTS (
            SELECT 1 FROM process_route_version_items version_item
            WHERE version_item.legacy_route_item_id=item.id
        )
        """
    )

    db.execute(
        """
        INSERT INTO process_version_events (
            entity_id,version_id,event_type,actor_name,actor_role,reason,
            idempotency_key,from_status,to_status,payload_json
        )
        SELECT process.id,version.id,'legacy_baseline_created','System migration','system',
            'Legacy V1 baseline; prior revision unavailable',
            'v060:process:' || process.id || ':baseline','',version.status,
            json_object('legacy_baseline',1,'prior_revision_unavailable',1)
        FROM processes process
        JOIN process_versions version
            ON version.process_id=process.id AND version.version=1
        WHERE NOT EXISTS (
            SELECT 1 FROM process_version_events event
            WHERE event.idempotency_key='v060:process:' || process.id || ':baseline'
        )
        """
    )
    db.execute(
        """
        INSERT INTO process_route_version_events (
            entity_id,version_id,event_type,actor_name,actor_role,reason,
            idempotency_key,from_status,to_status,payload_json
        )
        SELECT route.id,version.id,'legacy_baseline_created','System migration','system',
            'Legacy V1 baseline; prior revision unavailable',
            'v060:route:' || route.id || ':baseline','',version.status,
            json_object('legacy_baseline',1,'prior_revision_unavailable',1)
        FROM process_routes route
        JOIN process_route_versions version
            ON version.process_route_id=route.id AND version.version=1
        WHERE NOT EXISTS (
            SELECT 1 FROM process_route_version_events event
            WHERE event.idempotency_key='v060:route:' || route.id || ':baseline'
        )
        """
    )


def _create_triggers(db):
    terminal = "'" + "','".join(TERMINAL_VERSION_STATUSES) + "'"
    statements = (
        """
        CREATE TRIGGER IF NOT EXISTS protect_process_root_code_update
        BEFORE UPDATE OF process_code ON processes
        WHEN OLD.process_code<>NEW.process_code
        BEGIN SELECT RAISE(ABORT,'stable process code is immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS protect_route_root_code_update
        BEFORE UPDATE OF route_code ON process_routes
        WHEN OLD.route_code<>NEW.route_code
        BEGIN SELECT RAISE(ABORT,'stable route code is immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS protect_process_version_identity_update
        BEFORE UPDATE OF process_id,version,process_code_snapshot ON process_versions
        WHEN OLD.process_id<>NEW.process_id OR OLD.version<>NEW.version
            OR OLD.process_code_snapshot<>NEW.process_code_snapshot
        BEGIN SELECT RAISE(ABORT,'process version identity is immutable'); END
        """,
        f"""
        CREATE TRIGGER IF NOT EXISTS protect_terminal_process_version_content
        BEFORE UPDATE OF process_id,version,process_code_snapshot,name,category,description,
            seq_order,revision_reason,legacy_baseline,prior_revision_unavailable,created_by,
            created_by_name,created_at,idempotency_key
        ON process_versions
        WHEN OLD.status IN ({terminal})
        BEGIN SELECT RAISE(ABORT,'published process version content is immutable'); END
        """,
        f"""
        CREATE TRIGGER IF NOT EXISTS prevent_terminal_process_version_delete
        BEFORE DELETE ON process_versions
        WHEN OLD.status IN ({terminal})
        BEGIN SELECT RAISE(ABORT,'published process versions are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_terminal_process_version_reopen
        BEFORE UPDATE OF status ON process_versions
        WHEN (OLD.status='published' AND NEW.status NOT IN ('published','superseded','retired'))
            OR (OLD.status='superseded' AND NEW.status<>'superseded')
            OR (OLD.status='retired' AND NEW.status<>'retired')
        BEGIN SELECT RAISE(ABORT,'terminal process version status is immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS protect_route_version_identity_update
        BEFORE UPDATE OF process_route_id,version,route_code_snapshot ON process_route_versions
        WHEN OLD.process_route_id<>NEW.process_route_id OR OLD.version<>NEW.version
            OR OLD.route_code_snapshot<>NEW.route_code_snapshot
        BEGIN SELECT RAISE(ABORT,'route version identity is immutable'); END
        """,
        f"""
        CREATE TRIGGER IF NOT EXISTS protect_terminal_route_version_content
        BEFORE UPDATE OF process_route_id,version,route_code_snapshot,name,category,description,
            revision_reason,legacy_baseline,prior_revision_unavailable,created_by,
            created_by_name,created_at,idempotency_key
        ON process_route_versions
        WHEN OLD.status IN ({terminal})
        BEGIN SELECT RAISE(ABORT,'published route version content is immutable'); END
        """,
        f"""
        CREATE TRIGGER IF NOT EXISTS prevent_terminal_route_version_delete
        BEFORE DELETE ON process_route_versions
        WHEN OLD.status IN ({terminal})
        BEGIN SELECT RAISE(ABORT,'published route versions are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_terminal_route_version_reopen
        BEFORE UPDATE OF status ON process_route_versions
        WHEN (OLD.status='published' AND NEW.status NOT IN ('published','superseded','retired'))
            OR (OLD.status='superseded' AND NEW.status<>'superseded')
            OR (OLD.status='retired' AND NEW.status<>'retired')
        BEGIN SELECT RAISE(ABORT,'terminal route version status is immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS validate_route_version_item_process_insert
        BEFORE INSERT ON process_route_version_items
        WHEN NOT EXISTS (
            SELECT 1 FROM process_versions version
            WHERE version.id=NEW.process_version_id AND version.process_id=NEW.process_id
        )
        BEGIN SELECT RAISE(ABORT,'route item process version does not belong to process'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS validate_route_version_item_process_update
        BEFORE UPDATE OF process_id,process_version_id ON process_route_version_items
        WHEN NOT EXISTS (
            SELECT 1 FROM process_versions version
            WHERE version.id=NEW.process_version_id AND version.process_id=NEW.process_id
        )
        BEGIN SELECT RAISE(ABORT,'route item process version does not belong to process'); END
        """,
        f"""
        CREATE TRIGGER IF NOT EXISTS prevent_terminal_route_item_insert
        BEFORE INSERT ON process_route_version_items
        WHEN EXISTS (
            SELECT 1 FROM process_route_versions version
            WHERE version.id=NEW.route_version_id AND version.status IN ({terminal})
        )
        BEGIN SELECT RAISE(ABORT,'published route version items are immutable'); END
        """,
        f"""
        CREATE TRIGGER IF NOT EXISTS prevent_terminal_route_item_update
        BEFORE UPDATE ON process_route_version_items
        WHEN EXISTS (
            SELECT 1 FROM process_route_versions version
            WHERE version.id=OLD.route_version_id AND version.status IN ({terminal})
        )
        OR EXISTS (
            SELECT 1 FROM process_route_versions version
            WHERE version.id=NEW.route_version_id AND version.status IN ({terminal})
        )
        BEGIN SELECT RAISE(ABORT,'published route version items are immutable'); END
        """,
        f"""
        CREATE TRIGGER IF NOT EXISTS prevent_terminal_route_item_delete
        BEFORE DELETE ON process_route_version_items
        WHEN EXISTS (
            SELECT 1 FROM process_route_versions version
            WHERE version.id=OLD.route_version_id AND version.status IN ({terminal})
        )
        BEGIN SELECT RAISE(ABORT,'published route version items are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_process_version_event_update
        BEFORE UPDATE ON process_version_events
        BEGIN SELECT RAISE(ABORT,'process version events are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_process_version_event_delete
        BEFORE DELETE ON process_version_events
        BEGIN SELECT RAISE(ABORT,'process version events are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_route_version_event_update
        BEFORE UPDATE ON process_route_version_events
        BEGIN SELECT RAISE(ABORT,'route version events are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_route_version_event_delete
        BEFORE DELETE ON process_route_version_events
        BEGIN SELECT RAISE(ABORT,'route version events are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_master_data_release_exception_update
        BEFORE UPDATE ON master_data_release_exceptions
        BEGIN SELECT RAISE(ABORT,'master data release exceptions are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_master_data_release_exception_delete
        BEFORE DELETE ON master_data_release_exceptions
        BEGIN SELECT RAISE(ABORT,'master data release exceptions are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_process_version_manifest_update
        BEFORE UPDATE ON process_version_migration_manifests
        BEGIN SELECT RAISE(ABORT,'process version migration manifests are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_process_version_manifest_delete
        BEFORE DELETE ON process_version_migration_manifests
        BEGIN SELECT RAISE(ABORT,'process version migration manifests are immutable'); END
        """,
    )
    for statement in statements:
        db.execute(statement)


def _source_manifest(db):
    process_rows = [
        list(row)
        for row in db.execute(
            "SELECT id,process_code,name,category,description,seq_order,status,created_at "
            "FROM processes ORDER BY id"
        ).fetchall()
    ]
    route_rows = [
        list(row)
        for row in db.execute(
            "SELECT id,route_code,name,category,description,status,created_at "
            "FROM process_routes ORDER BY id"
        ).fetchall()
    ]
    item_rows = [
        list(row)
        for row in db.execute(
            "SELECT id,route_id,process_id,seq_order,is_required,required_audit "
            "FROM process_route_items ORDER BY id"
        ).fetchall()
    ]
    source = {"processes": process_rows, "routes": route_rows, "route_items": item_rows}
    canonical = json.dumps(
        source, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return source, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_baseline(db):
    checks = (
        (
            "process V1 count",
            "SELECT COUNT(*) FROM processes",
            "SELECT COUNT(*) FROM process_versions WHERE version=1 AND legacy_baseline=1 "
            "AND prior_revision_unavailable=1",
        ),
        (
            "route V1 count",
            "SELECT COUNT(*) FROM process_routes",
            "SELECT COUNT(*) FROM process_route_versions WHERE version=1 AND legacy_baseline=1 "
            "AND prior_revision_unavailable=1",
        ),
        (
            "route V1 item count",
            "SELECT COUNT(*) FROM process_route_items",
            "SELECT COUNT(*) FROM process_route_version_items "
            "WHERE legacy_route_item_id IS NOT NULL",
        ),
        (
            "process baseline event count",
            "SELECT COUNT(*) FROM processes",
            "SELECT COUNT(*) FROM process_version_events "
            "WHERE event_type='legacy_baseline_created'",
        ),
        (
            "route baseline event count",
            "SELECT COUNT(*) FROM process_routes",
            "SELECT COUNT(*) FROM process_route_version_events "
            "WHERE event_type='legacy_baseline_created'",
        ),
    )
    for label, expected_sql, actual_sql in checks:
        expected = db.execute(expected_sql).fetchone()[0]
        actual = db.execute(actual_sql).fetchone()[0]
        if actual != expected:
            raise MigrationInvariantError(
                f"Migration v60 blocked: {label} expected {expected}, got {actual}"
            )

    mismatch_queries = (
        (
            "process root/version projection mismatch",
            "SELECT process.id FROM processes process "
            "LEFT JOIN process_versions version "
            "ON version.id=process.current_effective_version_id "
            "WHERE version.id IS NULL OR version.process_id<>process.id OR version.version<>1 "
            "OR version.process_code_snapshot<>process.process_code "
            "OR version.name<>process.name OR version.category<>COALESCE(process.category,'') "
            "OR version.description<>COALESCE(process.description,'') "
            "OR version.seq_order<>COALESCE(process.seq_order,0) "
            "OR version.status<>CASE WHEN process.status='active' THEN 'published' ELSE 'retired' END "
            "LIMIT 1",
        ),
        (
            "route root/version projection mismatch",
            "SELECT route.id FROM process_routes route "
            "LEFT JOIN process_route_versions version "
            "ON version.id=route.current_effective_version_id "
            "WHERE version.id IS NULL OR version.process_route_id<>route.id OR version.version<>1 "
            "OR version.route_code_snapshot<>route.route_code OR version.name<>route.name "
            "OR version.category<>COALESCE(route.category,'') "
            "OR version.description<>COALESCE(route.description,'') "
            "OR version.status<>CASE WHEN route.status='active' THEN 'published' ELSE 'retired' END "
            "LIMIT 1",
        ),
        (
            "route item/version projection mismatch",
            "SELECT item.id FROM process_route_items item "
            "LEFT JOIN process_route_version_items version_item "
            "ON version_item.legacy_route_item_id=item.id "
            "LEFT JOIN process_versions process_version "
            "ON process_version.id=version_item.process_version_id "
            "LEFT JOIN process_route_versions route_version "
            "ON route_version.id=version_item.route_version_id "
            "WHERE version_item.id IS NULL OR version_item.process_id<>item.process_id "
            "OR process_version.process_id<>item.process_id "
            "OR route_version.process_route_id<>item.route_id "
            "OR version_item.seq_order<>item.seq_order "
            "OR version_item.is_required<>COALESCE(item.is_required,1) "
            "OR version_item.required_audit<>COALESCE(item.required_audit,0) LIMIT 1",
        ),
    )
    for label, sql in mismatch_queries:
        row = db.execute(sql).fetchone()
        if row is not None:
            raise MigrationInvariantError(
                f"Migration v60 blocked: {label} at legacy id {row[0]}"
            )


def _write_manifest(db):
    source, digest = _source_manifest(db)
    counts = {
        "source_process_count": len(source["processes"]),
        "source_route_count": len(source["routes"]),
        "source_route_item_count": len(source["route_items"]),
        "migrated_process_version_count": db.execute(
            "SELECT COUNT(*) FROM process_versions WHERE version=1 AND legacy_baseline=1"
        ).fetchone()[0],
        "migrated_route_version_count": db.execute(
            "SELECT COUNT(*) FROM process_route_versions WHERE version=1 AND legacy_baseline=1"
        ).fetchone()[0],
        "migrated_route_item_count": db.execute(
            "SELECT COUNT(*) FROM process_route_version_items "
            "WHERE legacy_route_item_id IS NOT NULL"
        ).fetchone()[0],
    }
    summary = dict(counts)
    summary.update(
        {
            "legacy_baseline": True,
            "prior_revision_unavailable": True,
            "stable_code_policy": "legacy_database_id",
        }
    )
    existing = db.execute(
        "SELECT manifest_sha256 FROM process_version_migration_manifests "
        "WHERE migration_key=?",
        (MIGRATION_KEY,),
    ).fetchone()
    if existing is not None:
        if existing[0] != digest:
            raise MigrationInvariantError(
                "Migration v60 blocked: existing baseline manifest does not match legacy projection"
            )
        return
    db.execute(
        "INSERT INTO process_version_migration_manifests ("
        "migration_key,source_process_count,source_route_count,source_route_item_count,"
        "migrated_process_version_count,migrated_route_version_count,"
        "migrated_route_item_count,manifest_sha256,summary_json) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (
            MIGRATION_KEY,
            counts["source_process_count"],
            counts["source_route_count"],
            counts["source_route_item_count"],
            counts["migrated_process_version_count"],
            counts["migrated_route_version_count"],
            counts["migrated_route_item_count"],
            digest,
            json.dumps(summary, ensure_ascii=False, sort_keys=True),
        ),
    )


def m060_process_master_versioning(db):
    """Create immutable V1 baselines for legacy process and route master data."""
    _create_exception_table(db)
    issues = _collect_preflight_issues(db)
    if issues:
        _record_blocking_issues(db, issues)
        # The exception evidence must survive the migration runner rollback while
        # user_version remains at v059. No versioned schema changes have run yet.
        db.commit()
        sample = ", ".join(
            f"{issue['entity_type']}:{issue['legacy_id']}:{issue['reason_code']}"
            for issue in issues[:5]
        )
        raise MigrationInvariantError(
            f"Migration v60 blocked by {len(issues)} blocking legacy exception(s): {sample}"
        )

    db.execute("SAVEPOINT process_master_v060")
    try:
        _add_root_columns(db)
        _create_version_tables(db)
        _create_workflow_tables(db)
        _create_indexes(db)
        _backfill_legacy_v1(db)
        _create_triggers(db)
        from modules.migration_process_management import (
            rebuild_master_data_reference_guards,
        )

        rebuild_master_data_reference_guards(db)
        _validate_baseline(db)
        _write_manifest(db)
    except Exception:
        db.execute("ROLLBACK TO process_master_v060")
        db.execute("RELEASE process_master_v060")
        raise
    db.execute("RELEASE process_master_v060")


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
        ("id", "order_id", "process_id", "completed"),
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
    route_item_ready = _required_columns(
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

    if all(
        (
            order_ready,
            order_process_ready,
            route_version_ready,
            route_item_ready,
        )
    ):
        for row in db.execute(
            "SELECT op.id,op.order_id,order_row.route_id,op.process_id "
            "FROM order_processes op "
            "JOIN orders order_row ON order_row.id=op.order_id "
            "JOIN process_route_versions route_version "
            "ON route_version.process_route_id=order_row.route_id "
            "AND route_version.version=1 "
            "LEFT JOIN process_route_version_items item "
            "ON item.route_version_id=route_version.id "
            "AND item.process_id=op.process_id "
            "WHERE order_row.route_id IS NOT NULL AND "
            + process_needs_binding
            + " AND item.id IS NULL ORDER BY op.id"
        ).fetchall():
            _append_order_binding_issue(
                issues,
                "order_process",
                row[0],
                "missing_route_v1_node",
                order_id=row[1],
                route_id=row[2],
                process_id=row[3],
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
            "WHERE order_row.route_version_id IS NOT NULL AND item.id IS NULL LIMIT 1",
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


MIGRATIONS = [
    (60, "Add versioned process and route master-data baseline", m060_process_master_versioning),
    (61, "Bind orders to process and route versions", m061_bind_order_versions),
]
