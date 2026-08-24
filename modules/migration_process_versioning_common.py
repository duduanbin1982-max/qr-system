"""Shared constants and schema guards for process-version migrations."""

from modules.migration_helpers import column_exists, table_exists


MIGRATION_KEY = "v060:legacy-baseline"
ORDER_BINDING_MIGRATION_KEY = "v061:order-version-bindings"
PRICE_BINDING_MIGRATION_KEY = "v062:price-version-bindings"
PROCESS_FACT_MIGRATION_KEY = "v063:process-fact-version-bindings"
TERMINAL_VERSION_STATUSES = ("published", "superseded", "retired")


PROCESS_FACT_BINDINGS = (
    {
        "table": "work_records",
        "roles": ("process",),
        "work_sources": (),
        "index_key": "work_records",
        "user_column": "user_id",
        "time_column": "created_at",
    },
    {
        "table": "material_consumptions",
        "roles": ("process",),
        "work_sources": ("source_work_record_id",),
        "index_key": "material_consumptions",
        "user_column": "operator_id",
        "time_column": "created_at",
    },
    {
        "table": "order_completion_focus_events",
        "roles": ("process",),
        "work_sources": (),
        "index_key": "completion_focus",
        "user_column": "user_id",
        "time_column": "created_at",
    },
    {
        "table": "process_handoff_reviews",
        "roles": ("from_process", "to_process"),
        "work_sources": ("source_work_record_id",),
        "index_key": "handoff",
        "user_column": "from_user_id",
        "time_column": "created_at",
    },
    {
        "table": "process_quality_evaluation_tasks",
        "roles": ("target_process", "evaluator_process"),
        "work_sources": ("target_work_record_id", "trigger_work_record_id"),
        "index_key": "quality_task",
        "user_column": "target_user_id",
        "time_column": "created_at",
    },
    {
        "table": "process_quality_evaluation_task_audits",
        "roles": ("target_process", "evaluator_process"),
        "work_sources": (),
        "index_key": "quality_task_audit",
        "user_column": "target_user_id",
        "time_column": "created_at",
    },
    {
        "table": "process_quality_evaluations",
        "roles": ("target_process", "evaluator_process"),
        "work_sources": ("target_work_record_id", "trigger_work_record_id"),
        "index_key": "quality_evaluation",
        "user_column": "target_user_id",
        "time_column": "created_at",
    },
    {
        "table": "quality_inspection_tasks",
        "roles": ("process",),
        "work_sources": ("work_record_id",),
        "index_key": "inspection_task",
        "user_column": "assigned_to",
        "time_column": "created_at",
    },
    {
        "table": "quality_inspections",
        "roles": ("process",),
        "work_sources": (),
        "index_key": "inspection",
        "user_column": "inspector_id",
        "time_column": "inspected_at",
    },
    {
        "table": "quality_nonconformances",
        "roles": ("process", "responsible_process"),
        "work_sources": (),
        "index_key": "nonconformance",
        "user_column": "responsible_user_id",
        "time_column": "created_at",
    },
    {
        "table": "rework_records",
        "roles": ("process",),
        "work_sources": (),
        "index_key": "rework",
        "user_column": "user_id",
        "time_column": "created_at",
    },
    {
        "table": "scrap_records",
        "roles": ("process",),
        "work_sources": (),
        "index_key": "scrap",
        "user_column": "user_id",
        "time_column": "created_at",
    },
    {
        "table": "work_time_records",
        "roles": ("process",),
        "work_sources": ("source_work_record_id",),
        "index_key": "work_time",
        "user_column": "user_id",
        "time_column": "start_time",
    },
    {
        "table": "work_time_standards",
        "roles": ("process",),
        "work_sources": (),
        "index_key": "work_time_standard",
        "user_column": "created_by",
        "time_column": "effective_from",
    },
    {
        "table": "payroll_detail_lines",
        "roles": ("process",),
        "work_sources": ("work_record_id",),
        "index_key": "payroll_detail",
        "user_column": None,
        "time_column": "work_recorded_at",
    },
    {
        "table": "performance_quality_events",
        "roles": ("process",),
        "work_sources": (),
        "index_key": "performance_event",
        "user_column": "user_id",
        "time_column": "business_at",
    },
    {
        "table": "performance_source_facts",
        "roles": ("process",),
        "work_sources": (),
        "index_key": "performance_fact",
        "user_column": "user_id",
        "time_column": "business_at",
    },
)


def _create_exception_table(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS process_version_migration_exceptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            migration_key TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            legacy_id INTEGER NOT NULL DEFAULT 0,
            reason_code TEXT NOT NULL,
            blocking INTEGER NOT NULL DEFAULT 1 CHECK(blocking IN (0,1)),
            source_summary_json TEXT NOT NULL DEFAULT '{}',
            resolution_status TEXT NOT NULL DEFAULT 'open'
                CHECK(resolution_status IN ('open','resolved','accepted')),
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(migration_key,entity_type,legacy_id,reason_code)
        )
        """
    )


def _required_columns(db, table, columns, issues):
    if not table_exists(db, table):
        issues.append(
            {
                "entity_type": "schema",
                "legacy_id": 0,
                "reason_code": "missing_required_table_" + table,
                "summary": {"table": table},
            }
        )
        return False
    missing = [column for column in columns if not column_exists(db, table, column)]
    for column in missing:
        issues.append(
            {
                "entity_type": "schema",
                "legacy_id": 0,
                "reason_code": f"missing_required_column_{table}_{column}",
                "summary": {"table": table, "column": column},
            }
        )
    return not missing
