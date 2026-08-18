"""Persistence for the versioned process configuration workflow."""

import json

from modules.audit_writer import insert_audit_log
from modules.domain.process_config import PROCESS_CONFIG_FIELDS
from modules.repositories.context import resolve_db


class ProcessConfigRepository:
    @staticmethod
    def get_active(db=None):
        db = resolve_db(db)
        return db.execute("SELECT * FROM process_configs WHERE id=1").fetchone()

    @staticmethod
    def get_revision(revision_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM process_config_revisions WHERE id=?", (revision_id,)
        ).fetchone()

    @staticmethod
    def list_revisions(limit=100, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM process_config_revisions "
            "WHERE config_id=1 ORDER BY version DESC LIMIT ?",
            (limit,),
        ).fetchall()

    @staticmethod
    def list_events(revision_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM process_config_events WHERE revision_id=? ORDER BY id",
            (revision_id,),
        ).fetchall()

    @staticmethod
    def open_revision(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM process_config_revisions WHERE config_id=1 "
            "AND status IN ('draft','pending_approval') ORDER BY version DESC LIMIT 1"
        ).fetchone()

    @staticmethod
    def revision_by_idempotency_key(key, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM process_config_revisions WHERE idempotency_key=?", (key,)
        ).fetchone()

    @staticmethod
    def event_by_idempotency_key(key, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM process_config_events WHERE idempotency_key=?", (key,)
        ).fetchone()

    @staticmethod
    def next_version(db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT COALESCE(MAX(version),0)+1 AS next_version "
            "FROM process_config_revisions WHERE config_id=1"
        ).fetchone()
        return int(row["next_version"])

    @staticmethod
    def create_revision(values, metadata, db):
        cursor = db.execute(
            "INSERT INTO process_config_revisions "
            "(config_id,version,process_order_mode,serial_process_report_mode,"
            "limit_by_prev_process,limit_by_order_qty,approval_enabled,status,"
            "base_row_version,row_version,changed_fields,revision_reason,created_by,"
            "created_by_name,idempotency_key) "
            "VALUES (1,?,?,?,?,?,?,'draft',?,0,?,?,?,?,?)",
            (
                metadata["version"],
                *(values[field] for field in PROCESS_CONFIG_FIELDS),
                metadata["base_row_version"],
                json.dumps(metadata["changed_fields"], ensure_ascii=False),
                metadata["revision_reason"],
                metadata["created_by"],
                metadata["created_by_name"],
                metadata["idempotency_key"],
            ),
        )
        return ProcessConfigRepository.get_revision(cursor.lastrowid, db=db)

    @staticmethod
    def update_draft(revision_id, expected_row_version, values, metadata, db):
        result = db.execute(
            "UPDATE process_config_revisions SET process_order_mode=?,"
            "serial_process_report_mode=?,limit_by_prev_process=?,limit_by_order_qty=?,"
            "approval_enabled=?,changed_fields=?,revision_reason=?,row_version=row_version+1,"
            "updated_at=datetime('now','localtime') "
            "WHERE id=? AND status='draft' AND row_version=?",
            (
                *(values[field] for field in PROCESS_CONFIG_FIELDS),
                json.dumps(metadata["changed_fields"], ensure_ascii=False),
                metadata["revision_reason"],
                revision_id,
                expected_row_version,
            ),
        )
        if result.rowcount != 1:
            return None
        return ProcessConfigRepository.get_revision(revision_id, db=db)

    @staticmethod
    def transition_revision(
        revision_id, expected_status, expected_row_version, target_status, fields, db
    ):
        assignments = ["status=?", "row_version=row_version+1", "updated_at=datetime('now','localtime')"]
        params = [target_status]
        for field, value in fields.items():
            assignments.append(f"{field}=?")
            params.append(value)
        params.extend([revision_id, expected_status, expected_row_version])
        result = db.execute(
            f"UPDATE process_config_revisions SET {','.join(assignments)} "
            "WHERE id=? AND status=? AND row_version=?",
            params,
        )
        if result.rowcount != 1:
            return None
        return ProcessConfigRepository.get_revision(revision_id, db=db)

    @staticmethod
    def publish_active(revision, actor, db):
        result = db.execute(
            "UPDATE process_configs SET process_order_mode=?,serial_process_report_mode=?,"
            "limit_by_prev_process=?,limit_by_order_qty=?,approval_enabled=?,version=?,"
            "row_version=row_version+1,active_revision_id=?,updated_by=?,updated_by_name=?,"
            "updated_at=datetime('now','localtime') WHERE id=1 AND row_version=?",
            (
                *(revision[field] for field in PROCESS_CONFIG_FIELDS),
                revision["version"],
                revision["id"],
                actor["id"],
                actor["name"],
                revision["base_row_version"],
            ),
        )
        if result.rowcount != 1:
            return None
        return ProcessConfigRepository.get_active(db=db)

    @staticmethod
    def update_legacy_mirrors(config, db):
        for field in PROCESS_CONFIG_FIELDS:
            db.execute(
                "INSERT INTO system_settings (key,value,updated_at) "
                "VALUES (?,?,datetime('now','localtime')) "
                "ON CONFLICT(key) DO UPDATE SET "
                "value=excluded.value,updated_at=excluded.updated_at",
                (field, str(config[field])),
            )

    @staticmethod
    def insert_event(revision_id, event_type, actor, key, db, **fields):
        detail = fields.pop("detail", {})
        cursor = db.execute(
            "INSERT INTO process_config_events "
            "(revision_id,event_type,actor_id,actor_name,from_status,to_status,detail,"
            "idempotency_key) VALUES (?,?,?,?,?,?,?,?)",
            (
                revision_id,
                event_type,
                actor["id"],
                actor["name"],
                fields.get("from_status", ""),
                fields.get("to_status", ""),
                json.dumps(detail, ensure_ascii=False, sort_keys=True),
                key,
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def insert_audit(action, revision, actor, db, **detail):
        payload = {
            "revision_id": revision["id"],
            "version": revision["version"],
            "status": revision["status"],
            **detail,
        }
        return insert_audit_log(
            db,
            actor["id"],
            action,
            "process_config_revision",
            revision["id"],
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
        )
