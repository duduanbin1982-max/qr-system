"""Read models and evidence access for controlled performance history migration."""

from modules.repositories.context import resolve_db


class PerformanceHistoryMigrationRepository:
    @staticmethod
    def table_names(db=None):
        db = resolve_db(db)
        return {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

    @staticmethod
    def legacy_months(start_month="", end_month="", db=None):
        db = resolve_db(db)
        clauses = ["legacy_imported=1"]
        params = []
        if start_month:
            clauses.append("production_month>=?")
            params.append(start_month)
        if end_month:
            clauses.append("production_month<=?")
            params.append(end_month)
        rows = db.execute(
            "SELECT DISTINCT production_month FROM performance_batches WHERE "
            + " AND ".join(clauses)
            + " ORDER BY production_month",
            params,
        ).fetchall()
        return [row[0] for row in rows]

    @staticmethod
    def legacy_batch(production_month, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM performance_batches WHERE production_month=? "
            "AND legacy_imported=1 ORDER BY version,id LIMIT 1",
            (production_month,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def legacy_manifest(production_month, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM performance_migration_manifests "
            "WHERE production_month=?",
            (production_month,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def legacy_scores(batch_id, db=None):
        db = resolve_db(db)
        rows = db.execute(
            "SELECT score.* FROM performance_score_revisions score "
            "WHERE score.batch_id=? AND NOT EXISTS ("
            "SELECT 1 FROM performance_score_revisions newer "
            "WHERE newer.batch_id=score.batch_id AND newer.user_id=score.user_id "
            "AND newer.revision>score.revision) "
            "ORDER BY COALESCE(score.legacy_score_id,score.id),score.user_id,score.id",
            (batch_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def work_records(period_start, period_end, db=None):
        db = resolve_db(db)
        business_at = "COALESCE(NULLIF(actual_completed_at,''),created_at)"
        rows = db.execute(
            "SELECT id,user_id,order_id,process_id,type,status,quantity,created_at,"
            "actual_completed_at," + business_at + " AS business_at "
            "FROM work_records WHERE status='approved' AND "
            + business_at
            + ">=? AND "
            + business_at
            + "<? ORDER BY business_at,id",
            (period_start, period_end),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def work_time_records(period_start, period_end, db=None):
        db = resolve_db(db)
        business_at = (
            "COALESCE(NULLIF(end_time,''),NULLIF(start_time,''),created_at)"
        )
        rows = db.execute(
            "SELECT id,user_id,order_id,process_id,review_status,start_time,end_time,"
            "quantity,standard_minutes,actual_minutes,effective_minutes,created_at,"
            + business_at
            + " AS business_at FROM work_time_records "
            "WHERE review_status='approved' AND "
            + business_at
            + ">=? AND "
            + business_at
            + "<? ORDER BY business_at,id",
            (period_start, period_end),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def scrap_records(period_start, period_end, db=None):
        db = resolve_db(db)
        rows = db.execute(
            "SELECT scrap.*,source.quality_event_id FROM scrap_records scrap "
            "LEFT JOIN performance_quality_event_sources source "
            "ON source.source_type='scrap_record' AND source.source_id=scrap.id "
            "WHERE scrap.created_at>=? AND scrap.created_at<? "
            "ORDER BY scrap.created_at,scrap.id",
            (period_start, period_end),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def rework_records(period_start, period_end, db=None):
        db = resolve_db(db)
        rows = db.execute(
            "SELECT rework.*,source.quality_event_id FROM rework_records rework "
            "LEFT JOIN performance_quality_event_sources source "
            "ON source.source_type='rework_record' AND source.source_id=rework.id "
            "WHERE rework.created_at>=? AND rework.created_at<? "
            "ORDER BY rework.created_at,rework.id",
            (period_start, period_end),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def quality_inspections(period_start, period_end, db=None):
        db = resolve_db(db)
        business_at = "COALESCE(NULLIF(inspection.inspected_at,''),inspection.created_at)"
        rows = db.execute(
            "SELECT inspection.*,source.quality_event_id,("
            "SELECT GROUP_CONCAT(ncr.id) FROM quality_nonconformances ncr "
            "WHERE ncr.inspection_id=inspection.id) AS related_ncr_ids,"
            + business_at
            + " AS business_at FROM quality_inspections inspection "
            "LEFT JOIN performance_quality_event_sources source "
            "ON source.source_type='quality_inspection' "
            "AND source.source_id=inspection.id "
            "WHERE inspection.quantity_failed>0 AND "
            + business_at
            + ">=? AND "
            + business_at
            + "<? ORDER BY business_at,inspection.id",
            (period_start, period_end),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def quality_events(period_start, period_end, db=None):
        db = resolve_db(db)
        events = [
            dict(row)
            for row in db.execute(
                "SELECT * FROM performance_quality_events "
                "WHERE business_at>=? AND business_at<? ORDER BY business_at,id",
                (period_start, period_end),
            ).fetchall()
        ]
        if not events:
            return []
        event_ids = [event["id"] for event in events]
        placeholders = ",".join("?" for _ in event_ids)
        sources = db.execute(
            "SELECT quality_event_id,source_type,source_id FROM "
            "performance_quality_event_sources WHERE quality_event_id IN ("
            + placeholders
            + ") ORDER BY quality_event_id,source_type,source_id",
            event_ids,
        ).fetchall()
        by_event = {event_id: [] for event_id in event_ids}
        for row in sources:
            by_event[row["quality_event_id"]].append(
                {
                    "source_type": row["source_type"],
                    "source_id": row["source_id"],
                }
            )
        for event in events:
            event["sources"] = by_event[event["id"]]
        return events

    @staticmethod
    def process_quality_evaluations(period_start, period_end, db=None):
        db = resolve_db(db)
        rows = db.execute(
            "SELECT evaluation.*,source.quality_event_id,"
            "handoff.from_user_id AS handoff_target_user_id "
            "FROM process_quality_evaluations evaluation "
            "LEFT JOIN performance_quality_event_sources source "
            "ON source.source_type='process_quality_evaluation' "
            "AND source.source_id=evaluation.id "
            "LEFT JOIN process_handoff_reviews handoff "
            "ON handoff.id=evaluation.source_handoff_review_id "
            "WHERE evaluation.created_at>=? AND evaluation.created_at<? "
            "ORDER BY evaluation.created_at,evaluation.id",
            (period_start, period_end),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def quality_candidate_work_records(order_id, process_id, db=None):
        db = resolve_db(db)
        rows = db.execute(
            "SELECT id,user_id,serial_no,created_at FROM work_records "
            "WHERE order_id=? AND process_id=? AND type='normal' "
            "AND status='approved' ORDER BY created_at,id",
            (order_id, process_id),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def historical_quality_ambiguity(source_type, source_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM performance_data_exceptions WHERE batch_id IS NULL "
            "AND exception_type='ambiguous_quality_source' AND source_type=? "
            "AND source_id=? ORDER BY id LIMIT 1",
            (source_type, source_id),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def insert_historical_quality_ambiguity(payload, db=None):
        db = resolve_db(db)
        cursor = db.execute(
            "INSERT INTO performance_data_exceptions ("
            "batch_id,user_id,exception_type,source_type,source_id,status,snapshot_json"
            ") VALUES (NULL,?,'ambiguous_quality_source',?,?,'pending',?)",
            (
                payload.get("user_id"),
                payload["source_type"],
                payload["source_id"],
                payload["snapshot_json"],
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def quality_ambiguities(period_start, period_end, db=None):
        db = resolve_db(db)
        business_at = (
            "COALESCE(NULLIF(json_extract(exception.snapshot_json,'$.business_at'),''),("
            "SELECT event.business_at FROM "
            "json_each(exception.snapshot_json,'$.candidates') candidate "
            "JOIN performance_quality_event_sources source "
            "ON source.source_type=json_extract(candidate.value,'$.source_type') "
            "AND source.source_id=json_extract(candidate.value,'$.source_id') "
            "JOIN performance_quality_events event "
            "ON event.id=source.quality_event_id "
            "ORDER BY event.business_at,event.id LIMIT 1),exception.created_at)"
        )
        rows = db.execute(
            "WITH ambiguity AS (SELECT exception.*,"
            + business_at
            + " AS business_at FROM performance_data_exceptions exception "
            "WHERE exception.batch_id IS NULL "
            "AND exception.exception_type='ambiguous_quality_source' "
            "AND exception.status='pending') "
            "SELECT * FROM ambiguity WHERE business_at>=? AND business_at<? "
            "ORDER BY business_at,source_type,source_id,id",
            (period_start, period_end),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def assignments(period_start, period_end, db=None):
        db = resolve_db(db)
        rows = db.execute(
            "SELECT * FROM performance_assignment_history "
            "WHERE valid_from<? AND (valid_to='' OR valid_to>?) "
            "ORDER BY user_id,valid_from,id",
            (period_end, period_start),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def approved_targets(production_month, db=None):
        db = resolve_db(db)
        rows = db.execute(
            "SELECT * FROM performance_position_target_versions "
            "WHERE status='approved' AND effective_from_month<=? "
            "AND (effective_to_month='' OR effective_to_month>=?) "
            "ORDER BY position_id,effective_from_month,id",
            (production_month, production_month),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def published_rules(production_month, db=None):
        db = resolve_db(db)
        rows = db.execute(
            "SELECT * FROM performance_rule_versions WHERE status='published' "
            "AND effective_from_month<=? "
            "AND (effective_to_month='' OR effective_to_month>=?) "
            "ORDER BY effective_from_month,id",
            (production_month, production_month),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def improvement_plans(production_month, db=None):
        db = resolve_db(db)
        rows = db.execute(
            "SELECT * FROM performance_improvement_plans_v2 "
            "WHERE production_month=? ORDER BY user_id,id",
            (production_month,),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def preparer(preparer_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT id,name,username,status FROM users WHERE id=?",
            (preparer_id,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def batch_by_idempotency(idempotency_key, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM performance_batches WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        return dict(row) if row else None

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
    def batch(batch_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM performance_batches WHERE id=?", (batch_id,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def event_by_idempotency(idempotency_key, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM performance_batch_events WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def score_revisions(batch_id, db=None):
        db = resolve_db(db)
        rows = db.execute(
            "SELECT score.* FROM performance_score_revisions score "
            "WHERE score.batch_id=? AND NOT EXISTS ("
            "SELECT 1 FROM performance_score_revisions newer "
            "WHERE newer.batch_id=score.batch_id AND newer.user_id=score.user_id "
            "AND newer.revision>score.revision) ORDER BY score.user_id,score.id",
            (batch_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def payroll_fingerprint(db=None):
        db = resolve_db(db)
        tables = (
            "payroll_batches",
            "payroll_employee_lines",
            "payroll_adjustments",
            "payroll_detail_lines",
            "payroll_work_price_resolutions",
            "payroll_events",
            "payroll_migration_manifests",
        )
        return {
            table: int(db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0])
            for table in tables
        }
