"""Performance and quality migrations for versions 23 through 27."""

import json

from modules.migration_helpers import add_column_if_missing
from modules.permission_catalog import default_role_permission_additions
def m023_performance_management(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS performance_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            year_month TEXT NOT NULL,
            role_type TEXT DEFAULT 'worker',
            output_qty INTEGER DEFAULT 0,
            report_count INTEGER DEFAULT 0,
            work_days INTEGER DEFAULT 0,
            scrap_qty INTEGER DEFAULT 0,
            rework_qty INTEGER DEFAULT 0,
            inspection_failed_qty INTEGER DEFAULT 0,
            output_score REAL DEFAULT 0,
            quality_score REAL DEFAULT 0,
            delivery_score REAL DEFAULT 0,
            discipline_score REAL DEFAULT 0,
            improvement_score REAL DEFAULT 0,
            total_score REAL DEFAULT 0,
            rank_no INTEGER DEFAULT 0,
            rank_total INTEGER DEFAULT 0,
            warning_level TEXT DEFAULT 'green',
            warning_reason TEXT DEFAULT '',
            status TEXT DEFAULT 'draft',
            generated_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(user_id, year_month),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_perf_scores_month ON performance_scores(year_month)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_perf_scores_user ON performance_scores(user_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_perf_scores_warning ON performance_scores(warning_level)")
    db.execute("""
        CREATE TABLE IF NOT EXISTS performance_improvement_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            score_id INTEGER,
            user_id INTEGER NOT NULL,
            year_month TEXT NOT NULL,
            warning_level TEXT DEFAULT 'yellow',
            reason TEXT DEFAULT '',
            goal TEXT DEFAULT '',
            actions TEXT DEFAULT '',
            owner_id INTEGER,
            due_date TEXT DEFAULT '',
            status TEXT DEFAULT 'open',
            review_result TEXT DEFAULT '',
            review_notes TEXT DEFAULT '',
            created_by INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            closed_at TEXT DEFAULT '',
            FOREIGN KEY (score_id) REFERENCES performance_scores(id) ON DELETE SET NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_perf_plans_user ON performance_improvement_plans(user_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_perf_plans_month ON performance_improvement_plans(year_month)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_perf_plans_status ON performance_improvement_plans(status)")
    db.commit()


def m024_performance_review_inputs(db):
    score_columns = {
        "discipline_deduction": "REAL DEFAULT 0",
        "discipline_reason": "TEXT DEFAULT ''",
        "improvement_deduction": "REAL DEFAULT 0",
        "improvement_reason": "TEXT DEFAULT ''",
        "manual_score": "REAL DEFAULT 0",
        "manual_comment": "TEXT DEFAULT ''",
        "score_details": "TEXT DEFAULT '{}'",
        "reviewed_by": "INTEGER",
        "reviewed_at": "TEXT DEFAULT ''",
    }
    for column, definition in score_columns.items():
        add_column_if_missing(db, "performance_scores", column, definition)

    db.execute("""
        CREATE TABLE IF NOT EXISTS performance_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            year_month TEXT NOT NULL,
            discipline_deduction REAL DEFAULT 0,
            discipline_reason TEXT DEFAULT '',
            improvement_adjustment REAL DEFAULT 0,
            improvement_reason TEXT DEFAULT '',
            manual_score REAL DEFAULT 10,
            manual_comment TEXT DEFAULT '',
            reviewed_by INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(user_id, year_month),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (reviewed_by) REFERENCES users(id) ON DELETE SET NULL
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_perf_reviews_month ON performance_reviews(year_month)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_perf_reviews_user ON performance_reviews(user_id)")
    db.commit()


def m025_process_handoff_reviews(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS process_handoff_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            serial_no TEXT DEFAULT '',
            from_process_id INTEGER NOT NULL,
            to_process_id INTEGER NOT NULL,
            from_user_id INTEGER NOT NULL,
            evaluator_user_id INTEGER NOT NULL,
            source_work_record_id INTEGER,
            quantity INTEGER DEFAULT 1,
            rating INTEGER NOT NULL,
            issue_type TEXT DEFAULT '',
            comment TEXT DEFAULT '',
            status TEXT DEFAULT 'confirmed',
            confirmed_by INTEGER,
            confirmed_at TEXT DEFAULT '',
            confirm_note TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
            FOREIGN KEY (from_process_id) REFERENCES processes(id) ON DELETE CASCADE,
            FOREIGN KEY (to_process_id) REFERENCES processes(id) ON DELETE CASCADE,
            FOREIGN KEY (from_user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (evaluator_user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (source_work_record_id) REFERENCES work_records(id) ON DELETE SET NULL,
            FOREIGN KEY (confirmed_by) REFERENCES users(id) ON DELETE SET NULL
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_handoff_reviews_month ON process_handoff_reviews(created_at)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_handoff_reviews_from_user ON process_handoff_reviews(from_user_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_handoff_reviews_status ON process_handoff_reviews(status)")
    db.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_handoff_reviews_unique_serial
        ON process_handoff_reviews(order_id, serial_no, from_process_id, to_process_id)
        WHERE serial_no IS NOT NULL AND serial_no <> ''
    """)
    db.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_handoff_reviews_unique_batch
        ON process_handoff_reviews(order_id, from_process_id, to_process_id, evaluator_user_id)
        WHERE serial_no IS NULL OR serial_no = ''
    """)
    db.commit()


def m026_grant_performance_permissions(db):
    for role_code in ("production_manager", "qc_inspector", "warehouse_keeper"):
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


def m027_quality_inspection_scoring(db):
    columns = {
        "score_total": "REAL DEFAULT 0",
        "score_detail_json": "TEXT DEFAULT '{}'",
        "defect_level": "TEXT DEFAULT ''",
        "defect_items_json": "TEXT DEFAULT '[]'",
        "suggested_result": "TEXT DEFAULT ''",
        "final_result": "TEXT DEFAULT ''",
        "override_reason": "TEXT DEFAULT ''",
    }
    for column, definition in columns.items():
        add_column_if_missing(db, "quality_inspections", column, definition)
    db.commit()



MIGRATIONS = [
    (23, "Add performance evaluation and improvement workflow", m023_performance_management),
    (24, "Deepen performance review scoring inputs", m024_performance_review_inputs),
    (25, "Add process handoff quality reviews", m025_process_handoff_reviews),
    (26, "Grant performance permissions to management roles", m026_grant_performance_permissions),
    (27, "Add quality inspection scoring fields", m027_quality_inspection_scoring),
]
