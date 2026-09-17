"""V086 stable production-node master data and legacy line mappings."""


def m086_production_node_master(db):
    """Add stable physical-capacity nodes without changing legacy scheduling."""
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
            FOREIGN KEY(production_node_id) REFERENCES production_nodes(id) ON DELETE RESTRICT
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
        "FROM process_production_lines WHERE calendar_id IS NOT NULL"
    )


MIGRATIONS = [
    (86, "Add stable production-node master data", m086_production_node_master),
]
