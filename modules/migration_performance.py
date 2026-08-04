"""Performance and quality migrations for versions 23 through 56."""

from datetime import datetime
import hashlib
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


def _performance_month_bounds(year_month):
    start = datetime.strptime(year_month, "%Y-%m").replace(
        day=1, hour=7, minute=0, second=0, microsecond=0
    )
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return (
        start.strftime("%Y-%m-%d %H:%M:%S"),
        end.strftime("%Y-%m-%d %H:%M:%S"),
    )


def _json_object(value):
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _position_snapshot(score_details):
    raw_id = score_details.get("position_id")
    try:
        position_id = int(raw_id) if raw_id not in (None, "") else None
    except (TypeError, ValueError):
        position_id = None
    return position_id, str(score_details.get("position_name") or "").strip()


def _create_performance_ledger_tables(db):
    statements = (
        """
        CREATE TABLE IF NOT EXISTS performance_rule_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL DEFAULT '',
            weights_json TEXT NOT NULL DEFAULT '{}',
            warning_levels_json TEXT NOT NULL DEFAULT '[]',
            scoring_parameters_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','published','retired')),
            effective_from_month TEXT NOT NULL DEFAULT '',
            effective_to_month TEXT NOT NULL DEFAULT '',
            created_by INTEGER,
            created_by_name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            published_by INTEGER,
            published_by_name TEXT NOT NULL DEFAULT '',
            published_at TEXT NOT NULL DEFAULT '',
            row_version INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (published_by) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS performance_position_target_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_id INTEGER NOT NULL,
            position_name_snapshot TEXT NOT NULL DEFAULT '',
            target_output_qty REAL NOT NULL,
            minimum_effective_work_days INTEGER NOT NULL,
            effective_from_month TEXT NOT NULL,
            effective_to_month TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','approved','retired')),
            created_by INTEGER,
            created_by_name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            approved_by INTEGER,
            approved_by_name TEXT NOT NULL DEFAULT '',
            approved_at TEXT NOT NULL DEFAULT '',
            row_version INTEGER NOT NULL DEFAULT 1,
            CHECK(target_output_qty > 0),
            CHECK(minimum_effective_work_days > 0),
            FOREIGN KEY (position_id) REFERENCES positions(id) ON DELETE RESTRICT,
            FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (approved_by) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS performance_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            production_month TEXT NOT NULL,
            version INTEGER NOT NULL,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            source_cutoff_at TEXT NOT NULL DEFAULT '',
            rule_version_id INTEGER,
            input_digest TEXT NOT NULL DEFAULT '',
            idempotency_key TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN (
                'draft','supervisor_review','approval_pending','approved','superseded','cancelled'
            )),
            prepared_by INTEGER,
            prepared_by_name TEXT NOT NULL DEFAULT '',
            prepared_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            submitted_at TEXT NOT NULL DEFAULT '',
            approved_by INTEGER,
            approved_by_name TEXT NOT NULL DEFAULT '',
            approved_at TEXT NOT NULL DEFAULT '',
            supersedes_batch_id INTEGER,
            superseded_by_batch_id INTEGER,
            revision_reason TEXT NOT NULL DEFAULT '',
            row_version INTEGER NOT NULL DEFAULT 1,
            legacy_imported INTEGER NOT NULL DEFAULT 0 CHECK(legacy_imported IN (0,1)),
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(production_month, version),
            FOREIGN KEY (rule_version_id) REFERENCES performance_rule_versions(id) ON DELETE RESTRICT,
            FOREIGN KEY (prepared_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (approved_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (supersedes_batch_id) REFERENCES performance_batches(id) ON DELETE RESTRICT,
            FOREIGN KEY (superseded_by_batch_id) REFERENCES performance_batches(id) ON DELETE RESTRICT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS performance_reviews_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            revision INTEGER NOT NULL,
            discipline_deduction REAL NOT NULL DEFAULT 0,
            discipline_reason TEXT NOT NULL DEFAULT '',
            improvement_adjustment REAL NOT NULL DEFAULT 0,
            improvement_reason TEXT NOT NULL DEFAULT '',
            manual_score REAL NOT NULL DEFAULT 10,
            manual_comment TEXT NOT NULL DEFAULT '',
            reviewed_by INTEGER,
            reviewed_by_name TEXT NOT NULL DEFAULT '',
            reviewed_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            input_digest TEXT NOT NULL DEFAULT '',
            idempotency_key TEXT UNIQUE,
            legacy_review_id INTEGER UNIQUE,
            legacy_review_json TEXT NOT NULL DEFAULT '{}',
            UNIQUE(batch_id, user_id, revision),
            FOREIGN KEY (batch_id) REFERENCES performance_batches(id) ON DELETE RESTRICT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT,
            FOREIGN KEY (reviewed_by) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS performance_score_revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            revision INTEGER NOT NULL,
            employee_name_snapshot TEXT NOT NULL DEFAULT '',
            employee_no_snapshot TEXT NOT NULL DEFAULT '',
            role_type_snapshot TEXT NOT NULL DEFAULT '',
            department_id_snapshot INTEGER,
            department_name_snapshot TEXT NOT NULL DEFAULT '',
            position_id_snapshot INTEGER,
            position_name_snapshot TEXT NOT NULL DEFAULT '',
            eligibility_status TEXT NOT NULL DEFAULT 'eligible' CHECK(eligibility_status IN ('eligible','insufficient_data')),
            eligibility_reason_code TEXT NOT NULL DEFAULT '',
            eligibility_reason TEXT NOT NULL DEFAULT '',
            output_qty REAL NOT NULL DEFAULT 0,
            report_count INTEGER NOT NULL DEFAULT 0,
            work_days INTEGER NOT NULL DEFAULT 0,
            scrap_qty REAL NOT NULL DEFAULT 0,
            rework_qty REAL NOT NULL DEFAULT 0,
            inspection_failed_qty REAL NOT NULL DEFAULT 0,
            output_score REAL,
            quality_score REAL,
            delivery_score REAL,
            discipline_score REAL,
            improvement_score REAL,
            total_score REAL,
            rank_no INTEGER,
            rank_total INTEGER,
            warning_level TEXT,
            warning_reason TEXT NOT NULL DEFAULT '',
            discipline_deduction REAL NOT NULL DEFAULT 0,
            discipline_reason TEXT NOT NULL DEFAULT '',
            improvement_deduction REAL NOT NULL DEFAULT 0,
            improvement_reason TEXT NOT NULL DEFAULT '',
            manual_score REAL NOT NULL DEFAULT 10,
            manual_comment TEXT NOT NULL DEFAULT '',
            score_details_json TEXT NOT NULL DEFAULT '{}',
            rule_version_id INTEGER,
            position_target_version_id INTEGER,
            review_revision_id INTEGER,
            input_digest TEXT NOT NULL DEFAULT '',
            ranking_digest TEXT NOT NULL DEFAULT '',
            calculation_group_id TEXT NOT NULL DEFAULT '',
            calculated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            created_by INTEGER,
            created_by_name TEXT NOT NULL DEFAULT '',
            legacy_score_id INTEGER UNIQUE,
            legacy_score_json TEXT NOT NULL DEFAULT '{}',
            prior_revisions_unavailable INTEGER NOT NULL DEFAULT 0 CHECK(prior_revisions_unavailable IN (0,1)),
            UNIQUE(batch_id, user_id, revision),
            FOREIGN KEY (batch_id) REFERENCES performance_batches(id) ON DELETE RESTRICT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT,
            FOREIGN KEY (department_id_snapshot) REFERENCES departments(id) ON DELETE SET NULL,
            FOREIGN KEY (position_id_snapshot) REFERENCES positions(id) ON DELETE SET NULL,
            FOREIGN KEY (rule_version_id) REFERENCES performance_rule_versions(id) ON DELETE RESTRICT,
            FOREIGN KEY (position_target_version_id) REFERENCES performance_position_target_versions(id) ON DELETE RESTRICT,
            FOREIGN KEY (review_revision_id) REFERENCES performance_reviews_v2(id) ON DELETE RESTRICT,
            FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS performance_quality_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            quantity REAL NOT NULL DEFAULT 0,
            order_id INTEGER,
            process_id INTEGER,
            user_id INTEGER,
            business_at TEXT NOT NULL DEFAULT '',
            snapshot_json TEXT NOT NULL DEFAULT '{}',
            event_digest TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE SET NULL,
            FOREIGN KEY (process_id) REFERENCES processes(id) ON DELETE SET NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS performance_quality_event_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quality_event_id INTEGER NOT NULL,
            source_type TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(source_type, source_id),
            FOREIGN KEY (quality_event_id) REFERENCES performance_quality_events(id) ON DELETE RESTRICT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS performance_source_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL,
            fact_type TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            canonical_event_id INTEGER,
            business_at TEXT NOT NULL DEFAULT '',
            user_id INTEGER,
            employee_name_snapshot TEXT NOT NULL DEFAULT '',
            employee_no_snapshot TEXT NOT NULL DEFAULT '',
            department_id_snapshot INTEGER,
            department_name_snapshot TEXT NOT NULL DEFAULT '',
            position_id_snapshot INTEGER,
            position_name_snapshot TEXT NOT NULL DEFAULT '',
            order_id INTEGER,
            order_no_snapshot TEXT NOT NULL DEFAULT '',
            product_id INTEGER,
            product_code_snapshot TEXT NOT NULL DEFAULT '',
            product_name_snapshot TEXT NOT NULL DEFAULT '',
            process_id INTEGER,
            process_name_snapshot TEXT NOT NULL DEFAULT '',
            quantity REAL NOT NULL DEFAULT 0,
            payload_json TEXT NOT NULL DEFAULT '{}',
            source_digest TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(batch_id, fact_type, source_type, source_id),
            FOREIGN KEY (batch_id) REFERENCES performance_batches(id) ON DELETE RESTRICT,
            FOREIGN KEY (canonical_event_id) REFERENCES performance_quality_events(id) ON DELETE RESTRICT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (department_id_snapshot) REFERENCES departments(id) ON DELETE SET NULL,
            FOREIGN KEY (position_id_snapshot) REFERENCES positions(id) ON DELETE SET NULL,
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE SET NULL,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL,
            FOREIGN KEY (process_id) REFERENCES processes(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS performance_data_exceptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER,
            user_id INTEGER,
            exception_type TEXT NOT NULL,
            source_type TEXT NOT NULL DEFAULT '',
            source_id INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','resolved','confirmed_insufficient','excluded')),
            snapshot_json TEXT NOT NULL DEFAULT '{}',
            resolution_json TEXT NOT NULL DEFAULT '{}',
            resolution_reason TEXT NOT NULL DEFAULT '',
            resolved_by INTEGER,
            resolved_by_name TEXT NOT NULL DEFAULT '',
            resolved_at TEXT NOT NULL DEFAULT '',
            row_version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(batch_id, exception_type, source_type, source_id),
            FOREIGN KEY (batch_id) REFERENCES performance_batches(id) ON DELETE RESTRICT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (resolved_by) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS performance_batch_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER,
            event_type TEXT NOT NULL,
            from_status TEXT NOT NULL DEFAULT '',
            to_status TEXT NOT NULL DEFAULT '',
            operator_id INTEGER,
            operator_name TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}',
            request_id TEXT NOT NULL DEFAULT '',
            idempotency_key TEXT UNIQUE,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (batch_id) REFERENCES performance_batches(id) ON DELETE RESTRICT,
            FOREIGN KEY (operator_id) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS performance_assignment_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            employee_name_snapshot TEXT NOT NULL DEFAULT '',
            employee_no_snapshot TEXT NOT NULL DEFAULT '',
            position_id INTEGER,
            position_name_snapshot TEXT NOT NULL DEFAULT '',
            department_id INTEGER,
            department_name_snapshot TEXT NOT NULL DEFAULT '',
            valid_from TEXT NOT NULL,
            valid_to TEXT NOT NULL DEFAULT '',
            source_type TEXT NOT NULL DEFAULT 'application',
            source_key TEXT NOT NULL,
            created_by INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(user_id, source_key),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT,
            FOREIGN KEY (position_id) REFERENCES positions(id) ON DELETE SET NULL,
            FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE SET NULL,
            FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS performance_department_scopes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            department_id INTEGER NOT NULL,
            granted_by INTEGER,
            granted_by_name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(user_id, department_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE CASCADE,
            FOREIGN KEY (granted_by) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS performance_improvement_plans_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            score_revision_id INTEGER,
            user_id INTEGER NOT NULL,
            employee_name_snapshot TEXT NOT NULL DEFAULT '',
            employee_no_snapshot TEXT NOT NULL DEFAULT '',
            department_id_snapshot INTEGER,
            department_name_snapshot TEXT NOT NULL DEFAULT '',
            production_month TEXT NOT NULL,
            warning_level_snapshot TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT '',
            goal TEXT NOT NULL DEFAULT '',
            actions TEXT NOT NULL DEFAULT '',
            owner_id INTEGER,
            owner_name_snapshot TEXT NOT NULL DEFAULT '',
            due_date TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','active','reassessment_pending','closed','cancelled')),
            reassessment_round INTEGER NOT NULL DEFAULT 0,
            row_version INTEGER NOT NULL DEFAULT 1,
            created_by INTEGER,
            created_by_name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            closed_at TEXT NOT NULL DEFAULT '',
            cancelled_at TEXT NOT NULL DEFAULT '',
            cancellation_reason TEXT NOT NULL DEFAULT '',
            legacy_plan_id INTEGER UNIQUE,
            legacy_plan_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (score_revision_id) REFERENCES performance_score_revisions(id) ON DELETE SET NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT,
            FOREIGN KEY (department_id_snapshot) REFERENCES departments(id) ON DELETE SET NULL,
            FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS performance_plan_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            from_status TEXT NOT NULL DEFAULT '',
            to_status TEXT NOT NULL DEFAULT '',
            reassessment_round INTEGER NOT NULL DEFAULT 0,
            operator_id INTEGER,
            operator_name TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}',
            idempotency_key TEXT UNIQUE,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (plan_id) REFERENCES performance_improvement_plans_v2(id) ON DELETE RESTRICT,
            FOREIGN KEY (operator_id) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS performance_plan_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL,
            reassessment_round INTEGER NOT NULL DEFAULT 0,
            evidence_type TEXT NOT NULL DEFAULT 'note',
            description TEXT NOT NULL DEFAULT '',
            file_name TEXT NOT NULL DEFAULT '',
            file_path TEXT NOT NULL DEFAULT '',
            source_url TEXT NOT NULL DEFAULT '',
            submitted_by INTEGER,
            submitted_by_name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (plan_id) REFERENCES performance_improvement_plans_v2(id) ON DELETE RESTRICT,
            FOREIGN KEY (submitted_by) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS performance_plan_reassessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL,
            reassessment_round INTEGER NOT NULL,
            result TEXT NOT NULL CHECK(result IN ('passed','failed')),
            notes TEXT NOT NULL DEFAULT '',
            evidence_ids_json TEXT NOT NULL DEFAULT '[]',
            reassessed_by INTEGER,
            reassessed_by_name TEXT NOT NULL DEFAULT '',
            reassessed_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            idempotency_key TEXT UNIQUE,
            UNIQUE(plan_id, reassessment_round),
            FOREIGN KEY (plan_id) REFERENCES performance_improvement_plans_v2(id) ON DELETE RESTRICT,
            FOREIGN KEY (reassessed_by) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS performance_permission_migration_report (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role_id INTEGER NOT NULL UNIQUE,
            role_code TEXT NOT NULL DEFAULT '',
            role_name TEXT NOT NULL DEFAULT '',
            old_permissions_json TEXT NOT NULL DEFAULT '[]',
            new_permissions_json TEXT NOT NULL DEFAULT '[]',
            assigned_user_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE RESTRICT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS performance_migration_manifests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            production_month TEXT NOT NULL UNIQUE,
            legacy_batch_id INTEGER NOT NULL,
            source_score_count INTEGER NOT NULL DEFAULT 0,
            overwritten_score_count INTEGER NOT NULL DEFAULT 0,
            missing_position_count INTEGER NOT NULL DEFAULT 0,
            records_json TEXT NOT NULL DEFAULT '[]',
            manifest_sha256 TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (legacy_batch_id) REFERENCES performance_batches(id) ON DELETE RESTRICT
        )
        """,
    )
    for statement in statements:
        db.execute(statement)


def _create_performance_ledger_indexes(db):
    statements = (
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_performance_current_approved ON performance_batches(production_month) WHERE status='approved'",
        "CREATE INDEX IF NOT EXISTS idx_performance_batches_month_status ON performance_batches(production_month,status)",
        "CREATE INDEX IF NOT EXISTS idx_performance_score_batch_user ON performance_score_revisions(batch_id,user_id,revision DESC)",
        "CREATE INDEX IF NOT EXISTS idx_performance_score_position ON performance_score_revisions(batch_id,position_id_snapshot,total_score DESC)",
        "CREATE INDEX IF NOT EXISTS idx_performance_fact_batch_user ON performance_source_facts(batch_id,user_id)",
        "CREATE INDEX IF NOT EXISTS idx_performance_fact_business_at ON performance_source_facts(business_at)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_performance_fact_canonical ON performance_source_facts(batch_id,fact_type,canonical_event_id) WHERE canonical_event_id IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS idx_performance_exception_batch_status ON performance_data_exceptions(batch_id,status)",
        "CREATE INDEX IF NOT EXISTS idx_performance_event_batch ON performance_batch_events(batch_id,created_at)",
        "CREATE INDEX IF NOT EXISTS idx_performance_assignment_user_period ON performance_assignment_history(user_id,valid_from,valid_to)",
        "CREATE INDEX IF NOT EXISTS idx_performance_scope_user ON performance_department_scopes(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_performance_plan_user_month ON performance_improvement_plans_v2(user_id,production_month)",
        "CREATE INDEX IF NOT EXISTS idx_performance_plan_status ON performance_improvement_plans_v2(status,due_date)",
        "CREATE INDEX IF NOT EXISTS idx_performance_quality_event_user_time ON performance_quality_events(user_id,business_at)",
    )
    for statement in statements:
        db.execute(statement)


def _legacy_performance_months(db):
    rows = db.execute(
        "SELECT year_month FROM performance_scores WHERE COALESCE(year_month,'')<>'' "
        "UNION SELECT year_month FROM performance_reviews WHERE COALESCE(year_month,'')<>'' "
        "UNION SELECT year_month FROM performance_improvement_plans WHERE COALESCE(year_month,'')<>'' "
        "ORDER BY year_month"
    ).fetchall()
    return [row[0] for row in rows]


def _ensure_legacy_performance_batch(db, production_month):
    existing = db.execute(
        "SELECT id FROM performance_batches WHERE production_month=? AND legacy_imported=1",
        (production_month,),
    ).fetchone()
    if existing:
        return existing[0], False
    period_start, period_end = _performance_month_bounds(production_month)
    cursor = db.execute(
        """
        INSERT INTO performance_batches (
            production_month,version,period_start,period_end,source_cutoff_at,input_digest,
            idempotency_key,status,prepared_by_name,approved_by_name,approved_at,
            revision_reason,legacy_imported
        ) VALUES (?,?,?,?,?,'legacy-performance-scores',?,'approved','legacy import',
                  'legacy import',datetime('now','localtime'),'Imported immutable Legacy V1 performance',1)
        """,
        (
            production_month,
            1,
            period_start,
            period_end,
            period_end,
            f"legacy:performance:{production_month}:v1",
        ),
    )
    return cursor.lastrowid, True


def _import_legacy_performance_scores(db, production_month, batch_id):
    existing = db.execute(
        "SELECT COUNT(*) FROM performance_score_revisions WHERE batch_id=? AND legacy_score_id IS NOT NULL",
        (batch_id,),
    ).fetchone()[0]
    if existing:
        return
    rows = db.execute(
        "SELECT ps.*,u.name AS employee_name,u.employee_no,u.role AS employee_role "
        "FROM performance_scores ps LEFT JOIN users u ON u.id=ps.user_id "
        "WHERE ps.year_month=? ORDER BY ps.id",
        (production_month,),
    ).fetchall()
    manifest_records = []
    overwritten_count = 0
    missing_position_count = 0
    for row in rows:
        item = dict(row)
        details = _json_object(item.get("score_details"))
        position_id, position_name = _position_snapshot(details)
        prior_unavailable = int(
            bool(item.get("updated_at"))
            and bool(item.get("generated_at"))
            and str(item["updated_at"]) > str(item["generated_at"])
        )
        overwritten_count += prior_unavailable
        if position_id is None or not position_name:
            missing_position_count += 1
        cursor = db.execute(
            """
            INSERT INTO performance_score_revisions (
                batch_id,user_id,revision,employee_name_snapshot,employee_no_snapshot,role_type_snapshot,
                position_id_snapshot,position_name_snapshot,eligibility_status,
                output_qty,report_count,work_days,scrap_qty,rework_qty,inspection_failed_qty,
                output_score,quality_score,delivery_score,discipline_score,improvement_score,total_score,
                rank_no,rank_total,warning_level,warning_reason,discipline_deduction,discipline_reason,
                improvement_deduction,improvement_reason,manual_score,manual_comment,score_details_json,
                input_digest,calculated_at,created_by_name,legacy_score_id,legacy_score_json,
                prior_revisions_unavailable
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
                      'legacy import',?,?,?)
            """,
            (
                batch_id,
                item["user_id"],
                1,
                item.get("employee_name") or "",
                item.get("employee_no") or "",
                item.get("role_type") or item.get("employee_role") or "worker",
                position_id,
                position_name,
                "eligible",
                item.get("output_qty") or 0,
                item.get("report_count") or 0,
                item.get("work_days") or 0,
                item.get("scrap_qty") or 0,
                item.get("rework_qty") or 0,
                item.get("inspection_failed_qty") or 0,
                item.get("output_score"),
                item.get("quality_score"),
                item.get("delivery_score"),
                item.get("discipline_score"),
                item.get("improvement_score"),
                item.get("total_score"),
                item.get("rank_no"),
                item.get("rank_total"),
                item.get("warning_level"),
                item.get("warning_reason") or "",
                item.get("discipline_deduction") or 0,
                item.get("discipline_reason") or "",
                item.get("improvement_deduction") or 0,
                item.get("improvement_reason") or "",
                item.get("manual_score") if item.get("manual_score") is not None else 10,
                item.get("manual_comment") or "",
                _json_text(details),
                f"legacy:performance_score:{item['id']}:{item.get('updated_at') or ''}",
                item.get("updated_at") or item.get("generated_at") or "",
                item["id"],
                _json_text(item),
                prior_unavailable,
            ),
        )
        if position_id is None or not position_name:
            db.execute(
                """
                INSERT OR IGNORE INTO performance_data_exceptions (
                    batch_id,user_id,exception_type,source_type,source_id,snapshot_json
                ) VALUES (?,?,?,?,?,?)
                """,
                (
                    batch_id,
                    item["user_id"],
                    "missing_position_snapshot",
                    "performance_scores",
                    item["id"],
                    _json_text({"legacy_score_id": item["id"], "year_month": production_month}),
                ),
            )
        manifest_records.append(
            {
                "legacy_score_id": item["id"],
                "user_id": item["user_id"],
                "prior_revisions_unavailable": prior_unavailable,
                "missing_position_snapshot": int(position_id is None or not position_name),
                "revision_id": cursor.lastrowid,
            }
        )
    records_json = _json_text(manifest_records)
    manifest_sha256 = hashlib.sha256(records_json.encode("utf-8")).hexdigest()
    db.execute(
        """
        INSERT OR IGNORE INTO performance_migration_manifests (
            production_month,legacy_batch_id,source_score_count,overwritten_score_count,
            missing_position_count,records_json,manifest_sha256
        ) VALUES (?,?,?,?,?,?,?)
        """,
        (
            production_month,
            batch_id,
            len(rows),
            overwritten_count,
            missing_position_count,
            records_json,
            manifest_sha256,
        ),
    )


def _import_legacy_performance_reviews(db, production_month, batch_id):
    rows = db.execute(
        "SELECT pr.*,u.name AS reviewer_name FROM performance_reviews pr "
        "LEFT JOIN users u ON u.id=pr.reviewed_by "
        "WHERE pr.year_month=? AND NOT EXISTS ("
        "SELECT 1 FROM performance_reviews_v2 imported WHERE imported.legacy_review_id=pr.id"
        ") ORDER BY pr.id",
        (production_month,),
    ).fetchall()
    for row in rows:
        item = dict(row)
        db.execute(
            """
            INSERT OR IGNORE INTO performance_reviews_v2 (
                batch_id,user_id,revision,discipline_deduction,discipline_reason,
                improvement_adjustment,improvement_reason,manual_score,manual_comment,
                reviewed_by,reviewed_by_name,reviewed_at,input_digest,legacy_review_id,
                legacy_review_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                batch_id,
                item["user_id"],
                1,
                item.get("discipline_deduction") or 0,
                item.get("discipline_reason") or "",
                item.get("improvement_adjustment") or 0,
                item.get("improvement_reason") or "",
                item.get("manual_score") if item.get("manual_score") is not None else 10,
                item.get("manual_comment") or "",
                item.get("reviewed_by"),
                item.get("reviewer_name") or "",
                item.get("updated_at") or item.get("created_at") or "",
                f"legacy:performance_review:{item['id']}:{item.get('updated_at') or ''}",
                item["id"],
                _json_text(item),
            ),
        )


def _legacy_plan_status(status):
    if status in ("closed", "passed"):
        return "closed", ""
    if status == "open":
        return "active", ""
    if status == "failed":
        return "active", "legacy_plan_reassessment_missing"
    return "draft", "legacy_plan_status_unmapped"


def _import_legacy_performance_plans(db, production_month, batch_id):
    rows = db.execute(
        "SELECT pip.*,u.name AS employee_name,u.employee_no,owner.name AS owner_name,"
        "creator.name AS creator_name FROM performance_improvement_plans pip "
        "LEFT JOIN users u ON u.id=pip.user_id "
        "LEFT JOIN users owner ON owner.id=pip.owner_id "
        "LEFT JOIN users creator ON creator.id=pip.created_by "
        "WHERE pip.year_month=? ORDER BY pip.id",
        (production_month,),
    ).fetchall()
    for row in rows:
        item = dict(row)
        status, exception_type = _legacy_plan_status(item.get("status"))
        score_revision = None
        if item.get("score_id"):
            score_revision = db.execute(
                "SELECT id FROM performance_score_revisions WHERE legacy_score_id=?",
                (item["score_id"],),
            ).fetchone()
        cursor = db.execute(
            """
            INSERT OR IGNORE INTO performance_improvement_plans_v2 (
                score_revision_id,user_id,employee_name_snapshot,employee_no_snapshot,
                production_month,warning_level_snapshot,reason,goal,actions,owner_id,
                owner_name_snapshot,due_date,status,created_by,created_by_name,created_at,
                updated_at,closed_at,legacy_plan_id,legacy_plan_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                score_revision[0] if score_revision else None,
                item["user_id"],
                item.get("employee_name") or "",
                item.get("employee_no") or "",
                production_month,
                item.get("warning_level") or "",
                item.get("reason") or "",
                item.get("goal") or "",
                item.get("actions") or "",
                item.get("owner_id"),
                item.get("owner_name") or "",
                item.get("due_date") or "",
                status,
                item.get("created_by"),
                item.get("creator_name") or "",
                item.get("created_at") or "",
                item.get("updated_at") or "",
                item.get("closed_at") or "",
                item["id"],
                _json_text(item),
            ),
        )
        if exception_type and cursor.rowcount:
            db.execute(
                """
                INSERT OR IGNORE INTO performance_data_exceptions (
                    batch_id,user_id,exception_type,source_type,source_id,snapshot_json
                ) VALUES (?,?,?,?,?,?)
                """,
                (
                    batch_id,
                    item["user_id"],
                    exception_type,
                    "performance_improvement_plans",
                    item["id"],
                    _json_text({"legacy_plan_id": item["id"], "legacy_status": item.get("status")}),
                ),
            )


def _import_legacy_performance(db):
    for production_month in _legacy_performance_months(db):
        batch_id, created = _ensure_legacy_performance_batch(db, production_month)
        _import_legacy_performance_scores(db, production_month, batch_id)
        _import_legacy_performance_reviews(db, production_month, batch_id)
        _import_legacy_performance_plans(db, production_month, batch_id)
        if created:
            db.execute(
                """
                INSERT INTO performance_batch_events (
                    batch_id,event_type,to_status,operator_name,reason,payload_json,idempotency_key
                ) VALUES (?,'legacy_imported','approved','migration',?,?,?)
                """,
                (
                    batch_id,
                    "Imported current Legacy V1 performance; unavailable prior revisions were not reconstructed",
                    _json_text({"production_month": production_month, "version": 1}),
                    f"legacy:performance:{production_month}:event",
                ),
            )


def _seed_current_performance_assignments(db):
    db.execute(
        """
        INSERT OR IGNORE INTO performance_assignment_history (
            user_id,employee_name_snapshot,employee_no_snapshot,position_id,
            position_name_snapshot,department_id,department_name_snapshot,
            valid_from,source_type,source_key
        )
        SELECT u.id,u.name,COALESCE(u.employee_no,''),u.position_id,COALESCE(p.name,''),
               u.department_id,COALESCE(d.name,''),datetime('now','localtime'),
               'current_baseline','current_baseline:v56'
        FROM users u
        LEFT JOIN positions p ON p.id=u.position_id
        LEFT JOIN departments d ON d.id=u.department_id
        """
    )


def _migrate_performance_permissions(db):
    legacy_codes = {
        "performance:view",
        "performance:create",
        "performance:edit",
        "performance:delete",
        "performance:export",
    }
    rows = db.execute(
        "SELECT id,code,name,permissions FROM roles ORDER BY id"
    ).fetchall()
    for row in rows:
        try:
            permissions = json.loads(row["permissions"] or "[]")
        except (TypeError, json.JSONDecodeError):
            permissions = []
        if not isinstance(permissions, list) or "*" in permissions:
            continue
        old_permissions = list(permissions)
        has_legacy = bool(legacy_codes.intersection(permissions))
        if not has_legacy and row["code"] != "worker":
            continue
        permissions = [code for code in permissions if code not in legacy_codes]
        for code in ("page:performance", "performance:view_self"):
            if code not in permissions:
                permissions.append(code)
        assigned_user_count = db.execute(
            "SELECT COUNT(DISTINCT user_id) FROM user_roles WHERE role_id=?",
            (row["id"],),
        ).fetchone()[0]
        db.execute(
            """
            INSERT OR IGNORE INTO performance_permission_migration_report (
                role_id,role_code,role_name,old_permissions_json,new_permissions_json,
                assigned_user_count
            ) VALUES (?,?,?,?,?,?)
            """,
            (
                row["id"],
                row["code"],
                row["name"],
                json.dumps(old_permissions, ensure_ascii=False),
                json.dumps(permissions, ensure_ascii=False),
                assigned_user_count,
            ),
        )
        if permissions != old_permissions:
            db.execute(
                "UPDATE roles SET permissions=? WHERE id=?",
                (json.dumps(permissions, ensure_ascii=False), row["id"]),
            )


def _create_performance_ledger_triggers(db):
    statements = (
        """
        CREATE TRIGGER IF NOT EXISTS prevent_invalid_performance_batch_insert
        BEFORE INSERT ON performance_batches
        WHEN NEW.status<>'draft'
        BEGIN SELECT RAISE(ABORT,'performance batch initial status must be draft'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_invalid_performance_batch_transition
        BEFORE UPDATE OF status ON performance_batches
        WHEN OLD.status<>NEW.status AND NOT (
            (OLD.status='draft' AND NEW.status IN ('supervisor_review','cancelled')) OR
            (OLD.status='supervisor_review' AND NEW.status IN ('draft','approval_pending','cancelled')) OR
            (OLD.status='approval_pending' AND NEW.status IN ('supervisor_review','approved')) OR
            (OLD.status='approved' AND NEW.status='superseded')
        )
        BEGIN SELECT RAISE(ABORT,'invalid performance batch status transition'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_performance_batch_delete
        BEFORE DELETE ON performance_batches
        BEGIN SELECT RAISE(ABORT,'performance batches are auditable and cannot be deleted'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS protect_final_performance_batch_fields
        BEFORE UPDATE OF production_month,version,period_start,period_end,source_cutoff_at,
            rule_version_id,input_digest,idempotency_key,prepared_by,prepared_by_name,
            prepared_at,submitted_at,approved_by,approved_by_name,approved_at,
            supersedes_batch_id,revision_reason,legacy_imported,created_at
        ON performance_batches
        WHEN OLD.status IN ('approved','superseded','cancelled')
        BEGIN SELECT RAISE(ABORT,'final performance batches are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS protect_final_performance_batch_supersession_fields
        BEFORE UPDATE OF superseded_by_batch_id,row_version,updated_at
        ON performance_batches
        WHEN OLD.status IN ('approved','superseded','cancelled') AND NOT (
            OLD.status='approved' AND NEW.status='superseded'
        )
        BEGIN SELECT RAISE(ABORT,'final performance batches are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_invalid_performance_batch_supersession
        BEFORE UPDATE OF status ON performance_batches
        WHEN OLD.status='approved' AND NEW.status='superseded' AND (
            NEW.superseded_by_batch_id IS NULL OR NOT EXISTS (
                SELECT 1 FROM performance_batches successor
                WHERE successor.id=NEW.superseded_by_batch_id
                  AND successor.supersedes_batch_id=OLD.id
                  AND successor.production_month=OLD.production_month
                  AND successor.status='approval_pending'
            )
        )
        BEGIN SELECT RAISE(ABORT,'invalid performance batch supersession'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_missing_performance_approval_actor
        BEFORE UPDATE OF status ON performance_batches
        WHEN OLD.status='approval_pending' AND NEW.status='approved' AND NEW.approved_by IS NULL
        BEGIN SELECT RAISE(ABORT,'performance approver is required'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_same_performance_preparer_approver
        BEFORE UPDATE OF status ON performance_batches
        WHEN OLD.status='approval_pending' AND NEW.status='approved'
          AND NEW.prepared_by IS NOT NULL AND NEW.approved_by=NEW.prepared_by
        BEGIN SELECT RAISE(ABORT,'performance preparer and approver must differ'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_final_performance_score_insert
        BEFORE INSERT ON performance_score_revisions
        WHEN (SELECT status FROM performance_batches WHERE id=NEW.batch_id) NOT IN ('draft','supervisor_review')
        BEGIN SELECT RAISE(ABORT,'approved performance batches are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_performance_score_update
        BEFORE UPDATE ON performance_score_revisions
        BEGIN SELECT RAISE(ABORT,'performance score revisions are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_performance_score_delete
        BEFORE DELETE ON performance_score_revisions
        BEGIN SELECT RAISE(ABORT,'performance score revisions are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_final_performance_fact_insert
        BEFORE INSERT ON performance_source_facts
        WHEN (SELECT status FROM performance_batches WHERE id=NEW.batch_id)<>'draft'
        BEGIN SELECT RAISE(ABORT,'performance source facts can only be added to draft batches'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_performance_fact_update
        BEFORE UPDATE ON performance_source_facts
        BEGIN SELECT RAISE(ABORT,'performance source facts are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_performance_fact_delete
        BEFORE DELETE ON performance_source_facts
        BEGIN SELECT RAISE(ABORT,'performance source facts are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_invalid_performance_review_insert
        BEFORE INSERT ON performance_reviews_v2
        WHEN (SELECT status FROM performance_batches WHERE id=NEW.batch_id)<>'supervisor_review'
        BEGIN SELECT RAISE(ABORT,'performance reviews require supervisor review status'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_performance_review_update
        BEFORE UPDATE ON performance_reviews_v2
        BEGIN SELECT RAISE(ABORT,'performance reviews are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_performance_review_delete
        BEFORE DELETE ON performance_reviews_v2
        BEGIN SELECT RAISE(ABORT,'performance reviews are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_performance_event_update
        BEFORE UPDATE ON performance_batch_events
        BEGIN SELECT RAISE(ABORT,'performance events are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_performance_event_delete
        BEFORE DELETE ON performance_batch_events
        BEGIN SELECT RAISE(ABORT,'performance events are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_final_performance_exception_update
        BEFORE UPDATE ON performance_data_exceptions
        WHEN (SELECT status FROM performance_batches WHERE id=OLD.batch_id) IN ('approved','superseded','cancelled')
        BEGIN SELECT RAISE(ABORT,'final performance exceptions are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_final_performance_exception_delete
        BEFORE DELETE ON performance_data_exceptions
        WHEN (SELECT status FROM performance_batches WHERE id=OLD.batch_id) IN ('approved','superseded','cancelled')
        BEGIN SELECT RAISE(ABORT,'final performance exceptions are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_performance_quality_event_update
        BEFORE UPDATE ON performance_quality_events
        BEGIN SELECT RAISE(ABORT,'performance quality events are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_performance_quality_event_delete
        BEFORE DELETE ON performance_quality_events
        BEGIN SELECT RAISE(ABORT,'performance quality events are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_performance_quality_source_update
        BEFORE UPDATE ON performance_quality_event_sources
        BEGIN SELECT RAISE(ABORT,'performance quality event sources are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_performance_quality_source_delete
        BEFORE DELETE ON performance_quality_event_sources
        BEGIN SELECT RAISE(ABORT,'performance quality event sources are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS protect_published_performance_rule_update
        BEFORE UPDATE ON performance_rule_versions
        WHEN OLD.status IN ('published','retired') OR EXISTS (
            SELECT 1 FROM performance_batches WHERE rule_version_id=OLD.id
        )
        BEGIN SELECT RAISE(ABORT,'published performance rules are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS protect_published_performance_rule_delete
        BEFORE DELETE ON performance_rule_versions
        WHEN OLD.status IN ('published','retired') OR EXISTS (
            SELECT 1 FROM performance_batches WHERE rule_version_id=OLD.id
        )
        BEGIN SELECT RAISE(ABORT,'published performance rules are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS protect_approved_performance_target_update
        BEFORE UPDATE ON performance_position_target_versions
        WHEN OLD.status IN ('approved','retired') OR EXISTS (
            SELECT 1 FROM performance_score_revisions WHERE position_target_version_id=OLD.id
        )
        BEGIN SELECT RAISE(ABORT,'approved performance targets are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS protect_approved_performance_target_delete
        BEFORE DELETE ON performance_position_target_versions
        WHEN OLD.status IN ('approved','retired') OR EXISTS (
            SELECT 1 FROM performance_score_revisions WHERE position_target_version_id=OLD.id
        )
        BEGIN SELECT RAISE(ABORT,'approved performance targets are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_invalid_performance_plan_transition
        BEFORE UPDATE OF status ON performance_improvement_plans_v2
        WHEN OLD.status<>NEW.status AND NOT (
            (OLD.status='draft' AND NEW.status IN ('active','cancelled')) OR
            (OLD.status='active' AND NEW.status IN ('reassessment_pending','cancelled')) OR
            (OLD.status='reassessment_pending' AND NEW.status IN ('active','closed'))
        )
        BEGIN SELECT RAISE(ABORT,'invalid performance plan status transition'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_performance_plan_delete
        BEFORE DELETE ON performance_improvement_plans_v2
        BEGIN SELECT RAISE(ABORT,'performance improvement plans are auditable and cannot be deleted'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_performance_plan_event_update
        BEFORE UPDATE ON performance_plan_events
        BEGIN SELECT RAISE(ABORT,'performance plan events are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_performance_plan_event_delete
        BEFORE DELETE ON performance_plan_events
        BEGIN SELECT RAISE(ABORT,'performance plan events are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_performance_plan_evidence_update
        BEFORE UPDATE ON performance_plan_evidence
        BEGIN SELECT RAISE(ABORT,'performance plan evidence is immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_performance_plan_evidence_delete
        BEFORE DELETE ON performance_plan_evidence
        BEGIN SELECT RAISE(ABORT,'performance plan evidence is immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_performance_reassessment_update
        BEFORE UPDATE ON performance_plan_reassessments
        BEGIN SELECT RAISE(ABORT,'performance reassessments are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_performance_reassessment_delete
        BEFORE DELETE ON performance_plan_reassessments
        BEGIN SELECT RAISE(ABORT,'performance reassessments are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_performance_permission_report_update
        BEFORE UPDATE ON performance_permission_migration_report
        BEGIN SELECT RAISE(ABORT,'performance permission migration reports are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_performance_permission_report_delete
        BEFORE DELETE ON performance_permission_migration_report
        BEGIN SELECT RAISE(ABORT,'performance permission migration reports are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_performance_manifest_update
        BEFORE UPDATE ON performance_migration_manifests
        BEGIN SELECT RAISE(ABORT,'performance migration manifests are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_performance_manifest_delete
        BEFORE DELETE ON performance_migration_manifests
        BEGIN SELECT RAISE(ABORT,'performance migration manifests are immutable'); END
        """,
    )
    for statement in statements:
        db.execute(statement)
    legacy_tables = (
        ("performance_scores", "legacy performance scores"),
        ("performance_reviews", "legacy performance reviews"),
        ("performance_improvement_plans", "legacy performance improvement plans"),
    )
    for table, label in legacy_tables:
        for action in ("INSERT", "UPDATE", "DELETE"):
            trigger_name = f"prevent_legacy_{table}_{action.lower()}"
            db.execute(
                f"CREATE TRIGGER IF NOT EXISTS {trigger_name} BEFORE {action} ON {table} "
                f"BEGIN SELECT RAISE(ABORT,'{label} are read-only after performance ledger migration'); END"
            )


def m056_versioned_performance_ledger(db):
    _create_performance_ledger_tables(db)
    _create_performance_ledger_indexes(db)
    _import_legacy_performance(db)
    _seed_current_performance_assignments(db)
    _migrate_performance_permissions(db)
    _create_performance_ledger_triggers(db)



MIGRATIONS = [
    (23, "Add performance evaluation and improvement workflow", m023_performance_management),
    (24, "Deepen performance review scoring inputs", m024_performance_review_inputs),
    (25, "Add process handoff quality reviews", m025_process_handoff_reviews),
    (26, "Grant performance permissions to management roles", m026_grant_performance_permissions),
    (27, "Add quality inspection scoring fields", m027_quality_inspection_scoring),
    (56, "Add versioned performance ledger and scoped workflow", m056_versioned_performance_ledger),
]
