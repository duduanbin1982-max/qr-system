"""Controlled serial-number cross-process backfill migrations."""

import json

from modules.migration_helpers import add_column_if_missing


SERIAL_PROCESS_REPORT_MODE_KEY = "serial_process_report_mode"


def _grant_serial_backfill_permissions(db):
    rows = db.execute("SELECT id, permissions FROM roles").fetchall()
    for row in rows:
        try:
            permissions = json.loads(row["permissions"] or "[]")
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(permissions, list) or "*" in permissions:
            continue
        additions = []
        if "scan:report" in permissions:
            additions.append("scan:serial_backfill")
        if "approvals:edit" in permissions:
            additions.append("scan:serial_backfill_approve")
        merged = list(dict.fromkeys([*permissions, *additions]))
        if merged != permissions:
            db.execute(
                "UPDATE roles SET permissions = ?, "
                "updated_at = datetime('now','localtime') WHERE id = ?",
                (json.dumps(merged, ensure_ascii=False), row["id"]),
            )


def m047_controlled_serial_process_backfill(db):
    add_column_if_missing(
        db, "work_records", "report_source", "TEXT NOT NULL DEFAULT 'standard'"
    )
    add_column_if_missing(db, "work_records", "actual_completed_at", "TEXT")
    add_column_if_missing(db, "work_records", "backfill_reason", "TEXT NOT NULL DEFAULT ''")
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_wr_serial_source_status "
        "ON work_records(serial_no, report_source, status)"
    )
    db.execute(
        "INSERT INTO system_settings (key, value, updated_at) "
        "VALUES (?, 'controlled_backfill', datetime('now','localtime')) "
        "ON CONFLICT(key) DO NOTHING",
        (SERIAL_PROCESS_REPORT_MODE_KEY,),
    )
    _grant_serial_backfill_permissions(db)
    db.commit()


def m048_position_aware_serial_backfill(db):
    add_column_if_missing(db, "work_records", "submit_position_id", "INTEGER")
    add_column_if_missing(
        db,
        "work_records",
        "submit_position_name",
        "TEXT NOT NULL DEFAULT ''",
    )


MIGRATIONS = [
    (47, "Add controlled serial-number cross-process backfill", m047_controlled_serial_process_backfill),
    (48, "Add serial backfill position snapshots", m048_position_aware_serial_backfill),
]
