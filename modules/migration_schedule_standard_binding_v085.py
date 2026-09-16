"""V085 exact standard-binding evidence and execution-mode policy tables."""

from modules.migration_helpers import add_column_if_missing


def m085_schedule_standard_binding(db):
    """Add auditable historical-standard bindings and non-scheduled policies.

    The migration is intentionally additive.  Existing standards, schedule
    facts and audit evidence are never rewritten.  A later controlled repair
    command may create exact target standards and append one evidence row per
    binding.
    """
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS work_time_standard_binding_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            idempotency_key TEXT NOT NULL UNIQUE,
            source_standard_id INTEGER NOT NULL,
            target_standard_id INTEGER NOT NULL,
            source_route_version_id INTEGER,
            source_process_version_id INTEGER,
            target_route_version_id INTEGER NOT NULL,
            target_process_version_id INTEGER NOT NULL,
            product_id INTEGER,
            product_code TEXT NOT NULL DEFAULT '',
            standard_minutes_per_unit REAL NOT NULL,
            setup_minutes REAL NOT NULL DEFAULT 0,
            difficulty_factor REAL NOT NULL DEFAULT 1,
            effective_from TEXT NOT NULL DEFAULT '',
            effective_to TEXT NOT NULL DEFAULT '',
            source_snapshot_json TEXT NOT NULL DEFAULT '{}',
            target_snapshot_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'applied'
                CHECK(status IN ('planned','applied','skipped','blocked','cancelled')),
            reason TEXT NOT NULL DEFAULT '',
            operator_id INTEGER,
            approver_id INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(source_standard_id) REFERENCES work_time_standards(id) ON DELETE RESTRICT,
            FOREIGN KEY(target_standard_id) REFERENCES work_time_standards(id) ON DELETE RESTRICT,
            FOREIGN KEY(source_route_version_id) REFERENCES process_route_versions(id) ON DELETE RESTRICT,
            FOREIGN KEY(source_process_version_id) REFERENCES process_versions(id) ON DELETE RESTRICT,
            FOREIGN KEY(target_route_version_id) REFERENCES process_route_versions(id) ON DELETE RESTRICT,
            FOREIGN KEY(target_process_version_id) REFERENCES process_versions(id) ON DELETE RESTRICT,
            FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE SET NULL,
            FOREIGN KEY(operator_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(approver_id) REFERENCES users(id) ON DELETE SET NULL
        )
        """
    )
    db.execute(
        """CREATE INDEX IF NOT EXISTS idx_wt_binding_target
           ON work_time_standard_binding_events(target_route_version_id,target_process_version_id,status)"""
    )
    db.execute(
        """CREATE INDEX IF NOT EXISTS idx_wt_binding_source
           ON work_time_standard_binding_events(source_standard_id,created_at)"""
    )

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS route_process_execution_policies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            route_version_id INTEGER NOT NULL,
            process_version_id INTEGER NOT NULL,
            process_id INTEGER NOT NULL,
            execution_mode TEXT NOT NULL DEFAULT 'internal'
                CHECK(execution_mode IN ('internal','outsourced','non_scheduled')),
            external_lead_minutes REAL NOT NULL DEFAULT 0 CHECK(external_lead_minutes >= 0),
            status TEXT NOT NULL DEFAULT 'active'
                CHECK(status IN ('active','inactive')),
            reason TEXT NOT NULL DEFAULT '',
            created_by INTEGER,
            updated_by INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(route_version_id,process_version_id),
            FOREIGN KEY(route_version_id) REFERENCES process_route_versions(id) ON DELETE RESTRICT,
            FOREIGN KEY(process_version_id) REFERENCES process_versions(id) ON DELETE RESTRICT,
            FOREIGN KEY(process_id) REFERENCES processes(id) ON DELETE RESTRICT,
            FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(updated_by) REFERENCES users(id) ON DELETE SET NULL
        )
        """
    )
    db.execute(
        """CREATE INDEX IF NOT EXISTS idx_route_process_policy_lookup
           ON route_process_execution_policies(route_version_id,process_version_id,status)"""
    )

    # These three process roots are explicitly external/non-scheduled in the
    # approved baseline.  Seed every published/superseded route revision that
    # contains them; no internal line or standard is created here.
    db.execute(
        """
        INSERT OR IGNORE INTO route_process_execution_policies
            (route_version_id,process_version_id,process_id,execution_mode,reason)
        SELECT item.route_version_id,item.process_version_id,item.process_id,'non_scheduled',
               'V085 approved external/non-scheduled process baseline'
        FROM process_route_version_items item
        WHERE item.process_id IN (983,984,12316)
        """
    )

    add_column_if_missing(
        db, "order_process_schedules", "execution_mode",
        "TEXT NOT NULL DEFAULT 'internal' CHECK(execution_mode IN ('internal','outsourced','non_scheduled'))",
    )
    add_column_if_missing(
        db, "schedule_revision_items", "execution_mode",
        "TEXT NOT NULL DEFAULT 'internal' CHECK(execution_mode IN ('internal','outsourced','non_scheduled'))",
    )
    db.execute(
        """CREATE INDEX IF NOT EXISTS idx_schedule_facts_execution_mode
           ON order_process_schedules(execution_mode,status)"""
    )

    # Approved production baseline: every default internal node has 540
    # effective minutes/day (08:00-12:00 + 13:00-18:00).  Only rows still
    # carrying the system-default marker are adjusted; custom calendars and
    # manually configured capacities remain untouched.
    db.execute(
        "UPDATE process_production_lines SET daily_minutes=540 "
        "WHERE remark='系统默认产线' AND daily_minutes=480"
    )
    db.execute(
        "UPDATE schedule_shifts SET end_minute=1080,updated_at=datetime('now','localtime') "
        "WHERE shift_code='DAY-PM' AND end_minute=1020"
    )


MIGRATIONS = [
    (85, "Add exact work-time binding evidence and execution-mode policies", m085_schedule_standard_binding),
]
