"""Versioned process configuration and scoped permission migration."""

import json

from modules.domain.process_config import (
    PROCESS_CONFIG_DEFAULTS,
    PROCESS_CONFIG_FIELDS,
    normalize_process_config,
)


PROCESS_CONFIG_PERMISSIONS = [
    "page:settings",
    "page:settings.process-config",
    "process_config:view",
    "process_config:create",
    "process_config:submit",
    "process_config:approve",
    "process_config:reject",
    "process_config:history",
]


def _legacy_values(db):
    rows = db.execute(
        "SELECT key, value FROM system_settings WHERE key IN (?,?,?,?,?)",
        PROCESS_CONFIG_FIELDS,
    ).fetchall()
    raw = {row["key"]: row["value"] for row in rows}
    valid = {}
    for field in PROCESS_CONFIG_FIELDS:
        if field not in raw:
            continue
        try:
            valid[field] = normalize_process_config(
                {field: raw[field]}, base=PROCESS_CONFIG_DEFAULTS
            )[field]
        except ValueError:
            valid[field] = PROCESS_CONFIG_DEFAULTS[field]
    return normalize_process_config(valid, base=PROCESS_CONFIG_DEFAULTS)


def _merge_permissions(db):
    for role in db.execute("SELECT id, permissions FROM roles").fetchall():
        try:
            permissions = json.loads(role["permissions"] or "[]")
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(permissions, list) or "*" in permissions:
            continue
        if not (
            "settings:manage" in permissions
            or "page:settings.process-config" in permissions
        ):
            continue
        merged = list(dict.fromkeys([*permissions, *PROCESS_CONFIG_PERMISSIONS]))
        if merged != permissions:
            db.execute(
                "UPDATE roles SET permissions=? WHERE id=?",
                (json.dumps(merged, ensure_ascii=False), role["id"]),
            )


def m067_version_process_config(db):
    db.execute(
        """CREATE TABLE IF NOT EXISTS process_configs (
            id INTEGER PRIMARY KEY CHECK(id=1),
            process_order_mode TEXT NOT NULL
                CHECK(process_order_mode IN ('sequential','out_of_order')),
            serial_process_report_mode TEXT NOT NULL
                CHECK(serial_process_report_mode IN ('strict','controlled_backfill')),
            limit_by_prev_process INTEGER NOT NULL CHECK(limit_by_prev_process IN (0,1)),
            limit_by_order_qty INTEGER NOT NULL CHECK(limit_by_order_qty IN (0,1)),
            approval_enabled INTEGER NOT NULL CHECK(approval_enabled IN (0,1)),
            version INTEGER NOT NULL DEFAULT 1 CHECK(version >= 1),
            row_version INTEGER NOT NULL DEFAULT 0 CHECK(row_version >= 0),
            active_revision_id INTEGER,
            updated_by INTEGER,
            updated_by_name TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS process_config_revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            config_id INTEGER NOT NULL DEFAULT 1 CHECK(config_id=1),
            version INTEGER NOT NULL CHECK(version >= 1),
            process_order_mode TEXT NOT NULL
                CHECK(process_order_mode IN ('sequential','out_of_order')),
            serial_process_report_mode TEXT NOT NULL
                CHECK(serial_process_report_mode IN ('strict','controlled_backfill')),
            limit_by_prev_process INTEGER NOT NULL CHECK(limit_by_prev_process IN (0,1)),
            limit_by_order_qty INTEGER NOT NULL CHECK(limit_by_order_qty IN (0,1)),
            approval_enabled INTEGER NOT NULL CHECK(approval_enabled IN (0,1)),
            status TEXT NOT NULL
                CHECK(status IN ('draft','pending_approval','published','rejected')),
            base_row_version INTEGER NOT NULL DEFAULT 0 CHECK(base_row_version >= 0),
            row_version INTEGER NOT NULL DEFAULT 0 CHECK(row_version >= 0),
            changed_fields TEXT NOT NULL DEFAULT '[]',
            revision_reason TEXT NOT NULL,
            created_by INTEGER,
            created_by_name TEXT NOT NULL DEFAULT '',
            submitted_at TEXT NOT NULL DEFAULT '',
            approved_by INTEGER,
            approved_by_name TEXT NOT NULL DEFAULT '',
            approved_at TEXT NOT NULL DEFAULT '',
            rejected_reason TEXT NOT NULL DEFAULT '',
            rejected_by INTEGER,
            rejected_by_name TEXT NOT NULL DEFAULT '',
            rejected_at TEXT NOT NULL DEFAULT '',
            idempotency_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(config_id, version),
            FOREIGN KEY(config_id) REFERENCES process_configs(id) ON DELETE RESTRICT
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS process_config_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            revision_id INTEGER NOT NULL,
            event_type TEXT NOT NULL
                CHECK(event_type IN ('created','updated','submitted','approved','published','rejected')),
            actor_id INTEGER,
            actor_name TEXT NOT NULL DEFAULT '',
            from_status TEXT NOT NULL DEFAULT '',
            to_status TEXT NOT NULL DEFAULT '',
            detail TEXT NOT NULL DEFAULT '{}',
            idempotency_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(revision_id) REFERENCES process_config_revisions(id) ON DELETE RESTRICT
        )"""
    )
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_process_config_open_revision "
        "ON process_config_revisions(config_id) "
        "WHERE status IN ('draft','pending_approval')"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_process_config_revisions_status "
        "ON process_config_revisions(status, version DESC)"
    )
    db.execute(
        "CREATE TRIGGER IF NOT EXISTS prevent_process_config_revision_content_update "
        "BEFORE UPDATE OF process_order_mode,serial_process_report_mode,"
        "limit_by_prev_process,limit_by_order_qty,approval_enabled,revision_reason "
        "ON process_config_revisions WHEN OLD.status <> 'draft' BEGIN "
        "SELECT RAISE(ABORT, 'process config revision is immutable'); END"
    )
    db.execute(
        "CREATE TRIGGER IF NOT EXISTS prevent_process_config_revision_final_update "
        "BEFORE UPDATE ON process_config_revisions "
        "WHEN OLD.status IN ('published','rejected') BEGIN "
        "SELECT RAISE(ABORT, 'process config revision is immutable'); END"
    )
    db.execute(
        "CREATE TRIGGER IF NOT EXISTS validate_process_config_revision_transition "
        "BEFORE UPDATE OF status ON process_config_revisions "
        "WHEN NEW.status <> OLD.status AND NOT ("
        "(OLD.status='draft' AND NEW.status='pending_approval') OR "
        "(OLD.status='pending_approval' AND NEW.status IN ('published','rejected'))) BEGIN "
        "SELECT RAISE(ABORT, 'invalid process config revision transition'); END"
    )
    db.execute(
        "CREATE TRIGGER IF NOT EXISTS prevent_process_config_revision_delete "
        "BEFORE DELETE ON process_config_revisions BEGIN "
        "SELECT RAISE(ABORT, 'process config revisions are immutable'); END"
    )
    db.execute(
        "CREATE TRIGGER IF NOT EXISTS prevent_process_config_event_update "
        "BEFORE UPDATE ON process_config_events BEGIN "
        "SELECT RAISE(ABORT, 'process config events are immutable'); END"
    )
    db.execute(
        "CREATE TRIGGER IF NOT EXISTS prevent_process_config_event_delete "
        "BEFORE DELETE ON process_config_events BEGIN "
        "SELECT RAISE(ABORT, 'process config events are immutable'); END"
    )

    values = _legacy_values(db)
    db.execute(
        "INSERT OR IGNORE INTO process_configs "
        "(id,process_order_mode,serial_process_report_mode,limit_by_prev_process,"
        "limit_by_order_qty,approval_enabled,version,row_version,updated_by_name) "
        "VALUES (1,?,?,?,?,?,1,0,'系统迁移')",
        tuple(values[field] for field in PROCESS_CONFIG_FIELDS),
    )
    config = db.execute("SELECT * FROM process_configs WHERE id=1").fetchone()
    revision = db.execute(
        "SELECT id FROM process_config_revisions WHERE config_id=1 AND version=1"
    ).fetchone()
    if revision is None:
        cursor = db.execute(
            "INSERT INTO process_config_revisions "
            "(config_id,version,process_order_mode,serial_process_report_mode,"
            "limit_by_prev_process,limit_by_order_qty,approval_enabled,status,row_version,"
            "base_row_version,changed_fields,revision_reason,created_by_name,approved_by_name,approved_at,"
            "idempotency_key) VALUES (1,1,?,?,?,?,?,'published',0,0,?,?,?,?,"
            "datetime('now','localtime'),'process-config-v067-baseline')",
            (
                *(config[field] for field in PROCESS_CONFIG_FIELDS),
                json.dumps(list(PROCESS_CONFIG_FIELDS), ensure_ascii=False),
                "v067 工艺配置基线",
                "系统迁移",
                "系统迁移",
            ),
        )
        revision_id = cursor.lastrowid
        db.execute(
            "UPDATE process_configs SET active_revision_id=? WHERE id=1",
            (revision_id,),
        )
    else:
        revision_id = revision["id"]

    if not db.execute(
        "SELECT 1 FROM process_config_events WHERE idempotency_key='process-config-v067-baseline'"
    ).fetchone():
        db.execute(
            "INSERT INTO process_config_events "
            "(revision_id,event_type,actor_name,to_status,detail,idempotency_key) "
            "VALUES (?,'published','系统迁移','published',?,?)",
            (
                revision_id,
                json.dumps({"source": "system_settings"}, ensure_ascii=False),
                "process-config-v067-baseline",
            ),
        )

    for field in PROCESS_CONFIG_FIELDS:
        db.execute(
            "INSERT INTO system_settings (key,value,updated_at) "
            "VALUES (?,?,datetime('now','localtime')) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (field, str(config[field])),
        )
    _merge_permissions(db)


MIGRATIONS = [
    (67, "Version process configuration and scoped workflow", m067_version_process_config),
]
