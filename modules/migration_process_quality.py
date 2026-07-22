"""Full-process quality evaluation migration."""

import json


DEFAULT_RULES = {
    "enabled": True,
    "required_previous_process": True,
    "low_score_threshold": 60,
    "dimensions": [
        {"key": "processing_quality", "label": "加工质量"},
        {"key": "dimensional_accuracy", "label": "尺寸或精度"},
        {"key": "appearance_quality", "label": "外观质量"},
        {"key": "process_continuity", "label": "工序可接续性"},
        {"key": "cleanliness_protection", "label": "清洁及防护"},
    ],
    "issue_tags": ["尺寸问题", "外观问题", "漏加工", "毛刺锐边", "标识不清", "清洁防护", "返修风险", "其他"],
}


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
        ("process_quality_evaluation_rules", json.dumps(DEFAULT_RULES, ensure_ascii=False)),
    )
    _grant_role_permissions(db)
    db.commit()


MIGRATIONS = [
    (33, "Add full-process quality evaluation workflow", m033_full_process_quality_evaluation),
]
