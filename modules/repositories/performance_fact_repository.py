"""Persistence for canonical performance quality events and source facts."""

from modules.repositories.context import resolve_db


class PerformanceFactRepository:
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
        cursor = db.execute(
            "INSERT INTO performance_quality_events ("
            "event_type,quantity,order_id,process_id,user_id,business_at,"
            "snapshot_json,event_digest"
            ") VALUES (?,?,?,?,?,?,?,?)",
            (
                payload["event_type"],
                payload["quantity"],
                payload.get("order_id"),
                payload.get("process_id"),
                payload.get("user_id"),
                payload["business_at"],
                payload["snapshot_json"],
                payload["event_digest"],
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
            "SELECT id,order_id,process_id,user_id,quantity,created_at "
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
    def list_quality_events(period_start, period_end, db=None):
        """Return each canonical event once with all of its mapped sources."""
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
        source_rows = db.execute(
            "SELECT source.quality_event_id,source.source_type,source.source_id "
            "FROM performance_quality_event_sources source "
            "JOIN performance_quality_events event "
            "ON event.id=source.quality_event_id "
            "WHERE event.business_at>=? AND event.business_at<? "
            "ORDER BY source.quality_event_id,source.source_type,source.source_id",
            (period_start, period_end),
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
