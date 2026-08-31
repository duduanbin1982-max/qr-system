"""工序级多产线排程基础表与默认资源池。"""

from modules.migration_helpers import add_column_if_missing
from modules.schedule_capacity_config import (
    DEFAULT_DAILY_MINUTES,
    DEFAULT_PROCESS_LINE_COUNTS,
)


def m076_schedule_capacity(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS process_production_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            process_id INTEGER NOT NULL,
            line_code TEXT NOT NULL,
            line_name TEXT NOT NULL,
            daily_minutes REAL NOT NULL DEFAULT 480 CHECK (daily_minutes > 0),
            status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','inactive')),
            remark TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(process_id, line_code),
            FOREIGN KEY (process_id) REFERENCES processes(id) ON DELETE RESTRICT
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS order_process_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            order_process_id INTEGER NOT NULL,
            process_id INTEGER NOT NULL,
            process_line_id INTEGER,
            seq_order INTEGER NOT NULL DEFAULT 0,
            quantity INTEGER NOT NULL DEFAULT 0,
            standard_minutes_per_unit REAL NOT NULL DEFAULT 0,
            setup_minutes REAL NOT NULL DEFAULT 0,
            difficulty_factor REAL NOT NULL DEFAULT 1,
            planned_minutes REAL NOT NULL DEFAULT 0,
            plan_start TEXT NOT NULL,
            plan_end TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'planned' CHECK (status IN ('planned','in_progress','completed','blocked')),
            blocked_reason TEXT NOT NULL DEFAULT '',
            schedule_run_key TEXT NOT NULL DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(order_process_id),
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
            FOREIGN KEY (order_process_id) REFERENCES order_processes(id) ON DELETE CASCADE,
            FOREIGN KEY (process_id) REFERENCES processes(id) ON DELETE RESTRICT,
            FOREIGN KEY (process_line_id) REFERENCES process_production_lines(id) ON DELETE SET NULL
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_process_lines_process_status ON process_production_lines(process_id, status)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_order_process_schedules_order_seq ON order_process_schedules(order_id, seq_order)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_order_process_schedules_line_dates ON order_process_schedules(process_line_id, plan_start, plan_end)")

    # The legacy order-level line remains available for compatibility; new scheduling uses this pool.
    add_column_if_missing(db, "orders", "schedule_version", "INTEGER NOT NULL DEFAULT 1")
    # Keep the applied work-time factor immutable on each generated schedule.
    add_column_if_missing(db, "order_process_schedules", "difficulty_factor", "REAL NOT NULL DEFAULT 1")
    add_column_if_missing(db, "order_process_schedules", "blocked_reason", "TEXT NOT NULL DEFAULT ''")

    processes = db.execute(
        "SELECT id, name FROM processes WHERE status = 'active' ORDER BY seq_order, id"
    ).fetchall()
    for process in processes:
        count = DEFAULT_PROCESS_LINE_COUNTS.get(process["name"])
        if not count:
            continue
        for index in range(1, count + 1):
            code = f"{process['name']}-{index:02d}"
            name = f"{process['name']}{index}线"
            db.execute(
                "INSERT OR IGNORE INTO process_production_lines "
                "(process_id, line_code, line_name, daily_minutes, remark) VALUES (?,?,?,?,?)",
                (process["id"], code, name, DEFAULT_DAILY_MINUTES, "系统默认产线"),
            )


def _schedule_snapshot(row, db):
    """Return the unambiguous version snapshot for one legacy schedule row."""
    order = db.execute(
        "SELECT route_id,route_version_id,route_name_snapshot FROM orders WHERE id=?",
        (row["order_id"],),
    ).fetchone()
    operation = db.execute(
        "SELECT op.process_id,op.process_version_id,op.process_name_snapshot,"
        "op.process_category_snapshot,p.name FROM order_processes op "
        "JOIN processes p ON p.id=op.process_id WHERE op.id=? AND op.order_id=?",
        (row["order_process_id"], row["order_id"]),
    ).fetchone()
    if not order or not operation:
        return None
    route_version_id = order["route_version_id"]
    process_version_id = operation["process_version_id"]
    if route_version_id is None or process_version_id is None:
        return None
    item = db.execute(
        "SELECT 1 FROM process_route_version_items WHERE route_version_id=? "
        "AND process_id=? AND process_version_id=?",
        (route_version_id, operation["process_id"], process_version_id),
    ).fetchone()
    if item is None:
        return None
    route = db.execute(
        "SELECT name FROM process_route_versions WHERE id=?", (route_version_id,)
    ).fetchone()
    standard = db.execute(
        "SELECT id,version FROM work_time_standards "
        "WHERE process_id=? AND process_version_id=? AND route_version_id=? "
        "AND status='active' AND standard_minutes_per_unit>0 "
        "AND (effective_from='' OR effective_from IS NULL OR effective_from<=date('now')) "
        "AND (effective_to='' OR effective_to IS NULL OR effective_to>=date('now')) "
        "ORDER BY CASE WHEN product_code=(SELECT product_code FROM orders WHERE id=?) THEN 0 ELSE 1 END,id DESC LIMIT 1",
        (operation["process_id"], process_version_id, route_version_id, row["order_id"]),
    ).fetchone()
    return {
        "route_version_id": route_version_id,
        "process_version_id": process_version_id,
        "standard_id": standard["id"] if standard else None,
        "standard_version": standard["version"] if standard else None,
        "process_name_snapshot": operation["process_name_snapshot"] or operation["name"] or "",
        "route_name_snapshot": (order["route_name_snapshot"] or (route["name"] if route else "")),
    }


def m077_harden_schedule_capacity(db):
    """Version scheduling facts and retain an independent run/idempotency ledger."""
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS process_capacity_profiles (
            process_id INTEGER PRIMARY KEY,
            configured_line_count INTEGER NOT NULL CHECK(configured_line_count > 0),
            source_process_name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(process_id) REFERENCES processes(id) ON DELETE RESTRICT
        )
        """
    )
    db.execute(
        """
        INSERT OR IGNORE INTO process_capacity_profiles
            (process_id,configured_line_count,source_process_name)
        SELECT p.id,COUNT(pl.id),p.name
        FROM processes p JOIN process_production_lines pl ON pl.process_id=p.id
        GROUP BY p.id
        """
    )
    # Create the run ledger before adding its foreign-key column to schedule
    # facts.  This keeps strict SQLite foreign-key mode happy during upgrades.
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS schedule_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_run_key TEXT NOT NULL UNIQUE,
            order_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'started'
                CHECK(status IN ('started','completed','failed')),
            requested_start_date TEXT NOT NULL DEFAULT '',
            result_json TEXT NOT NULL DEFAULT '[]',
            result_digest TEXT NOT NULL DEFAULT '',
            error_message TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            completed_at TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE RESTRICT
        )
        """
    )
    db.execute("CREATE INDEX IF NOT EXISTS idx_schedule_runs_order ON schedule_runs(order_id, id DESC)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_schedule_runs_status ON schedule_runs(status, created_at)")

    for column, definition in {
        "route_version_id": "INTEGER REFERENCES process_route_versions(id) ON DELETE RESTRICT",
        "process_version_id": "INTEGER REFERENCES process_versions(id) ON DELETE RESTRICT",
        "standard_id": "INTEGER REFERENCES work_time_standards(id) ON DELETE SET NULL",
        "standard_version": "INTEGER",
        "process_name_snapshot": "TEXT NOT NULL DEFAULT ''",
        "route_name_snapshot": "TEXT NOT NULL DEFAULT ''",
        "schedule_run_id": "INTEGER REFERENCES schedule_runs(id) ON DELETE RESTRICT",
    }.items():
        add_column_if_missing(db, "order_process_schedules", column, definition)

    db.execute("CREATE INDEX IF NOT EXISTS idx_schedule_facts_route_version ON order_process_schedules(route_version_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_schedule_facts_process_version ON order_process_schedules(process_version_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_schedule_facts_standard ON order_process_schedules(standard_id)")

    # Backfill only facts that can be proven from immutable order bindings.
    rows = db.execute(
        "SELECT * FROM order_process_schedules WHERE route_version_id IS NULL "
        "OR process_version_id IS NULL OR process_name_snapshot=''"
    ).fetchall()
    for row in rows:
        snapshot = _schedule_snapshot(row, db)
        if snapshot is None:
            continue
        db.execute(
            "UPDATE order_process_schedules SET route_version_id=?,process_version_id=?,"
            "standard_id=COALESCE(standard_id,?),standard_version=COALESCE(standard_version,?),"
            "process_name_snapshot=CASE WHEN process_name_snapshot='' THEN ? ELSE process_name_snapshot END,"
            "route_name_snapshot=CASE WHEN route_name_snapshot='' THEN ? ELSE route_name_snapshot END "
            "WHERE id=?",
            (
                snapshot["route_version_id"], snapshot["process_version_id"],
                snapshot["standard_id"], snapshot["standard_version"],
                snapshot["process_name_snapshot"], snapshot["route_name_snapshot"], row["id"],
            ),
        )

    # New writes must carry an exact order/process/route binding. Existing
    # legacy rows remain readable as historical evidence and are not rewritten.
    db.executescript(
        """
        CREATE TRIGGER IF NOT EXISTS validate_schedule_fact_insert
        BEFORE INSERT ON order_process_schedules
        WHEN NOT EXISTS (
            SELECT 1 FROM orders o JOIN order_processes op
              ON op.order_id=o.id AND op.id=NEW.order_process_id
            JOIN process_versions pv
              ON pv.id=NEW.process_version_id AND pv.process_id=NEW.process_id
            WHERE o.id=NEW.order_id AND o.deleted_at IS NULL
              AND NEW.schedule_run_id IS NOT NULL
              AND (
                (o.route_id IS NULL AND NEW.route_version_id IS NULL)
                OR EXISTS (
                  SELECT 1 FROM process_route_versions rv
                  JOIN process_route_version_items item
                    ON item.route_version_id=rv.id AND item.process_id=NEW.process_id
                   AND item.process_version_id=NEW.process_version_id
                  WHERE rv.id=NEW.route_version_id AND rv.process_route_id=o.route_id
                )
              )
        )
        BEGIN SELECT RAISE(ABORT,'schedule fact version binding is inconsistent'); END;

        CREATE TRIGGER IF NOT EXISTS validate_schedule_fact_update
        BEFORE UPDATE OF order_id,order_process_id,process_id,route_version_id,
            process_version_id,schedule_run_id,standard_id ON order_process_schedules
        WHEN NOT EXISTS (
            SELECT 1 FROM orders o JOIN order_processes op
              ON op.order_id=o.id AND op.id=NEW.order_process_id
            JOIN process_versions pv
              ON pv.id=NEW.process_version_id AND pv.process_id=NEW.process_id
            WHERE o.id=NEW.order_id AND o.deleted_at IS NULL
              AND NEW.schedule_run_id IS NOT NULL
              AND (
                (o.route_id IS NULL AND NEW.route_version_id IS NULL)
                OR EXISTS (
                  SELECT 1 FROM process_route_versions rv
                  JOIN process_route_version_items item
                    ON item.route_version_id=rv.id AND item.process_id=NEW.process_id
                   AND item.process_version_id=NEW.process_version_id
                  WHERE rv.id=NEW.route_version_id AND rv.process_route_id=o.route_id
                )
              )
        )
        BEGIN SELECT RAISE(ABORT,'schedule fact version binding is inconsistent'); END;

        CREATE TRIGGER IF NOT EXISTS validate_schedule_fact_standard
        BEFORE INSERT ON order_process_schedules
        WHEN NEW.standard_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM work_time_standards s
            WHERE s.id=NEW.standard_id AND s.process_id=NEW.process_id
              AND s.status='active' AND s.standard_minutes_per_unit>0
        )
        BEGIN SELECT RAISE(ABORT,'schedule fact standard is invalid'); END;
        """
    )


MIGRATIONS = [
    (76, "Add process-level multi-line scheduling capacity", m076_schedule_capacity),
    (77, "Version scheduling facts and retain run ledger", m077_harden_schedule_capacity),
]
