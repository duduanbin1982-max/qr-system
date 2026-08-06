"""Persistence for versioned performance batches and score revisions."""

from modules.repositories.context import resolve_db


class PerformanceLedgerRepository:
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
    def review_by_idempotency_key(idempotency_key, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM performance_reviews_v2 WHERE idempotency_key=?",
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
