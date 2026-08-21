"""Persistence for versioned performance batches and score revisions."""

from modules.repositories.context import resolve_db


class PerformanceLedgerRepository:
    @staticmethod
    def _score_scope_sql(scope, alias):
        if scope.get("all"):
            return "1=1", []
        clauses = []
        params = []
        if scope.get("self_user_id") is not None:
            clauses.append(alias + ".user_id=?")
            params.append(scope["self_user_id"])
        department_ids = list(scope.get("department_ids") or [])
        if department_ids:
            placeholders = ",".join("?" for _ in department_ids)
            clauses.append(
                alias + ".department_id_snapshot IN (" + placeholders + ")"
            )
            params.extend(department_ids)
        if not clauses:
            return "0=1", []
        return "(" + " OR ".join(clauses) + ")", params

    @staticmethod
    def database_now(db=None):
        db = resolve_db(db)
        return db.execute("SELECT datetime('now','localtime')").fetchone()[0]

    @staticmethod
    def batch(batch_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM performance_batches WHERE id=?", (batch_id,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def batch_by_idempotency_key(idempotency_key, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM performance_batches WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _batch_visibility_sql(scope):
        if scope.get("all"):
            return "1=1", []
        score_scope_sql, params = PerformanceLedgerRepository._score_scope_sql(
            scope, alias="visible_score"
        )
        return (
            "EXISTS (SELECT 1 FROM performance_score_revisions visible_score "
            "WHERE visible_score.batch_id=batch.id AND "
            + score_scope_sql
            + ")",
            params,
        )

    @staticmethod
    def list_batches(
        scope,
        production_month="",
        status="",
        page=1,
        limit=20,
        db=None,
    ):
        db = resolve_db(db)
        visibility_sql, params = PerformanceLedgerRepository._batch_visibility_sql(
            scope
        )
        clauses = [visibility_sql]
        if production_month:
            clauses.append("batch.production_month=?")
            params.append(production_month)
        if status:
            clauses.append("batch.status=?")
            params.append(status)
        where_sql = " AND ".join(clauses)
        total = db.execute(
            "SELECT COUNT(*) FROM performance_batches batch WHERE " + where_sql,
            params,
        ).fetchone()[0]
        rows = db.execute(
            "SELECT batch.*,(SELECT COUNT(*) FROM performance_score_revisions score "
            "WHERE score.batch_id=batch.id AND NOT EXISTS ("
            "SELECT 1 FROM performance_score_revisions newer "
            "WHERE newer.batch_id=score.batch_id AND newer.user_id=score.user_id "
            "AND newer.revision>score.revision)) AS score_count,"
            "(SELECT COUNT(*) FROM performance_data_exceptions exception "
            "WHERE exception.batch_id=batch.id AND exception.status='pending') "
            "AS pending_exception_count FROM performance_batches batch WHERE "
            + where_sql
            + " ORDER BY batch.production_month DESC,batch.version DESC,batch.id DESC "
            "LIMIT ? OFFSET ?",
            params + [limit, (page - 1) * limit],
        ).fetchall()
        return {
            "items": [dict(row) for row in rows],
            "total": int(total),
            "page": page,
            "per_page": limit,
        }

    @staticmethod
    def batch_is_visible(batch_id, scope, db=None):
        db = resolve_db(db)
        visibility_sql, params = PerformanceLedgerRepository._batch_visibility_sql(
            scope
        )
        return db.execute(
            "SELECT 1 FROM performance_batches batch WHERE batch.id=? AND "
            + visibility_sql,
            [batch_id] + params,
        ).fetchone() is not None

    @staticmethod
    def list_batch_events(batch_id, db=None):
        db = resolve_db(db)
        return [
            dict(row)
            for row in db.execute(
                "SELECT * FROM performance_batch_events WHERE batch_id=? "
                "ORDER BY created_at,id",
                (batch_id,),
            ).fetchall()
        ]

    @staticmethod
    def list_exceptions(scope, batch_id, status="", page=1, limit=50, db=None):
        db = resolve_db(db)
        clauses = ["exception.batch_id=?"]
        params = [batch_id]
        if not scope.get("all"):
            score_scope_sql, scope_params = (
                PerformanceLedgerRepository._score_scope_sql(
                    scope, alias="visible_score"
                )
            )
            clauses.append(
                "exception.user_id IS NOT NULL AND EXISTS ("
                "SELECT 1 FROM performance_score_revisions visible_score "
                "WHERE visible_score.batch_id=exception.batch_id "
                "AND visible_score.user_id=exception.user_id AND "
                + score_scope_sql
                + ")"
            )
            params.extend(scope_params)
        if status:
            clauses.append("exception.status=?")
            params.append(status)
        where_sql = " AND ".join(clauses)
        total = db.execute(
            "SELECT COUNT(*) FROM performance_data_exceptions exception WHERE "
            + where_sql,
            params,
        ).fetchone()[0]
        rows = db.execute(
            "SELECT exception.* FROM performance_data_exceptions exception WHERE "
            + where_sql
            + " ORDER BY exception.id LIMIT ? OFFSET ?",
            params + [limit, (page - 1) * limit],
        ).fetchall()
        return {
            "items": [dict(row) for row in rows],
            "total": int(total),
            "page": page,
            "per_page": limit,
        }

    @staticmethod
    def review_by_idempotency_key(idempotency_key, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM performance_reviews_v2 WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def event_by_idempotency_key(idempotency_key, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM performance_batch_events WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def latest_score_revisions(batch_id, user_id=None, position_id=None, db=None):
        """Return one immutable, current score revision per employee."""
        db = resolve_db(db)
        clauses = [
            "score.batch_id=?",
            "NOT EXISTS (SELECT 1 FROM performance_score_revisions newer "
            "WHERE newer.batch_id=score.batch_id AND newer.user_id=score.user_id "
            "AND newer.revision>score.revision)",
        ]
        params = [batch_id]
        if user_id is not None:
            clauses.append("score.user_id=?")
            params.append(user_id)
        if position_id is not None:
            clauses.append("score.position_id_snapshot=?")
            params.append(position_id)
        rows = db.execute(
            "SELECT score.* FROM performance_score_revisions score WHERE "
            + " AND ".join(clauses)
            + " ORDER BY score.user_id",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def latest_review(batch_id, user_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM performance_reviews_v2 "
            "WHERE batch_id=? AND user_id=? ORDER BY revision DESC,id DESC LIMIT 1",
            (batch_id, user_id),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def next_review_revision(batch_id, user_id, db=None):
        db = resolve_db(db)
        return int(
            db.execute(
                "SELECT COALESCE(MAX(revision),0)+1 "
                "FROM performance_reviews_v2 WHERE batch_id=? AND user_id=?",
                (batch_id, user_id),
            ).fetchone()[0]
        )

    @staticmethod
    def insert_review(payload, db):
        cursor = db.execute(
            "INSERT INTO performance_reviews_v2 ("
            "batch_id,user_id,revision,discipline_deduction,discipline_reason,"
            "improvement_adjustment,improvement_reason,manual_score,manual_comment,"
            "reviewed_by,reviewed_by_name,input_digest,idempotency_key"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                payload["batch_id"],
                payload["user_id"],
                payload["revision"],
                payload.get("discipline_deduction", 0),
                payload.get("discipline_reason", ""),
                payload.get("improvement_adjustment", 0),
                payload.get("improvement_reason", ""),
                payload.get("manual_score", 10),
                payload.get("manual_comment", ""),
                payload.get("reviewed_by"),
                payload.get("reviewed_by_name", ""),
                payload.get("input_digest", ""),
                payload.get("idempotency_key"),
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def update_batch_row_version(batch_id, expected_row_version, db):
        cursor = db.execute(
            "UPDATE performance_batches SET row_version=row_version+1,"
            "updated_at=datetime('now','localtime') "
            "WHERE id=? AND row_version=? AND status='supervisor_review'",
            (batch_id, expected_row_version),
        )
        if cursor.rowcount != 1:
            return None
        row = PerformanceLedgerRepository.batch(batch_id, db=db)
        return row["row_version"] if row else None

    @staticmethod
    def transition_batch(
        batch_id,
        expected_row_version,
        current_status,
        target_status,
        fields,
        db,
    ):
        allowed_fields = {
            "submitted_at",
            "approved_by",
            "approved_by_name",
            "approved_at",
        }
        invalid_fields = set(fields) - allowed_fields
        if invalid_fields:
            raise ValueError("不允许更新绩效批次工作流字段")
        assignments = ["status=?", "row_version=row_version+1"]
        params = [target_status]
        for field in sorted(fields):
            assignments.append(field + "=?")
            params.append(fields[field])
        assignments.append("updated_at=datetime('now','localtime')")
        params.extend([batch_id, expected_row_version, current_status])
        cursor = db.execute(
            "UPDATE performance_batches SET "
            + ",".join(assignments)
            + " WHERE id=? AND row_version=? AND status=?",
            params,
        )
        return cursor.rowcount == 1

    @staticmethod
    def approve_batch(
        batch_id,
        expected_row_version,
        actor_id,
        actor_name,
        approved_at,
        db,
    ):
        return PerformanceLedgerRepository.transition_batch(
            batch_id,
            expected_row_version,
            "approval_pending",
            "approved",
            {
                "approved_by": actor_id,
                "approved_by_name": actor_name,
                "approved_at": approved_at,
            },
            db,
        )

    @staticmethod
    def mark_superseded(batch_id, successor_batch_id, expected_row_version, db):
        cursor = db.execute(
            "UPDATE performance_batches SET status='superseded',"
            "superseded_by_batch_id=?,row_version=row_version+1,"
            "updated_at=datetime('now','localtime') "
            "WHERE id=? AND row_version=? AND status='approved'",
            (successor_batch_id, batch_id, expected_row_version),
        )
        return cursor.rowcount == 1

    @staticmethod
    def next_version(production_month, db=None):
        db = resolve_db(db)
        return int(
            db.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM performance_batches "
                "WHERE production_month=?",
                (production_month,),
            ).fetchone()[0]
        )

    @staticmethod
    def current_approved_batch(production_month, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM performance_batches WHERE production_month=? "
            "AND status='approved' ORDER BY version DESC LIMIT 1",
            (production_month,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def insert_batch(payload, db):
        cursor = db.execute(
            "INSERT INTO performance_batches ("
            "production_month,version,period_start,period_end,source_cutoff_at,"
            "rule_version_id,idempotency_key,prepared_by,prepared_by_name,"
            "supersedes_batch_id,revision_reason"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                payload["production_month"],
                payload["version"],
                payload["period_start"],
                payload["period_end"],
                payload["source_cutoff_at"],
                payload["rule_version_id"],
                payload["idempotency_key"],
                payload.get("prepared_by"),
                payload.get("prepared_by_name", ""),
                payload.get("supersedes_batch_id"),
                payload.get("revision_reason", ""),
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def insert_exception(payload, db):
        cursor = db.execute(
            "INSERT OR IGNORE INTO performance_data_exceptions ("
            "batch_id,user_id,exception_type,source_type,source_id,status,snapshot_json"
            ") VALUES (?,?,?,?,?,'pending',?)",
            (
                payload["batch_id"],
                payload.get("user_id"),
                payload["exception_type"],
                payload.get("source_type", ""),
                payload.get("source_id", 0),
                payload.get("snapshot_json", "{}"),
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def pending_exception_counts(batch_id, db=None):
        db = resolve_db(db)
        rows = db.execute(
            "SELECT user_id,COUNT(*) AS exception_count "
            "FROM performance_data_exceptions "
            "WHERE batch_id=? AND status='pending' AND user_id IS NOT NULL "
            "GROUP BY user_id",
            (batch_id,),
        ).fetchall()
        return {int(row["user_id"]): int(row["exception_count"]) for row in rows}

    @staticmethod
    def unresolved_exceptions(batch_id, db=None):
        db = resolve_db(db)
        rows = db.execute(
            "SELECT * FROM performance_data_exceptions "
            "WHERE batch_id=? AND status='pending' ORDER BY id",
            (batch_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def insert_score_revision(payload, db):
        columns = (
            "batch_id",
            "user_id",
            "revision",
            "employee_name_snapshot",
            "employee_no_snapshot",
            "role_type_snapshot",
            "department_id_snapshot",
            "department_name_snapshot",
            "position_id_snapshot",
            "position_version_id_snapshot",
            "position_name_snapshot",
            "eligibility_status",
            "eligibility_reason_code",
            "eligibility_reason",
            "output_qty",
            "report_count",
            "work_days",
            "scrap_qty",
            "rework_qty",
            "inspection_failed_qty",
            "output_score",
            "quality_score",
            "delivery_score",
            "discipline_score",
            "improvement_score",
            "total_score",
            "rank_no",
            "rank_total",
            "warning_level",
            "warning_reason",
            "discipline_deduction",
            "discipline_reason",
            "improvement_deduction",
            "improvement_reason",
            "manual_score",
            "manual_comment",
            "score_details_json",
            "rule_version_id",
            "position_target_version_id",
            "review_revision_id",
            "input_digest",
            "ranking_digest",
            "calculation_group_id",
            "calculated_at",
            "created_by",
            "created_by_name",
        )
        cursor = db.execute(
            "INSERT INTO performance_score_revisions ("
            + ",".join(columns)
            + ") VALUES ("
            + ",".join("?" for _ in columns)
            + ")",
            [payload.get(column) for column in columns],
        )
        return cursor.lastrowid

    @staticmethod
    def insert_batch_event(payload, db):
        cursor = db.execute(
            "INSERT INTO performance_batch_events ("
            "batch_id,event_type,from_status,to_status,operator_id,operator_name,"
            "reason,payload_json,request_id,idempotency_key"
            ") VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                payload.get("batch_id"),
                payload["event_type"],
                payload.get("from_status", ""),
                payload.get("to_status", ""),
                payload.get("operator_id"),
                payload.get("operator_name", ""),
                payload.get("reason", ""),
                payload.get("payload_json", "{}"),
                payload.get("request_id", ""),
                payload.get("idempotency_key"),
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def batch_summary(batch_id, db=None):
        db = resolve_db(db)
        batch = PerformanceLedgerRepository.batch(batch_id, db=db)
        if not batch:
            return None
        score_counts = db.execute(
            "SELECT COUNT(*) AS score_count,"
            "SUM(CASE WHEN eligibility_status='eligible' THEN 1 ELSE 0 END) "
            "AS eligible_count,"
            "SUM(CASE WHEN eligibility_status='insufficient_data' THEN 1 ELSE 0 END) "
            "AS insufficient_count "
            "FROM performance_score_revisions WHERE batch_id=? AND revision=1",
            (batch_id,),
        ).fetchone()
        exception_counts = db.execute(
            "SELECT COUNT(*) AS exception_count,"
            "SUM(CASE WHEN exception_type='missing_position_target' THEN 1 ELSE 0 END) "
            "AS missing_target_count "
            "FROM performance_data_exceptions WHERE batch_id=?",
            (batch_id,),
        ).fetchone()
        return {
            "batch": batch,
            "batch_id": batch["id"],
            "production_month": batch["production_month"],
            "version": batch["version"],
            "status": batch["status"],
            "row_version": batch["row_version"],
            "score_count": int(score_counts["score_count"] or 0),
            "eligible_count": int(score_counts["eligible_count"] or 0),
            "insufficient_data_count": int(score_counts["insufficient_count"] or 0),
            "exception_count": int(exception_counts["exception_count"] or 0),
            "missing_target_count": int(
                exception_counts["missing_target_count"] or 0
            ),
            "input_digest": batch["input_digest"],
        }
