"""V086-V087 production-node master data and exact legacy fact mappings."""

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
        "f.execution_mode,n.id AS production_node_id "
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


MIGRATIONS = [
    (86, "Add stable production-node master data", m086_production_node_master),
    (87, "Add production-node scheduling facts", m087_production_node_schedule_facts),
]
