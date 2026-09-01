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
        "SELECT route_id,route_version_id,route_name_snapshot,product_id,product_code "
        "FROM orders WHERE id=?",
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
    effective_date = (row["plan_start"] or "").strip() or None
    base = (
        "SELECT id,version FROM work_time_standards "
        "WHERE process_id=? AND process_version_id=? AND route_version_id=? "
        "AND status='active' AND standard_minutes_per_unit>0 "
        "AND (effective_from='' OR effective_from IS NULL OR (? IS NULL OR effective_from<=?)) "
        "AND (effective_to='' OR effective_to IS NULL OR (? IS NULL OR effective_to>=?)) "
    )
    base_params = (
        operation["process_id"], process_version_id, route_version_id,
        effective_date, effective_date, effective_date, effective_date,
    )
    product_id = order["product_id"] if "product_id" in order.keys() else None
    product_code = (order["product_code"] or "").strip()
    product_match = None
    if product_id is not None:
        product_match = db.execute(
            base + "AND product_id=? ORDER BY version DESC,id DESC LIMIT 1",
            base_params + (product_id,),
        ).fetchone()
    elif product_code:
        product_match = db.execute(
            base + "AND product_id IS NULL AND product_code=? "
            "ORDER BY version DESC,id DESC LIMIT 1",
            base_params + (product_code,),
        ).fetchone()
    standard = product_match or db.execute(
        base + "AND COALESCE(product_id,0)=0 AND COALESCE(product_code,'')='' "
        "ORDER BY version DESC,id DESC LIMIT 1",
        base_params,
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


def m078_precision_schedule_capacity(db):
    """Add calendar/shift primitives and minute-level schedule snapshots.

    v76/v77 intentionally kept the legacy date-level schedule API intact. This
    migration adds precision facts alongside those columns so old readers
    continue to work while new scheduling writes carry auditable timestamps,
    capacity and standard-match snapshots.
    """
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS schedule_calendars (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            calendar_code TEXT NOT NULL UNIQUE,
            calendar_name TEXT NOT NULL,
            timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
            weekly_workdays TEXT NOT NULL DEFAULT '1,2,3,4,5',
            status TEXT NOT NULL DEFAULT 'active'
                CHECK(status IN ('active','inactive')),
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS schedule_shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            calendar_id INTEGER NOT NULL,
            shift_code TEXT NOT NULL,
            shift_name TEXT NOT NULL,
            start_minute INTEGER NOT NULL CHECK(start_minute >= 0 AND start_minute < 1440),
            end_minute INTEGER NOT NULL CHECK(end_minute > start_minute AND end_minute <= 1440),
            status TEXT NOT NULL DEFAULT 'active'
                CHECK(status IN ('active','inactive')),
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(calendar_id, shift_code),
            FOREIGN KEY(calendar_id) REFERENCES schedule_calendars(id) ON DELETE CASCADE
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS schedule_calendar_exceptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            calendar_id INTEGER NOT NULL,
            work_date TEXT NOT NULL,
            is_working_day INTEGER NOT NULL DEFAULT 0 CHECK(is_working_day IN (0,1)),
            shift_ids TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(calendar_id, work_date),
            FOREIGN KEY(calendar_id) REFERENCES schedule_calendars(id) ON DELETE CASCADE
        )
        """
    )
    db.execute(
        """INSERT OR IGNORE INTO schedule_calendars
            (calendar_code,calendar_name,timezone,weekly_workdays)
         VALUES ('DEFAULT','默认生产日历','Asia/Shanghai','1,2,3,4,5')"""
    )
    calendar = db.execute(
        "SELECT id FROM schedule_calendars WHERE calendar_code='DEFAULT'"
    ).fetchone()
    calendar_id = calendar[0]
    db.execute(
        """INSERT OR IGNORE INTO schedule_shifts
            (calendar_id,shift_code,shift_name,start_minute,end_minute)
         VALUES (?,?,?,?,?)""",
        (calendar_id, "DAY-AM", "早班", 8 * 60, 12 * 60),
    )
    db.execute(
        """INSERT OR IGNORE INTO schedule_shifts
            (calendar_id,shift_code,shift_name,start_minute,end_minute)
         VALUES (?,?,?,?,?)""",
        (calendar_id, "DAY-PM", "晚班", 13 * 60, 17 * 60),
    )

    add_column_if_missing(
        db, "process_production_lines", "calendar_id",
        "INTEGER REFERENCES schedule_calendars(id) ON DELETE RESTRICT",
    )
    for column, definition in {
        "planned_start_at": "TEXT NOT NULL DEFAULT ''",
        "planned_end_at": "TEXT NOT NULL DEFAULT ''",
        "occupied_minutes": "REAL NOT NULL DEFAULT 0",
        "capacity_snapshot_json": "TEXT NOT NULL DEFAULT '{}'",
        "standard_match_scope": "TEXT NOT NULL DEFAULT ''",
        "calendar_id": "INTEGER REFERENCES schedule_calendars(id) ON DELETE RESTRICT",
        "shift_snapshot_json": "TEXT NOT NULL DEFAULT '[]'",
        "line_name_snapshot": "TEXT NOT NULL DEFAULT ''",
    }.items():
        add_column_if_missing(db, "order_process_schedules", column, definition)

    db.execute(
        "UPDATE process_production_lines SET calendar_id=? WHERE calendar_id IS NULL",
        (calendar_id,),
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS order_process_schedule_segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER NOT NULL,
            process_line_id INTEGER NOT NULL,
            segment_start_at TEXT NOT NULL,
            segment_end_at TEXT NOT NULL,
            occupied_minutes REAL NOT NULL CHECK(occupied_minutes > 0),
            shift_id INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(schedule_id) REFERENCES order_process_schedules(id) ON DELETE CASCADE,
            FOREIGN KEY(process_line_id) REFERENCES process_production_lines(id) ON DELETE RESTRICT,
            FOREIGN KEY(shift_id) REFERENCES schedule_shifts(id) ON DELETE SET NULL
        )
        """
    )
    db.execute(
        """CREATE INDEX IF NOT EXISTS idx_schedule_segments_line_time
           ON order_process_schedule_segments(process_line_id,segment_start_at,segment_end_at)"""
    )
    db.execute(
        """CREATE INDEX IF NOT EXISTS idx_schedule_segments_schedule
           ON order_process_schedule_segments(schedule_id)"""
    )
    db.execute(
        """CREATE INDEX IF NOT EXISTS idx_schedule_facts_planned_at
           ON order_process_schedules(planned_start_at,planned_end_at)"""
    )


MIGRATIONS = [
    (76, "Add process-level multi-line scheduling capacity", m076_schedule_capacity),
    (77, "Version scheduling facts and retain run ledger", m077_harden_schedule_capacity),
    (78, "Add calendar shifts and minute-level scheduling facts", m078_precision_schedule_capacity),
]
