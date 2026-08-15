"""Persistence for canonical performance quality events and source facts."""

from modules.repositories.context import resolve_db
from modules.process_fact_projection import (
    capture_process_fact_binding,
    process_value_sql,
    process_version_join,
    route_name_sql,
    route_version_join,
    warn_legacy_fact_rows,
)


class PerformanceFactRepository:
    @staticmethod
    def batch(batch_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM performance_batches WHERE id=?", (batch_id,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def database_now(db=None):
        db = resolve_db(db)
        return db.execute("SELECT datetime('now','localtime')").fetchone()[0]

    @staticmethod
    def quality_event(event_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM performance_quality_events WHERE id=?", (event_id,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def quality_event_for_source(source_type, source_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT event.* FROM performance_quality_events event "
            "JOIN performance_quality_event_sources source "
            "ON source.quality_event_id=event.id "
            "WHERE source.source_type=? AND source.source_id=?",
            (source_type, source_id),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def source_mappings(sources, db=None):
        db = resolve_db(db)
        if not sources:
            return []
        clauses = []
        params = []
        for source_type, source_id in sources:
            clauses.append("(source_type=? AND source_id=?)")
            params.extend([source_type, source_id])
        rows = db.execute(
            "SELECT * FROM performance_quality_event_sources WHERE "
            + " OR ".join(clauses)
            + " ORDER BY id",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def quality_event_sources(event_id, db=None):
        db = resolve_db(db)
        return [
            dict(row)
            for row in db.execute(
                "SELECT * FROM performance_quality_event_sources "
                "WHERE quality_event_id=? ORDER BY source_type,source_id",
                (event_id,),
            ).fetchall()
        ]

    @staticmethod
    def insert_quality_event(payload, db):
        binding = capture_process_fact_binding(
            db,
            order_id=payload.get("order_id"),
            process_id=payload.get("process_id"),
            route_id=payload.get("route_id"),
        )
        cursor = db.execute(
            "INSERT INTO performance_quality_events ("
            "event_type,quantity,order_id,process_id,user_id,business_at,"
            "snapshot_json,event_digest,process_version_id,process_code_snapshot,"
            "process_name_snapshot,process_category_snapshot,route_id,route_version_id,"
            "route_name_snapshot,version_binding_source"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                payload["event_type"],
                payload["quantity"],
                payload.get("order_id"),
                payload.get("process_id"),
                payload.get("user_id"),
                payload["business_at"],
                payload["snapshot_json"],
                payload["event_digest"],
                binding["process_version_id"],
                binding["process_code_snapshot"],
                binding["process_name_snapshot"],
                binding["process_category_snapshot"],
                binding["route_id"],
                binding["route_version_id"],
                binding["route_name_snapshot"],
                binding["version_binding_source"],
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def insert_quality_event_source(event_id, source_type, source_id, db):
        db.execute(
            "INSERT OR IGNORE INTO performance_quality_event_sources ("
            "quality_event_id,source_type,source_id"
            ") VALUES (?,?,?)",
            (event_id, source_type, source_id),
        )
        row = db.execute(
            "SELECT * FROM performance_quality_event_sources "
            "WHERE source_type=? AND source_id=?",
            (source_type, source_id),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def work_record_context(work_record_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT id,order_id,process_id,user_id,quantity,created_at,"
            "process_version_id,process_code_snapshot,process_name_snapshot,"
            "process_category_snapshot,route_id,route_version_id,route_name_snapshot,"
            "version_binding_source "
            "FROM work_records WHERE id=?",
            (work_record_id,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def historical_quality_exception(source_type, source_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM performance_data_exceptions "
            "WHERE batch_id IS NULL AND exception_type='ambiguous_quality_source' "
            "AND source_type=? AND source_id=? ORDER BY id LIMIT 1",
            (source_type, source_id),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def insert_historical_quality_exception(payload, db):
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
    def list_quality_events(
        period_start, period_end, db=None, source_cutoff_at=""
    ):
        """Return each canonical event once with all of its mapped sources."""
        db = resolve_db(db)
        cutoff_clause = " AND event.created_at<=?" if source_cutoff_at else ""
        params = [period_start, period_end]
        if source_cutoff_at:
            params.append(source_cutoff_at)
        process_name = process_value_sql("event", "process_version", "process")
        route_name = route_name_sql("event", "route_version", "route")
        event_rows = db.execute(
            "SELECT event.*," + process_name + " AS process_name," + route_name
            + " AS route_name FROM performance_quality_events event "
            "LEFT JOIN processes process ON process.id=event.process_id "
            + process_version_join("event", "process_version")
            + "LEFT JOIN process_routes route ON route.id=event.route_id "
            + route_version_join("event", "route_version")
            + "WHERE event.business_at>=? AND event.business_at<?"
            + cutoff_clause
            + " ORDER BY event.business_at,event.id",
            params,
        ).fetchall()
        warn_legacy_fact_rows("performance_quality_events", event_rows)
        events = [dict(row) for row in event_rows]
        if not events:
            return []
        source_cutoff_clause = ""
        source_params = [period_start, period_end]
        if source_cutoff_at:
            source_cutoff_clause = (
                " AND event.created_at<=? AND source.created_at<=?"
            )
            source_params.extend([source_cutoff_at, source_cutoff_at])
        source_rows = db.execute(
            "SELECT source.quality_event_id,source.source_type,source.source_id "
            "FROM performance_quality_event_sources source "
            "JOIN performance_quality_events event "
            "ON event.id=source.quality_event_id "
            "WHERE event.business_at>=? AND event.business_at<?"
            + source_cutoff_clause
            + " "
            "ORDER BY source.quality_event_id,source.source_type,source.source_id",
            source_params,
        ).fetchall()
        event_ids = [event["id"] for event in events]
        sources_by_event = {event_id: [] for event_id in event_ids}
        for row in source_rows:
            sources_by_event[row["quality_event_id"]].append(
                {"source_type": row["source_type"], "source_id": row["source_id"]}
            )
        for event in events:
            event["sources"] = sources_by_event[event["id"]]
        return events

    @staticmethod
    def list_work_records(period_start, period_end, source_cutoff_at="", db=None):
        db = resolve_db(db)
        business_at = "COALESCE(NULLIF(wr.actual_completed_at,''),wr.created_at)"
        clauses = [
            "wr.status='approved'",
            business_at + ">=?",
            business_at + "<?",
        ]
        params = [period_start, period_end]
        if source_cutoff_at:
            clauses.append("wr.created_at<=?")
            params.append(source_cutoff_at)
            clauses.append(
                "NOT EXISTS (SELECT 1 FROM approval_records approval "
                "WHERE approval.work_record_id=wr.id AND approval.status='approved' "
                "AND COALESCE(NULLIF(approval.processed_at,''),approval.created_at)>?)"
            )
            params.append(source_cutoff_at)
        process_name = process_value_sql("wr", "process_version", "proc")
        route_name = route_name_sql("wr", "route_version", "route")
        rows = db.execute(
            "SELECT wr.*,"
            + business_at
            + " AS business_at,o.order_no,opl.product_id,"
            "COALESCE(o.product_code,'') AS order_product_code,"
            "COALESCE(o.product_name,'') AS order_product_name,"
            "COALESCE(prod.product_code,'') AS current_product_code,"
            "COALESCE(prod.product_name,'') AS current_product_name,"
            + process_name + " AS process_name," + route_name + " AS route_name "
            + "FROM work_records wr "
            "LEFT JOIN orders o ON o.id=wr.order_id "
            "LEFT JOIN order_product_links opl ON opl.order_id=wr.order_id "
            "LEFT JOIN products prod ON prod.id=opl.product_id "
            "LEFT JOIN processes proc ON proc.id=wr.process_id "
            + process_version_join("wr", "process_version")
            + "LEFT JOIN process_routes route ON route.id=wr.route_id "
            + route_version_join("wr", "route_version")
            + "WHERE "
            + " AND ".join(clauses)
            + " ORDER BY business_at,wr.id",
            params,
        ).fetchall()
        warn_legacy_fact_rows("work_records", rows)
        return [dict(row) for row in rows]

    @staticmethod
    def list_work_time_records(
        period_start, period_end, source_cutoff_at="", db=None
    ):
        db = resolve_db(db)
        business_at = (
            "COALESCE(NULLIF(wt.end_time,''),NULLIF(wt.start_time,''),wt.created_at)"
        )
        clauses = [
            "wt.review_status='approved'",
            business_at + ">=?",
            business_at + "<?",
        ]
        params = [period_start, period_end]
        if source_cutoff_at:
            clauses.append("wt.created_at<=?")
            params.append(source_cutoff_at)
            clauses.append(
                "COALESCE(NULLIF(wt.reviewed_at,''),wt.created_at)<=?"
            )
            params.append(source_cutoff_at)
        process_name = process_value_sql("wt", "process_version", "proc")
        route_name = route_name_sql("wt", "route_version", "route")
        rows = db.execute(
            "SELECT wt.*,"
            + business_at
            + " AS business_at,o.order_no AS current_order_no,opl.product_id,"
            "COALESCE(o.product_code,'') AS order_product_code,"
            "COALESCE(o.product_name,'') AS order_product_name,"
            + process_name + " AS current_process_name,"
            + route_name + " AS route_name_display "
            + "FROM work_time_records wt "
            "LEFT JOIN orders o ON o.id=wt.order_id "
            "LEFT JOIN order_product_links opl ON opl.order_id=wt.order_id "
            "LEFT JOIN processes proc ON proc.id=wt.process_id "
            + process_version_join("wt", "process_version")
            + "LEFT JOIN process_routes route ON route.id=wt.route_id "
            + route_version_join("wt", "route_version")
            + "WHERE "
            + " AND ".join(clauses)
            + " ORDER BY business_at,wt.id",
            params,
        ).fetchall()
        warn_legacy_fact_rows("work_time_records", rows)
        return [dict(row) for row in rows]

    @staticmethod
    def business_context(order_id=None, process_id=None, db=None):
        db = resolve_db(db)
        process_name = process_value_sql("op", "process_version", "proc")
        row = db.execute(
            "SELECT o.id AS order_id,COALESCE(o.order_no,'') AS order_no,"
            "opl.product_id,COALESCE(o.product_code,'') AS order_product_code,"
            "COALESCE(o.product_name,'') AS order_product_name,"
            "COALESCE(prod.product_code,'') AS current_product_code,"
            "COALESCE(prod.product_name,'') AS current_product_name,"
            "proc.id AS process_id," + process_name + " AS process_name,"
            "op.process_version_id,op.process_code_snapshot,op.process_name_snapshot,"
            "op.process_category_snapshot,o.route_id,o.route_version_id,o.route_name_snapshot,"
            "CASE WHEN op.process_version_id IS NOT NULL THEN 'captured' ELSE '' END AS version_binding_source "
            "FROM (SELECT ? AS order_key,? AS process_key) keys "
            "LEFT JOIN orders o ON o.id=keys.order_key "
            "LEFT JOIN order_product_links opl ON opl.order_id=o.id "
            "LEFT JOIN products prod ON prod.id=opl.product_id "
            "LEFT JOIN processes proc ON proc.id=keys.process_key "
            "LEFT JOIN order_processes op ON op.order_id=o.id AND op.process_id=proc.id "
            + process_version_join("op", "process_version"),
            (order_id, process_id),
        ).fetchone()
        return dict(row) if row else {}

    @staticmethod
    def process_quality_evaluation(evaluation_id, source_cutoff_at="", db=None):
        db = resolve_db(db)
        cutoff = source_cutoff_at or "9999-12-31 23:59:59"
        params = [cutoff, cutoff, evaluation_id]
        cutoff_clause = ""
        if source_cutoff_at:
            cutoff_clause = " AND evaluation.created_at<=?"
            params.append(cutoff)
        row = db.execute(
            "SELECT evaluation.*,EXISTS("
            "SELECT 1 FROM process_quality_evaluation_appeals appeal "
            "WHERE appeal.evaluation_id=evaluation.id AND appeal.created_at<=? "
            "AND (appeal.status='pending' OR NULLIF(appeal.reviewed_at,'')>?)"
            ") AS has_pending_appeal "
            "FROM process_quality_evaluations evaluation WHERE evaluation.id=?"
            + cutoff_clause,
            params,
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def list_plan_statuses(period_start, period_end, source_cutoff_at="", db=None):
        """Return one status snapshot per plan whose authoritative time is in range."""
        db = resolve_db(db)
        cutoff = source_cutoff_at or "9999-12-31 23:59:59"
        rows = db.execute(
            "SELECT plan.*,event.id AS event_id,"
            "COALESCE(NULLIF(event.to_status,''),plan.status) AS status_snapshot,"
            "COALESCE(event.created_at,NULLIF(plan.closed_at,''),"
            "NULLIF(plan.cancelled_at,''),plan.updated_at,plan.created_at) AS business_at,"
            "COALESCE(event.payload_json,'{}') AS event_payload_json,"
            "COALESCE(event.reassessment_round,plan.reassessment_round,0) AS event_round "
            "FROM performance_improvement_plans_v2 plan "
            "LEFT JOIN performance_plan_events event ON event.id=("
            "SELECT latest.id FROM performance_plan_events latest "
            "WHERE latest.plan_id=plan.id AND latest.created_at<=? "
            "ORDER BY latest.created_at DESC,latest.id DESC LIMIT 1) "
            "WHERE COALESCE(event.created_at,NULLIF(plan.closed_at,''),"
            "NULLIF(plan.cancelled_at,''),plan.updated_at,plan.created_at)>=? "
            "AND COALESCE(event.created_at,NULLIF(plan.closed_at,''),"
            "NULLIF(plan.cancelled_at,''),plan.updated_at,plan.created_at)<? "
            "AND plan.created_at<=? ORDER BY business_at,plan.id",
            (cutoff, period_start, period_end, cutoff),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def list_ambiguous_quality_exceptions(
        period_start, period_end, source_cutoff_at="", db=None
    ):
        db = resolve_db(db)
        business_at = "COALESCE(NULLIF(json_extract(exception.snapshot_json,'$.business_at'),''),("
        business_at += (
            "SELECT event.business_at FROM json_each(exception.snapshot_json,'$.candidates') candidate "
            "JOIN performance_quality_event_sources source "
            "ON source.source_type=json_extract(candidate.value,'$.source_type') "
            "AND source.source_id=json_extract(candidate.value,'$.source_id') "
            "JOIN performance_quality_events event ON event.id=source.quality_event_id "
            "WHERE event.business_at>=? AND event.business_at<? "
            "ORDER BY event.business_at,event.id LIMIT 1),exception.created_at)"
        )
        clauses = [
            "exception.batch_id IS NULL",
            "exception.exception_type='ambiguous_quality_source'",
            "(exception.status='pending' OR NULLIF(exception.resolved_at,'')>?)",
        ]
        cutoff = source_cutoff_at or "9999-12-31 23:59:59"
        params = [period_start, period_end, cutoff]
        if source_cutoff_at:
            clauses.append("exception.created_at<=?")
            params.append(source_cutoff_at)
        rows = db.execute(
            "WITH ambiguity AS (SELECT exception.*," + business_at + " AS business_at "
            "FROM performance_data_exceptions exception WHERE "
            + " AND ".join(clauses)
            + ") SELECT * FROM ambiguity WHERE business_at>=? AND business_at<? "
            "ORDER BY business_at,source_type,source_id,id",
            params + [period_start, period_end],
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def list_batch_facts(batch_id, db=None):
        db = resolve_db(db)
        rows = db.execute(
                "SELECT * FROM performance_source_facts WHERE batch_id=? "
                "ORDER BY fact_type,source_type,source_id,id",
                (batch_id,),
            ).fetchall()
        warn_legacy_fact_rows("performance_source_facts", rows)
        return [dict(row) for row in rows]

    @staticmethod
    def list_batch_exceptions(batch_id, db=None):
        db = resolve_db(db)
        return [
            dict(row)
            for row in db.execute(
                "SELECT * FROM performance_data_exceptions WHERE batch_id=? "
                "ORDER BY exception_type,source_type,source_id,id",
                (batch_id,),
            ).fetchall()
        ]

    @staticmethod
    def insert_source_fact(payload, db):
        columns = (
            "batch_id",
            "fact_type",
            "source_type",
            "source_id",
            "canonical_event_id",
            "business_at",
            "user_id",
            "employee_name_snapshot",
            "employee_no_snapshot",
            "department_id_snapshot",
            "department_name_snapshot",
            "position_id_snapshot",
            "position_name_snapshot",
            "order_id",
            "order_no_snapshot",
            "product_id",
            "product_code_snapshot",
            "product_name_snapshot",
            "process_id",
            "process_name_snapshot",
            "process_version_id",
            "process_code_snapshot",
            "process_category_snapshot",
            "route_id",
            "route_version_id",
            "route_name_snapshot",
            "version_binding_source",
            "quantity",
            "payload_json",
            "source_digest",
        )
        values = [payload.get(column) for column in columns]
        cursor = db.execute(
            "INSERT INTO performance_source_facts ("
            + ",".join(columns)
            + ") VALUES ("
            + ",".join("?" for _ in columns)
            + ")",
            values,
        )
        return cursor.lastrowid

    @staticmethod
    def insert_batch_exception(payload, db):
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
    def save_collection_digest(batch_id, source_cutoff_at, input_digest, db):
        cursor = db.execute(
            "UPDATE performance_batches SET source_cutoff_at=?,input_digest=?,"
            "row_version=row_version+1,updated_at=datetime('now','localtime') "
            "WHERE id=? AND status='draft' AND input_digest=''",
            (source_cutoff_at, input_digest, batch_id),
        )
        return cursor.rowcount
