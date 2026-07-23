"""Quality management closed-loop migration."""

import json

from modules.migration_helpers import add_column_if_missing


DEFAULT_SCORE_ITEMS = [
    ("DIMENSION", "尺寸精度", "score", "分", "", "", "", 30, 10),
    ("PROCESS", "工艺符合度", "score", "分", "", "", "", 25, 20),
    ("APPEARANCE", "外观质量", "score", "分", "", "", "", 20, 30),
    ("FUNCTION", "装配及功能影响", "score", "分", "", "", "", 15, 40),
    ("DOCUMENT", "标识资料及防护", "score", "分", "", "", "", 10, 50),
]


DEFAULT_STANDARDS = [
    ("QS-DEFAULT-FAI", "默认首件检验标准", "first_article", "hard"),
    ("QS-DEFAULT-IPQC", "默认过程检验标准", "in_process", "soft"),
    ("QS-DEFAULT-FQC", "默认完工检验标准", "final", "hard"),
    ("QS-DEFAULT-OQC", "默认出库检验标准", "outgoing", "hard"),
    ("QS-DEFAULT-RC", "默认返修复检标准", "rework_check", "hard"),
]


DEFAULT_RULES = {
    "enabled": True,
    "first_article_gate": "hard",
    "in_process_gate": "soft",
    "final_gate": "hard",
    "shipment_gate": "hard",
    "auto_first_article": True,
    "auto_final_inspection": True,
    "auto_outgoing_inspection": True,
    "in_process_frequency": 20,
    "low_evaluation_creates_task": True,
    "capa_repeat_threshold": 3,
    "gauge_due_warning_days": 30,
}


def _create_tables(db):
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS quality_standards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            standard_no TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            product_code TEXT DEFAULT '',
            route_id INTEGER,
            process_id INTEGER,
            inspection_type TEXT NOT NULL DEFAULT 'in_process',
            version INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'active',
            gate_mode TEXT NOT NULL DEFAULT 'soft',
            sampling_mode TEXT NOT NULL DEFAULT 'fixed',
            sample_value REAL NOT NULL DEFAULT 1,
            min_score REAL NOT NULL DEFAULT 85,
            acceptance_rule TEXT NOT NULL DEFAULT 'all_required_pass',
            notes TEXT DEFAULT '',
            created_by INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (route_id) REFERENCES process_routes(id) ON DELETE SET NULL,
            FOREIGN KEY (process_id) REFERENCES processes(id) ON DELETE SET NULL,
            FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS quality_standard_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            standard_id INTEGER NOT NULL,
            item_code TEXT NOT NULL,
            item_name TEXT NOT NULL,
            item_type TEXT NOT NULL DEFAULT 'boolean',
            unit TEXT DEFAULT '',
            nominal_value TEXT DEFAULT '',
            lower_limit TEXT DEFAULT '',
            upper_limit TEXT DEFAULT '',
            required INTEGER NOT NULL DEFAULT 1,
            weight REAL NOT NULL DEFAULT 0,
            inspection_method TEXT DEFAULT '',
            acceptance_criteria TEXT DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (standard_id) REFERENCES quality_standards(id) ON DELETE CASCADE,
            UNIQUE (standard_id, item_code)
        );

        CREATE TABLE IF NOT EXISTS quality_inspection_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            standard_id INTEGER,
            product_code TEXT DEFAULT '',
            route_id INTEGER,
            process_id INTEGER,
            trigger_type TEXT NOT NULL,
            inspection_type TEXT NOT NULL,
            gate_mode TEXT NOT NULL DEFAULT 'soft',
            sampling_mode TEXT NOT NULL DEFAULT 'fixed',
            sample_value REAL NOT NULL DEFAULT 1,
            frequency_qty INTEGER NOT NULL DEFAULT 0,
            due_minutes INTEGER NOT NULL DEFAULT 120,
            status TEXT NOT NULL DEFAULT 'active',
            created_by INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (standard_id) REFERENCES quality_standards(id) ON DELETE SET NULL,
            FOREIGN KEY (route_id) REFERENCES process_routes(id) ON DELETE SET NULL,
            FOREIGN KEY (process_id) REFERENCES processes(id) ON DELETE SET NULL,
            FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS quality_inspection_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_no TEXT NOT NULL UNIQUE,
            trigger_key TEXT NOT NULL UNIQUE,
            plan_id INTEGER,
            standard_id INTEGER,
            standard_version INTEGER DEFAULT 1,
            order_id INTEGER,
            process_id INTEGER,
            work_record_id INTEGER,
            shipment_id INTEGER,
            supplier_id INTEGER,
            material_id INTEGER,
            source_evaluation_id INTEGER,
            source_ncr_id INTEGER,
            serial_no TEXT DEFAULT '',
            batch_no TEXT DEFAULT '',
            inspection_type TEXT NOT NULL,
            trigger_type TEXT NOT NULL DEFAULT 'manual',
            gate_mode TEXT NOT NULL DEFAULT 'soft',
            sample_qty INTEGER NOT NULL DEFAULT 1,
            priority TEXT NOT NULL DEFAULT 'normal',
            status TEXT NOT NULL DEFAULT 'pending',
            assigned_to INTEGER,
            inspection_id INTEGER,
            due_at TEXT DEFAULT '',
            started_at TEXT DEFAULT '',
            completed_at TEXT DEFAULT '',
            created_by INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (plan_id) REFERENCES quality_inspection_plans(id) ON DELETE SET NULL,
            FOREIGN KEY (standard_id) REFERENCES quality_standards(id) ON DELETE SET NULL,
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
            FOREIGN KEY (process_id) REFERENCES processes(id) ON DELETE SET NULL,
            FOREIGN KEY (work_record_id) REFERENCES work_records(id) ON DELETE SET NULL,
            FOREIGN KEY (shipment_id) REFERENCES shipments(id) ON DELETE CASCADE,
            FOREIGN KEY (supplier_id) REFERENCES suppliers(id) ON DELETE SET NULL,
            FOREIGN KEY (material_id) REFERENCES materials(id) ON DELETE SET NULL,
            FOREIGN KEY (source_evaluation_id) REFERENCES process_quality_evaluations(id) ON DELETE SET NULL,
            FOREIGN KEY (source_ncr_id) REFERENCES quality_nonconformances(id) ON DELETE SET NULL,
            FOREIGN KEY (assigned_to) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (inspection_id) REFERENCES quality_inspections(id) ON DELETE SET NULL,
            FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS quality_nonconformances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ncr_no TEXT NOT NULL UNIQUE,
            task_id INTEGER,
            inspection_id INTEGER,
            order_id INTEGER,
            process_id INTEGER,
            serial_no TEXT DEFAULT '',
            supplier_id INTEGER,
            material_id INTEGER,
            defect_category TEXT DEFAULT '',
            defect_level TEXT DEFAULT '',
            defect_quantity INTEGER NOT NULL DEFAULT 0,
            description TEXT DEFAULT '',
            disposition TEXT NOT NULL DEFAULT 'pending',
            status TEXT NOT NULL DEFAULT 'open',
            responsible_user_id INTEGER,
            responsible_process_id INTEGER,
            owner_id INTEGER,
            due_at TEXT DEFAULT '',
            root_cause TEXT DEFAULT '',
            corrective_action TEXT DEFAULT '',
            verification_result TEXT DEFAULT '',
            source_type TEXT DEFAULT 'inspection',
            closed_by INTEGER,
            closed_at TEXT DEFAULT '',
            created_by INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (task_id) REFERENCES quality_inspection_tasks(id) ON DELETE SET NULL,
            FOREIGN KEY (inspection_id) REFERENCES quality_inspections(id) ON DELETE SET NULL,
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
            FOREIGN KEY (process_id) REFERENCES processes(id) ON DELETE SET NULL,
            FOREIGN KEY (supplier_id) REFERENCES suppliers(id) ON DELETE SET NULL,
            FOREIGN KEY (material_id) REFERENCES materials(id) ON DELETE SET NULL,
            FOREIGN KEY (responsible_user_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (responsible_process_id) REFERENCES processes(id) ON DELETE SET NULL,
            FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (closed_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS quality_nonconformance_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ncr_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            from_status TEXT DEFAULT '',
            to_status TEXT DEFAULT '',
            note TEXT DEFAULT '',
            actor_id INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (ncr_id) REFERENCES quality_nonconformances(id) ON DELETE CASCADE,
            FOREIGN KEY (actor_id) REFERENCES users(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS quality_capa_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            capa_no TEXT NOT NULL UNIQUE,
            ncr_id INTEGER,
            title TEXT NOT NULL,
            problem_description TEXT DEFAULT '',
            root_cause TEXT DEFAULT '',
            corrective_action TEXT DEFAULT '',
            preventive_action TEXT DEFAULT '',
            owner_id INTEGER,
            due_at TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open',
            effectiveness_result TEXT DEFAULT '',
            verified_by INTEGER,
            verified_at TEXT DEFAULT '',
            created_by INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (ncr_id) REFERENCES quality_nonconformances(id) ON DELETE SET NULL,
            FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (verified_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS quality_supplier_inspections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_id INTEGER NOT NULL,
            material_id INTEGER,
            batch_no TEXT DEFAULT '',
            delivery_no TEXT DEFAULT '',
            quantity_checked INTEGER NOT NULL DEFAULT 0,
            quantity_passed INTEGER NOT NULL DEFAULT 0,
            quantity_failed INTEGER NOT NULL DEFAULT 0,
            result TEXT NOT NULL DEFAULT 'pending',
            score_total REAL DEFAULT 0,
            defect_category TEXT DEFAULT '',
            defect_level TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            inspector_id INTEGER,
            ncr_id INTEGER,
            inspected_at TEXT DEFAULT (datetime('now','localtime')),
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (supplier_id) REFERENCES suppliers(id) ON DELETE RESTRICT,
            FOREIGN KEY (material_id) REFERENCES materials(id) ON DELETE SET NULL,
            FOREIGN KEY (inspector_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (ncr_id) REFERENCES quality_nonconformances(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS quality_gauges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gauge_no TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            model TEXT DEFAULT '',
            measurement_range TEXT DEFAULT '',
            accuracy TEXT DEFAULT '',
            location TEXT DEFAULT '',
            calibration_cycle_days INTEGER NOT NULL DEFAULT 365,
            last_calibrated_at TEXT DEFAULT '',
            next_calibration_at TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            owner_id INTEGER,
            certificate_no TEXT DEFAULT '',
            remark TEXT DEFAULT '',
            created_by INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS quality_gauge_calibrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gauge_id INTEGER NOT NULL,
            calibrated_at TEXT NOT NULL,
            next_calibration_at TEXT NOT NULL,
            result TEXT NOT NULL,
            certificate_no TEXT DEFAULT '',
            organization TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            operator_id INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (gauge_id) REFERENCES quality_gauges(id) ON DELETE CASCADE,
            FOREIGN KEY (operator_id) REFERENCES users(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_quality_standard_scope ON quality_standards(product_code, route_id, process_id, inspection_type, status);
        CREATE INDEX IF NOT EXISTS idx_quality_plan_trigger ON quality_inspection_plans(trigger_type, status, product_code, route_id, process_id);
        CREATE INDEX IF NOT EXISTS idx_quality_task_status_due ON quality_inspection_tasks(status, due_at);
        CREATE INDEX IF NOT EXISTS idx_quality_task_order_process ON quality_inspection_tasks(order_id, process_id, inspection_type);
        CREATE INDEX IF NOT EXISTS idx_quality_task_shipment ON quality_inspection_tasks(shipment_id, status);
        CREATE INDEX IF NOT EXISTS idx_quality_ncr_status_due ON quality_nonconformances(status, due_at);
        CREATE INDEX IF NOT EXISTS idx_quality_ncr_order_process ON quality_nonconformances(order_id, process_id);
        CREATE INDEX IF NOT EXISTS idx_quality_capa_status_due ON quality_capa_records(status, due_at);
        CREATE INDEX IF NOT EXISTS idx_quality_supplier_date ON quality_supplier_inspections(supplier_id, inspected_at);
        CREATE INDEX IF NOT EXISTS idx_quality_gauge_due ON quality_gauges(status, next_calibration_at);
        """
    )


def _extend_inspections(db):
    columns = [
        ("task_id", "INTEGER"),
        ("standard_id", "INTEGER"),
        ("standard_version", "INTEGER DEFAULT 1"),
        ("measurements_json", "TEXT DEFAULT '[]'"),
        ("quality_status", "TEXT DEFAULT 'pending'"),
        ("batch_no", "TEXT DEFAULT ''"),
        ("scope_type", "TEXT DEFAULT 'production'"),
        ("reviewed_by", "INTEGER"),
        ("reviewed_at", "TEXT DEFAULT ''"),
        ("review_status", "TEXT DEFAULT 'unreviewed'"),
        ("review_note", "TEXT DEFAULT ''"),
        ("updated_at", "TEXT DEFAULT ''"),
    ]
    for name, definition in columns:
        add_column_if_missing(db, "quality_inspections", name, definition)
    db.execute(
        "UPDATE quality_inspections SET quality_status = CASE "
        "WHEN result = 'pass' THEN 'released' "
        "WHEN result IN ('rework','scrap','fail','partial') THEN 'nonconforming' "
        "ELSE 'pending' END WHERE COALESCE(quality_status, '') IN ('', 'pending')"
    )
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_quality_inspection_task ON quality_inspections(task_id) WHERE task_id IS NOT NULL")
    db.execute("CREATE INDEX IF NOT EXISTS idx_quality_inspection_review ON quality_inspections(review_status, inspected_at)")
    add_column_if_missing(db, "rework_records", "source_ncr_id", "INTEGER")
    add_column_if_missing(db, "inventory", "quality_status", "TEXT DEFAULT 'released'")
    add_column_if_missing(db, "inventory", "quality_hold_reason", "TEXT DEFAULT ''")


def _seed_standards_and_plans(db):
    for standard_no, name, inspection_type, gate_mode in DEFAULT_STANDARDS:
        db.execute(
            "INSERT OR IGNORE INTO quality_standards "
            "(standard_no, name, inspection_type, gate_mode, sampling_mode, sample_value, min_score, notes) "
            "VALUES (?, ?, ?, ?, 'fixed', 1, 85, '系统默认标准，可按产品和工序复制完善')",
            (standard_no, name, inspection_type, gate_mode),
        )
        standard_id = db.execute(
            "SELECT id FROM quality_standards WHERE standard_no = ?", (standard_no,)
        ).fetchone()[0]
        for item_code, item_name, item_type, unit, nominal, lower, upper, weight, sort_order in DEFAULT_SCORE_ITEMS:
            db.execute(
                "INSERT OR IGNORE INTO quality_standard_items "
                "(standard_id, item_code, item_name, item_type, unit, nominal_value, lower_limit, "
                "upper_limit, required, weight, sort_order) VALUES (?,?,?,?,?,?,?,?,1,?,?)",
                (standard_id, item_code, item_name, item_type, unit, nominal, lower, upper, weight, sort_order),
            )

    plan_rows = [
        ("默认首件检验", "QS-DEFAULT-FAI", "first_report", "first_article", "hard", 0, 60),
        ("默认过程巡检", "QS-DEFAULT-IPQC", "quantity_interval", "in_process", "soft", 20, 120),
        ("默认完工检验", "QS-DEFAULT-FQC", "final_process", "final", "hard", 0, 120),
        ("默认出库检验", "QS-DEFAULT-OQC", "shipment", "outgoing", "hard", 0, 60),
        ("默认返修复检", "QS-DEFAULT-RC", "rework_complete", "rework_check", "hard", 0, 60),
    ]
    for name, standard_no, trigger_type, inspection_type, gate_mode, frequency, due_minutes in plan_rows:
        standard_id = db.execute(
            "SELECT id FROM quality_standards WHERE standard_no = ?", (standard_no,)
        ).fetchone()[0]
        exists = db.execute(
            "SELECT id FROM quality_inspection_plans WHERE name = ? AND product_code = '' "
            "AND route_id IS NULL AND process_id IS NULL",
            (name,),
        ).fetchone()
        if not exists:
            db.execute(
                "INSERT INTO quality_inspection_plans "
                "(name, standard_id, trigger_type, inspection_type, gate_mode, sampling_mode, "
                "sample_value, frequency_qty, due_minutes, status) VALUES (?,?,?,?,?,'fixed',1,?,?,'active')",
                (name, standard_id, trigger_type, inspection_type, gate_mode, frequency, due_minutes),
            )


def _migrate_history(db):
    db.execute(
        "INSERT OR IGNORE INTO quality_inspection_tasks "
        "(task_no, trigger_key, order_id, process_id, serial_no, inspection_type, trigger_type, "
        "gate_mode, sample_qty, status, assigned_to, inspection_id, completed_at, created_at, updated_at) "
        "SELECT 'QT-LEGACY-' || printf('%06d', id), 'legacy-inspection:' || id, order_id, process_id, "
        "COALESCE(serial_no,''), inspection_type, 'legacy', 'off', MAX(COALESCE(quantity_checked,1),1), "
        "CASE WHEN result = 'pass' THEN 'passed' WHEN result IN ('rework','scrap','fail','partial') THEN 'failed' ELSE 'cancelled' END, "
        "inspector_id, id, COALESCE(inspected_at,created_at), created_at, created_at FROM quality_inspections"
    )
    db.execute(
        "UPDATE quality_inspections SET task_id = ("
        "SELECT task.id FROM quality_inspection_tasks task WHERE task.inspection_id = quality_inspections.id"
        ") WHERE task_id IS NULL"
    )
    db.execute(
        "INSERT OR IGNORE INTO quality_nonconformances "
        "(ncr_no, task_id, inspection_id, order_id, process_id, serial_no, defect_category, defect_level, "
        "defect_quantity, description, disposition, status, source_type, closed_at, created_at, updated_at) "
        "SELECT 'NCR-LEGACY-' || printf('%06d', qi.id), qi.task_id, qi.id, qi.order_id, qi.process_id, "
        "COALESCE(qi.serial_no,''), COALESCE(qi.defect_category,''), COALESCE(qi.defect_level,''), "
        "MAX(COALESCE(qi.quantity_failed, qi.defect_quantity, 0),0), COALESCE(qi.notes,''), "
        "CASE WHEN qi.result IN ('rework','partial') THEN 'rework' ELSE 'scrap' END, 'closed', 'legacy', "
        "COALESCE(qi.inspected_at, qi.created_at), qi.created_at, qi.created_at "
        "FROM quality_inspections qi WHERE qi.result IN ('rework','scrap','fail','partial')"
    )


def _grant_permissions(db):
    for role in db.execute("SELECT id, permissions FROM roles").fetchall():
        try:
            permissions = json.loads(role["permissions"] or "[]")
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(permissions, list) or "*" in permissions:
            continue
        permission_set = set(permissions)
        additions = []
        if "quality:view" in permission_set:
            additions.append("page:quality-management")
        if "quality:edit" in permission_set:
            additions.extend([
                "quality:inspect", "quality:standards", "quality:plans", "quality:disposition",
                "quality:review", "quality:capa", "quality:supplier", "quality:calibration",
            ])
        merged = list(dict.fromkeys(permissions + additions))
        if merged != permissions:
            db.execute(
                "UPDATE roles SET permissions = ?, updated_at = datetime('now','localtime') WHERE id = ?",
                (json.dumps(merged, ensure_ascii=False), role["id"]),
            )


def m034_quality_management_closed_loop(db):
    _create_tables(db)
    _extend_inspections(db)
    _seed_standards_and_plans(db)
    _migrate_history(db)
    db.execute(
        "INSERT INTO system_settings (key, value, updated_at) VALUES (?, ?, datetime('now','localtime')) "
        "ON CONFLICT(key) DO NOTHING",
        ("quality_management_rules", json.dumps(DEFAULT_RULES, ensure_ascii=False)),
    )
    _grant_permissions(db)
    db.commit()


def m035_quality_audit_and_ncr_workflow(db):
    """Add review metadata while keeping existing inspections operational."""
    _extend_inspections(db)
    db.execute(
        "UPDATE quality_inspections SET review_status='approved' "
        "WHERE COALESCE(review_status, '') IN ('', 'unreviewed') "
        "AND result='pass'"
    )
    db.execute(
        "UPDATE quality_inspections SET review_status='rejected' "
        "WHERE COALESCE(review_status, '') IN ('', 'unreviewed') "
        "AND result IN ('rework','scrap','fail','partial')"
    )
    _grant_permissions(db)
    db.commit()


MIGRATIONS = [
    (34, "Add quality management closed-loop workflow", m034_quality_management_closed_loop),
    (35, "Add quality review and manual NCR workflow", m035_quality_audit_and_ncr_workflow),
]
