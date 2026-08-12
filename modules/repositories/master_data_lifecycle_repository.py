"""Persistence for process and route retirement/reactivation requests."""

import sqlite3

from modules.domain.errors import ConflictError
from modules.repositories.context import resolve_db


class MasterDataLifecycleRepository:
    _TRANSITION_FIELDS = {
        "approved_by",
        "approved_by_name",
        "resolved_at",
    }

    @staticmethod
    def process_request(request_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM process_lifecycle_requests WHERE id=?", (request_id,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def route_request(request_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM process_route_lifecycle_requests WHERE id=?", (request_id,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def process_request_by_idempotency_key(idempotency_key, db=None):
        key = str(idempotency_key or "")
        if not key:
            return None
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM process_lifecycle_requests WHERE idempotency_key=?", (key,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def route_request_by_idempotency_key(idempotency_key, db=None):
        key = str(idempotency_key or "")
        if not key:
            return None
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM process_route_lifecycle_requests WHERE idempotency_key=?", (key,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def pending_process_request(process_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM process_lifecycle_requests "
            "WHERE process_id=? AND status='pending' ORDER BY created_at DESC,id DESC LIMIT 1",
            (process_id,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def pending_route_request(route_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM process_route_lifecycle_requests "
            "WHERE process_route_id=? AND status='pending' "
            "ORDER BY created_at DESC,id DESC LIMIT 1",
            (route_id,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def list_process_requests(process_id, db=None):
        db = resolve_db(db)
        rows = db.execute(
            "SELECT * FROM process_lifecycle_requests WHERE process_id=? "
            "ORDER BY created_at,id",
            (process_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def list_route_requests(route_id, db=None):
        db = resolve_db(db)
        rows = db.execute(
            "SELECT * FROM process_route_lifecycle_requests WHERE process_route_id=? "
            "ORDER BY created_at,id",
            (route_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _create_request(
        entity_id,
        payload,
        *,
        table,
        entity_column,
        by_key,
        pending,
        load,
        label,
        db,
    ):
        key = str(payload.get("idempotency_key") or "")
        existing = by_key(key, db=db)
        if existing is not None:
            return existing
        if pending(entity_id, db=db) is not None:
            raise ConflictError(
                f"该{label}已有待审批生命周期申请",
                details={entity_column: entity_id},
            )
        try:
            cursor = db.execute(
                f"INSERT INTO {table} ("
                f"{entity_column},action,status,reason,requested_by,requested_by_name,"
                "approved_by,approved_by_name,idempotency_key,row_version,resolved_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,0,?)",
                (
                    entity_id,
                    payload["action"],
                    payload.get("status", "pending"),
                    payload["reason"],
                    payload.get("requested_by"),
                    payload.get("requested_by_name", ""),
                    payload.get("approved_by"),
                    payload.get("approved_by_name", ""),
                    key,
                    payload.get("resolved_at", ""),
                ),
            )
        except sqlite3.IntegrityError as exc:
            replay = by_key(key, db=db)
            if replay is not None:
                return replay
            if pending(entity_id, db=db) is not None:
                raise ConflictError(
                    f"该{label}已有待审批生命周期申请",
                    details={entity_column: entity_id},
                ) from exc
            raise
        return load(cursor.lastrowid, db=db)

    @staticmethod
    def create_process_request(process_id, payload, db):
        return MasterDataLifecycleRepository._create_request(
            process_id,
            payload,
            table="process_lifecycle_requests",
            entity_column="process_id",
            by_key=MasterDataLifecycleRepository.process_request_by_idempotency_key,
            pending=MasterDataLifecycleRepository.pending_process_request,
            load=MasterDataLifecycleRepository.process_request,
            label="工序",
            db=db,
        )

    @staticmethod
    def create_route_request(route_id, payload, db):
        return MasterDataLifecycleRepository._create_request(
            route_id,
            payload,
            table="process_route_lifecycle_requests",
            entity_column="process_route_id",
            by_key=MasterDataLifecycleRepository.route_request_by_idempotency_key,
            pending=MasterDataLifecycleRepository.pending_route_request,
            load=MasterDataLifecycleRepository.route_request,
            label="路线",
            db=db,
        )

    @staticmethod
    def _transition_request(
        request_id,
        expected_status,
        expected_row_version,
        target_status,
        fields,
        *,
        table,
        load,
        label,
        db,
    ):
        fields = dict(fields or {})
        if not set(fields).issubset(MasterDataLifecycleRepository._TRANSITION_FIELDS):
            raise ValueError("非法生命周期申请更新字段")
        assignments = ["status=?"] + [key + "=?" for key in fields]
        values = [target_status] + list(fields.values())
        assignments.append("row_version=row_version+1")
        values.extend([request_id, expected_status, expected_row_version])
        cursor = db.execute(
            f"UPDATE {table} SET "
            + ",".join(assignments)
            + " WHERE id=? AND status=? AND row_version=?",
            values,
        )
        if cursor.rowcount != 1:
            raise ConflictError(f"{label}生命周期申请状态已变化，请刷新后重试")
        return load(request_id, db=db)

    @staticmethod
    def transition_process_request(
        request_id,
        expected_status,
        expected_row_version,
        target_status,
        fields,
        db,
    ):
        return MasterDataLifecycleRepository._transition_request(
            request_id,
            expected_status,
            expected_row_version,
            target_status,
            fields,
            table="process_lifecycle_requests",
            load=MasterDataLifecycleRepository.process_request,
            label="工序",
            db=db,
        )

    @staticmethod
    def transition_route_request(
        request_id,
        expected_status,
        expected_row_version,
        target_status,
        fields,
        db,
    ):
        return MasterDataLifecycleRepository._transition_request(
            request_id,
            expected_status,
            expected_row_version,
            target_status,
            fields,
            table="process_route_lifecycle_requests",
            load=MasterDataLifecycleRepository.route_request,
            label="路线",
            db=db,
        )
