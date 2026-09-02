"""Audit event foundation migration."""

from modules.audit_action_catalog import describe_action
from modules.audit_policy import sanitize_audit_detail


def _has_column(db, table, column):
    return any(row["name"] == column for row in db.execute(
        "PRAGMA table_info(" + table + ")"
    ).fetchall())


def _add_column(db, table, definition):
    column = definition.split()[0]
    if not _has_column(db, table, column):
        db.execute("ALTER TABLE " + table + " ADD COLUMN " + definition)


def _table_exists(db, table):
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def m066_audit_event_foundation(db):
    """Add metadata and durable queues without changing existing log meaning."""

    _add_column(db, "audit_logs", "event_id TEXT DEFAULT ''")
    _add_column(db, "audit_logs", "category TEXT NOT NULL DEFAULT 'legacy'")
    _add_column(db, "audit_logs", "severity TEXT NOT NULL DEFAULT 'info'")
    _add_column(db, "audit_logs", "mandatory INTEGER NOT NULL DEFAULT 0")
    _add_column(db, "audit_logs", "schema_version INTEGER NOT NULL DEFAULT 1")
    _add_column(db, "audit_logs", "redaction_version INTEGER NOT NULL DEFAULT 1")
    _add_column(db, "audit_logs", "request_id TEXT NOT NULL DEFAULT ''")

    legacy_rows = db.execute(
        "SELECT id, action, detail FROM audit_logs WHERE COALESCE(event_id, '') = ''"
    ).fetchall()
    for row in legacy_rows:
        metadata = describe_action(row["action"])
        db.execute(
            "UPDATE audit_logs SET event_id=?, category=?, severity=?, mandatory=?, "
            "detail=?, redaction_version=1 "
            "WHERE id=?",
            (
                f"legacy-{row['id']}",
                metadata.category,
                metadata.severity,
                int(metadata.mandatory),
                sanitize_audit_detail(row["detail"]),
                row["id"],
            ),
        )

    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_audit_logs_event_id "
        "ON audit_logs(event_id) WHERE event_id <> ''"
    )

    if _table_exists(db, "operation_logs"):
        operation_rows = db.execute(
            "SELECT id,user_id,action,target_type,target_id,detail,created_at "
            "FROM operation_logs ORDER BY id"
        ).fetchall()
        for row in operation_rows:
            metadata = describe_action(row["action"])
            db.execute(
                "INSERT OR IGNORE INTO audit_logs "
                "(event_id,user_id,action,target_type,target_id,detail,created_at,"
                "category,severity,mandatory,schema_version,redaction_version,request_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f"operation-{row['id']}",
                    row["user_id"],
                    row["action"],
                    row["target_type"] or "",
                    row["target_id"] or 0,
                    sanitize_audit_detail(row["detail"]),
                    row["created_at"],
                    metadata.category,
                    metadata.severity,
                    int(metadata.mandatory),
                    1,
                    1,
                    "",
                ),
            )
        db.execute(
            "CREATE TRIGGER IF NOT EXISTS prevent_operation_log_insert "
            "BEFORE INSERT ON operation_logs BEGIN "
            "SELECT RAISE(ABORT, 'operation_logs is read-only; use audit_logs'); END"
        )
        db.execute(
            "CREATE TRIGGER IF NOT EXISTS prevent_operation_log_update "
            "BEFORE UPDATE ON operation_logs BEGIN "
            "SELECT RAISE(ABORT, 'operation_logs is read-only; use audit_logs'); END"
        )
        db.execute(
            "CREATE TRIGGER IF NOT EXISTS prevent_operation_log_delete "
            "BEFORE DELETE ON operation_logs BEGIN "
            "SELECT RAISE(ABORT, 'operation_logs is read-only; use audit_logs'); END"
        )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_logs_category_created "
        "ON audit_logs(category, created_at DESC, id DESC)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_logs_target "
        "ON audit_logs(target_type, target_id, created_at DESC)"
    )
    db.execute(
        "CREATE TRIGGER IF NOT EXISTS prevent_audit_log_update "
        "BEFORE UPDATE ON audit_logs BEGIN "
        "SELECT RAISE(ABORT, 'audit logs are append-only'); END"
    )

    db.execute(
        """CREATE TABLE IF NOT EXISTS audit_event_outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            action TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'legacy',
            payload TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending','processing','published','failed')),
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT NOT NULL DEFAULT '',
            next_retry_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            published_at TEXT
        )"""
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_outbox_pending "
        "ON audit_event_outbox(status, next_retry_at, id)"
    )

    db.execute(
        """CREATE TABLE IF NOT EXISTS audit_log_cleanup_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            before_at TEXT NOT NULL,
            reason TEXT NOT NULL,
            requested_by INTEGER NOT NULL,
            requested_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            approved_by INTEGER,
            approved_at TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending','approved','executed','rejected','cancelled')),
            affected_count INTEGER,
            archive_batch_id TEXT NOT NULL DEFAULT '',
            decision_reason TEXT NOT NULL DEFAULT '',
            executed_at TEXT
        )"""
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_cleanup_status "
        "ON audit_log_cleanup_requests(status, requested_at DESC)"
    )

    db.execute(
        """CREATE TABLE IF NOT EXISTS audit_log_archive (
            archive_batch_id TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            event_id TEXT NOT NULL,
            payload TEXT NOT NULL,
            archived_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            PRIMARY KEY(archive_batch_id, source_id)
        )"""
    )
    _add_column(
        db,
        "audit_log_cleanup_requests",
        "decision_reason TEXT NOT NULL DEFAULT ''",
    )
    db.execute(
        "CREATE TRIGGER IF NOT EXISTS prevent_audit_archive_update "
        "BEFORE UPDATE ON audit_log_archive BEGIN "
        "SELECT RAISE(ABORT, 'audit log archive is immutable'); END"
    )
    db.execute(
        "CREATE TRIGGER IF NOT EXISTS prevent_audit_archive_delete "
        "BEFORE DELETE ON audit_log_archive BEGIN "
        "SELECT RAISE(ABORT, 'audit log archive is immutable'); END"
    )


MIGRATIONS = [
    (66, "Add audit event metadata, outbox, and controlled cleanup foundation", m066_audit_event_foundation),
]
