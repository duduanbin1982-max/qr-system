"""Persistence primitives for stable process-route roots and revisions."""

import json
import sqlite3

from modules.domain.errors import ConflictError
from modules.domain.process_versioning import RouteVersionStaleError
from modules.repositories.context import resolve_db


class RouteVersionRepository:
    """SQL-only route version access, including bounded item prefetching."""

    _VERSION_CONTENT_FIELDS = {
        "name",
        "category",
        "description",
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
    def root(route_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM process_routes WHERE id=?", (route_id,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def roots(route_ids=None, db=None):
        """Return roots, current revisions, and nodes without per-row queries."""
        db = resolve_db(db)
        params = []
        where_sql = ""
        if route_ids is not None:
            normalized = list(dict.fromkeys(int(value) for value in route_ids))
            if not normalized:
                return []
            where_sql = " WHERE route.id IN (" + ",".join("?" for _ in normalized) + ")"
            params.extend(normalized)
        roots = [
            dict(row)
            for row in db.execute(
                "SELECT route.* FROM process_routes route"
                + where_sql
                + " ORDER BY route.category,route.name,route.id",
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
            for version in RouteVersionRepository.versions_by_ids(version_ids, db=db)
        }
        for root in roots:
            root["current_version"] = versions.get(root.get("current_effective_version_id"))
        return roots

    @staticmethod
    def _attach_items(versions, db):
        if not versions:
            return versions
        version_map = {version["id"]: version for version in versions}
        for version in versions:
            version["items"] = []
        placeholders = ",".join("?" for _ in version_map)
        rows = db.execute(
            "SELECT item.*,process_version.name AS process_name_snapshot,"
            "process_version.category AS process_category,"
            "process_version.status AS process_version_status "
            "FROM process_route_version_items item "
            "JOIN process_versions process_version ON process_version.id=item.process_version_id "
            "WHERE item.route_version_id IN ("
            + placeholders
            + ") ORDER BY item.route_version_id,item.seq_order,item.id",
            list(version_map),
        ).fetchall()
        for row in rows:
            item = dict(row)
            version_map[item["route_version_id"]]["items"].append(item)
        return versions

    @staticmethod
    def version(version_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM process_route_versions WHERE id=?", (version_id,)
        ).fetchone()
        if row is None:
            return None
        return RouteVersionRepository._attach_items([dict(row)], db)[0]

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
                "SELECT * FROM process_route_versions WHERE id IN ("
                + placeholders
                + ") ORDER BY process_route_id,version,id",
                normalized,
            ).fetchall()
        ]
        return RouteVersionRepository._attach_items(versions, db)

    @staticmethod
    def version_by_number(route_id, version, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM process_route_versions "
            "WHERE process_route_id=? AND version=?",
            (route_id, version),
        ).fetchone()
        if row is None:
            return None
        return RouteVersionRepository._attach_items([dict(row)], db)[0]

    @staticmethod
    def version_by_idempotency_key(idempotency_key, db=None):
        key = str(idempotency_key or "")
        if not key:
            return None
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM process_route_versions WHERE idempotency_key=?", (key,)
        ).fetchone()
        if row is None:
            return None
        return RouteVersionRepository._attach_items([dict(row)], db)[0]

    @staticmethod
    def current_version(route_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT version.* FROM process_routes route "
            "JOIN process_route_versions version "
            "ON version.id=route.current_effective_version_id "
            "WHERE route.id=? AND version.process_route_id=route.id",
            (route_id,),
        ).fetchone()
        if row is None:
            return None
        return RouteVersionRepository._attach_items([dict(row)], db)[0]

    @staticmethod
    def open_version(route_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM process_route_versions WHERE process_route_id=? "
            "AND status IN ('draft','pending_approval') ORDER BY version DESC,id DESC LIMIT 1",
            (route_id,),
        ).fetchone()
        if row is None:
            return None
        return RouteVersionRepository._attach_items([dict(row)], db)[0]

    @staticmethod
    def list_versions(route_id, db=None):
        db = resolve_db(db)
        versions = [
            dict(row)
            for row in db.execute(
                "SELECT * FROM process_route_versions WHERE process_route_id=? "
                "ORDER BY version,id",
                (route_id,),
            ).fetchall()
        ]
        return RouteVersionRepository._attach_items(versions, db)

    @staticmethod
    def current_versions_for_process_ids(process_ids, db=None):
        db = resolve_db(db)
        normalized = list(dict.fromkeys(int(value) for value in process_ids))
        if not normalized:
            return []
        placeholders = ",".join("?" for _ in normalized)
        versions = [
            dict(row)
            for row in db.execute(
                "SELECT DISTINCT version.* FROM process_routes route "
                "JOIN process_route_versions version "
                "ON version.id=route.current_effective_version_id "
                "JOIN process_route_version_items item "
                "ON item.route_version_id=version.id "
                "WHERE item.process_id IN (" + placeholders + ") "
                "ORDER BY version.process_route_id,version.id",
                normalized,
            ).fetchall()
        ]
        return RouteVersionRepository._attach_items(versions, db)

    @staticmethod
    def find_legacy_items(route_id, db=None):
        db = resolve_db(db)
        rows = db.execute(
            "SELECT * FROM process_route_items WHERE route_id=? ORDER BY seq_order,id",
            (route_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def create_root(payload, db):
        cursor = db.execute(
            "INSERT INTO process_routes ("
            "id,route_code,name,description,category,status,lifecycle_status,row_version,"
            "created_by,updated_at) "
            "SELECT next_id,printf('ROUTE-%04d',next_id),?,?,?,?,'active',0,?,"
            "datetime('now','localtime') FROM ("
            "SELECT COALESCE(MAX(id),0)+1 AS next_id FROM process_routes)",
            (
                payload["name"],
                payload.get("description", ""),
                payload.get("category", ""),
                payload.get("status", "inactive"),
                payload.get("created_by"),
            ),
        )
        return RouteVersionRepository.root(cursor.lastrowid, db=db)

    @staticmethod
    def _insert_items(route_version_id, items, db):
        for item in items:
            db.execute(
                "INSERT INTO process_route_version_items ("
                "route_version_id,process_id,process_version_id,seq_order,is_required,"
                "required_audit,legacy_route_item_id) VALUES (?,?,?,?,?,?,?)",
                (
                    route_version_id,
                    item["process_id"],
                    item["process_version_id"],
                    item.get("seq_order", 0),
                    int(bool(item.get("is_required", 1))),
                    int(bool(item.get("required_audit", 0))),
                    item.get("legacy_route_item_id"),
                ),
            )

    @staticmethod
    def create_revision(route_id, payload, items, db):
        key = str(payload.get("idempotency_key") or "")
        existing = RouteVersionRepository.version_by_idempotency_key(key, db=db)
        if existing is not None:
            return existing
        try:
            cursor = db.execute(
                "INSERT INTO process_route_versions ("
                "process_route_id,version,route_code_snapshot,name,category,description,status,"
                "effective_from,effective_to,supersedes_version_id,revision_reason,impact_digest,"
                "content_digest,legacy_baseline,prior_revision_unavailable,created_by,"
                "created_by_name,approved_by,approved_by_name,approved_at,published_at,"
                "idempotency_key,row_version) "
                "SELECT ?,COALESCE(MAX(version),0)+1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0 "
                "FROM process_route_versions WHERE process_route_id=?",
                (
                    route_id,
                    payload["route_code_snapshot"],
                    payload["name"],
                    payload.get("category", ""),
                    payload.get("description", ""),
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
                    route_id,
                ),
            )
        except sqlite3.IntegrityError as exc:
            replay = RouteVersionRepository.version_by_idempotency_key(key, db=db)
            if replay is not None:
                return replay
            raise ConflictError(
                "路线修订版创建冲突，请刷新后重试",
                details={"process_route_id": route_id},
            ) from exc
        try:
            RouteVersionRepository._insert_items(cursor.lastrowid, items, db)
        except sqlite3.IntegrityError as exc:
            raise ConflictError(
                "路线修订版节点写入冲突，请检查工序版本、顺序和重复节点",
                details={"process_route_id": route_id},
            ) from exc
        return RouteVersionRepository.version(cursor.lastrowid, db=db)

    @staticmethod
    def update_version_content(
        version_id, expected_status, expected_row_version, fields, db
    ):
        fields = dict(fields or {})
        if not set(fields).issubset(RouteVersionRepository._VERSION_CONTENT_FIELDS):
            raise ValueError("非法路线版本更新字段")
        assignments = [key + "=?" for key in fields]
        values = list(fields.values())
        assignments.append("row_version=row_version+1")
        values.extend([version_id, expected_status, expected_row_version])
        cursor = db.execute(
            "UPDATE process_route_versions SET "
            + ",".join(assignments)
            + " WHERE id=? AND status=? AND row_version=?",
            values,
        )
        if cursor.rowcount != 1:
            raise RouteVersionStaleError("路线版本状态已变化，请刷新后重试")
        return RouteVersionRepository.version(version_id, db=db)

    @staticmethod
    def replace_items(
        version_id, expected_status, expected_row_version, items, db
    ):
        cursor = db.execute(
            "UPDATE process_route_versions SET row_version=row_version+1 "
            "WHERE id=? AND status=? AND row_version=?",
            (version_id, expected_status, expected_row_version),
        )
        if cursor.rowcount != 1:
            raise RouteVersionStaleError("路线版本状态已变化，请刷新后重试")
        db.execute(
            "DELETE FROM process_route_version_items WHERE route_version_id=?",
            (version_id,),
        )
        RouteVersionRepository._insert_items(version_id, items, db)
        return RouteVersionRepository.version(version_id, db=db)

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
        if not set(fields).issubset(RouteVersionRepository._TRANSITION_FIELDS):
            raise ValueError("非法路线版本状态更新字段")
        assignments = ["status=?"] + [key + "=?" for key in fields]
        values = [target_status] + list(fields.values())
        assignments.append("row_version=row_version+1")
        values.extend([version_id, expected_status, expected_row_version])
        cursor = db.execute(
            "UPDATE process_route_versions SET "
            + ",".join(assignments)
            + " WHERE id=? AND status=? AND row_version=?",
            values,
        )
        if cursor.rowcount != 1:
            raise RouteVersionStaleError("路线版本状态已变化，请刷新后重试")
        return RouteVersionRepository.version(version_id, db=db)

    @staticmethod
    def update_compatibility_projection(
        route_id, version_id, expected_root_row_version, db
    ):
        cursor = db.execute(
            "UPDATE process_routes SET "
            "name=(SELECT name FROM process_route_versions "
            "WHERE id=? AND process_route_id=process_routes.id),"
            "category=(SELECT category FROM process_route_versions "
            "WHERE id=? AND process_route_id=process_routes.id),"
            "description=(SELECT description FROM process_route_versions "
            "WHERE id=? AND process_route_id=process_routes.id),"
            "current_effective_version_id=?,"
            "status=CASE WHEN lifecycle_status='active' THEN 'active' ELSE 'inactive' END,"
            "row_version=row_version+1,updated_at=datetime('now','localtime') "
            "WHERE id=? AND row_version=? AND EXISTS ("
            "SELECT 1 FROM process_route_versions "
            "WHERE id=? AND process_route_id=process_routes.id)",
            (
                version_id,
                version_id,
                version_id,
                version_id,
                route_id,
                expected_root_row_version,
                version_id,
            ),
        )
        if cursor.rowcount != 1:
            raise RouteVersionStaleError("路线根实体版本已变化，请刷新后重试")

        db.execute("DELETE FROM process_route_items WHERE route_id=?", (route_id,))
        db.execute(
            "INSERT INTO process_route_items ("
            "route_id,process_id,seq_order,is_required,required_audit) "
            "SELECT ?,process_id,seq_order,is_required,required_audit "
            "FROM process_route_version_items WHERE route_version_id=? "
            "ORDER BY seq_order,id",
            (route_id, version_id),
        )
        return RouteVersionRepository.root(route_id, db=db)

    @staticmethod
    def transition_root_lifecycle(
        route_id,
        expected_lifecycle_status,
        expected_row_version,
        target_lifecycle_status,
        legacy_status,
        db,
    ):
        cursor = db.execute(
            "UPDATE process_routes SET lifecycle_status=?,status=?,row_version=row_version+1,"
            "updated_at=datetime('now','localtime') "
            "WHERE id=? AND lifecycle_status=? AND row_version=?",
            (
                target_lifecycle_status,
                legacy_status,
                route_id,
                expected_lifecycle_status,
                expected_row_version,
            ),
        )
        if cursor.rowcount != 1:
            raise RouteVersionStaleError("路线生命周期已变化，请刷新后重试")
        return RouteVersionRepository.root(route_id, db=db)

    @staticmethod
    def event_by_idempotency_key(idempotency_key, db=None):
        key = str(idempotency_key or "")
        if not key:
            return None
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM process_route_version_events WHERE idempotency_key=?", (key,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def insert_event(payload, db):
        key = str(payload.get("idempotency_key") or "")
        existing = RouteVersionRepository.event_by_idempotency_key(key, db=db)
        if existing is not None:
            return existing
        try:
            cursor = db.execute(
                "INSERT INTO process_route_version_events ("
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
            replay = RouteVersionRepository.event_by_idempotency_key(key, db=db)
            if replay is None:
                raise
            return replay
        return RouteVersionRepository.event(cursor.lastrowid, db=db)

    @staticmethod
    def event(event_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM process_route_version_events WHERE id=?", (event_id,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def list_events(route_id, db=None):
        db = resolve_db(db)
        rows = db.execute(
            "SELECT * FROM process_route_version_events WHERE entity_id=? "
            "ORDER BY created_at,id",
            (route_id,),
        ).fetchall()
        return [dict(row) for row in rows]
