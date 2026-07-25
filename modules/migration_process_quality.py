"""Full-process quality evaluation migration."""

import json

from modules.domain.quality_rules import PROCESS_QUALITY_EVALUATION_DEFAULT_RULES

def _grade_sql(rating_column):
    return (
        f"CASE WHEN {rating_column} >= 5 THEN '优秀' "
        f"WHEN {rating_column} >= 4 THEN '良好' "
        f"WHEN {rating_column} >= 3 THEN '合格' "
        f"WHEN {rating_column} >= 2 THEN '待改进' ELSE '不合格' END"
    )


def _grant_role_permissions(db):
    for role in db.execute("SELECT id, permissions FROM roles").fetchall():
        try:
            permissions = json.loads(role["permissions"] or "[]")
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(permissions, list) or "*" in permissions:
            continue

        additions = []
        permission_set = set(permissions)
        if "scan:report" in permission_set:
            additions.append("process_quality_evaluation:submit")
        if permission_set.intersection({"quality:view", "performance:view"}):
            additions.extend([
                "page:process-quality-evaluation",
                "process_quality_evaluation:view",
                "process_quality_evaluation:stats",
            ])
        if permission_set.intersection({"quality:edit", "performance:edit"}):
            additions.append("process_quality_evaluation:review")
        if "settings:manage" in permission_set:
            additions.append("process_quality_evaluation:rules")

        merged = list(dict.fromkeys(permissions + additions))
        if merged != permissions:
            db.execute(
                "UPDATE roles SET permissions = ?, updated_at = datetime('now','localtime') WHERE id = ?",
                (json.dumps(merged, ensure_ascii=False), role["id"]),
            )


def m033_full_process_quality_evaluation(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS process_quality_evaluation_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trigger_work_record_id INTEGER NOT NULL,
            order_id INTEGER NOT NULL,
            serial_no TEXT DEFAULT '',
            target_process_id INTEGER NOT NULL,
            evaluator_process_id INTEGER NOT NULL,
            target_work_record_id INTEGER,
            target_user_id INTEGER,
            evaluator_user_id INTEGER NOT NULL,
            quantity INTEGER DEFAULT 1,
            is_required INTEGER DEFAULT 0,
            attribution_type TEXT DEFAULT 'worker',
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            completed_at TEXT DEFAULT '',
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(trigger_work_record_id, target_process_id),
            FOREIGN KEY (trigger_work_record_id) REFERENCES work_records(id) ON DELETE CASCADE,
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
            FOREIGN KEY (target_process_id) REFERENCES processes(id) ON DELETE CASCADE,
            FOREIGN KEY (evaluator_process_id) REFERENCES processes(id) ON DELETE CASCADE,
            FOREIGN KEY (target_work_record_id) REFERENCES work_records(id) ON DELETE SET NULL,
            FOREIGN KEY (target_user_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (evaluator_user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS process_quality_evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER,
            order_id INTEGER NOT NULL,
            serial_no TEXT DEFAULT '',
            target_process_id INTEGER NOT NULL,
            evaluator_process_id INTEGER NOT NULL,
            target_work_record_id INTEGER,
            trigger_work_record_id INTEGER,
            target_user_id INTEGER,
            evaluator_user_id INTEGER NOT NULL,
            quantity INTEGER DEFAULT 1,
            attribution_type TEXT DEFAULT 'worker',
            processing_quality INTEGER NOT NULL,
            dimensional_accuracy INTEGER NOT NULL,
            appearance_quality INTEGER NOT NULL,
            process_continuity INTEGER NOT NULL,
            cleanliness_protection INTEGER NOT NULL,
            total_score REAL NOT NULL,
            grade TEXT NOT NULL,
            issue_tags_json TEXT DEFAULT '[]',
            comment TEXT DEFAULT '',
            status TEXT DEFAULT 'confirmed',
            source_type TEXT DEFAULT 'full_process',
            source_handoff_review_id INTEGER,
            reviewed_by INTEGER,
            reviewed_at TEXT DEFAULT '',
            review_note TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (task_id) REFERENCES process_quality_evaluation_tasks(id) ON DELETE SET NULL,
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
            FOREIGN KEY (target_process_id) REFERENCES processes(id) ON DELETE CASCADE,
            FOREIGN KEY (evaluator_process_id) REFERENCES processes(id) ON DELETE CASCADE,
            FOREIGN KEY (target_work_record_id) REFERENCES work_records(id) ON DELETE SET NULL,
            FOREIGN KEY (trigger_work_record_id) REFERENCES work_records(id) ON DELETE SET NULL,
            FOREIGN KEY (target_user_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (evaluator_user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (source_handoff_review_id) REFERENCES process_handoff_reviews(id) ON DELETE SET NULL,
            FOREIGN KEY (reviewed_by) REFERENCES users(id) ON DELETE SET NULL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS process_quality_evaluation_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            evaluation_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            reviewer_user_id INTEGER NOT NULL,
            note TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (evaluation_id) REFERENCES process_quality_evaluations(id) ON DELETE CASCADE,
            FOREIGN KEY (reviewer_user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_pqe_tasks_evaluator_status ON process_quality_evaluation_tasks(evaluator_user_id, status)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_pqe_tasks_order_serial ON process_quality_evaluation_tasks(order_id, serial_no)")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_pqe_evaluations_task ON process_quality_evaluations(task_id) WHERE task_id IS NOT NULL")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_pqe_evaluations_legacy ON process_quality_evaluations(source_handoff_review_id) WHERE source_handoff_review_id IS NOT NULL")
    db.execute("CREATE INDEX IF NOT EXISTS idx_pqe_evaluations_status ON process_quality_evaluations(status)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_pqe_evaluations_month ON process_quality_evaluations(created_at)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_pqe_evaluations_target_user ON process_quality_evaluations(target_user_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_pqe_reviews_evaluation ON process_quality_evaluation_reviews(evaluation_id)")

    db.execute(
        "INSERT OR IGNORE INTO process_quality_evaluations ("
        "order_id, serial_no, target_process_id, evaluator_process_id, target_work_record_id, "
        "target_user_id, evaluator_user_id, quantity, attribution_type, processing_quality, "
        "dimensional_accuracy, appearance_quality, process_continuity, cleanliness_protection, "
        "total_score, grade, issue_tags_json, comment, status, source_type, source_handoff_review_id, "
        "reviewed_by, reviewed_at, review_note, created_at, updated_at"
        ") SELECT order_id, serial_no, from_process_id, to_process_id, source_work_record_id, "
        "from_user_id, evaluator_user_id, quantity, 'worker', rating, rating, rating, rating, rating, "
        "rating * 20.0, " + _grade_sql("rating") + ", "
        "CASE WHEN issue_type <> '' THEN json_array(issue_type) ELSE '[]' END, comment, "
        "CASE WHEN status = 'pending' THEN 'pending_verification' ELSE status END, "
        "'legacy_handoff', id, confirmed_by, confirmed_at, confirm_note, created_at, updated_at "
        "FROM process_handoff_reviews"
    )
    db.execute(
        "INSERT INTO system_settings (key, value, updated_at) VALUES (?, ?, datetime('now','localtime')) "
        "ON CONFLICT(key) DO NOTHING",
        ("process_quality_evaluation_rules", json.dumps(PROCESS_QUALITY_EVALUATION_DEFAULT_RULES, ensure_ascii=False)),
    )
    _grant_role_permissions(db)
    db.commit()


def _column_names(db, table_name):
    return {row[1] for row in db.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _add_column(db, table_name, definition):
    column_name = definition.split()[0]
    if column_name not in _column_names(db, table_name):
        db.execute(f"ALTER TABLE {table_name} ADD COLUMN {definition}")


def m036_process_quality_evaluation_b(db):
    _add_column(db, "process_quality_evaluation_tasks", "template_id INTEGER")
    _add_column(db, "process_quality_evaluation_tasks", "template_snapshot_json TEXT DEFAULT '{}'")
    _add_column(db, "process_quality_evaluation_tasks", "skip_reason TEXT DEFAULT ''")
    _add_column(db, "process_quality_evaluation_tasks", "skipped_at TEXT DEFAULT ''")
    _add_column(db, "process_quality_evaluations", "template_id INTEGER")
    _add_column(db, "process_quality_evaluations", "dimension_scores_json TEXT DEFAULT '{}'")
    _add_column(db, "process_quality_evaluations", "template_snapshot_json TEXT DEFAULT '{}'")
    _add_column(db, "process_quality_evaluations", "severity TEXT DEFAULT 'normal'")

    db.execute("""
        CREATE TABLE IF NOT EXISTS process_quality_evaluation_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            route_id INTEGER,
            process_id INTEGER NOT NULL,
            dimensions_json TEXT NOT NULL DEFAULT '[]',
            issue_tags_json TEXT NOT NULL DEFAULT '[]',
            critical_issue_tags_json TEXT NOT NULL DEFAULT '[]',
            low_score_threshold INTEGER DEFAULT 60,
            critical_score_threshold INTEGER DEFAULT 40,
            status TEXT DEFAULT 'active',
            created_by INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (route_id) REFERENCES process_routes(id) ON DELETE SET NULL,
            FOREIGN KEY (process_id) REFERENCES processes(id) ON DELETE CASCADE,
            FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS process_quality_evaluation_appeals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            evaluation_id INTEGER NOT NULL,
            requester_user_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            reviewed_by INTEGER,
            review_note TEXT DEFAULT '',
            reviewed_at TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (evaluation_id) REFERENCES process_quality_evaluations(id) ON DELETE CASCADE,
            FOREIGN KEY (requester_user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (reviewed_by) REFERENCES users(id) ON DELETE SET NULL
        )
    """)
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_pqe_templates_scope "
        "ON process_quality_evaluation_templates(process_id, route_id, status)"
    )
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_pqe_appeals_pending "
        "ON process_quality_evaluation_appeals(evaluation_id) WHERE status = 'pending'"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_pqe_appeals_status "
        "ON process_quality_evaluation_appeals(status, created_at)"
    )

    row = db.execute(
        "SELECT value FROM system_settings WHERE key = 'process_quality_evaluation_rules'"
    ).fetchone()
    try:
        stored = json.loads(row[0] or "{}") if row else {}
    except (TypeError, json.JSONDecodeError):
        stored = {}
    merged = dict(PROCESS_QUALITY_EVALUATION_DEFAULT_RULES)
    if isinstance(stored, dict):
        merged.update(stored)
    db.execute(
        "INSERT INTO system_settings (key, value, updated_at) VALUES (?, ?, datetime('now','localtime')) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        ("process_quality_evaluation_rules", json.dumps(merged, ensure_ascii=False)),
    )
    _grant_role_permissions(db)
    db.commit()


def _evaluation_severity(row, rules):
    try:
        snapshot = json.loads(row["template_snapshot_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        snapshot = {}
    if not isinstance(snapshot, dict):
        snapshot = {}
    try:
        issue_tags = json.loads(row["issue_tags_json"] or "[]")
    except (TypeError, json.JSONDecodeError):
        issue_tags = []
    if not isinstance(issue_tags, list):
        issue_tags = []

    def threshold(key, default):
        value = snapshot.get(key)
        if value is None:
            value = rules.get(key, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    low_threshold = threshold("low_score_threshold", 60)
    critical_threshold = threshold("critical_score_threshold", 40)
    critical_tags = snapshot.get("critical_issue_tags") or rules.get("critical_issue_tags") or []
    if row["total_score"] < critical_threshold or set(critical_tags).intersection(issue_tags):
        return "critical"
    if row["total_score"] < low_threshold:
        return "warning"
    return "normal"


def m037_process_quality_review_remediation(db):
    _add_column(db, "quality_inspection_tasks", "cancelled_at TEXT DEFAULT ''")
    _add_column(db, "quality_inspection_tasks", "cancel_reason TEXT DEFAULT ''")
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_quality_tasks_source_evaluation "
        "ON quality_inspection_tasks(source_evaluation_id)"
    )

    row = db.execute(
        "SELECT value FROM system_settings WHERE key = 'process_quality_evaluation_rules'"
    ).fetchone()
    try:
        rules = json.loads(row[0] or "{}") if row else {}
    except (TypeError, json.JSONDecodeError):
        rules = {}
    if not isinstance(rules, dict):
        rules = {}
    rules = {**PROCESS_QUALITY_EVALUATION_DEFAULT_RULES, **rules}
    evaluations = db.execute(
        "SELECT id, total_score, issue_tags_json, template_snapshot_json "
        "FROM process_quality_evaluations"
    ).fetchall()
    db.executemany(
        "UPDATE process_quality_evaluations SET severity = ? WHERE id = ?",
        [(_evaluation_severity(evaluation, rules), evaluation["id"]) for evaluation in evaluations],
    )

    db.execute(
        "UPDATE quality_inspection_tasks SET status = 'cancelled', "
        "cancelled_at = datetime('now','localtime'), cancel_reason = '关联评价已被驳回', "
        "completed_at = COALESCE(NULLIF(completed_at, ''), datetime('now','localtime')), "
        "updated_at = datetime('now','localtime') "
        "WHERE source_evaluation_id IN ("
        "SELECT id FROM process_quality_evaluations WHERE status = 'rejected'"
        ") AND status IN ('pending','in_progress','failed')"
    )

    db.execute(
        "UPDATE process_quality_evaluation_templates AS template SET status = 'inactive', "
        "updated_at = datetime('now','localtime') WHERE template.status = 'active' AND EXISTS ("
        "SELECT 1 FROM process_quality_evaluation_templates AS newer "
        "WHERE newer.status = 'active' AND newer.process_id = template.process_id "
        "AND newer.route_id IS template.route_id AND newer.id > template.id)"
    )
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_pqe_templates_active_general "
        "ON process_quality_evaluation_templates(process_id) "
        "WHERE status = 'active' AND route_id IS NULL"
    )
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_pqe_templates_active_route "
        "ON process_quality_evaluation_templates(process_id, route_id) "
        "WHERE status = 'active' AND route_id IS NOT NULL"
    )
    db.commit()


def m038_converge_legacy_handoff_status(db):
    db.execute(
        "UPDATE process_handoff_reviews SET "
        "status = (SELECT CASE evaluation.status WHEN 'pending_verification' THEN 'pending' ELSE evaluation.status END "
        "FROM process_quality_evaluations evaluation WHERE evaluation.source_handoff_review_id = process_handoff_reviews.id), "
        "confirmed_by = COALESCE((SELECT evaluation.reviewed_by FROM process_quality_evaluations evaluation "
        "WHERE evaluation.source_handoff_review_id = process_handoff_reviews.id), confirmed_by), "
        "confirm_note = COALESCE(NULLIF((SELECT evaluation.review_note FROM process_quality_evaluations evaluation "
        "WHERE evaluation.source_handoff_review_id = process_handoff_reviews.id), ''), confirm_note), "
        "confirmed_at = COALESCE((SELECT evaluation.reviewed_at FROM process_quality_evaluations evaluation "
        "WHERE evaluation.source_handoff_review_id = process_handoff_reviews.id), confirmed_at), "
        "updated_at = datetime('now','localtime') "
        "WHERE EXISTS (SELECT 1 FROM process_quality_evaluations evaluation "
        "WHERE evaluation.source_handoff_review_id = process_handoff_reviews.id)"
    )
    db.commit()


MIGRATIONS = [
    (33, "Add full-process quality evaluation workflow", m033_full_process_quality_evaluation),
    (36, "Upgrade process quality evaluation workflow", m036_process_quality_evaluation_b),
    (37, "Remediate process quality review invariants", m037_process_quality_review_remediation),
    (38, "Converge legacy handoff review status", m038_converge_legacy_handoff_status),
]
