"""V086 stable production-node master data and legacy line mappings."""


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
        """
    )
    db.execute(
        "INSERT OR IGNORE INTO production_nodes "
        "(process_id,node_code,node_name,capacity_mode,status,calendar_id,legacy_process_line_id) "
        "SELECT process_id,line_code,line_name,'exclusive',status,calendar_id,id "
        "FROM process_production_lines"
    )
    _validate_legacy_node_mapping(db)


MIGRATIONS = [
    (86, "Add stable production-node master data", m086_production_node_master),
]
