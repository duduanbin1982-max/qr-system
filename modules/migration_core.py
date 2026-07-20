"""Core compatibility migrations for versions 13 through 22."""

import json

from modules.migration_helpers import add_column_if_missing
from modules.migration_materials import ensure_material_planning_tables
from modules.migration_schema_compat import ensure_current_schema_compat
from modules.permission_catalog import infer_page_permissions
def _ensure_board_sessions_table(db):
    db.execute('''CREATE TABLE IF NOT EXISTS board_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        token TEXT UNIQUE NOT NULL,
        expires_at TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )''')




def m013_board_sessions(db):
    _ensure_board_sessions_table(db)
    db.commit()


def m014_material_planning_tables(db):
    ensure_material_planning_tables(db)
    db.commit()


def m015_roles_is_builtin(db):
    add_column_if_missing(db, "roles", "is_builtin", "INTEGER DEFAULT 0")
    db.execute("UPDATE roles SET is_builtin = 1 WHERE id IN (1, 2)")
    db.commit()


def m016_approval_columns(db):
    add_column_if_missing(db, "approval_config", "approver_role_2", "TEXT DEFAULT ''")
    add_column_if_missing(db, "approval_config", "approver_role_3", "TEXT DEFAULT ''")
    add_column_if_missing(db, "approval_records", "processed_at", "TEXT")
    add_column_if_missing(db, "approval_records", "current_level", "INTEGER DEFAULT 1")
    db.commit()



def m017_approval_indexes(db):
    db.execute("CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_records(status)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_approval_work_record ON approval_records(work_record_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_approval_created ON approval_records(created_at)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_approval_config_process ON approval_config(process_id)")
    db.commit()



def m018_quality_attachments_index(db):
    exists = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='quality_attachments'"
    ).fetchone()
    if exists:
        db.execute("CREATE INDEX IF NOT EXISTS idx_qa_inspection_id ON quality_attachments(inspection_id)")
    db.commit()


def m019_users_marker(db):
    add_column_if_missing(db, "users", "marker", 'TEXT DEFAULT ""')
    db.commit()


def m020_ensure_legacy_gap_tables(db):
    _ensure_board_sessions_table(db)
    ensure_material_planning_tables(db)
    db.commit()


def m021_backfill_page_permissions(db):
    for role in db.execute('SELECT id, permissions FROM roles').fetchall():
        try:
            permissions = json.loads(role['permissions'] or '[]')
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(permissions, list) or '*' in permissions:
            continue
        merged = list(dict.fromkeys(permissions + infer_page_permissions(permissions)))
        if merged != permissions:
            db.execute('UPDATE roles SET permissions = ? WHERE id = ?',
                       (json.dumps(merged, ensure_ascii=False), role['id']))
    db.commit()


def m022_current_schema_compat(db):
    ensure_current_schema_compat(db)
    db.commit()



MIGRATIONS = [
    (13, "Create board sessions table", m013_board_sessions),
    (14, "Create product BOM and order material tables", m014_material_planning_tables),
    (15, "Add is_builtin column to roles", m015_roles_is_builtin),
    (16, "Add approval missing columns (approver_role_2/3, processed_at, current_level)", m016_approval_columns),
    (17, "Add indexes on approval_records and approval_config", m017_approval_indexes),
    (18, "Add index on quality_attachments.inspection_id", m018_quality_attachments_index),
    (19, "Add marker column to users", m019_users_marker),
    (20, "Ensure board/material planning tables after legacy migration gap", m020_ensure_legacy_gap_tables),
    (21, "Backfill page permissions for existing roles", m021_backfill_page_permissions),
    (22, "Ensure current schema compatibility columns", m022_current_schema_compat),
]
