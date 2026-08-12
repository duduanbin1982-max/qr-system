"""Persistence for atomic master-data release batches and their members."""

import sqlite3

from modules.domain.errors import ConflictError
from modules.repositories.context import resolve_db


class MasterDataReleaseRepository:
    _TRANSITION_FIELDS = {
        "revision_reason",
        "impact_digest",
        "approved_by",
        "approved_by_name",
        "approved_at",
        "published_at",
    }

    @staticmethod
    def _attach_members(batches, db):
        if not batches:
            return batches
        batch_map = {batch["id"]: batch for batch in batches}
        for batch in batches:
            batch["process_versions"] = []
            batch["route_versions"] = []
            batch["price_versions"] = []
            batch["approved_exceptions"] = []
        placeholders = ",".join("?" for _ in batch_map)
        params = list(batch_map)
        member_queries = (
            (
                "process_versions",
                "SELECT member.batch_id,version.* "
                "FROM master_data_release_process_versions member "
                "JOIN process_versions version ON version.id=member.process_version_id "
                "WHERE member.batch_id IN ("
                + placeholders
                + ") ORDER BY member.batch_id,version.process_id,version.version,version.id",
            ),
            (
                "route_versions",
                "SELECT member.batch_id,version.* "
                "FROM master_data_release_route_versions member "
                "JOIN process_route_versions version ON version.id=member.route_version_id "
                "WHERE member.batch_id IN ("
                + placeholders
                + ") ORDER BY member.batch_id,version.process_route_id,version.version,version.id",
            ),
            (
                "price_versions",
                "SELECT member.batch_id,version.* "
                "FROM master_data_release_price_versions member "
                "JOIN route_price_versions version ON version.id=member.price_version_id "
                "WHERE member.batch_id IN ("
                + placeholders
                + ") ORDER BY member.batch_id,version.id",
            ),
        )
        for collection, sql in member_queries:
            for row in db.execute(sql, params).fetchall():
                item = dict(row)
                batch_id = item.pop("batch_id")
                batch_map[batch_id][collection].append(item)
        for row in db.execute(
            "SELECT * FROM master_data_release_exceptions WHERE batch_id IN ("
            + placeholders
            + ") ORDER BY batch_id,route_version_id,replacement_process_version_id,id",
            params,
        ).fetchall():
            item = dict(row)
            batch_map[item["batch_id"]]["approved_exceptions"].append(item)
        return batches

    @staticmethod
    def batch(batch_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM master_data_release_batches WHERE id=?", (batch_id,)
        ).fetchone()
        if row is None:
            return None
        return MasterDataReleaseRepository._attach_members([dict(row)], db)[0]

    @staticmethod
    def batch_by_idempotency_key(idempotency_key, db=None):
        key = str(idempotency_key or "")
        if not key:
            return None
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM master_data_release_batches WHERE idempotency_key=?", (key,)
        ).fetchone()
        if row is None:
            return None
        return MasterDataReleaseRepository._attach_members([dict(row)], db)[0]

    @staticmethod
    def list_batches(status="", db=None):
        db = resolve_db(db)
        params = []
        where_sql = ""
        if status:
            where_sql = " WHERE status=?"
            params.append(status)
        batches = [
            dict(row)
            for row in db.execute(
                "SELECT * FROM master_data_release_batches"
                + where_sql
                + " ORDER BY created_at DESC,id DESC",
                params,
            ).fetchall()
        ]
        return MasterDataReleaseRepository._attach_members(batches, db)

    @staticmethod
    def create_batch(payload, db):
        key = str(payload.get("idempotency_key") or "")
        existing = MasterDataReleaseRepository.batch_by_idempotency_key(key, db=db)
        if existing is not None:
            return existing
        try:
            cursor = db.execute(
                "INSERT INTO master_data_release_batches ("
                "release_no,status,revision_reason,impact_digest,created_by,created_by_name,"
                "approved_by,approved_by_name,approved_at,published_at,idempotency_key,row_version) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,0)",
                (
                    payload["release_no"],
                    payload.get("status", "draft"),
                    payload.get("revision_reason", ""),
                    payload.get("impact_digest", ""),
                    payload.get("created_by"),
                    payload.get("created_by_name", ""),
                    payload.get("approved_by"),
                    payload.get("approved_by_name", ""),
                    payload.get("approved_at", ""),
                    payload.get("published_at", ""),
                    key,
                ),
            )
        except sqlite3.IntegrityError as exc:
            replay = MasterDataReleaseRepository.batch_by_idempotency_key(key, db=db)
            if replay is not None:
                return replay
            raise ConflictError("主数据发布批次编号或幂等键冲突") from exc
        return MasterDataReleaseRepository.batch(cursor.lastrowid, db=db)

    @staticmethod
    def _add_member(batch_id, version_id, *, table, column, label, db):
        try:
            db.execute(
                f"INSERT INTO {table} (batch_id,{column}) VALUES (?,?)",
                (batch_id, version_id),
            )
        except sqlite3.IntegrityError as exc:
            duplicate = db.execute(
                f"SELECT 1 FROM {table} WHERE batch_id=? AND {column}=?",
                (batch_id, version_id),
            ).fetchone()
            if duplicate is not None:
                raise ConflictError(
                    f"发布批次已绑定该{label}",
                    details={"batch_id": batch_id, column: version_id},
                ) from exc
            raise

    @staticmethod
    def add_process_version(batch_id, process_version_id, db):
        MasterDataReleaseRepository._add_member(
            batch_id,
            process_version_id,
            table="master_data_release_process_versions",
            column="process_version_id",
            label="工序版本",
            db=db,
        )

    @staticmethod
    def add_route_version(batch_id, route_version_id, db):
        MasterDataReleaseRepository._add_member(
            batch_id,
            route_version_id,
            table="master_data_release_route_versions",
            column="route_version_id",
            label="路线版本",
            db=db,
        )

    @staticmethod
    def add_price_version(batch_id, price_version_id, db):
        MasterDataReleaseRepository._add_member(
            batch_id,
            price_version_id,
            table="master_data_release_price_versions",
            column="price_version_id",
            label="工价版本",
            db=db,
        )

    @staticmethod
    def add_approved_exception(batch_id, payload, db):
        try:
            cursor = db.execute(
                "INSERT INTO master_data_release_exceptions ("
                "batch_id,route_version_id,retained_process_version_id,"
                "replacement_process_version_id,reason,approved_by,approved_by_name,"
                "valid_from,valid_to) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    batch_id,
                    payload["route_version_id"],
                    payload["retained_process_version_id"],
                    payload["replacement_process_version_id"],
                    payload["reason"],
                    payload["approved_by"],
                    payload.get("approved_by_name", ""),
                    payload["valid_from"],
                    payload["valid_to"],
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError(
                "主数据发布例外冲突或有效期无效",
                details={
                    "batch_id": batch_id,
                    "route_version_id": payload.get("route_version_id"),
                },
            ) from exc
        row = db.execute(
            "SELECT * FROM master_data_release_exceptions WHERE id=?",
            (cursor.lastrowid,),
        ).fetchone()
        return dict(row)

    @staticmethod
    def transition_batch(
        batch_id,
        expected_status,
        expected_row_version,
        target_status,
        fields,
        db,
    ):
        fields = dict(fields or {})
        if not set(fields).issubset(MasterDataReleaseRepository._TRANSITION_FIELDS):
            raise ValueError("非法主数据发布批次更新字段")
        assignments = ["status=?"] + [key + "=?" for key in fields]
        values = [target_status] + list(fields.values())
        assignments.append("row_version=row_version+1")
        values.extend([batch_id, expected_status, expected_row_version])
        cursor = db.execute(
            "UPDATE master_data_release_batches SET "
            + ",".join(assignments)
            + " WHERE id=? AND status=? AND row_version=?",
            values,
        )
        if cursor.rowcount != 1:
            raise ConflictError("主数据发布批次状态已变化，请刷新后重试")
        return MasterDataReleaseRepository.batch(batch_id, db=db)
