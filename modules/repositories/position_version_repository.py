"""SQL primitives for stable position roots and immutable revisions."""

import json
import sqlite3

from modules.domain.position_versioning import (
    PositionVersionAlreadyOpenError,
    PositionVersionStaleError,
)
from modules.repositories.context import resolve_db


class PositionVersionRepository:
    _VERSION_CONTENT_FIELDS = {
        "name",
        "description",
        "revision_reason",
        "content_digest",
        "impact_digest",
    }
    _VERSION_TRANSITION_FIELDS = {
        "effective_from",
        "effective_to",
        "submitted_at",
        "approved_by",
        "approved_by_name",
        "approved_at",
        "published_at",
        "content_digest",
        "impact_digest",
    }
    _LIFECYCLE_TRANSITION_FIELDS = {
        "approved_by",
        "approved_by_name",
        "resolved_at",
        "impact_digest",
    }

    @staticmethod
    def root(position_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM positions WHERE id=?", (position_id,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def roots(position_ids=None, db=None):
        db = resolve_db(db)
        params = []
        where = ""
        if position_ids is not None:
            normalized = list(dict.fromkeys(int(value) for value in position_ids))
            if not normalized:
                return []
            where = " WHERE id IN (" + ",".join("?" for _ in normalized) + ")"
            params.extend(normalized)
        roots = [
            dict(row)
            for row in db.execute(
                "SELECT * FROM positions" + where + " ORDER BY id", params
            ).fetchall()
        ]
        version_ids = [
            root["current_effective_version_id"]
            for root in roots
            if root.get("current_effective_version_id") is not None
        ]
        versions = {
            version["id"]: version
            for version in PositionVersionRepository.versions_by_ids(
                version_ids, db=db
            )
        }
        for root in roots:
            root["current_version"] = versions.get(
                root.get("current_effective_version_id")
            )
        return roots

    @staticmethod
    def _attach_processes(versions, db):
        if not versions:
            return versions
        version_ids = [version["id"] for version in versions]
        placeholders = ",".join("?" for _ in version_ids)
        process_map = {}
        for row in db.execute(
            "SELECT position_version_id,process_id,seq_order "
            "FROM position_version_processes WHERE position_version_id IN ("
            + placeholders
            + ") ORDER BY position_version_id,seq_order,id",
            version_ids,
        ).fetchall():
            process_map.setdefault(row["position_version_id"], []).append(
                {
                    "process_id": int(row["process_id"]),
                    "seq_order": int(row["seq_order"]),
                }
            )
        for version in versions:
            processes = process_map.get(version["id"], [])
            version["processes"] = processes
            version["process_ids"] = [item["process_id"] for item in processes]
        return versions

    @staticmethod
    def version(version_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM position_versions WHERE id=?", (version_id,)
        ).fetchone()
        if row is None:
            return None
        return PositionVersionRepository._attach_processes([dict(row)], db)[0]

    @staticmethod
    def versions_by_ids(version_ids, db=None):
        db = resolve_db(db)
        normalized = list(dict.fromkeys(int(value) for value in version_ids))
        if not normalized:
            return []
        placeholders = ",".join("?" for _ in normalized)
        versions = [
            dict(row)
            for row in db.execute(
                "SELECT * FROM position_versions WHERE id IN ("
                + placeholders
                + ") ORDER BY position_id,version,id",
                normalized,
            ).fetchall()
        ]
        return PositionVersionRepository._attach_processes(versions, db)

    @staticmethod
    def version_by_number(position_id, version, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT id FROM position_versions WHERE position_id=? AND version=?",
            (position_id, version),
        ).fetchone()
        return PositionVersionRepository.version(row["id"], db=db) if row else None

    @staticmethod
    def version_by_idempotency_key(idempotency_key, db=None):
        key = str(idempotency_key or "")
        if not key:
            return None
        db = resolve_db(db)
        row = db.execute(
            "SELECT id FROM position_versions WHERE idempotency_key=?", (key,)
        ).fetchone()
        return PositionVersionRepository.version(row["id"], db=db) if row else None

    @staticmethod
    def current_version(position_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT version.id FROM positions position "
            "JOIN position_versions version "
            "ON version.id=position.current_effective_version_id "
            "AND version.position_id=position.id WHERE position.id=?",
            (position_id,),
        ).fetchone()
        return PositionVersionRepository.version(row["id"], db=db) if row else None

    @staticmethod
    def open_version(position_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT id FROM position_versions WHERE position_id=? "
            "AND status IN ('draft','pending_approval') "
            "ORDER BY version DESC,id DESC LIMIT 1",
            (position_id,),
        ).fetchone()
        return PositionVersionRepository.version(row["id"], db=db) if row else None

    @staticmethod
    def list_versions(position_id, db=None):
        db = resolve_db(db)
        rows = db.execute(
            "SELECT * FROM position_versions WHERE position_id=? ORDER BY version,id",
            (position_id,),
        ).fetchall()
        return PositionVersionRepository._attach_processes(
            [dict(row) for row in rows], db
        )

    @staticmethod
    def create_root(payload, db):
        cursor = db.execute(
            "INSERT INTO positions ("
            "id,position_code,name,description,status,lifecycle_status,row_version,"
            "created_by,updated_at) "
            "SELECT next_id,printf('POS-%04d',next_id),?,?,'inactive','active',0,?,"
            "datetime('now','localtime') FROM ("
            "SELECT COALESCE(MAX(id),0)+1 AS next_id FROM positions)",
            (
                payload["name"],
                payload.get("description", ""),
                payload.get("created_by"),
            ),
        )
        return PositionVersionRepository.root(cursor.lastrowid, db=db)

    @staticmethod
    def create_revision(position_id, payload, db):
        key = str(payload.get("idempotency_key") or "")
        replay = PositionVersionRepository.version_by_idempotency_key(key, db=db)
        if replay is not None:
            return replay
        try:
            cursor = db.execute(
                "INSERT INTO position_versions ("
                "position_id,version,position_code_snapshot,name,description,status,"
                "effective_from,effective_to,supersedes_version_id,revision_reason,"
                "legacy_baseline,prior_revision_unavailable,content_digest,impact_digest,"
                "idempotency_key,created_by,created_by_name,submitted_at,approved_by,"
                "approved_by_name,approved_at,published_at,row_version) "
                "SELECT ?,COALESCE(MAX(version),0)+1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0 "
                "FROM position_versions WHERE position_id=?",
                (
                    position_id,
                    payload["position_code_snapshot"],
                    payload["name"],
                    payload.get("description", ""),
                    payload.get("status", "draft"),
                    payload.get("effective_from", ""),
                    payload.get("effective_to", ""),
                    payload.get("supersedes_version_id"),
                    payload.get("revision_reason", ""),
                    int(bool(payload.get("legacy_baseline", 0))),
                    int(bool(payload.get("prior_revision_unavailable", 0))),
                    payload.get("content_digest", ""),
                    payload.get("impact_digest", ""),
                    key,
                    payload.get("created_by"),
                    payload.get("created_by_name", ""),
                    payload.get("submitted_at", ""),
                    payload.get("approved_by"),
                    payload.get("approved_by_name", ""),
                    payload.get("approved_at", ""),
                    payload.get("published_at", ""),
                    position_id,
                ),
            )
        except sqlite3.IntegrityError as exc:
            replay = PositionVersionRepository.version_by_idempotency_key(key, db=db)
            if replay is not None:
                return replay
            raise PositionVersionAlreadyOpenError(
                "该岗位已有草稿或待审批修订版",
                details={"position_id": position_id},
            ) from exc
        return PositionVersionRepository.version(cursor.lastrowid, db=db)

    @staticmethod
    def replace_version_processes(version_id, process_ids, db):
        normalized = list(dict.fromkeys(int(value) for value in process_ids))
        db.execute(
            "DELETE FROM position_version_processes WHERE position_version_id=?",
            (version_id,),
        )
        for seq_order, process_id in enumerate(normalized, start=1):
            db.execute(
                "INSERT INTO position_version_processes "
                "(position_version_id,process_id,seq_order) VALUES (?,?,?)",
                (version_id, process_id, seq_order),
            )
        return PositionVersionRepository.version(version_id, db=db)

    @staticmethod
    def update_version_content(
        version_id, expected_status, expected_row_version, fields, db
    ):
        values_by_field = dict(fields or {})
        if not set(values_by_field).issubset(
            PositionVersionRepository._VERSION_CONTENT_FIELDS
        ):
            raise ValueError("非法岗位版本更新字段")
        assignments = [field + "=?" for field in values_by_field]
        values = list(values_by_field.values())
        assignments.append("row_version=row_version+1")
        values.extend([version_id, expected_status, expected_row_version])
        cursor = db.execute(
            "UPDATE position_versions SET "
            + ",".join(assignments)
            + " WHERE id=? AND status=? AND row_version=?",
            values,
        )
        if cursor.rowcount != 1:
            raise PositionVersionStaleError("岗位版本状态已变化，请刷新后重试")
        return PositionVersionRepository.version(version_id, db=db)

    @staticmethod
    def transition_version(
        version_id,
        expected_status,
        expected_row_version,
        target_status,
        fields,
        db,
    ):
        values_by_field = dict(fields or {})
        if not set(values_by_field).issubset(
            PositionVersionRepository._VERSION_TRANSITION_FIELDS
        ):
            raise ValueError("非法岗位版本状态更新字段")
        assignments = ["status=?"] + [
            field + "=?" for field in values_by_field
        ]
        values = [target_status] + list(values_by_field.values())
        assignments.append("row_version=row_version+1")
        values.extend([version_id, expected_status, expected_row_version])
        cursor = db.execute(
            "UPDATE position_versions SET "
            + ",".join(assignments)
            + " WHERE id=? AND status=? AND row_version=?",
            values,
        )
        if cursor.rowcount != 1:
            raise PositionVersionStaleError("岗位版本状态已变化，请刷新后重试")
        return PositionVersionRepository.version(version_id, db=db)

    @staticmethod
    def update_compatibility_projection(
        position_id, version_id, expected_root_row_version, db
    ):
        cursor = db.execute(
            "UPDATE positions SET "
            "name=(SELECT name FROM position_versions "
            "WHERE id=? AND position_id=positions.id),"
            "description=(SELECT description FROM position_versions "
            "WHERE id=? AND position_id=positions.id),"
            "current_effective_version_id=?,"
            "status=CASE WHEN lifecycle_status='active' THEN 'active' ELSE 'inactive' END,"
            "row_version=row_version+1,updated_at=datetime('now','localtime') "
            "WHERE id=? AND row_version=? AND EXISTS ("
            "SELECT 1 FROM position_versions WHERE id=? AND position_id=positions.id)",
            (
                version_id,
                version_id,
                version_id,
                position_id,
                expected_root_row_version,
                version_id,
            ),
        )
        if cursor.rowcount != 1:
            raise PositionVersionStaleError("岗位根数据已变化，请刷新后重试")
        db.execute(
            "DELETE FROM position_processes WHERE position_id=?", (position_id,)
        )
        db.execute(
            "INSERT INTO position_processes(position_id,process_id) "
            "SELECT ?,process_id FROM position_version_processes "
            "WHERE position_version_id=? ORDER BY seq_order,id",
            (position_id, version_id),
        )
        return PositionVersionRepository.root(position_id, db=db)

    @staticmethod
    def update_root_lifecycle(
        position_id,
        expected_row_version,
        lifecycle_status,
        *,
        retired_at="",
        db,
    ):
        cursor = db.execute(
            "UPDATE positions SET lifecycle_status=?,"
            "status=CASE WHEN ?='active' THEN 'active' ELSE 'inactive' END,"
            "retired_at=?,row_version=row_version+1,"
            "updated_at=datetime('now','localtime') "
            "WHERE id=? AND row_version=?",
            (
                lifecycle_status,
                lifecycle_status,
                retired_at,
                position_id,
                expected_row_version,
            ),
        )
        if cursor.rowcount != 1:
            raise PositionVersionStaleError("岗位根数据已变化，请刷新后重试")
        return PositionVersionRepository.root(position_id, db=db)

    @staticmethod
    def _event_row(row):
        if row is None:
            return None
        result = dict(row)
        try:
            result["payload"] = json.loads(result.get("payload_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            result["payload"] = {}
        return result

    @staticmethod
    def event_by_idempotency_key(idempotency_key, db=None):
        key = str(idempotency_key or "")
        if not key:
            return None
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM position_version_events WHERE idempotency_key=?",
            (key,),
        ).fetchone()
        return PositionVersionRepository._event_row(row)

    @staticmethod
    def create_event(payload, db):
        key = str(payload.get("idempotency_key") or "")
        replay = PositionVersionRepository.event_by_idempotency_key(key, db=db)
        if replay is not None:
            return replay
        cursor = db.execute(
            "INSERT INTO position_version_events ("
            "position_id,position_version_id,event_type,from_status,to_status,actor_id,"
            "actor_name,actor_role,reason,impact_digest,payload_json,idempotency_key) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                payload["position_id"],
                payload.get("position_version_id"),
                payload["event_type"],
                payload.get("from_status", ""),
                payload.get("to_status", ""),
                payload.get("actor_id"),
                payload.get("actor_name", ""),
                payload.get("actor_role", ""),
                payload.get("reason", ""),
                payload.get("impact_digest", ""),
                json.dumps(
                    payload.get("payload") or {},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                key,
            ),
        )
        row = db.execute(
            "SELECT * FROM position_version_events WHERE id=?", (cursor.lastrowid,)
        ).fetchone()
        return PositionVersionRepository._event_row(row)

    @staticmethod
    def list_events(position_id, db=None):
        db = resolve_db(db)
        return [
            PositionVersionRepository._event_row(row)
            for row in db.execute(
                "SELECT * FROM position_version_events WHERE position_id=? "
                "ORDER BY created_at,id",
                (position_id,),
            ).fetchall()
        ]

    @staticmethod
    def lifecycle_request(request_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM position_lifecycle_requests WHERE id=?", (request_id,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def lifecycle_request_by_idempotency_key(idempotency_key, db=None):
        key = str(idempotency_key or "")
        if not key:
            return None
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM position_lifecycle_requests WHERE idempotency_key=?",
            (key,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def pending_lifecycle_request(position_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM position_lifecycle_requests WHERE position_id=? "
            "AND status='pending' ORDER BY id DESC LIMIT 1",
            (position_id,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def list_lifecycle_requests(position_id, db=None):
        db = resolve_db(db)
        return [
            dict(row)
            for row in db.execute(
                "SELECT * FROM position_lifecycle_requests WHERE position_id=? "
                "ORDER BY created_at,id",
                (position_id,),
            ).fetchall()
        ]

    @staticmethod
    def create_lifecycle_request(payload, db):
        key = str(payload.get("idempotency_key") or "")
        replay = PositionVersionRepository.lifecycle_request_by_idempotency_key(
            key, db=db
        )
        if replay is not None:
            return replay
        try:
            cursor = db.execute(
                "INSERT INTO position_lifecycle_requests ("
                "position_id,action,status,reason,impact_digest,requested_by,"
                "requested_by_name,idempotency_key,row_version) "
                "VALUES (?,?,'pending',?,?,?,?,?,0)",
                (
                    payload["position_id"],
                    payload["action"],
                    payload["reason"],
                    payload.get("impact_digest", ""),
                    payload.get("requested_by"),
                    payload.get("requested_by_name", ""),
                    key,
                ),
            )
        except sqlite3.IntegrityError as exc:
            replay = PositionVersionRepository.lifecycle_request_by_idempotency_key(
                key, db=db
            )
            if replay is not None:
                return replay
            raise PositionVersionAlreadyOpenError(
                "该岗位已有待处理生命周期申请",
                details={"position_id": payload["position_id"]},
            ) from exc
        return PositionVersionRepository.lifecycle_request(
            cursor.lastrowid, db=db
        )

    @staticmethod
    def transition_lifecycle_request(
        request_id,
        expected_status,
        expected_row_version,
        target_status,
        fields,
        db,
    ):
        values_by_field = dict(fields or {})
        if not set(values_by_field).issubset(
            PositionVersionRepository._LIFECYCLE_TRANSITION_FIELDS
        ):
            raise ValueError("非法岗位生命周期状态更新字段")
        assignments = ["status=?"] + [
            field + "=?" for field in values_by_field
        ]
        values = [target_status] + list(values_by_field.values())
        assignments.append("row_version=row_version+1")
        values.extend([request_id, expected_status, expected_row_version])
        cursor = db.execute(
            "UPDATE position_lifecycle_requests SET "
            + ",".join(assignments)
            + " WHERE id=? AND status=? AND row_version=?",
            values,
        )
        if cursor.rowcount != 1:
            raise PositionVersionStaleError(
                "岗位生命周期申请已变化，请刷新后重试"
            )
        return PositionVersionRepository.lifecycle_request(request_id, db=db)
