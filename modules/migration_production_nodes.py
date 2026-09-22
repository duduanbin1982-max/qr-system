"""V086-V087 production-node master data and exact legacy fact mappings."""

import hashlib
import json

from modules.migration_helpers import add_column_if_missing


APPROVED_PRODUCTION_NODE_COUNTS = {
    "下料": 1,
    "铆接": 4,
    "焊接": 10,
    "抛丸": 1,
    "打磨": 1,
    "镗孔": 2,
    "喷漆": 2,
}


def _format_distribution(distribution):
    ordered_names = list(APPROVED_PRODUCTION_NODE_COUNTS)
    ordered_names.extend(
        sorted(name for name in distribution if name not in APPROVED_PRODUCTION_NODE_COUNTS)
    )
    return "{" + ", ".join(
        f"{name}:{distribution.get(name, 0)}" for name in ordered_names
    ) + "}"


def _validate_legacy_node_baseline(db):
    """Reject an incomplete V085 source before creating any V086 object."""
    missing_calendar_rows = db.execute(
        "SELECT id FROM process_production_lines "
        "WHERE calendar_id IS NULL ORDER BY id"
    ).fetchall()
    if missing_calendar_rows:
        legacy_ids = ",".join(str(row[0]) for row in missing_calendar_rows)
        raise RuntimeError(
            "V086 production-node baseline invalid: NULL calendar_id for "
            f"legacy ids [{legacy_ids}]; every process_production_lines row must map"
        )

    total = db.execute(
        "SELECT COUNT(*) FROM process_production_lines"
    ).fetchone()[0]
    distribution = {
        row[0]: row[1]
        for row in db.execute(
            "SELECT COALESCE(p.name,'<missing process_id=' || pl.process_id || '>'),"
            "COUNT(pl.id) "
            "FROM process_production_lines pl "
            "LEFT JOIN processes p ON p.id=pl.process_id "
            "GROUP BY pl.process_id,p.name ORDER BY p.name,pl.process_id"
        ).fetchall()
    }
    expected_total = sum(APPROVED_PRODUCTION_NODE_COUNTS.values())
    if total != expected_total or distribution != APPROVED_PRODUCTION_NODE_COUNTS:
        raise RuntimeError(
            "V086 production-node baseline invalid: "
            f"expected total={expected_total} distribution="
            f"{_format_distribution(APPROVED_PRODUCTION_NODE_COUNTS)}; "
            f"actual total={total} distribution={_format_distribution(distribution)}"
        )


def _validate_legacy_node_mapping(db):
    unmapped = [
        row[0]
        for row in db.execute(
            "SELECT pl.id FROM process_production_lines pl "
            "LEFT JOIN production_nodes n ON n.legacy_process_line_id=pl.id "
            "WHERE n.id IS NULL ORDER BY pl.id"
        ).fetchall()
    ]
    mismatched = [
        row[0]
        for row in db.execute(
            "SELECT pl.id FROM process_production_lines pl "
            "JOIN production_nodes n ON n.legacy_process_line_id=pl.id "
            "WHERE n.process_id<>pl.process_id OR n.node_code<>pl.line_code "
            "OR n.node_name<>pl.line_name OR n.status<>pl.status "
            "OR n.calendar_id<>pl.calendar_id ORDER BY pl.id"
        ).fetchall()
    ]
    if unmapped or mismatched:
        raise RuntimeError(
            "V086 production-node mapping incomplete: "
            f"unmapped legacy ids={unmapped}; mismatched legacy ids={mismatched}"
        )


def m086_production_node_master(db):
    """Add stable physical-capacity nodes without changing legacy scheduling."""
    _validate_legacy_node_baseline(db)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS production_nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            process_id INTEGER NOT NULL,
            node_code TEXT NOT NULL,
            node_name TEXT NOT NULL,
            capacity_mode TEXT NOT NULL DEFAULT 'exclusive'
                CHECK(capacity_mode IN ('exclusive','batch')),
            status TEXT NOT NULL DEFAULT 'active'
                CHECK(status IN ('active','inactive','maintenance')),
            calendar_id INTEGER NOT NULL,
            legacy_process_line_id INTEGER UNIQUE,
            row_version INTEGER NOT NULL DEFAULT 1 CHECK(row_version > 0),
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(process_id,node_code),
            FOREIGN KEY(process_id) REFERENCES processes(id) ON DELETE RESTRICT,
            FOREIGN KEY(calendar_id) REFERENCES schedule_calendars(id) ON DELETE RESTRICT,
            FOREIGN KEY(legacy_process_line_id) REFERENCES process_production_lines(id) ON DELETE RESTRICT
        );

        CREATE TABLE IF NOT EXISTS production_node_capabilities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            production_node_id INTEGER NOT NULL,
            product_id INTEGER,
            product_family TEXT NOT NULL DEFAULT '',
            material_code TEXT NOT NULL DEFAULT '',
            specification TEXT NOT NULL DEFAULT '',
            route_version_id INTEGER,
            process_version_id INTEGER,
            max_batch_quantity INTEGER CHECK(max_batch_quantity IS NULL OR max_batch_quantity > 0),
            batch_minutes REAL CHECK(batch_minutes IS NULL OR batch_minutes > 0),
            changeover_minutes REAL NOT NULL DEFAULT 0 CHECK(changeover_minutes >= 0),
            allow_mixed_orders INTEGER NOT NULL DEFAULT 0 CHECK(allow_mixed_orders IN (0,1)),
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','inactive')),
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(production_node_id) REFERENCES production_nodes(id) ON DELETE RESTRICT,
            FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE RESTRICT,
            FOREIGN KEY(route_version_id) REFERENCES process_route_versions(id) ON DELETE RESTRICT,
            FOREIGN KEY(process_version_id) REFERENCES process_versions(id) ON DELETE RESTRICT
        );

        CREATE TABLE IF NOT EXISTS production_node_calendar_overrides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            production_node_id INTEGER NOT NULL,
            start_at TEXT NOT NULL,
            end_at TEXT NOT NULL,
            override_type TEXT NOT NULL CHECK(override_type IN ('unavailable','maintenance','overtime','holiday')),
            reason TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','cancelled','completed')),
            created_by INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            CHECK(end_at > start_at),
            FOREIGN KEY(production_node_id) REFERENCES production_nodes(id) ON DELETE RESTRICT,
            FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS production_node_audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            production_node_id INTEGER,
            event_type TEXT NOT NULL,
            actor_id INTEGER,
            reason TEXT NOT NULL DEFAULT '',
            before_json TEXT NOT NULL DEFAULT '{}',
            after_json TEXT NOT NULL DEFAULT '{}',
            idempotency_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(production_node_id) REFERENCES production_nodes(id) ON DELETE RESTRICT,
            FOREIGN KEY(actor_id) REFERENCES users(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_production_nodes_process_status
            ON production_nodes(process_id,status);
        CREATE INDEX IF NOT EXISTS idx_production_node_capabilities_lookup
            ON production_node_capabilities(
                production_node_id,status,product_id,product_family,material_code,specification
            );
        CREATE INDEX IF NOT EXISTS idx_production_node_overrides_time
            ON production_node_calendar_overrides(production_node_id,start_at,end_at,status);
        CREATE INDEX IF NOT EXISTS idx_production_node_audit_node_time
            ON production_node_audit_events(production_node_id,created_at);

        CREATE TRIGGER IF NOT EXISTS trg_production_node_audit_immutable_update
        BEFORE UPDATE ON production_node_audit_events
        BEGIN
            SELECT RAISE(ABORT, 'production node audit events are immutable');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_production_node_audit_immutable_delete
        BEFORE DELETE ON production_node_audit_events
        BEGIN
            SELECT RAISE(ABORT, 'production node audit events are immutable');
        END;
        """
    )
    db.execute(
        "INSERT OR IGNORE INTO production_nodes "
        "(process_id,node_code,node_name,capacity_mode,status,calendar_id,legacy_process_line_id) "
        "SELECT process_id,line_code,line_name,'exclusive',status,calendar_id,id "
        "FROM process_production_lines"
    )
    _validate_legacy_node_mapping(db)


NODE_FACT_COLUMNS = {
    "production_node_id": (
        "INTEGER REFERENCES production_nodes(id) ON DELETE RESTRICT"
    ),
    "node_code_snapshot": "TEXT NOT NULL DEFAULT ''",
    "node_name_snapshot": "TEXT NOT NULL DEFAULT ''",
    "capacity_mode_snapshot": "TEXT NOT NULL DEFAULT ''",
    "node_calendar_snapshot_json": "TEXT NOT NULL DEFAULT '{}'",
    "node_capability_snapshot_json": "TEXT NOT NULL DEFAULT '[]'",
    "locked": "INTEGER NOT NULL DEFAULT 0 CHECK(locked IN (0,1))",
    "lock_reason": "TEXT NOT NULL DEFAULT ''",
    "blocked_code": "TEXT NOT NULL DEFAULT ''",
}


def _fetch_dicts(db, sql, params=()):
    cursor = db.execute(sql, params)
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _compact_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _calendar_snapshot(db, calendar_id):
    calendars = _fetch_dicts(
        db,
        "SELECT id AS calendar_id,calendar_code,calendar_name,timezone,"
        "weekly_workdays,status FROM schedule_calendars WHERE id=?",
        (calendar_id,),
    )
    if not calendars:
        raise RuntimeError(
            f"V087 production-node calendar missing: calendar_id={calendar_id}"
        )
    calendar = calendars[0]
    calendar["shifts"] = _fetch_dicts(
        db,
        "SELECT id AS shift_id,shift_code,shift_name,start_minute,end_minute,status "
        "FROM schedule_shifts WHERE calendar_id=? ORDER BY start_minute,end_minute,id",
        (calendar_id,),
    )
    calendar["exceptions"] = _fetch_dicts(
        db,
        "SELECT id AS exception_id,work_date,is_working_day,shift_ids,note "
        "FROM schedule_calendar_exceptions WHERE calendar_id=? ORDER BY work_date,id",
        (calendar_id,),
    )
    return _compact_json(calendar)


def _capability_snapshot(db, production_node_id):
    capabilities = _fetch_dicts(
        db,
        "SELECT id AS capability_id,product_id,product_family,material_code,"
        "specification,route_version_id,process_version_id,max_batch_quantity,"
        "batch_minutes,changeover_minutes,allow_mixed_orders,status "
        "FROM production_node_capabilities WHERE production_node_id=? ORDER BY id",
        (production_node_id,),
    )
    return _compact_json(capabilities)


def _node_snapshot(db, production_node_id, cache):
    if production_node_id not in cache:
        nodes = _fetch_dicts(
            db,
            "SELECT id,node_code,node_name,capacity_mode,calendar_id "
            "FROM production_nodes WHERE id=?",
            (production_node_id,),
        )
        if not nodes:
            raise RuntimeError(
                "V087 production-node mapping disappeared during backfill: "
                f"node_id={production_node_id}"
            )
        node = nodes[0]
        cache[production_node_id] = (
            node["id"],
            node["node_code"],
            node["node_name"],
            node["capacity_mode"],
            _calendar_snapshot(db, node["calendar_id"]),
            _capability_snapshot(db, node["id"]),
        )
    return cache[production_node_id]


def _record_mapping_difference(
    db,
    *,
    source_table,
    source_id,
    legacy_process_line_id,
    difference_code,
):
    detail_json = _compact_json(
        {
            "mapping_key": "production_nodes.legacy_process_line_id",
            "legacy_process_line_id": legacy_process_line_id,
            "reason": difference_code,
        }
    )
    db.execute(
        "INSERT OR IGNORE INTO production_node_migration_differences "
        "(source_table,source_id,legacy_process_line_id,difference_code,detail_json) "
        "VALUES (?,?,?,?,?)",
        (
            source_table,
            source_id,
            legacy_process_line_id,
            difference_code,
            detail_json,
        ),
    )


def _backfill_node_snapshots(db, table, snapshot_cache):
    rows = _fetch_dicts(
        db,
        f"SELECT f.id AS source_id,f.process_line_id AS legacy_process_line_id,"
        "f.execution_mode,f.status,n.id AS production_node_id "
        f"FROM {table} f LEFT JOIN production_nodes n "
        "ON n.legacy_process_line_id=f.process_line_id "
        "WHERE f.production_node_id IS NULL ORDER BY f.id",
    )
    for row in rows:
        if row["production_node_id"] is None:
            if (
                row["legacy_process_line_id"] is None
                and row["execution_mode"] in ("outsourced", "non_scheduled")
            ):
                continue
            if (
                row["legacy_process_line_id"] is None
                and row["status"] == "blocked"
            ):
                # A blocked schedule is evidence that no resource was assigned;
                # choosing one of several same-process nodes would invent a
                # historical production fact.  Preserve the NULL assignment and
                # retain a non-blocking audit difference instead.
                _record_mapping_difference(
                    db,
                    source_table=table,
                    source_id=row["source_id"],
                    legacy_process_line_id=None,
                    difference_code="intentionally_unassigned_blocked",
                )
                continue
            _record_mapping_difference(
                db,
                source_table=table,
                source_id=row["source_id"],
                legacy_process_line_id=row["legacy_process_line_id"],
                difference_code=(
                    "missing_legacy_reference"
                    if row["legacy_process_line_id"] is None
                    else "missing_mapping"
                ),
            )
            continue
        snapshot = _node_snapshot(db, row["production_node_id"], snapshot_cache)
        db.execute(
            f"UPDATE {table} SET production_node_id=?,node_code_snapshot=?,"
            "node_name_snapshot=?,capacity_mode_snapshot=?,"
            "node_calendar_snapshot_json=?,node_capability_snapshot_json=? "
            "WHERE id=? AND production_node_id IS NULL",
            (*snapshot, row["source_id"]),
        )


def _backfill_node_references(db, table):
    rows = _fetch_dicts(
        db,
        f"SELECT f.id AS source_id,f.process_line_id AS legacy_process_line_id,"
        "n.id AS production_node_id "
        f"FROM {table} f LEFT JOIN production_nodes n "
        "ON n.legacy_process_line_id=f.process_line_id "
        "WHERE f.production_node_id IS NULL ORDER BY f.id",
    )
    for row in rows:
        if row["production_node_id"] is None:
            _record_mapping_difference(
                db,
                source_table=table,
                source_id=row["source_id"],
                legacy_process_line_id=row["legacy_process_line_id"],
                difference_code=(
                    "missing_legacy_reference"
                    if row["legacy_process_line_id"] is None
                    else "missing_mapping"
                ),
            )
            continue
        db.execute(
            f"UPDATE {table} SET production_node_id=? "
            "WHERE id=? AND production_node_id IS NULL",
            (row["production_node_id"], row["source_id"]),
        )


def _create_revision_item_immutability_trigger(db):
    immutable_columns = [
        row[1]
        for row in db.execute("PRAGMA table_info(schedule_revision_items)")
    ]
    update_columns = ",".join(f'"{column}"' for column in immutable_columns)
    db.execute(
        "CREATE TRIGGER protect_schedule_revision_items_update "
        f"BEFORE UPDATE OF {update_columns} ON schedule_revision_items "
        "BEGIN SELECT RAISE(ABORT,'schedule revision items are immutable'); END"
    )


def m087_production_node_schedule_facts(db):
    """Add node facts and backfill only through the stable V086 legacy key."""
    # Python's sqlite3 legacy transaction control does not start a transaction
    # for DDL.  Begin before the first ALTER/CREATE so the outer migration
    # runner can roll every V087 schema and data change back atomically.  When
    # a caller already owns a transaction, preserve that boundary and never
    # commit it here.
    if not db.in_transaction:
        db.execute("BEGIN")

    for table in ("order_process_schedules", "schedule_revision_items"):
        for column, definition in NODE_FACT_COLUMNS.items():
            add_column_if_missing(db, table, column, definition)
    for table in ("order_process_schedule_segments", "schedule_downtime_events"):
        add_column_if_missing(
            db,
            table,
            "production_node_id",
            "INTEGER REFERENCES production_nodes(id) ON DELETE RESTRICT",
        )

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS production_node_migration_differences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_table TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            legacy_process_line_id INTEGER,
            difference_code TEXT NOT NULL,
            detail_json TEXT NOT NULL DEFAULT '{}',
            observed_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(source_table,source_id,difference_code)
        )
        """
    )
    # Keep each DDL statement inside the V087 transaction. sqlite3.executescript
    # commits an open transaction before running, which would make a later
    # backfill/trigger failure leave a partially migrated schema behind.
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS production_node_compatibility_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            observation_key TEXT NOT NULL UNIQUE,
            scope TEXT NOT NULL,
            source_id INTEGER,
            legacy_digest TEXT NOT NULL,
            node_digest TEXT NOT NULL,
            mismatch INTEGER NOT NULL CHECK(mismatch IN (0,1)),
            difference_json TEXT NOT NULL DEFAULT '{}',
            observed_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_node_compat_observations_scope_time "
        "ON production_node_compatibility_observations(scope,source_id,observed_at,id)"
    )
    db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS protect_node_compat_observations_update
        BEFORE UPDATE ON production_node_compatibility_observations
        BEGIN
            SELECT RAISE(ABORT,'production node compatibility observations are immutable');
        END
        """
    )
    db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS protect_node_compat_observations_delete
        BEFORE DELETE ON production_node_compatibility_observations
        BEGIN
            SELECT RAISE(ABORT,'production node compatibility observations are immutable');
        END
        """
    )

    snapshot_cache = {}
    _backfill_node_snapshots(db, "order_process_schedules", snapshot_cache)
    _backfill_node_references(db, "order_process_schedule_segments")

    db.execute("DROP TRIGGER IF EXISTS protect_schedule_revision_items_update")
    try:
        _backfill_node_snapshots(db, "schedule_revision_items", snapshot_cache)
    finally:
        _create_revision_item_immutability_trigger(db)

    _backfill_node_references(db, "schedule_downtime_events")

    for statement in (
        "CREATE INDEX IF NOT EXISTS idx_schedule_facts_node_time "
        "ON order_process_schedules("
        "production_node_id,planned_start_at,planned_end_at)",
        "CREATE INDEX IF NOT EXISTS idx_schedule_segments_node_time "
        "ON order_process_schedule_segments("
        "production_node_id,segment_start_at,segment_end_at)",
        "CREATE INDEX IF NOT EXISTS idx_schedule_revision_items_node "
        "ON schedule_revision_items(production_node_id,revision_id,id)",
        "CREATE INDEX IF NOT EXISTS idx_schedule_downtime_node_time "
        "ON schedule_downtime_events(production_node_id,start_at,end_at,status)",
    ):
        db.execute(statement)


def m088_batch_serial_allocations(db):
    """Persist exact batch and serial allocation facts for node schedules."""
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS production_node_schedule_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER NOT NULL,
            segment_id INTEGER,
            production_node_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL CHECK(quantity > 0),
            serial_id TEXT,
            batch_key TEXT NOT NULL DEFAULT '',
            changeover_minutes REAL NOT NULL DEFAULT 0 CHECK(changeover_minutes >= 0),
            allocation_start_at TEXT,
            allocation_end_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(schedule_id) REFERENCES order_process_schedules(id) ON DELETE CASCADE,
            FOREIGN KEY(segment_id) REFERENCES order_process_schedule_segments(id) ON DELETE CASCADE,
            FOREIGN KEY(production_node_id) REFERENCES production_nodes(id) ON DELETE RESTRICT
        )
        """
    )
    db.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS uq_node_allocation_serial_operation
        ON production_node_schedule_allocations(schedule_id, serial_id)
        WHERE serial_id IS NOT NULL AND serial_id <> ''"""
    )
    db.execute(
        """CREATE INDEX IF NOT EXISTS idx_node_allocations_schedule
        ON production_node_schedule_allocations(schedule_id, id)"""
    )
    db.execute(
        """CREATE INDEX IF NOT EXISTS idx_node_allocations_node_time
        ON production_node_schedule_allocations(
            production_node_id, allocation_start_at, allocation_end_at
        )"""
    )


def m089_schedule_revision_workflow(db):
    """Add approval, lock and immutable workflow facts for node schedules."""
    # Keep lifecycle (draft/published/superseded/cancelled) independent from
    # approval state. Existing published revisions are already approved facts.
    for column, definition in {
        "approval_status": "TEXT NOT NULL DEFAULT 'draft' CHECK(approval_status IN ('draft','submitted','approved','rejected'))",
        "submitted_by": "INTEGER REFERENCES users(id) ON DELETE SET NULL",
        "submitted_at": "TEXT NOT NULL DEFAULT ''",
        "submitted_reason": "TEXT NOT NULL DEFAULT ''",
        "approved_by": "INTEGER REFERENCES users(id) ON DELETE SET NULL",
        "approved_at": "TEXT NOT NULL DEFAULT ''",
        "approved_reason": "TEXT NOT NULL DEFAULT ''",
        "rejected_by": "INTEGER REFERENCES users(id) ON DELETE SET NULL",
        "rejected_at": "TEXT NOT NULL DEFAULT ''",
        "rejected_reason": "TEXT NOT NULL DEFAULT ''",
    }.items():
        add_column_if_missing(db, "schedule_revisions", column, definition)
    add_column_if_missing(
        db, "schedule_revision_items", "row_version",
        "INTEGER NOT NULL DEFAULT 1 CHECK(row_version > 0)",
    )
    # V087 created the immutable-item trigger from the columns that existed at
    # that time. Rebuild it after adding row_version so optimistic-lock facts
    # cannot be changed in place on an existing revision item either.
    db.execute("DROP TRIGGER IF EXISTS protect_schedule_revision_items_update")
    _create_revision_item_immutability_trigger(db)
    db.execute(
        "UPDATE schedule_revisions SET approval_status='approved' "
        "WHERE status='published' AND approval_status='draft'"
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS schedule_node_task_locks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            revision_item_id INTEGER NOT NULL,
            production_node_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','released')),
            locked_by INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            released_by INTEGER REFERENCES users(id) ON DELETE RESTRICT,
            released_at TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL,
            release_reason TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(revision_item_id) REFERENCES schedule_revision_items(id) ON DELETE RESTRICT,
            FOREIGN KEY(production_node_id) REFERENCES production_nodes(id) ON DELETE RESTRICT
        )"""
    )
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_schedule_node_task_active_lock "
        "ON schedule_node_task_locks(revision_item_id) WHERE status='active'"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_schedule_node_task_locks_node_time "
        "ON schedule_node_task_locks(production_node_id,status,created_at)"
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS schedule_node_workflow_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            revision_id INTEGER NOT NULL,
            revision_item_id INTEGER,
            event_type TEXT NOT NULL CHECK(event_type IN ('adjust','lock','unlock','submit','approve','reject','supersede')),
            actor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            reason TEXT NOT NULL,
            before_json TEXT NOT NULL DEFAULT '{}',
            after_json TEXT NOT NULL DEFAULT '{}',
            input_digest TEXT NOT NULL DEFAULT '',
            idempotency_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(revision_id) REFERENCES schedule_revisions(id) ON DELETE RESTRICT,
            FOREIGN KEY(revision_item_id) REFERENCES schedule_revision_items(id) ON DELETE RESTRICT
        )"""
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_schedule_node_workflow_events_revision "
        "ON schedule_node_workflow_events(revision_id,created_at,id)"
    )
    db.execute(
        """CREATE TRIGGER IF NOT EXISTS protect_schedule_node_workflow_events_update
        BEFORE UPDATE ON schedule_node_workflow_events
        BEGIN SELECT RAISE(ABORT,'schedule node workflow events are immutable'); END
        """
    )
    db.execute(
        """CREATE TRIGGER IF NOT EXISTS protect_schedule_node_workflow_events_delete
        BEFORE DELETE ON schedule_node_workflow_events
        BEGIN SELECT RAISE(ABORT,'schedule node workflow events are immutable'); END
        """
    )


def m090_production_node_shadow_ledger(db):
    """Add immutable node-shadow facts without touching official schedules."""
    statements = (
        """
        CREATE TABLE IF NOT EXISTS production_node_shadow_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shadow_run_key TEXT NOT NULL UNIQUE,
            order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE RESTRICT,
            requested_start_date TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('completed','failed')),
            request_digest TEXT NOT NULL,
            result_digest TEXT NOT NULL,
            result_json TEXT NOT NULL,
            error_message TEXT NOT NULL DEFAULT '',
            created_by INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            completed_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS production_node_shadow_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shadow_run_id INTEGER NOT NULL REFERENCES production_node_shadow_runs(id) ON DELETE RESTRICT,
            order_process_id INTEGER NOT NULL REFERENCES order_processes(id) ON DELETE RESTRICT,
            process_id INTEGER NOT NULL REFERENCES processes(id) ON DELETE RESTRICT,
            route_version_id INTEGER REFERENCES process_route_versions(id) ON DELETE RESTRICT,
            process_version_id INTEGER REFERENCES process_versions(id) ON DELETE RESTRICT,
            standard_id INTEGER REFERENCES work_time_standards(id) ON DELETE RESTRICT,
            production_node_id INTEGER REFERENCES production_nodes(id) ON DELETE RESTRICT,
            seq_order INTEGER NOT NULL DEFAULT 0,
            quantity INTEGER NOT NULL DEFAULT 0 CHECK(quantity >= 0),
            status TEXT NOT NULL,
            blocked_code TEXT NOT NULL DEFAULT '',
            blocked_reason TEXT NOT NULL DEFAULT '',
            planned_start_at TEXT NOT NULL DEFAULT '',
            planned_end_at TEXT NOT NULL DEFAULT '',
            occupied_minutes REAL NOT NULL DEFAULT 0 CHECK(occupied_minutes >= 0),
            payload_json TEXT NOT NULL,
            payload_digest TEXT NOT NULL,
            UNIQUE(shadow_run_id,order_process_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS production_node_shadow_segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shadow_item_id INTEGER NOT NULL REFERENCES production_node_shadow_items(id) ON DELETE RESTRICT,
            production_node_id INTEGER NOT NULL REFERENCES production_nodes(id) ON DELETE RESTRICT,
            segment_start_at TEXT NOT NULL,
            segment_end_at TEXT NOT NULL,
            occupied_minutes REAL NOT NULL CHECK(occupied_minutes >= 0),
            quantity INTEGER NOT NULL CHECK(quantity >= 0),
            shift_id INTEGER REFERENCES schedule_shifts(id) ON DELETE RESTRICT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS production_node_shadow_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shadow_item_id INTEGER NOT NULL REFERENCES production_node_shadow_items(id) ON DELETE RESTRICT,
            production_node_id INTEGER NOT NULL REFERENCES production_nodes(id) ON DELETE RESTRICT,
            quantity INTEGER NOT NULL CHECK(quantity > 0),
            serial_id TEXT,
            batch_key TEXT NOT NULL DEFAULT '',
            changeover_minutes REAL NOT NULL DEFAULT 0 CHECK(changeover_minutes >= 0),
            allocation_start_at TEXT NOT NULL DEFAULT '',
            allocation_end_at TEXT NOT NULL DEFAULT ''
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_node_shadow_runs_order_time "
        "ON production_node_shadow_runs(order_id,created_at,id)",
        "CREATE INDEX IF NOT EXISTS idx_node_shadow_items_run_sequence "
        "ON production_node_shadow_items(shadow_run_id,seq_order,id)",
        "CREATE INDEX IF NOT EXISTS idx_node_shadow_segments_node_time "
        "ON production_node_shadow_segments(production_node_id,segment_start_at,segment_end_at)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_node_shadow_serial_operation "
        "ON production_node_shadow_allocations(shadow_item_id,serial_id) "
        "WHERE serial_id IS NOT NULL AND serial_id<>''",
    )
    for statement in statements:
        db.execute(statement)

    for table in (
        "production_node_shadow_runs",
        "production_node_shadow_items",
        "production_node_shadow_segments",
        "production_node_shadow_allocations",
    ):
        db.execute(
            f"CREATE TRIGGER IF NOT EXISTS protect_{table}_update "
            f"BEFORE UPDATE ON {table} BEGIN "
            "SELECT RAISE(ABORT,'production node shadow facts are immutable'); END"
        )
        db.execute(
            f"CREATE TRIGGER IF NOT EXISTS protect_{table}_delete "
            f"BEFORE DELETE ON {table} BEGIN "
            "SELECT RAISE(ABORT,'production node shadow facts are immutable'); END"
        )


def m091_node_native_schedule_segments(db):
    """Allow node-native segments without manufacturing a Legacy line link.

    V078 created ``process_line_id`` as NOT NULL.  V087 added the stable node
    reference but deliberately kept the old column for compatibility, leaving
    unmapped physical nodes unable to persist a segment.  Rebuild the segment
    table and its allocation child atomically so either resource identity is
    sufficient while historical Legacy facts keep their original ids.
    """
    invalid = db.execute(
        "SELECT id FROM order_process_schedule_segments "
        "WHERE process_line_id IS NULL AND production_node_id IS NULL "
        "ORDER BY id LIMIT 20"
    ).fetchall()
    if invalid:
        sample = ",".join(str(row[0]) for row in invalid)
        raise RuntimeError(
            "V091 blocked: schedule segment has neither production node nor "
            f"Legacy line: {sample}"
        )

    db.execute("DROP TABLE IF EXISTS production_node_schedule_allocations_v091_backup")
    db.execute(
        "CREATE TABLE production_node_schedule_allocations_v091_backup AS "
        "SELECT * FROM production_node_schedule_allocations"
    )
    db.execute("DROP TABLE IF EXISTS order_process_schedule_segments_v091")
    db.execute(
        """
        CREATE TABLE order_process_schedule_segments_v091 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER NOT NULL,
            process_line_id INTEGER,
            production_node_id INTEGER,
            segment_start_at TEXT NOT NULL,
            segment_end_at TEXT NOT NULL,
            occupied_minutes REAL NOT NULL CHECK(occupied_minutes > 0),
            shift_id INTEGER,
            quantity INTEGER NOT NULL DEFAULT 0 CHECK(quantity >= 0),
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            CHECK(process_line_id IS NOT NULL OR production_node_id IS NOT NULL),
            FOREIGN KEY(schedule_id) REFERENCES order_process_schedules(id) ON DELETE CASCADE,
            FOREIGN KEY(process_line_id) REFERENCES process_production_lines(id) ON DELETE RESTRICT,
            FOREIGN KEY(production_node_id) REFERENCES production_nodes(id) ON DELETE RESTRICT,
            FOREIGN KEY(shift_id) REFERENCES schedule_shifts(id) ON DELETE SET NULL
        )
        """
    )
    db.execute(
        "INSERT INTO order_process_schedule_segments_v091 "
        "(id,schedule_id,process_line_id,production_node_id,segment_start_at,"
        "segment_end_at,occupied_minutes,shift_id,quantity,created_at) "
        "SELECT id,schedule_id,process_line_id,production_node_id,segment_start_at,"
        "segment_end_at,occupied_minutes,shift_id,quantity,created_at "
        "FROM order_process_schedule_segments ORDER BY id"
    )

    # Drop the child first so the parent can be rebuilt with foreign keys on.
    db.execute("DROP TABLE production_node_schedule_allocations")
    db.execute("DROP TABLE order_process_schedule_segments")
    db.execute(
        "ALTER TABLE order_process_schedule_segments_v091 "
        "RENAME TO order_process_schedule_segments"
    )
    db.execute(
        """
        CREATE TABLE production_node_schedule_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER NOT NULL,
            segment_id INTEGER,
            production_node_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL CHECK(quantity > 0),
            serial_id TEXT,
            batch_key TEXT NOT NULL DEFAULT '',
            changeover_minutes REAL NOT NULL DEFAULT 0 CHECK(changeover_minutes >= 0),
            allocation_start_at TEXT,
            allocation_end_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(schedule_id) REFERENCES order_process_schedules(id) ON DELETE CASCADE,
            FOREIGN KEY(segment_id) REFERENCES order_process_schedule_segments(id) ON DELETE CASCADE,
            FOREIGN KEY(production_node_id) REFERENCES production_nodes(id) ON DELETE RESTRICT
        )
        """
    )
    db.execute(
        "INSERT INTO production_node_schedule_allocations "
        "(id,schedule_id,segment_id,production_node_id,quantity,serial_id,batch_key,"
        "changeover_minutes,allocation_start_at,allocation_end_at,created_at) "
        "SELECT id,schedule_id,segment_id,production_node_id,quantity,serial_id,batch_key,"
        "changeover_minutes,allocation_start_at,allocation_end_at,created_at "
        "FROM production_node_schedule_allocations_v091_backup ORDER BY id"
    )
    db.execute("DROP TABLE production_node_schedule_allocations_v091_backup")

    for statement in (
        "CREATE INDEX idx_schedule_segments_line_time ON "
        "order_process_schedule_segments(process_line_id,segment_start_at,segment_end_at)",
        "CREATE INDEX idx_schedule_segments_schedule ON "
        "order_process_schedule_segments(schedule_id)",
        "CREATE INDEX idx_schedule_segments_line_quantity ON "
        "order_process_schedule_segments(process_line_id,quantity)",
        "CREATE INDEX idx_schedule_segments_node_time ON "
        "order_process_schedule_segments(production_node_id,segment_start_at,segment_end_at)",
        "CREATE UNIQUE INDEX uq_node_allocation_serial_operation ON "
        "production_node_schedule_allocations(schedule_id,serial_id) "
        "WHERE serial_id IS NOT NULL AND serial_id<>''",
        "CREATE INDEX idx_node_allocations_schedule ON "
        "production_node_schedule_allocations(schedule_id,id)",
        "CREATE INDEX idx_node_allocations_node_time ON "
        "production_node_schedule_allocations(production_node_id,allocation_start_at,allocation_end_at)",
    ):
        db.execute(statement)


def _schedule_revision_content_digest(db, revision_id):
    items = [
        {
            "order_process_id": int(row["order_process_id"]),
            "process_id": int(row["process_id"]),
            "seq_order": int(row["seq_order"] or 0),
            "payload_digest": row["payload_digest"] or "",
        }
        for row in db.execute(
            "SELECT order_process_id,process_id,seq_order,payload_digest "
            "FROM schedule_revision_items WHERE revision_id=? "
            "ORDER BY seq_order,order_process_id,id",
            (revision_id,),
        ).fetchall()
    ]
    encoded = json.dumps(
        items, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def m092_immutable_schedule_publication(db):
    """Freeze approved schedule content and make publication auditable.

    V080/V089 stored immutable items and an approval workflow, but the parent
    revision could still be edited directly and publication had no idempotent
    workflow event.  V092 closes those gaps without rewriting historical
    schedule items or production execution facts.
    """
    for column, definition in {
        "content_digest": "TEXT NOT NULL DEFAULT ''",
        "publication_reason": "TEXT NOT NULL DEFAULT ''",
        "publication_idempotency_key": "TEXT NOT NULL DEFAULT ''",
    }.items():
        add_column_if_missing(db, "schedule_revisions", column, definition)

    for row in db.execute(
        "SELECT id FROM schedule_revisions ORDER BY id"
    ).fetchall():
        db.execute(
            "UPDATE schedule_revisions SET content_digest=? "
            "WHERE id=? AND content_digest=''",
            (_schedule_revision_content_digest(db, row["id"]), row["id"]),
        )

    duplicate_published = db.execute(
        "SELECT order_id,COUNT(*) AS count FROM schedule_revisions "
        "WHERE status='published' GROUP BY order_id HAVING COUNT(*)>1 LIMIT 20"
    ).fetchall()
    if duplicate_published:
        details = ",".join(
            f"{row['order_id']}:{row['count']}" for row in duplicate_published
        )
        raise RuntimeError(
            "V092 blocked: multiple published schedule revisions for order(s) "
            + details
        )
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_schedule_revision_published_order "
        "ON schedule_revisions(order_id) WHERE status='published'"
    )

    db.execute("DROP TRIGGER IF EXISTS protect_schedule_node_workflow_events_update")
    db.execute("DROP TRIGGER IF EXISTS protect_schedule_node_workflow_events_delete")
    db.execute("DROP TABLE IF EXISTS schedule_node_workflow_events_v092")
    db.execute(
        """
        CREATE TABLE schedule_node_workflow_events_v092 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            revision_id INTEGER NOT NULL,
            revision_item_id INTEGER,
            event_type TEXT NOT NULL CHECK(event_type IN (
                'adjust','lock','unlock','submit','approve','reject','publish','supersede'
            )),
            actor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            reason TEXT NOT NULL,
            before_json TEXT NOT NULL DEFAULT '{}',
            after_json TEXT NOT NULL DEFAULT '{}',
            input_digest TEXT NOT NULL DEFAULT '',
            idempotency_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(revision_id) REFERENCES schedule_revisions(id) ON DELETE RESTRICT,
            FOREIGN KEY(revision_item_id) REFERENCES schedule_revision_items(id) ON DELETE RESTRICT
        )
        """
    )
    db.execute(
        "INSERT INTO schedule_node_workflow_events_v092 "
        "(id,revision_id,revision_item_id,event_type,actor_id,reason,before_json,"
        "after_json,input_digest,idempotency_key,created_at) "
        "SELECT id,revision_id,revision_item_id,event_type,actor_id,reason,before_json,"
        "after_json,input_digest,idempotency_key,created_at "
        "FROM schedule_node_workflow_events ORDER BY id"
    )
    db.execute("DROP TABLE schedule_node_workflow_events")
    db.execute(
        "ALTER TABLE schedule_node_workflow_events_v092 "
        "RENAME TO schedule_node_workflow_events"
    )
    db.execute(
        "CREATE INDEX idx_schedule_node_workflow_events_revision "
        "ON schedule_node_workflow_events(revision_id,created_at,id)"
    )
    db.execute(
        "CREATE TRIGGER protect_schedule_node_workflow_events_update "
        "BEFORE UPDATE ON schedule_node_workflow_events BEGIN "
        "SELECT RAISE(ABORT,'schedule node workflow events are immutable'); END"
    )
    db.execute(
        "CREATE TRIGGER protect_schedule_node_workflow_events_delete "
        "BEFORE DELETE ON schedule_node_workflow_events BEGIN "
        "SELECT RAISE(ABORT,'schedule node workflow events are immutable'); END"
    )

    revision_columns = [
        row[1] for row in db.execute("PRAGMA table_info(schedule_revisions)")
    ]
    published_mutable = {
        "status", "superseded_by", "superseded_at",
    }
    published_invariants = " AND ".join(
        f"NEW.\"{column}\" IS OLD.\"{column}\""
        for column in revision_columns
        if column not in published_mutable
    )
    approved_mutable = {
        "status", "published_by", "published_at",
        "publication_reason", "publication_idempotency_key",
    }
    approved_invariants = " AND ".join(
        f"NEW.\"{column}\" IS OLD.\"{column}\""
        for column in revision_columns
        if column not in approved_mutable
    )
    for trigger in (
        "protect_terminal_schedule_revision_delete",
        "protect_terminal_schedule_revision_update",
        "protect_published_schedule_revision_update",
        "protect_approved_schedule_revision_update",
        "validate_current_schedule_revision_pointer",
        "protect_current_schedule_revision_pointer_clear",
        "validate_inserted_current_schedule_revision_pointer",
    ):
        db.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    db.execute(
        "CREATE TRIGGER protect_terminal_schedule_revision_delete "
        "BEFORE DELETE ON schedule_revisions BEGIN "
        "SELECT RAISE(ABORT,'schedule revisions are immutable'); END"
    )
    db.execute(
        "CREATE TRIGGER protect_terminal_schedule_revision_update "
        "BEFORE UPDATE ON schedule_revisions "
        "WHEN OLD.status IN ('superseded','cancelled') BEGIN "
        "SELECT RAISE(ABORT,'terminal schedule revision is immutable'); END"
    )
    db.execute(
        "CREATE TRIGGER protect_published_schedule_revision_update "
        "BEFORE UPDATE ON schedule_revisions WHEN OLD.status='published' AND NOT ("
        "NEW.status='superseded' AND NEW.superseded_by IS NOT NULL "
        "AND length(trim(NEW.superseded_at))>0 AND " + published_invariants + ") "
        "BEGIN SELECT RAISE(ABORT,'published schedule revision is immutable'); END"
    )
    db.execute(
        "CREATE TRIGGER protect_approved_schedule_revision_update "
        "BEFORE UPDATE ON schedule_revisions "
        "WHEN OLD.status='draft' AND OLD.approval_status='approved' AND NOT ("
        "NEW.status='published' AND NEW.published_by IS NOT NULL "
        "AND length(trim(NEW.published_at))>0 "
        "AND length(trim(NEW.publication_reason))>0 "
        "AND length(trim(NEW.publication_idempotency_key))>0 AND "
        + approved_invariants
        + ") BEGIN SELECT RAISE(ABORT,'approved schedule revision is immutable'); END"
    )
    db.execute(
        "CREATE TRIGGER validate_current_schedule_revision_pointer "
        "BEFORE UPDATE OF current_schedule_revision_id ON orders "
        "WHEN NEW.current_schedule_revision_id IS NOT NULL AND NOT EXISTS ("
        "SELECT 1 FROM schedule_revisions revision "
        "WHERE revision.id=NEW.current_schedule_revision_id "
        "AND revision.order_id=NEW.id AND revision.status='published' "
        "AND revision.approval_status='approved') BEGIN "
        "SELECT RAISE(ABORT,'current schedule revision must be approved and published'); END"
    )
    db.execute(
        "CREATE TRIGGER protect_current_schedule_revision_pointer_clear "
        "BEFORE UPDATE OF current_schedule_revision_id ON orders "
        "WHEN OLD.current_schedule_revision_id IS NOT NULL "
        "AND NEW.current_schedule_revision_id IS NULL BEGIN "
        "SELECT RAISE(ABORT,'current schedule revision cannot be cleared directly'); END"
    )
    db.execute(
        "CREATE TRIGGER validate_inserted_current_schedule_revision_pointer "
        "BEFORE INSERT ON orders "
        "WHEN NEW.current_schedule_revision_id IS NOT NULL AND NOT EXISTS ("
        "SELECT 1 FROM schedule_revisions revision "
        "WHERE revision.id=NEW.current_schedule_revision_id "
        "AND revision.order_id=NEW.id AND revision.status='published' "
        "AND revision.approval_status='approved') BEGIN "
        "SELECT RAISE(ABORT,'current schedule revision must be approved and published'); END"
    )


def m093_schedule_conflict_risk_evidence(db):
    """Add node-native conflict facts and immutable delivery-risk evidence."""
    db.executescript(
        """
        DROP VIEW IF EXISTS schedule_effective_capacity_intervals;
        CREATE VIEW schedule_effective_capacity_intervals AS
        SELECT
            'segment:' || ss.id AS fact_key,
            'segment' AS fact_type,
            ss.id AS fact_id,
            s.id AS schedule_id,
            s.schedule_revision_id,
            s.order_id,
            s.order_process_id,
            s.process_id,
            p.name AS process_name,
            ss.production_node_id,
            ss.process_line_id,
            COALESCE(NULLIF(s.node_name_snapshot,''),n.node_name,'') AS node_name,
            COALESCE(NULLIF(s.capacity_mode_snapshot,''),n.capacity_mode,'exclusive')
                AS capacity_mode,
            ss.segment_start_at AS start_at,
            ss.segment_end_at AS end_at,
            ss.occupied_minutes,
            CASE WHEN s.locked=1 OR EXISTS (
                SELECT 1 FROM schedule_revision_items ri
                JOIN schedule_node_task_locks task_lock
                  ON task_lock.revision_item_id=ri.id AND task_lock.status='active'
                WHERE ri.revision_id=s.schedule_revision_id
                  AND ri.order_process_id=s.order_process_id
            ) THEN 1 ELSE 0 END AS locked
        FROM order_process_schedule_segments ss
        JOIN order_process_schedules s ON s.id=ss.schedule_id
        JOIN orders o ON o.id=s.order_id
        JOIN processes p ON p.id=s.process_id
        LEFT JOIN production_nodes n ON n.id=ss.production_node_id
        WHERE o.deleted_at IS NULL
          AND s.status<>'blocked'
          AND COALESCE(s.execution_mode,'internal')='internal'
          AND (ss.production_node_id IS NOT NULL OR ss.process_line_id IS NOT NULL)
          AND (
              s.schedule_revision_id=o.current_schedule_revision_id
              OR (o.current_schedule_revision_id IS NULL AND s.schedule_revision_id IS NULL)
          )
        UNION ALL
        SELECT
            'schedule:' || s.id AS fact_key,
            'schedule' AS fact_type,
            s.id AS fact_id,
            s.id AS schedule_id,
            s.schedule_revision_id,
            s.order_id,
            s.order_process_id,
            s.process_id,
            p.name AS process_name,
            s.production_node_id,
            s.process_line_id,
            COALESCE(NULLIF(s.node_name_snapshot,''),n.node_name,'') AS node_name,
            COALESCE(NULLIF(s.capacity_mode_snapshot,''),n.capacity_mode,'exclusive')
                AS capacity_mode,
            CASE WHEN COALESCE(s.planned_start_at,'')<>''
                 THEN s.planned_start_at ELSE s.plan_start || ' 00:00:00' END AS start_at,
            CASE WHEN COALESCE(s.planned_end_at,'')<>''
                 THEN s.planned_end_at ELSE s.plan_end || ' 23:59:59' END AS end_at,
            s.occupied_minutes,
            CASE WHEN s.locked=1 OR EXISTS (
                SELECT 1 FROM schedule_revision_items ri
                JOIN schedule_node_task_locks task_lock
                  ON task_lock.revision_item_id=ri.id AND task_lock.status='active'
                WHERE ri.revision_id=s.schedule_revision_id
                  AND ri.order_process_id=s.order_process_id
            ) THEN 1 ELSE 0 END AS locked
        FROM order_process_schedules s
        JOIN orders o ON o.id=s.order_id
        JOIN processes p ON p.id=s.process_id
        LEFT JOIN production_nodes n ON n.id=s.production_node_id
        WHERE o.deleted_at IS NULL
          AND s.status<>'blocked'
          AND COALESCE(s.execution_mode,'internal')='internal'
          AND (s.production_node_id IS NOT NULL OR s.process_line_id IS NOT NULL)
          AND NOT EXISTS (
              SELECT 1 FROM order_process_schedule_segments ss
              WHERE ss.schedule_id=s.id
          )
          AND (
              s.schedule_revision_id=o.current_schedule_revision_id
              OR (o.current_schedule_revision_id IS NULL AND s.schedule_revision_id IS NULL)
          )
        UNION ALL
        SELECT
            'lock:' || task_lock.id AS fact_key,
            'locked_revision_item' AS fact_type,
            task_lock.id AS fact_id,
            i.source_schedule_id AS schedule_id,
            i.revision_id AS schedule_revision_id,
            r.order_id,
            i.order_process_id,
            i.process_id,
            p.name AS process_name,
            task_lock.production_node_id,
            i.process_line_id,
            COALESCE(NULLIF(i.node_name_snapshot,''),n.node_name,'') AS node_name,
            COALESCE(NULLIF(i.capacity_mode_snapshot,''),n.capacity_mode,'exclusive')
                AS capacity_mode,
            i.planned_start_at AS start_at,
            i.planned_end_at AS end_at,
            i.occupied_minutes,
            1 AS locked
        FROM schedule_node_task_locks task_lock
        JOIN schedule_revision_items i ON i.id=task_lock.revision_item_id
        JOIN schedule_revisions r ON r.id=i.revision_id
        JOIN orders o ON o.id=r.order_id
        JOIN processes p ON p.id=i.process_id
        LEFT JOIN production_nodes n ON n.id=task_lock.production_node_id
        WHERE task_lock.status='active'
          AND r.status='draft'
          AND o.deleted_at IS NULL
          AND i.status<>'blocked'
          AND COALESCE(i.execution_mode,'internal')='internal'
          AND COALESCE(i.planned_start_at,'')<>''
          AND COALESCE(i.planned_end_at,'')<>'';

        CREATE TABLE IF NOT EXISTS schedule_revision_conflict_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            revision_id INTEGER NOT NULL REFERENCES schedule_revisions(id) ON DELETE RESTRICT,
            check_stage TEXT NOT NULL,
            input_digest TEXT NOT NULL,
            blocking_count INTEGER NOT NULL DEFAULT 0 CHECK(blocking_count>=0),
            warning_count INTEGER NOT NULL DEFAULT 0 CHECK(warning_count>=0),
            summary_json TEXT NOT NULL DEFAULT '{}',
            result_digest TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(revision_id,check_stage,input_digest)
        );
        CREATE INDEX IF NOT EXISTS idx_schedule_conflict_checks_revision
            ON schedule_revision_conflict_checks(revision_id,created_at,id);

        CREATE TABLE IF NOT EXISTS schedule_revision_conflicts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            check_id INTEGER NOT NULL REFERENCES schedule_revision_conflict_checks(id) ON DELETE RESTRICT,
            revision_id INTEGER NOT NULL REFERENCES schedule_revisions(id) ON DELETE RESTRICT,
            conflict_type TEXT NOT NULL,
            severity TEXT NOT NULL CHECK(severity IN ('warning','blocking')),
            production_node_id INTEGER REFERENCES production_nodes(id) ON DELETE RESTRICT,
            process_line_id INTEGER REFERENCES process_production_lines(id) ON DELETE RESTRICT,
            first_order_id INTEGER,
            second_order_id INTEGER,
            first_order_process_id INTEGER,
            second_order_process_id INTEGER,
            first_revision_item_id INTEGER REFERENCES schedule_revision_items(id) ON DELETE RESTRICT,
            second_revision_item_id INTEGER REFERENCES schedule_revision_items(id) ON DELETE RESTRICT,
            first_schedule_id INTEGER,
            second_schedule_id INTEGER,
            overlap_start_at TEXT NOT NULL DEFAULT '',
            overlap_end_at TEXT NOT NULL DEFAULT '',
            overlap_minutes INTEGER NOT NULL DEFAULT 0 CHECK(overlap_minutes>=0),
            first_locked INTEGER NOT NULL DEFAULT 0 CHECK(first_locked IN (0,1)),
            second_locked INTEGER NOT NULL DEFAULT 0 CHECK(second_locked IN (0,1)),
            reason TEXT NOT NULL,
            details_json TEXT NOT NULL DEFAULT '{}',
            evidence_digest TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(check_id,evidence_digest)
        );
        CREATE INDEX IF NOT EXISTS idx_schedule_revision_conflicts_revision
            ON schedule_revision_conflicts(revision_id,severity,conflict_type,id);
        CREATE INDEX IF NOT EXISTS idx_schedule_revision_conflicts_node_time
            ON schedule_revision_conflicts(production_node_id,overlap_start_at,overlap_end_at);

        CREATE TABLE IF NOT EXISTS schedule_revision_risk_assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            revision_id INTEGER NOT NULL REFERENCES schedule_revisions(id) ON DELETE RESTRICT,
            assessment_stage TEXT NOT NULL,
            deadline_snapshot TEXT NOT NULL DEFAULT '',
            projected_completion_at_snapshot TEXT NOT NULL DEFAULT '',
            risk_level TEXT NOT NULL CHECK(risk_level IN ('none','low','medium','high','overdue')),
            delay_minutes INTEGER NOT NULL DEFAULT 0 CHECK(delay_minutes>=0),
            slack_minutes INTEGER,
            blocked_count INTEGER NOT NULL DEFAULT 0 CHECK(blocked_count>=0),
            conflict_count INTEGER NOT NULL DEFAULT 0 CHECK(conflict_count>=0),
            primary_risk_source TEXT NOT NULL DEFAULT '',
            bottleneck_process TEXT NOT NULL DEFAULT '',
            bottleneck_node TEXT NOT NULL DEFAULT '',
            risk_reason TEXT NOT NULL,
            suggested_actions_json TEXT NOT NULL DEFAULT '[]',
            details_json TEXT NOT NULL DEFAULT '{}',
            evidence_digest TEXT NOT NULL,
            assessed_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(revision_id,assessment_stage)
        );
        CREATE INDEX IF NOT EXISTS idx_schedule_risk_assessments_level
            ON schedule_revision_risk_assessments(risk_level,delay_minutes DESC,revision_id);

        CREATE TRIGGER IF NOT EXISTS protect_schedule_conflict_checks_update
        BEFORE UPDATE ON schedule_revision_conflict_checks BEGIN
            SELECT RAISE(ABORT,'schedule conflict checks are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS protect_schedule_conflict_checks_delete
        BEFORE DELETE ON schedule_revision_conflict_checks BEGIN
            SELECT RAISE(ABORT,'schedule conflict checks are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS protect_schedule_revision_conflicts_update
        BEFORE UPDATE ON schedule_revision_conflicts BEGIN
            SELECT RAISE(ABORT,'schedule revision conflicts are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS protect_schedule_revision_conflicts_delete
        BEFORE DELETE ON schedule_revision_conflicts BEGIN
            SELECT RAISE(ABORT,'schedule revision conflicts are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS protect_schedule_risk_assessments_update
        BEFORE UPDATE ON schedule_revision_risk_assessments BEGIN
            SELECT RAISE(ABORT,'schedule risk assessments are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS protect_schedule_risk_assessments_delete
        BEFORE DELETE ON schedule_revision_risk_assessments BEGIN
            SELECT RAISE(ABORT,'schedule risk assessments are immutable');
        END;
        """
    )


def m094_dynamic_replan_evidence(db):
    """Add immutable production-fact triggers and before/after replan evidence."""
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS schedule_replan_triggers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            order_process_id INTEGER REFERENCES order_processes(id) ON DELETE SET NULL,
            trigger_type TEXT NOT NULL CHECK(trigger_type IN (
                'work_report','scrap','rework_created','rework_completed',
                'downtime_created','downtime_cancelled','node_occupancy','manual'
            )),
            source_type TEXT NOT NULL,
            source_id INTEGER,
            reason TEXT NOT NULL,
            fact_digest TEXT NOT NULL,
            details_json TEXT NOT NULL DEFAULT '{}',
            created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(order_id,trigger_type,source_type,source_id,fact_digest)
        );
        CREATE INDEX IF NOT EXISTS idx_schedule_replan_triggers_order_time
            ON schedule_replan_triggers(order_id,created_at,id);
        CREATE INDEX IF NOT EXISTS idx_schedule_replan_triggers_source
            ON schedule_replan_triggers(source_type,source_id,order_id);

        CREATE TABLE IF NOT EXISTS schedule_replan_differences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            revision_id INTEGER NOT NULL REFERENCES schedule_revisions(id) ON DELETE RESTRICT,
            prior_revision_id INTEGER REFERENCES schedule_revisions(id) ON DELETE RESTRICT,
            order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE RESTRICT,
            order_process_id INTEGER NOT NULL REFERENCES order_processes(id) ON DELETE RESTRICT,
            process_id INTEGER NOT NULL REFERENCES processes(id) ON DELETE RESTRICT,
            change_type TEXT NOT NULL CHECK(change_type IN (
                'unchanged','completed','added','removed','quantity','node','time','capacity','blocked','multiple'
            )),
            node_changed INTEGER NOT NULL DEFAULT 0 CHECK(node_changed IN (0,1)),
            quantity_delta INTEGER NOT NULL DEFAULT 0,
            occupied_minutes_delta REAL NOT NULL DEFAULT 0,
            start_delta_minutes INTEGER NOT NULL DEFAULT 0,
            end_delta_minutes INTEGER NOT NULL DEFAULT 0,
            before_json TEXT NOT NULL DEFAULT '{}',
            after_json TEXT NOT NULL DEFAULT '{}',
            evidence_digest TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(revision_id,order_process_id),
            UNIQUE(revision_id,evidence_digest)
        );
        CREATE INDEX IF NOT EXISTS idx_schedule_replan_differences_revision
            ON schedule_replan_differences(revision_id,change_type,order_process_id);

        CREATE TABLE IF NOT EXISTS schedule_replan_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            revision_id INTEGER NOT NULL UNIQUE REFERENCES schedule_revisions(id) ON DELETE RESTRICT,
            prior_revision_id INTEGER REFERENCES schedule_revisions(id) ON DELETE RESTRICT,
            order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE RESTRICT,
            trigger_count INTEGER NOT NULL DEFAULT 0 CHECK(trigger_count>=0),
            changed_operation_count INTEGER NOT NULL DEFAULT 0 CHECK(changed_operation_count>=0),
            node_change_count INTEGER NOT NULL DEFAULT 0 CHECK(node_change_count>=0),
            delayed_operation_count INTEGER NOT NULL DEFAULT 0 CHECK(delayed_operation_count>=0),
            advanced_operation_count INTEGER NOT NULL DEFAULT 0 CHECK(advanced_operation_count>=0),
            before_risk_level TEXT NOT NULL DEFAULT 'none',
            after_risk_level TEXT NOT NULL DEFAULT 'none',
            before_delay_minutes INTEGER NOT NULL DEFAULT 0 CHECK(before_delay_minutes>=0),
            after_delay_minutes INTEGER NOT NULL DEFAULT 0 CHECK(after_delay_minutes>=0),
            risk_change TEXT NOT NULL DEFAULT 'unchanged'
                CHECK(risk_change IN ('improved','worsened','unchanged')),
            summary_json TEXT NOT NULL DEFAULT '{}',
            evidence_digest TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_schedule_replan_summaries_order
            ON schedule_replan_summaries(order_id,created_at,id);

        CREATE TRIGGER IF NOT EXISTS protect_schedule_replan_triggers_update
        BEFORE UPDATE ON schedule_replan_triggers BEGIN
            SELECT RAISE(ABORT,'schedule replan triggers are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS protect_schedule_replan_differences_update
        BEFORE UPDATE ON schedule_replan_differences BEGIN
            SELECT RAISE(ABORT,'schedule replan differences are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS protect_schedule_replan_differences_delete
        BEFORE DELETE ON schedule_replan_differences BEGIN
            SELECT RAISE(ABORT,'schedule replan differences are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS protect_schedule_replan_summaries_update
        BEFORE UPDATE ON schedule_replan_summaries BEGIN
            SELECT RAISE(ABORT,'schedule replan summaries are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS protect_schedule_replan_summaries_delete
        BEFORE DELETE ON schedule_replan_summaries BEGIN
            SELECT RAISE(ABORT,'schedule replan summaries are immutable');
        END;
        """
    )


MIGRATIONS = [
    (86, "Add stable production-node master data", m086_production_node_master),
    (87, "Add production-node scheduling facts", m087_production_node_schedule_facts),
    (88, "Add batch and serial node allocations", m088_batch_serial_allocations),
    (89, "Add schedule revision lock and approval workflow", m089_schedule_revision_workflow),
    (90, "Add isolated production-node shadow ledger", m090_production_node_shadow_ledger),
    (91, "Allow node-native schedule segments", m091_node_native_schedule_segments),
    (92, "Freeze and audit schedule revision publication", m092_immutable_schedule_publication),
    (93, "Add schedule conflict and delivery-risk evidence", m093_schedule_conflict_risk_evidence),
    (94, "Add dynamic replan trigger and difference evidence", m094_dynamic_replan_evidence),
]
