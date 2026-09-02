"""Persistence primitives for stable process roots and immutable revisions."""

import json
import sqlite3

from modules.domain.errors import ConflictError
from modules.domain.process_versioning import ProcessVersionStaleError
from modules.repositories.context import resolve_db


class ProcessVersionRepository:
    """SQL-only process version access used by version workflow services."""

    _VERSION_CONTENT_FIELDS = {
        "name",
        "category",
        "description",
        "seq_order",
        "revision_reason",
        "impact_digest",
        "content_digest",
    }
    _TRANSITION_FIELDS = {
        "effective_from",
        "effective_to",
        "approved_by",
        "approved_by_name",
        "approved_at",
        "published_at",
        "impact_digest",
        "content_digest",
    }

    @staticmethod
    def root(process_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM processes WHERE id=?", (process_id,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def roots(process_ids=None, db=None):
        """Return roots with their current versions in two bounded queries."""
        db = resolve_db(db)
        params = []
        where_sql = ""
        if process_ids is not None:
            normalized = list(dict.fromkeys(int(value) for value in process_ids))
            if not normalized:
                return []
            where_sql = " WHERE process.id IN (" + ",".join("?" for _ in normalized) + ")"
            params.extend(normalized)
        roots = [
            dict(row)
            for row in db.execute(
                "SELECT process.* FROM processes process"
                + where_sql
                + " ORDER BY process.seq_order,process.id",
                params,
            ).fetchall()
        ]
        version_ids = [
            root["current_effective_version_id"]
            for root in roots
            if root.get("current_effective_version_id") is not None
        ]
        versions = {
            version["id"]: version
            for version in ProcessVersionRepository.versions_by_ids(version_ids, db=db)
        }
        for root in roots:
            root["current_version"] = versions.get(root.get("current_effective_version_id"))
        return roots

    @staticmethod
    def version(version_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM process_versions WHERE id=?", (version_id,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def versions_by_ids(version_ids, db=None):
        db = resolve_db(db)
        normalized = list(dict.fromkeys(int(value) for value in version_ids))
        if not normalized:
            return []
        placeholders = ",".join("?" for _ in normalized)
        rows = db.execute(
            "SELECT * FROM process_versions WHERE id IN ("
            + placeholders
            + ") ORDER BY process_id,version,id",
            normalized,
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def version_by_number(process_id, version, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM process_versions WHERE process_id=? AND version=?",
            (process_id, version),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def version_by_idempotency_key(idempotency_key, db=None):
        key = str(idempotency_key or "")
        if not key:
            return None
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM process_versions WHERE idempotency_key=?", (key,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def current_version(process_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT version.* FROM processes process "
            "JOIN process_versions version "
            "ON version.id=process.current_effective_version_id "
            "WHERE process.id=? AND version.process_id=process.id",
            (process_id,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def open_version(process_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM process_versions WHERE process_id=? "
            "AND status IN ('draft','pending_approval') ORDER BY version DESC,id DESC LIMIT 1",
            (process_id,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def pending_routes_for_process_version(process_version_id, db=None):
        db = resolve_db(db)
        rows = db.execute(
            "SELECT DISTINCT route_version.* FROM process_route_versions route_version "
            "JOIN process_route_version_items item "
            "ON item.route_version_id=route_version.id "
            "WHERE item.process_version_id=? "
            "AND route_version.status='pending_approval' "
            "ORDER BY route_version.process_route_id,route_version.version,route_version.id",
            (process_version_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def list_versions(process_id, db=None):
        db = resolve_db(db)
        rows = db.execute(
            "SELECT * FROM process_versions WHERE process_id=? ORDER BY version,id",
            (process_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def create_root(payload, db):
        """Allocate a stable root identity without committing the caller's transaction."""
        cursor = db.execute(
            "INSERT INTO processes ("
            "id,process_code,name,description,category,seq_order,status,lifecycle_status,"
            "row_version,created_by,updated_at) "
            "SELECT next_id,printf('PROC-%04d',next_id),?,?,?,?,?,'active',0,?,"
            "datetime('now','localtime') FROM ("
            "SELECT COALESCE(MAX(id),0)+1 AS next_id FROM processes)",
            (
                payload["name"],
                payload.get("description", ""),
                payload.get("category", ""),
                payload.get("seq_order", 0),
                payload.get("status", "inactive"),
                payload.get("created_by"),
            ),
        )
        return ProcessVersionRepository.root(cursor.lastrowid, db=db)

    @staticmethod
    def create_revision(process_id, payload, db):
        key = str(payload.get("idempotency_key") or "")
        existing = ProcessVersionRepository.version_by_idempotency_key(key, db=db)
        if existing is not None:
            return existing

        try:
            cursor = db.execute(
                "INSERT INTO process_versions ("
                "process_id,version,process_code_snapshot,name,category,description,seq_order,"
                "status,effective_from,effective_to,supersedes_version_id,revision_reason,"
                "impact_digest,content_digest,legacy_baseline,prior_revision_unavailable,"
                "created_by,created_by_name,approved_by,approved_by_name,approved_at,"
                "published_at,idempotency_key,row_version) "
                "SELECT ?,COALESCE(MAX(version),0)+1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0 "
                "FROM process_versions WHERE process_id=?",
                (
                    process_id,
                    payload["process_code_snapshot"],
                    payload["name"],
                    payload.get("category", ""),
                    payload.get("description", ""),
                    payload.get("seq_order", 0),
                    payload.get("status", "draft"),
                    payload.get("effective_from", ""),
                    payload.get("effective_to", ""),
                    payload.get("supersedes_version_id"),
                    payload.get("revision_reason", ""),
                    payload.get("impact_digest", ""),
                    payload.get("content_digest", ""),
                    int(bool(payload.get("legacy_baseline", 0))),
                    int(bool(payload.get("prior_revision_unavailable", 0))),
                    payload.get("created_by"),
                    payload.get("created_by_name", ""),
                    payload.get("approved_by"),
                    payload.get("approved_by_name", ""),
                    payload.get("approved_at", ""),
                    payload.get("published_at", ""),
                    key,
                    process_id,
                ),
            )
        except sqlite3.IntegrityError as exc:
            replay = ProcessVersionRepository.version_by_idempotency_key(key, db=db)
            if replay is not None:
                return replay
            raise ConflictError(
                "工序修订版创建冲突，请刷新后重试",
                details={"process_id": process_id},
            ) from exc
        return ProcessVersionRepository.version(cursor.lastrowid, db=db)

    @staticmethod
    def update_version_content(
        version_id, expected_status, expected_row_version, fields, db
    ):
        fields = dict(fields or {})
        if not set(fields).issubset(ProcessVersionRepository._VERSION_CONTENT_FIELDS):
            raise ValueError("非法工序版本更新字段")
        assignments = [key + "=?" for key in fields]
        values = list(fields.values())
        assignments.append("row_version=row_version+1")
        values.extend([version_id, expected_status, expected_row_version])
        cursor = db.execute(
            "UPDATE process_versions SET "
            + ",".join(assignments)
            + " WHERE id=? AND status=? AND row_version=?",
            values,
        )
        if cursor.rowcount != 1:
            raise ProcessVersionStaleError("工序版本状态已变化，请刷新后重试")
        return ProcessVersionRepository.version(version_id, db=db)

    @staticmethod
    def transition_version(
        version_id,
        expected_status,
        expected_row_version,
        target_status,
        fields,
        db,
    ):
        fields = dict(fields or {})
        if not set(fields).issubset(ProcessVersionRepository._TRANSITION_FIELDS):
            raise ValueError("非法工序版本状态更新字段")
        assignments = ["status=?"] + [key + "=?" for key in fields]
        values = [target_status] + list(fields.values())
        assignments.append("row_version=row_version+1")
        values.extend([version_id, expected_status, expected_row_version])
        cursor = db.execute(
            "UPDATE process_versions SET "
            + ",".join(assignments)
            + " WHERE id=? AND status=? AND row_version=?",
            values,
        )
        if cursor.rowcount != 1:
            raise ProcessVersionStaleError("工序版本状态已变化，请刷新后重试")
        return ProcessVersionRepository.version(version_id, db=db)

    @staticmethod
    def update_compatibility_projection(
        process_id, version_id, expected_root_row_version, db
    ):
        cursor = db.execute(
            "UPDATE processes SET "
            "name=(SELECT name FROM process_versions WHERE id=? AND process_id=processes.id),"
            "category=(SELECT category FROM process_versions WHERE id=? AND process_id=processes.id),"
            "description=(SELECT description FROM process_versions WHERE id=? AND process_id=processes.id),"
            "seq_order=(SELECT seq_order FROM process_versions WHERE id=? AND process_id=processes.id),"
            "current_effective_version_id=?,"
            "status=CASE WHEN lifecycle_status='active' THEN 'active' ELSE 'inactive' END,"
            "row_version=row_version+1,updated_at=datetime('now','localtime') "
            "WHERE id=? AND row_version=? AND EXISTS ("
            "SELECT 1 FROM process_versions WHERE id=? AND process_id=processes.id)",
            (
                version_id,
                version_id,
                version_id,
                version_id,
                version_id,
                process_id,
                expected_root_row_version,
                version_id,
            ),
        )
        if cursor.rowcount != 1:
            raise ProcessVersionStaleError("工序根实体版本已变化，请刷新后重试")
        return ProcessVersionRepository.root(process_id, db=db)

    @staticmethod
    def transition_root_lifecycle(
        process_id,
        expected_lifecycle_status,
        expected_row_version,
        target_lifecycle_status,
        legacy_status,
        db,
    ):
        cursor = db.execute(
            "UPDATE processes SET lifecycle_status=?,status=?,row_version=row_version+1,"
            "updated_at=datetime('now','localtime') "
            "WHERE id=? AND lifecycle_status=? AND row_version=?",
            (
                target_lifecycle_status,
                legacy_status,
                process_id,
                expected_lifecycle_status,
                expected_row_version,
            ),
        )
        if cursor.rowcount != 1:
            raise ProcessVersionStaleError("工序生命周期已变化，请刷新后重试")
        return ProcessVersionRepository.root(process_id, db=db)

    @staticmethod
    def event_by_idempotency_key(idempotency_key, db=None):
        key = str(idempotency_key or "")
        if not key:
            return None
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM process_version_events WHERE idempotency_key=?", (key,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def insert_event(payload, db):
        key = str(payload.get("idempotency_key") or "")
        existing = ProcessVersionRepository.event_by_idempotency_key(key, db=db)
        if existing is not None:
            return existing
        try:
            cursor = db.execute(
                "INSERT INTO process_version_events ("
                "entity_id,version_id,event_type,actor_id,actor_name,actor_role,reason,"
                "impact_digest,idempotency_key,from_status,to_status,payload_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    payload["entity_id"],
                    payload.get("version_id"),
                    payload["event_type"],
                    payload.get("actor_id"),
                    payload.get("actor_name", ""),
                    payload.get("actor_role", ""),
                    payload.get("reason", ""),
                    payload.get("impact_digest", ""),
                    key,
                    payload.get("from_status", ""),
                    payload.get("to_status", ""),
                    json.dumps(
                        payload.get("payload", {}),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                ),
            )
        except sqlite3.IntegrityError:
            replay = ProcessVersionRepository.event_by_idempotency_key(key, db=db)
            if replay is None:
                raise
            return replay
        return ProcessVersionRepository.event(cursor.lastrowid, db=db)

    @staticmethod
    def event(event_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM process_version_events WHERE id=?", (event_id,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def list_events(process_id, db=None):
        db = resolve_db(db)
        rows = db.execute(
            "SELECT * FROM process_version_events WHERE entity_id=? ORDER BY created_at,id",
            (process_id,),
        ).fetchall()
        return [dict(row) for row in rows]
