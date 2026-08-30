"""工序级多产线排程基础表与默认资源池。"""

from modules.migration_helpers import add_column_if_missing


DEFAULT_PROCESS_LINE_COUNTS = {
    "下料": 1,
    "铆接": 4,
    "焊接": 10,
    "抛丸": 1,
    "打磨": 1,
    "镗孔": 2,
    "喷漆": 2,
}


def m065_schedule_capacity(db):
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
                (process["id"], code, name, 480, "系统默认产线"),
            )


MIGRATIONS = [
    (65, "Add process-level multi-line scheduling capacity", m065_schedule_capacity),
]
