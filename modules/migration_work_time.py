"""Work-time and completion-focus migrations for versions 28 through 30."""

import json

from modules.migration_helpers import add_column_if_missing
from modules.order_focus_config import COMPLETION_FOCUS_DEFAULT_SETTINGS
from modules.permission_catalog import default_role_permission_additions
def _ensure_completion_focus_tables(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS order_completion_focus_exceptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            detail TEXT DEFAULT '',
            expires_at TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            created_by INTEGER,
            created_by_name TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            cancelled_by INTEGER,
            cancelled_at TEXT DEFAULT '',
            cancel_reason TEXT DEFAULT ''
        )
    """)
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_focus_ex_order_status "
        "ON order_completion_focus_exceptions(order_id, status, expires_at)"
    )
    db.execute("""
        CREATE TABLE IF NOT EXISTS order_completion_focus_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            order_id INTEGER,
            process_id INTEGER,
            recommended_order_id INTEGER,
            recommended_order_no TEXT DEFAULT '',
            mode TEXT DEFAULT '',
            blocking INTEGER DEFAULT 0,
            bypass_allowed INTEGER DEFAULT 0,
            reason TEXT DEFAULT '',
            detail TEXT DEFAULT '',
            user_id INTEGER,
            user_name TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_focus_events_order_created "
        "ON order_completion_focus_events(order_id, created_at DESC)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_focus_events_type_created "
        "ON order_completion_focus_events(event_type, created_at DESC)"
    )



def m028_work_time_management(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS work_time_standards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            product_code TEXT DEFAULT '',
            product_name TEXT DEFAULT '',
            route_id INTEGER,
            process_id INTEGER NOT NULL,
            standard_minutes_per_unit REAL NOT NULL DEFAULT 0,
            setup_minutes REAL DEFAULT 0,
            difficulty_factor REAL DEFAULT 1,
            effective_from TEXT DEFAULT '',
            effective_to TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            version INTEGER DEFAULT 1,
            remark TEXT DEFAULT '',
            created_by INTEGER,
            updated_by INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL,
            FOREIGN KEY (route_id) REFERENCES process_routes(id) ON DELETE SET NULL,
            FOREIGN KEY (process_id) REFERENCES processes(id) ON DELETE CASCADE,
            FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (updated_by) REFERENCES users(id) ON DELETE SET NULL
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_wt_standards_process ON work_time_standards(process_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_wt_standards_product ON work_time_standards(product_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_wt_standards_status ON work_time_standards(status)")

    db.execute("""
        CREATE TABLE IF NOT EXISTS work_time_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER,
            order_no TEXT DEFAULT '',
            serial_no TEXT DEFAULT '',
            route_id INTEGER,
            route_name TEXT DEFAULT '',
            product_code TEXT DEFAULT '',
            product_name TEXT DEFAULT '',
            standard_missing INTEGER DEFAULT 0,
            process_id INTEGER NOT NULL,
            process_name TEXT DEFAULT '',
            user_id INTEGER NOT NULL,
            user_name TEXT DEFAULT '',
            standard_id INTEGER,
            source_work_record_id INTEGER,
            quantity INTEGER DEFAULT 1,
            standard_minutes REAL DEFAULT 0,
            start_time TEXT DEFAULT '',
            end_time TEXT DEFAULT '',
            pause_minutes REAL DEFAULT 0,
            actual_minutes REAL DEFAULT 0,
            effective_minutes REAL DEFAULT 0,
            status TEXT DEFAULT 'completed',
            abnormal_reason TEXT DEFAULT '',
            review_status TEXT DEFAULT 'approved',
            reviewed_by INTEGER,
            reviewed_at TEXT DEFAULT '',
            review_note TEXT DEFAULT '',
            created_by INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE SET NULL,
            FOREIGN KEY (process_id) REFERENCES processes(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (standard_id) REFERENCES work_time_standards(id) ON DELETE SET NULL,
            FOREIGN KEY (source_work_record_id) REFERENCES work_records(id) ON DELETE SET NULL,
            FOREIGN KEY (reviewed_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_wt_records_user ON work_time_records(user_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_wt_records_process ON work_time_records(process_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_wt_records_order ON work_time_records(order_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_wt_records_route_process ON work_time_records(route_id, process_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_wt_records_standard_missing ON work_time_records(standard_missing)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_wt_records_review ON work_time_records(review_status)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_wt_records_start ON work_time_records(start_time)")

    db.execute("""
        CREATE TABLE IF NOT EXISTS work_time_review_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id INTEGER NOT NULL,
            old_effective_minutes REAL DEFAULT 0,
            new_effective_minutes REAL DEFAULT 0,
            old_review_status TEXT DEFAULT '',
            new_review_status TEXT DEFAULT '',
            reason TEXT DEFAULT '',
            reviewer_id INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (record_id) REFERENCES work_time_records(id) ON DELETE CASCADE,
            FOREIGN KEY (reviewer_id) REFERENCES users(id) ON DELETE SET NULL
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_wt_review_logs_record ON work_time_review_logs(record_id)")

    for role_code in ("production_manager",):
        additions = default_role_permission_additions(role_code)
        if not additions:
            continue
        row = db.execute("SELECT id, permissions FROM roles WHERE code = ?", (role_code,)).fetchone()
        if not row:
            continue
        try:
            permissions = json.loads(row["permissions"] or "[]")
        except (TypeError, json.JSONDecodeError):
            permissions = []
        if not isinstance(permissions, list) or "*" in permissions:
            continue
        merged = list(dict.fromkeys(permissions + additions))
        if merged != permissions:
            db.execute(
                "UPDATE roles SET permissions = ?, updated_at = datetime('now','localtime') WHERE id = ?",
                (json.dumps(merged, ensure_ascii=False), row["id"]),
            )
    db.commit()




def m029_completion_focus_events(db):
    _ensure_completion_focus_tables(db)
    for key, value in COMPLETION_FOCUS_DEFAULT_SETTINGS.items():
        db.execute('INSERT OR IGNORE INTO system_settings (key, value) VALUES (?,?)', (key, value))
    db.commit()


def m030_work_time_record_snapshots(db):
    columns = {
        "route_id": "INTEGER",
        "route_name": "TEXT DEFAULT ''",
        "product_code": "TEXT DEFAULT ''",
        "product_name": "TEXT DEFAULT ''",
        "standard_missing": "INTEGER DEFAULT 0",
    }
    for column, definition in columns.items():
        add_column_if_missing(db, "work_time_records", column, definition)
    db.execute("CREATE INDEX IF NOT EXISTS idx_wt_records_route_process ON work_time_records(route_id, process_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_wt_records_standard_missing ON work_time_records(standard_missing)")
    db.commit()

MIGRATIONS = [
    (28, "Add work time management tables", m028_work_time_management),
    (29, "Add completion focus event table", m029_completion_focus_events),
    (30, "Add work time record route and product snapshots", m030_work_time_record_snapshots),
]
