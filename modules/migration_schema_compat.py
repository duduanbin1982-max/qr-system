"""Schema compatibility helpers used by incremental migrations."""

import sqlite3


def _column_exists(db, table, column):
    return any(row[1] == column for row in db.execute(f"PRAGMA table_info({table})"))


def _add_column_if_missing(db, table, column, definition):
    if not _column_exists(db, table, column):
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


_COMPAT_TABLE_SQL = [
        """CREATE TABLE IF NOT EXISTS departments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT DEFAULT '',
            parent_id INTEGER DEFAULT NULL,
            sort_order INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (parent_id) REFERENCES departments(id) ON DELETE SET NULL
        )""",
        """CREATE TABLE IF NOT EXISTS employee_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            doc_name TEXT NOT NULL,
            doc_type TEXT DEFAULT '',
            file_path TEXT NOT NULL,
            file_size INTEGER DEFAULT 0,
            uploaded_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )""",
        """CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER DEFAULT NULL,
            title TEXT NOT NULL,
            message TEXT DEFAULT '',
            type TEXT DEFAULT 'info',
            link TEXT DEFAULT '',
            is_read INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )""",
        """CREATE TABLE IF NOT EXISTS order_remark_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            old_remark TEXT DEFAULT '',
            new_remark TEXT DEFAULT '',
            user_id INTEGER,
            user_name TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (order_id) REFERENCES orders(id)
        )""",
        """CREATE TABLE IF NOT EXISTS production_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            capacity_per_day INTEGER DEFAULT 10,
            status TEXT DEFAULT 'active',
            remark TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )""",
        """CREATE TABLE IF NOT EXISTS quality_attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inspection_id INTEGER NOT NULL,
            file_name TEXT NOT NULL,
            file_type TEXT DEFAULT '',
            file_size INTEGER DEFAULT 0,
            file_data BLOB,
            uploaded_by INTEGER,
            created_at TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS route_price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            route_id INTEGER NOT NULL,
            process_id INTEGER NOT NULL,
            old_price REAL,
            new_price REAL NOT NULL,
            effective_date TEXT,
            remark TEXT,
            operator_id INTEGER,
            operator_name TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (route_id) REFERENCES process_routes(id)
        )""",
        """CREATE TABLE IF NOT EXISTS user_processes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            process_id INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (process_id) REFERENCES processes(id) ON DELETE CASCADE,
            UNIQUE(user_id, process_id)
        )""",
        """CREATE TABLE IF NOT EXISTS wage_adjustments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            year_month TEXT NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('bonus','deduction','allowance')),
            amount REAL NOT NULL DEFAULT 0,
            reason TEXT,
            created_by TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id, year_month, type, reason)
        )""",
        """CREATE TABLE IF NOT EXISTS wage_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            employee_name TEXT DEFAULT '',
            employee_no TEXT DEFAULT '',
            position_name TEXT DEFAULT '',
            year_month TEXT NOT NULL,
            total_quantity INTEGER DEFAULT 0,
            total_wage REAL DEFAULT 0,
            rework_wage REAL DEFAULT 0,
            details_json TEXT DEFAULT '[]',
            status TEXT DEFAULT 'draft',
            locked_at TEXT DEFAULT '',
            locked_by TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            notes TEXT DEFAULT '',
            confirmed_by TEXT DEFAULT '',
            confirmed_at TEXT DEFAULT '',
            FOREIGN KEY (employee_id) REFERENCES users(id)
        )""",
        """CREATE TABLE IF NOT EXISTS work_time_standards (
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
        )""",
        """CREATE TABLE IF NOT EXISTS work_time_records (
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
        )""",
        """CREATE TABLE IF NOT EXISTS work_time_review_logs (
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
        )""",
    ]

_COMPAT_COLUMNS = {
        'customers': [('tags', 'TEXT DEFAULT ""')],
        'inventory': [('order_id', 'INTEGER'), ('category', 'TEXT DEFAULT ""'), ('unit_cost', 'REAL DEFAULT 0'), ('last_count_date', 'TEXT DEFAULT ""'), ('reserved', 'INTEGER DEFAULT 0')],
        'materials': [('material_type', 'TEXT DEFAULT ""')],
        'orders': [('pre_delete_status', 'TEXT DEFAULT ""'), ('qr_mode', 'TEXT DEFAULT ""'), ('production_line_id', 'INTEGER'), ('delivery_status', 'TEXT DEFAULT "pending"')],
        'positions': [('updated_at', "TEXT DEFAULT ''")],
        'process_routes': [('category', 'TEXT DEFAULT ""')],
        'processes': [('updated_at', "TEXT DEFAULT ''")],
        'product_items': [('weight', 'REAL DEFAULT 0'), ('production_date', 'TEXT DEFAULT ""'), ('completed_at', 'TEXT DEFAULT ""'), ('version', 'INTEGER DEFAULT 1')],
        'products': [('deleted_at', 'TEXT DEFAULT NULL'), ('lower_opening', 'TEXT DEFAULT ""')],
        'quality_inspections': [
            ('order_no', 'TEXT DEFAULT ""'), ('product_code', 'TEXT DEFAULT ""'),
            ('process_name', 'TEXT DEFAULT ""'), ('inspector_name', 'TEXT DEFAULT ""'),
            ('rework_process', 'TEXT DEFAULT ""'), ('remark', 'TEXT DEFAULT ""'),
            ('serial_no', 'TEXT DEFAULT ""'), ('score_total', 'REAL DEFAULT 0'),
            ('score_detail_json', "TEXT DEFAULT '{}'"), ('defect_level', 'TEXT DEFAULT ""'),
            ('defect_items_json', "TEXT DEFAULT '[]'"), ('suggested_result', 'TEXT DEFAULT ""'),
            ('final_result', 'TEXT DEFAULT ""'), ('override_reason', 'TEXT DEFAULT ""')
        ],
        'rework_records': [('status', 'TEXT DEFAULT "pending"'), ('completed_at', 'TEXT DEFAULT ""'), ('completed_by', 'INTEGER'), ('result', 'TEXT DEFAULT ""'), ('result_remark', 'TEXT DEFAULT ""'), ('duration_hours', 'REAL DEFAULT 0')],
        'roles': [('updated_at', "TEXT DEFAULT ''")],
        'role_groups': [('updated_at', "TEXT DEFAULT ''"), ('permissions', 'TEXT DEFAULT ""'), ('data_scope', "TEXT DEFAULT 'all'")],
        'scrap_records': [('rework', 'INTEGER DEFAULT 0')],
        'shipment_items': [('order_id', 'INTEGER'), ('product_code', 'TEXT DEFAULT ""'), ('order_no', 'TEXT DEFAULT ""')],
        'shipments': [('deduction_mode', 'TEXT DEFAULT "auto"'), ('logistics_company', 'TEXT DEFAULT ""'), ('tracking_no', 'TEXT DEFAULT ""'), ('cancelled_at', 'TEXT DEFAULT ""'), ('reserved_at', 'TEXT DEFAULT ""'), ('material_bill_no', 'TEXT DEFAULT ""'), ('receivable_amount', 'REAL DEFAULT 0'), ('paid_amount', 'REAL DEFAULT 0'), ('payment_status', 'TEXT DEFAULT "unpaid"'), ('payment_date', 'TEXT DEFAULT ""'), ('payment_method', 'TEXT DEFAULT ""'), ('payment_remark', 'TEXT DEFAULT ""')],
        'system_settings': [('updated_at', "TEXT DEFAULT ''")],
        'work_time_records': [
            ('route_id', 'INTEGER'), ('route_name', 'TEXT DEFAULT ""'),
            ('product_code', 'TEXT DEFAULT ""'), ('product_name', 'TEXT DEFAULT ""'),
            ('standard_missing', 'INTEGER DEFAULT 0')
        ],
        'users': [('deleted_at', 'TEXT DEFAULT NULL'), ('department_id', 'INTEGER')],
    }

def _ensure_compat_tables(db):
    for sql in _COMPAT_TABLE_SQL:
        db.execute(sql)

def _ensure_compat_columns(db):
    for table, table_columns in _COMPAT_COLUMNS.items():
        for column, definition in table_columns:
            try:
                _add_column_if_missing(db, table, column, definition)
            except sqlite3.OperationalError:
                pass

def ensure_current_schema_compat(db):
    _ensure_compat_tables(db)
    _ensure_compat_columns(db)
    db.execute(
        'CREATE UNIQUE INDEX IF NOT EXISTS idx_wage_snapshots_employee_month '
        'ON wage_snapshots(employee_id, year_month)'
    )
    db.execute('CREATE INDEX IF NOT EXISTS idx_wt_standards_process ON work_time_standards(process_id)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_wt_standards_product ON work_time_standards(product_id)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_wt_standards_status ON work_time_standards(status)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_wt_records_user ON work_time_records(user_id)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_wt_records_process ON work_time_records(process_id)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_wt_records_order ON work_time_records(order_id)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_wt_records_review ON work_time_records(review_status)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_wt_records_start ON work_time_records(start_time)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_wt_review_logs_record ON work_time_review_logs(record_id)')
