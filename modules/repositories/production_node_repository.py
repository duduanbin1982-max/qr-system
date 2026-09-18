"""Read-side persistence for production-node staged compatibility cutover."""

import hashlib
import json

from modules.repositories.context import resolve_db


class ProductionNodeRepository:
    """The single production-node persistence seam, extended by later tasks."""

    MAX_RESOURCE_LIMIT = 1000

    @staticmethod
    def _bounded_limit(limit):
        try:
            value = int(limit or 500)
        except (TypeError, ValueError):
            value = 500
        return min(max(value, 1), ProductionNodeRepository.MAX_RESOURCE_LIMIT)

    @staticmethod
    def _dict_rows(cursor):
        return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def list_legacy_resources(process_id=None, limit=500, db=None):
        db = resolve_db(db)
        bounded_limit = ProductionNodeRepository._bounded_limit(limit)
        where = ""
        params = []
        if process_id not in (None, ""):
            where = "WHERE pl.process_id=?"
            params.append(int(process_id))
        cursor = db.execute(
            """
            SELECT pl.id,pl.process_id,pl.line_code,pl.line_name,pl.daily_minutes,
                   pl.status,pl.calendar_id,p.name AS process_name,
                   COALESCE((
                       SELECT COUNT(*) FROM order_process_schedules s
                       JOIN orders o ON o.id=s.order_id
                       WHERE s.process_line_id=pl.id AND s.status<>'blocked'
                         AND o.deleted_at IS NULL
                   ),0) AS scheduled_operations,
                   COALESCE((
                       SELECT SUM(ss.occupied_minutes)
                       FROM order_process_schedule_segments ss
                       JOIN order_process_schedules s ON s.id=ss.schedule_id
                       JOIN orders o ON o.id=s.order_id
                       WHERE ss.process_line_id=pl.id AND s.status<>'blocked'
                         AND o.deleted_at IS NULL
                   ),0) + COALESCE((
                       SELECT SUM(s.occupied_minutes)
                       FROM order_process_schedules s
                       JOIN orders o ON o.id=s.order_id
                       WHERE s.process_line_id=pl.id AND s.status<>'blocked'
                         AND o.deleted_at IS NULL
                         AND NOT EXISTS (
                             SELECT 1 FROM order_process_schedule_segments ss
                             WHERE ss.schedule_id=s.id
                         )
                   ),0) AS occupied_minutes,
                   COALESCE((
                       SELECT COUNT(*) FROM schedule_downtime_events d
                       WHERE d.process_line_id=pl.id AND d.status='active'
                   ),0) AS downtime_count,
                   COALESCE((
                       SELECT COUNT(*)
                       FROM order_process_schedule_segments a
                       JOIN order_process_schedule_segments b
                         ON a.process_line_id=b.process_line_id
                        AND a.id<b.id
                        AND a.segment_start_at<b.segment_end_at
                        AND b.segment_start_at<a.segment_end_at
                       JOIN order_process_schedules sa ON sa.id=a.schedule_id
                       JOIN order_process_schedules sb ON sb.id=b.schedule_id
                       JOIN orders oa ON oa.id=sa.order_id
                       JOIN orders ob ON ob.id=sb.order_id
                       WHERE a.process_line_id=pl.id
                         AND sa.status<>'blocked' AND sb.status<>'blocked'
                         AND oa.deleted_at IS NULL AND ob.deleted_at IS NULL
                   ),0) AS conflict_count
            FROM process_production_lines pl
            JOIN processes p ON p.id=pl.process_id
            """
            + where
            + " ORDER BY p.seq_order,p.id,pl.line_code,pl.id LIMIT ?",
            params + [bounded_limit],
        )
        return ProductionNodeRepository._dict_rows(cursor)

    @staticmethod
    def list_nodes(process_id=None, limit=500, db=None):
        db = resolve_db(db)
        bounded_limit = ProductionNodeRepository._bounded_limit(limit)
        where = ""
        params = []
        if process_id not in (None, ""):
            where = "WHERE n.process_id=?"
            params.append(int(process_id))
        cursor = db.execute(
            """
            SELECT n.id,n.process_id,n.node_code,n.node_name,n.capacity_mode,
                   n.status,n.calendar_id,n.legacy_process_line_id,
                   p.name AS process_name,
                   COALESCE((
                       SELECT SUM(shift.end_minute-shift.start_minute)
                       FROM schedule_shifts shift
                       WHERE shift.calendar_id=n.calendar_id
                         AND shift.status='active'
                   ),0) AS capacity_minutes,
                   COALESCE((
                       SELECT COUNT(*) FROM order_process_schedules s
                       JOIN orders o ON o.id=s.order_id
                       WHERE s.production_node_id=n.id AND s.status<>'blocked'
                         AND o.deleted_at IS NULL
                   ),0) AS scheduled_operations,
                   COALESCE((
                       SELECT SUM(ss.occupied_minutes)
                       FROM order_process_schedule_segments ss
                       JOIN order_process_schedules s ON s.id=ss.schedule_id
                       JOIN orders o ON o.id=s.order_id
                       WHERE ss.production_node_id=n.id AND s.status<>'blocked'
                         AND o.deleted_at IS NULL
                   ),0) + COALESCE((
                       SELECT SUM(s.occupied_minutes)
                       FROM order_process_schedules s
                       JOIN orders o ON o.id=s.order_id
                       WHERE s.production_node_id=n.id AND s.status<>'blocked'
                         AND o.deleted_at IS NULL
                         AND NOT EXISTS (
                             SELECT 1 FROM order_process_schedule_segments ss
                             WHERE ss.schedule_id=s.id
                         )
                   ),0) AS occupied_minutes,
                   COALESCE((
                       SELECT COUNT(*) FROM schedule_downtime_events d
                       WHERE d.production_node_id=n.id AND d.status='active'
                   ),0) AS downtime_count,
                   COALESCE((
                       SELECT COUNT(*)
                       FROM order_process_schedule_segments a
                       JOIN order_process_schedule_segments b
                         ON a.production_node_id=b.production_node_id
                        AND a.id<b.id
                        AND a.segment_start_at<b.segment_end_at
                        AND b.segment_start_at<a.segment_end_at
                       JOIN order_process_schedules sa ON sa.id=a.schedule_id
                       JOIN order_process_schedules sb ON sb.id=b.schedule_id
                       JOIN orders oa ON oa.id=sa.order_id
                       JOIN orders ob ON ob.id=sb.order_id
                       WHERE a.production_node_id=n.id
                         AND sa.status<>'blocked' AND sb.status<>'blocked'
                         AND oa.deleted_at IS NULL AND ob.deleted_at IS NULL
                   ),0) AS conflict_count
            FROM production_nodes n
            JOIN processes p ON p.id=n.process_id
            """
            + where
            + " ORDER BY p.seq_order,p.id,n.node_code,n.id LIMIT ?",
            params + [bounded_limit],
        )
        return ProductionNodeRepository._dict_rows(cursor)

    @staticmethod
    def canonical_payload(payload):
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

    @staticmethod
    def payload_digest(payload):
        encoded = ProductionNodeRepository.canonical_payload(payload)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def record_compatibility_observation(
        *, scope, source_id, legacy_payload, node_payload, difference, db=None
    ):
        db = resolve_db(db)
        legacy_digest = ProductionNodeRepository.payload_digest(legacy_payload)
        node_digest = ProductionNodeRepository.payload_digest(node_payload)
        key_material = {
            "scope": str(scope or ""),
            "source_id": source_id,
            "legacy_digest": legacy_digest,
            "node_digest": node_digest,
        }
        observation_key = ProductionNodeRepository.payload_digest(key_material)
        db.execute(
            "INSERT OR IGNORE INTO production_node_compatibility_observations "
            "(observation_key,scope,source_id,legacy_digest,node_digest,mismatch,difference_json) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                observation_key,
                str(scope or ""),
                source_id,
                legacy_digest,
                node_digest,
                int(legacy_digest != node_digest),
                ProductionNodeRepository.canonical_payload(difference or {}),
            ),
        )
        return observation_key
