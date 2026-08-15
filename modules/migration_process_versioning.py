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
PRICE_BINDING_MIGRATION_KEY = "v062:price-version-bindings"
PROCESS_FACT_MIGRATION_KEY = "v063:process-fact-version-bindings"
TERMINAL_VERSION_STATUSES = ("published", "superseded", "retired")


PROCESS_FACT_BINDINGS = (
    {
        "table": "work_records",
        "roles": ("process",),
        "work_sources": (),
        "index_key": "work_records",
        "user_column": "user_id",
        "time_column": "created_at",
    },
    {
        "table": "material_consumptions",
        "roles": ("process",),
        "work_sources": ("source_work_record_id",),
        "index_key": "material_consumptions",
        "user_column": "operator_id",
        "time_column": "created_at",
    },
    {
        "table": "order_completion_focus_events",
        "roles": ("process",),
        "work_sources": (),
        "index_key": "completion_focus",
        "user_column": "user_id",
        "time_column": "created_at",
    },
    {
        "table": "process_handoff_reviews",
        "roles": ("from_process", "to_process"),
        "work_sources": ("source_work_record_id",),
        "index_key": "handoff",
        "user_column": "from_user_id",
        "time_column": "created_at",
    },
    {
        "table": "process_quality_evaluation_tasks",
        "roles": ("target_process", "evaluator_process"),
        "work_sources": ("target_work_record_id", "trigger_work_record_id"),
        "index_key": "quality_task",
        "user_column": "target_user_id",
        "time_column": "created_at",
    },
    {
        "table": "process_quality_evaluation_task_audits",
        "roles": ("target_process", "evaluator_process"),
        "work_sources": (),
        "index_key": "quality_task_audit",
        "user_column": "target_user_id",
        "time_column": "created_at",
    },
    {
        "table": "process_quality_evaluations",
        "roles": ("target_process", "evaluator_process"),
        "work_sources": ("target_work_record_id", "trigger_work_record_id"),
        "index_key": "quality_evaluation",
        "user_column": "target_user_id",
        "time_column": "created_at",
    },
    {
        "table": "quality_inspection_tasks",
        "roles": ("process",),
        "work_sources": ("work_record_id",),
        "index_key": "inspection_task",
        "user_column": "assigned_to",
        "time_column": "created_at",
    },
    {
        "table": "quality_inspections",
        "roles": ("process",),
        "work_sources": (),
        "index_key": "inspection",
        "user_column": "inspector_id",
        "time_column": "inspected_at",
    },
    {
        "table": "quality_nonconformances",
        "roles": ("process", "responsible_process"),
        "work_sources": (),
        "index_key": "nonconformance",
        "user_column": "responsible_user_id",
        "time_column": "created_at",
    },
    {
        "table": "rework_records",
        "roles": ("process",),
        "work_sources": (),
        "index_key": "rework",
        "user_column": "user_id",
        "time_column": "created_at",
    },
    {
        "table": "scrap_records",
        "roles": ("process",),
        "work_sources": (),
        "index_key": "scrap",
        "user_column": "user_id",
        "time_column": "created_at",
    },
    {
        "table": "work_time_records",
        "roles": ("process",),
        "work_sources": ("source_work_record_id",),
        "index_key": "work_time",
        "user_column": "user_id",
        "time_column": "start_time",
    },
    {
        "table": "work_time_standards",
        "roles": ("process",),
        "work_sources": (),
        "index_key": "work_time_standard",
        "user_column": "created_by",
        "time_column": "effective_from",
    },
    {
        "table": "payroll_detail_lines",
        "roles": ("process",),
        "work_sources": ("work_record_id",),
        "index_key": "payroll_detail",
        "user_column": None,
        "time_column": "work_recorded_at",
    },
    {
        "table": "performance_quality_events",
        "roles": ("process",),
        "work_sources": (),
        "index_key": "performance_event",
        "user_column": "user_id",
        "time_column": "business_at",
    },
    {
        "table": "performance_source_facts",
        "roles": ("process",),
        "work_sources": (),
        "index_key": "performance_fact",
        "user_column": "user_id",
        "time_column": "business_at",
    },
)


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
        ("id", "route_id", "process_id", "seq_order"),
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
    # Older production databases predate optional route nodes and therefore do
    # not have these two additive flags.  Every historical node was mandatory;
    # required-audit was opt-in.  Add both inside the v060 savepoint so a later
    # invariant failure rolls the compatibility change back with the migration.
    add_column_if_missing(
        db,
        "process_route_items",
        "is_required",
        "INTEGER NOT NULL DEFAULT 1 CHECK(is_required IN (0,1))",
    )
    add_column_if_missing(
        db,
        "process_route_items",
        "required_audit",
        "INTEGER NOT NULL DEFAULT 0 CHECK(required_audit IN (0,1))",
    )

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


PRICE_VERSION_MUTATION_TRIGGERS = (
    "prevent_price_version_overlap_insert",
    "prevent_price_version_overlap_update",
    "protect_approved_price_version",
    "validate_price_version_binding_insert",
    "validate_price_version_binding_update",
    "validate_approved_price_version_insert",
    "validate_approved_price_version_update",
)


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
        "SELECT price.id,price.route_id,price.process_id,route_version.id,"
        "route_item.process_version_id FROM route_price_versions price "
        "LEFT JOIN process_route_versions route_version "
        "ON route_version.process_route_id=price.route_id AND route_version.version=1 "
        "LEFT JOIN process_route_version_items route_item "
        "ON route_item.route_version_id=route_version.id "
        "AND route_item.process_id=price.process_id "
        "WHERE (route_version.id IS NULL OR route_item.process_version_id IS NULL) "
        + legacy_filter
        + "ORDER BY price.id"
    ).fetchall()
    for row in rows:
        issues.append(
            {
                "entity_type": "route_price_version",
                "legacy_id": row[0],
                "reason_code": (
                    "missing_route_v1"
                    if row[3] is None
                    else "process_not_in_route_v1"
                ),
                "summary": {"route_id": row[1], "process_id": row[2]},
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
    return {
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


def _drop_price_version_mutation_triggers(db):
    for name in PRICE_VERSION_MUTATION_TRIGGERS:
        db.execute("DROP TRIGGER IF EXISTS " + name)


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


def _backfill_price_version_bindings(db):
    db.execute(
        "UPDATE route_price_versions SET route_version_id=("
        "SELECT version.id FROM process_route_versions version "
        "WHERE version.process_route_id=route_price_versions.route_id "
        "AND version.version=1) WHERE route_version_id IS NULL"
    )
    db.execute(
        "UPDATE route_price_versions SET process_version_id=("
        "SELECT item.process_version_id FROM process_route_version_items item "
        "WHERE item.route_version_id=route_price_versions.route_version_id "
        "AND item.process_id=route_price_versions.process_id) "
        "WHERE process_version_id IS NULL"
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
    statements = (
        """
        CREATE TRIGGER validate_price_version_binding_insert
        BEFORE INSERT ON route_price_versions
        WHEN NEW.route_version_id IS NULL OR NEW.process_version_id IS NULL
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
        BEGIN SELECT RAISE(ABORT,'price version binding is invalid'); END
        """,
        """
        CREATE TRIGGER validate_price_version_binding_update
        BEFORE UPDATE OF route_id,process_id,route_version_id,process_version_id
        ON route_price_versions
        WHEN NEW.route_version_id IS NULL OR NEW.process_version_id IS NULL
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
        BEGIN SELECT RAISE(ABORT,'price version binding is invalid'); END
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
    )
    for statement in statements:
        db.execute(statement)


def _validate_price_version_bindings(db, before):
    after = _price_binding_metrics(db)
    if after != before:
        raise MigrationInvariantError(
            f"Migration v62 changed protected payroll totals: {before} -> {after}"
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
        "WHERE route_version.id IS NULL OR process_version.id IS NULL "
        "OR route_version.process_route_id<>price.route_id "
        "OR process_version.process_id<>price.process_id OR item.id IS NULL LIMIT 1"
    ).fetchone()
    if invalid is not None:
        raise MigrationInvariantError(
            f"Migration v62 blocked: invalid price binding at legacy id {invalid[0]}"
        )
    trigger_names = {
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
    }
    missing = set(PRICE_VERSION_MUTATION_TRIGGERS) - trigger_names
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
    db.execute("SAVEPOINT process_price_v062")
    try:
        _drop_price_version_mutation_triggers(db)
        _add_price_binding_columns(db)
        _backfill_price_version_bindings(db)
        _create_price_binding_indexes(db)
        _create_price_binding_triggers(db)
        _validate_price_version_bindings(db, before)
    except Exception:
        db.execute("ROLLBACK TO process_price_v062")
        db.execute("RELEASE process_price_v062")
        raise
    db.execute("RELEASE process_price_v062")


PROTECTED_PROCESS_FACT_TABLES = (
    "payroll_detail_lines",
    "performance_quality_events",
    "performance_source_facts",
)


def _fact_binding_columns(spec):
    columns = {
        "route_id",
        "route_version_id",
        "route_name_snapshot",
        "version_binding_source",
    }
    for role in spec["roles"]:
        columns.update(
            {
                f"{role}_version_id",
                f"{role}_code_snapshot",
                f"{role}_name_snapshot",
                f"{role}_category_snapshot",
            }
        )
    return columns


def _fact_business_fingerprints(db):
    fingerprints = {}
    for spec in PROCESS_FACT_BINDINGS:
        table = spec["table"]
        excluded = _fact_binding_columns(spec)
        columns = tuple(
            row[1]
            for row in db.execute(f"PRAGMA table_info({table})").fetchall()
            if row[1] not in excluded
        )
        digest = hashlib.sha256()
        count = 0
        quoted = ",".join(f'"{column}"' for column in columns)
        for row in db.execute(f'SELECT {quoted} FROM "{table}" ORDER BY id'):
            digest.update(repr(tuple(row)).encode("utf-8"))
            digest.update(b"\n")
            count += 1
        fingerprints[table] = (columns, count, digest.hexdigest())
    return fingerprints


def _version_binding_context(db):
    process_versions = {
        row["id"]: row
        for row in db.execute(
            "SELECT id,process_id,version,process_code_snapshot,name,category "
            "FROM process_versions"
        ).fetchall()
    }
    process_v1 = {
        row["process_id"]: row
        for row in process_versions.values()
        if row["version"] == 1
    }
    route_versions = {
        row["id"]: row
        for row in db.execute(
            "SELECT id,process_route_id,version,name FROM process_route_versions"
        ).fetchall()
    }
    route_v1 = {
        row["process_route_id"]: row
        for row in route_versions.values()
        if row["version"] == 1
    }
    orders = {
        row["id"]: (row["route_id"], row["route_version_id"])
        for row in db.execute(
            "SELECT id,route_id,route_version_id FROM orders"
        ).fetchall()
    }
    return {
        "process_versions": process_versions,
        "process_v1": process_v1,
        "route_versions": route_versions,
        "route_v1": route_v1,
        "orders": orders,
        "work_records": _load_work_route_bindings(db, orders, route_v1),
    }


def _load_work_route_bindings(db, orders, route_v1):
    bindings = {}
    columns = {row[1] for row in db.execute("PRAGMA table_info(work_records)")}
    route_select = "route_id" if "route_id" in columns else "NULL"
    version_select = (
        "route_version_id" if "route_version_id" in columns else "NULL"
    )
    for row in db.execute(
        f"SELECT id,order_id,{route_select} AS route_id,"
        f"{version_select} AS route_version_id FROM work_records"
    ).fetchall():
        order_route = orders.get(row["order_id"], (None, None))
        route_id = row["route_id"] or order_route[0]
        route_version_id = row["route_version_id"] or order_route[1]
        if route_id is not None and route_version_id is None:
            v1 = route_v1.get(route_id)
            route_version_id = v1["id"] if v1 is not None else None
        bindings[row["id"]] = (route_id, route_version_id)
    return bindings


def _resolve_fact_route(row, spec, context):
    route_id = row.get("route_id")
    route_version_id = row.get("route_version_id")
    for source_column in spec["work_sources"]:
        source_id = row.get(source_column)
        source_route = context["work_records"].get(source_id)
        if source_route is None:
            continue
        route_id = route_id or source_route[0]
        route_version_id = route_version_id or source_route[1]
        if route_id is not None and route_version_id is not None:
            break
    order_route = context["orders"].get(row.get("order_id"))
    if order_route is not None:
        route_id = route_id or order_route[0]
        route_version_id = route_version_id or order_route[1]
    if route_version_id is not None and route_id is None:
        version = context["route_versions"].get(route_version_id)
        route_id = version["process_route_id"] if version is not None else None
    if route_id is not None and route_version_id is None:
        v1 = context["route_v1"].get(route_id)
        route_version_id = v1["id"] if v1 is not None else None
    return route_id, route_version_id


def _append_fact_binding_issue(issues, table, role, legacy_id, reason_code, **summary):
    issues.append(
        {
            "entity_type": f"{table}.{role}",
            "legacy_id": legacy_id,
            "reason_code": reason_code,
            "summary": summary,
        }
    )


def _collect_fact_binding_issues(db):
    issues = []
    required = (
        ("process_versions", ("id", "process_id", "version")),
        ("process_route_versions", ("id", "process_route_id", "version")),
        ("orders", ("id", "route_id", "route_version_id")),
        ("work_records", ("id", "order_id")),
    )
    if not all(
        _required_columns(db, table, columns, issues)
        for table, columns in required
    ):
        return issues
    for spec in PROCESS_FACT_BINDINGS:
        required_columns = ["id"]
        required_columns.extend(f"{role}_id" for role in spec["roles"])
        required_columns.extend(spec["work_sources"])
        if not _required_columns(db, spec["table"], required_columns, issues):
            return issues

    context = _version_binding_context(db)
    for spec in PROCESS_FACT_BINDINGS:
        table = spec["table"]
        rows = [dict(row) for row in db.execute(f'SELECT * FROM "{table}"')]
        table_columns = set(rows[0]) if rows else {
            row[1] for row in db.execute(f"PRAGMA table_info({table})")
        }
        for row in rows:
            for role in spec["roles"]:
                root_id = row.get(f"{role}_id")
                version_column = f"{role}_version_id"
                version_id = row.get(version_column) if version_column in table_columns else None
                if root_id is None and version_id is not None:
                    _append_fact_binding_issue(
                        issues,
                        table,
                        role,
                        row["id"],
                        "process_version_without_root",
                        process_version_id=version_id,
                    )
                    continue
                if root_id is None:
                    continue
                if version_id is None:
                    if root_id not in context["process_v1"]:
                        _append_fact_binding_issue(
                            issues,
                            table,
                            role,
                            row["id"],
                            "missing_process_v1",
                            process_id=root_id,
                        )
                    continue
                version = context["process_versions"].get(version_id)
                if version is None or version["process_id"] != root_id:
                    _append_fact_binding_issue(
                        issues,
                        table,
                        role,
                        row["id"],
                        "invalid_exact_process_version",
                        process_id=root_id,
                        process_version_id=version_id,
                    )

            route_id, route_version_id = _resolve_fact_route(row, spec, context)
            if route_id is None and route_version_id is None:
                continue
            if route_id is None:
                _append_fact_binding_issue(
                    issues,
                    table,
                    "route",
                    row["id"],
                    "route_version_without_root",
                    route_version_id=route_version_id,
                )
                continue
            if route_version_id is None:
                _append_fact_binding_issue(
                    issues,
                    table,
                    "route",
                    row["id"],
                    "missing_route_v1",
                    route_id=route_id,
                )
                continue
            route_version = context["route_versions"].get(route_version_id)
            if (
                route_version is None
                or route_version["process_route_id"] != route_id
            ):
                _append_fact_binding_issue(
                    issues,
                    table,
                    "route",
                    row["id"],
                    "invalid_exact_route_version",
                    route_id=route_id,
                    route_version_id=route_version_id,
                )
    return issues


def _record_fact_binding_issues(db, issues):
    for issue in issues:
        db.execute(
            "INSERT OR IGNORE INTO process_version_migration_exceptions "
            "(migration_key,entity_type,legacy_id,reason_code,blocking,source_summary_json) "
            "VALUES (?,?,?,?,1,?)",
            (
                PROCESS_FACT_MIGRATION_KEY,
                issue["entity_type"],
                issue["legacy_id"],
                issue["reason_code"],
                json.dumps(issue["summary"], ensure_ascii=False, sort_keys=True),
            ),
        )


def _add_fact_binding_columns(db):
    for spec in PROCESS_FACT_BINDINGS:
        table = spec["table"]
        for role in spec["roles"]:
            add_column_if_missing(
                db,
                table,
                f"{role}_version_id",
                "INTEGER REFERENCES process_versions(id) ON DELETE RESTRICT",
            )
            add_column_if_missing(
                db,
                table,
                f"{role}_code_snapshot",
                "TEXT NOT NULL DEFAULT ''",
            )
            add_column_if_missing(
                db,
                table,
                f"{role}_name_snapshot",
                "TEXT NOT NULL DEFAULT ''",
            )
            add_column_if_missing(
                db,
                table,
                f"{role}_category_snapshot",
                "TEXT NOT NULL DEFAULT ''",
            )
        add_column_if_missing(
            db,
            table,
            "route_id",
            "INTEGER REFERENCES process_routes(id) ON DELETE RESTRICT",
        )
        add_column_if_missing(
            db,
            table,
            "route_version_id",
            "INTEGER REFERENCES process_route_versions(id) ON DELETE RESTRICT",
        )
        add_column_if_missing(
            db,
            table,
            "route_name_snapshot",
            "TEXT NOT NULL DEFAULT ''",
        )
        add_column_if_missing(
            db,
            table,
            "version_binding_source",
            "TEXT NOT NULL DEFAULT '' "
            "CHECK(version_binding_source IN ('','legacy_v1','captured'))",
        )


def _saved_fact_mutation_triggers(db):
    placeholders = ",".join("?" for _ in PROTECTED_PROCESS_FACT_TABLES)
    return [
        (row["name"], row["sql"])
        for row in db.execute(
            "SELECT name,sql FROM sqlite_master WHERE type='trigger' "
            f"AND tbl_name IN ({placeholders}) ORDER BY name",
            PROTECTED_PROCESS_FACT_TABLES,
        ).fetchall()
        if row["sql"]
    ]


def _drop_saved_triggers(db, triggers):
    for name, _ in triggers:
        quoted_name = name.replace('"', '""')
        db.execute(f'DROP TRIGGER "{quoted_name}"')


def _restore_saved_triggers(db, triggers):
    for _, sql in triggers:
        db.execute(sql)


def _backfill_fact_bindings(db):
    context = _version_binding_context(db)
    for spec in PROCESS_FACT_BINDINGS:
        table = spec["table"]
        for source_row in db.execute(f'SELECT * FROM "{table}" ORDER BY id').fetchall():
            row = dict(source_row)
            updates = {}
            had_exact_binding = any(
                row.get(f"{role}_version_id") is not None
                for role in spec["roles"]
            ) or row.get("route_version_id") is not None
            has_binding = False
            for role in spec["roles"]:
                root_id = row.get(f"{role}_id")
                if root_id is None:
                    continue
                has_binding = True
                version_id = row.get(f"{role}_version_id")
                version = context["process_versions"].get(version_id)
                if version is None:
                    version = context["process_v1"][root_id]
                    updates[f"{role}_version_id"] = version["id"]
                snapshot_values = {
                    f"{role}_code_snapshot": version["process_code_snapshot"],
                    f"{role}_name_snapshot": version["name"],
                    f"{role}_category_snapshot": version["category"],
                }
                for column, value in snapshot_values.items():
                    if not row.get(column):
                        updates[column] = value or ""

            route_id, route_version_id = _resolve_fact_route(row, spec, context)
            if route_id is not None:
                has_binding = True
                if row.get("route_id") is None:
                    updates["route_id"] = route_id
                if row.get("route_version_id") is None:
                    updates["route_version_id"] = route_version_id
                route_version = context["route_versions"][route_version_id]
                if not row.get("route_name_snapshot"):
                    updates["route_name_snapshot"] = route_version["name"] or ""
            if has_binding and not row.get("version_binding_source"):
                updates["version_binding_source"] = (
                    "captured" if had_exact_binding else "legacy_v1"
                )
            if updates:
                assignments = ",".join(f'"{column}"=?' for column in updates)
                db.execute(
                    f'UPDATE "{table}" SET {assignments} WHERE id=?',
                    (*updates.values(), row["id"]),
                )
        if table == "work_records":
            context["work_records"] = _load_work_route_bindings(
                db, context["orders"], context["route_v1"]
            )


def _create_fact_binding_indexes(db):
    for spec in PROCESS_FACT_BINDINGS:
        table = spec["table"]
        key = spec["index_key"]
        for role in spec["roles"]:
            db.execute(
                f"CREATE INDEX IF NOT EXISTS idx_v63_{key}_{role}_version "
                f'ON "{table}"("{role}_version_id")'
            )
        db.execute(
            f"CREATE INDEX IF NOT EXISTS idx_v63_{key}_route_version "
            f'ON "{table}"(route_version_id)'
        )
        if column_exists(db, table, "order_id"):
            db.execute(
                f"CREATE INDEX IF NOT EXISTS idx_v63_{key}_order_route "
                f'ON "{table}"(order_id,route_version_id)'
            )
        user_column = spec["user_column"]
        time_column = spec["time_column"]
        if user_column and column_exists(db, table, user_column):
            db.execute(
                f"CREATE INDEX IF NOT EXISTS idx_v63_{key}_user_time "
                f'ON "{table}"("{user_column}","{time_column}")'
            )
        elif time_column and column_exists(db, table, time_column):
            db.execute(
                f"CREATE INDEX IF NOT EXISTS idx_v63_{key}_time "
                f'ON "{table}"("{time_column}")'
            )


def _validate_fact_bindings(db, before, saved_triggers):
    after = _fact_business_fingerprints(db)
    if after != before:
        changed = sorted(
            table for table in before if before[table] != after.get(table)
        )
        raise MigrationInvariantError(
            "Migration v63 changed protected business facts: " + ", ".join(changed)
        )
    issues = _collect_fact_binding_issues(db)
    if issues:
        issue = issues[0]
        raise MigrationInvariantError(
            "Migration v63 left an invalid fact binding at "
            f"{issue['entity_type']}:{issue['legacy_id']}:{issue['reason_code']}"
        )
    for spec in PROCESS_FACT_BINDINGS:
        table = spec["table"]
        binding_predicates = [
            f'"{role}_id" IS NOT NULL' for role in spec["roles"]
        ]
        binding_predicates.append("route_id IS NOT NULL")
        invalid_source = db.execute(
            f'SELECT id FROM "{table}" WHERE ('
            + " OR ".join(binding_predicates)
            + ") AND version_binding_source NOT IN ('legacy_v1','captured') LIMIT 1"
        ).fetchone()
        if invalid_source is not None:
            raise MigrationInvariantError(
                f"Migration v63 left {table}:{invalid_source[0]} without a binding source"
            )
        for role in spec["roles"]:
            incomplete = db.execute(
                f'SELECT id FROM "{table}" WHERE "{role}_id" IS NOT NULL AND ('
                f'"{role}_version_id" IS NULL OR COALESCE("{role}_code_snapshot",\'\')=\'\' '
                f'OR COALESCE("{role}_name_snapshot",\'\')=\'\') LIMIT 1'
            ).fetchone()
            if incomplete is not None:
                raise MigrationInvariantError(
                    f"Migration v63 left incomplete {table}.{role} snapshot "
                    f"at legacy id {incomplete[0]}"
                )
    restored = _saved_fact_mutation_triggers(db)
    if restored != saved_triggers:
        raise MigrationInvariantError(
            "Migration v63 failed to restore immutable payroll/performance guards"
        )


def m063_version_process_facts(db):
    """Bind process-bearing business facts to immutable master-data versions."""
    _create_exception_table(db)
    issues = _collect_fact_binding_issues(db)
    if issues:
        _record_fact_binding_issues(db, issues)
        db.commit()
        sample = ", ".join(
            f"{issue['entity_type']}:{issue['legacy_id']}:{issue['reason_code']}"
            for issue in issues[:5]
        )
        raise MigrationInvariantError(
            f"Migration v63 blocked by {len(issues)} fact binding exception(s): {sample}"
        )

    before = _fact_business_fingerprints(db)
    saved_triggers = _saved_fact_mutation_triggers(db)
    db.execute("SAVEPOINT process_facts_v063")
    try:
        _drop_saved_triggers(db, saved_triggers)
        _add_fact_binding_columns(db)
        _backfill_fact_bindings(db)
        _create_fact_binding_indexes(db)
        _restore_saved_triggers(db, saved_triggers)
        from modules.migration_process_management import (
            rebuild_master_data_reference_guards,
        )

        rebuild_master_data_reference_guards(db)
        _validate_fact_bindings(db, before, saved_triggers)
    except Exception:
        db.execute("ROLLBACK TO process_facts_v063")
        db.execute("RELEASE process_facts_v063")
        raise
    db.execute("RELEASE process_facts_v063")


MIGRATIONS = [
    (60, "Add versioned process and route master-data baseline", m060_process_master_versioning),
    (61, "Bind orders to process and route versions", m061_bind_order_versions),
    (62, "Bind payroll prices to route and process versions", m062_bind_price_versions),
    (63, "Version process and route references across business facts", m063_version_process_facts),
]
