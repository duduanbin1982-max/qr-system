"""Single persistence seam for production-node reads and administration."""

import hashlib
import json

from modules.repositories.context import resolve_db
from modules.domain.production_node_scheduling import ProductionNodePolicy


class ProductionNodeRepository:
    """The single production-node persistence seam, extended by later tasks."""

    MAX_RESOURCE_LIMIT = 1000

    @staticmethod
    def _bounded_limit(limit):
        if limit in (None, ""):
            return 500
        try:
            value = int(limit)
        except (TypeError, ValueError):
            value = 500
        return min(max(value, 1), ProductionNodeRepository.MAX_RESOURCE_LIMIT)

    @staticmethod
    def _dict_rows(cursor):
        return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def _resource_fact_summary(db, *, resource_column, resource_id):
        if resource_column not in {"process_line_id", "production_node_id"}:
            raise ValueError("unsupported production resource column")
        occupancy = ProductionNodeRepository._dict_rows(
            db.execute(
                f"""
                SELECT * FROM (
                    SELECT 'segment' AS fact_type,ss.id AS fact_id,ss.schedule_id,
                           ss.segment_start_at AS start_at,
                           ss.segment_end_at AS end_at,ss.occupied_minutes,ss.quantity
                    FROM order_process_schedule_segments ss
                    JOIN order_process_schedules s ON s.id=ss.schedule_id
                    JOIN orders o ON o.id=s.order_id
                    WHERE ss.{resource_column}=? AND s.status<>'blocked'
                      AND o.deleted_at IS NULL
                    UNION ALL
                    SELECT 'schedule' AS fact_type,s.id AS fact_id,s.id AS schedule_id,
                           CASE WHEN COALESCE(s.planned_start_at,'')<>''
                                THEN s.planned_start_at ELSE s.plan_start || ' 00:00' END,
                           CASE WHEN COALESCE(s.planned_end_at,'')<>''
                                THEN s.planned_end_at ELSE s.plan_end || ' 23:59' END,
                           s.occupied_minutes,s.quantity
                    FROM order_process_schedules s
                    JOIN orders o ON o.id=s.order_id
                    WHERE s.{resource_column}=? AND s.status<>'blocked'
                      AND o.deleted_at IS NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM order_process_schedule_segments ss
                          WHERE ss.schedule_id=s.id
                      )
                ) facts
                ORDER BY start_at,end_at,fact_type,fact_id
                """,
                (resource_id, resource_id),
            )
        )
        downtime = ProductionNodeRepository._dict_rows(
            db.execute(
                f"SELECT id,start_at,end_at,status,source_type,source_id "
                f"FROM schedule_downtime_events "
                f"WHERE {resource_column}=? AND status='active' "
                f"ORDER BY start_at,end_at,id",
                (resource_id,),
            )
        )
        conflict_count = sum(
            1
            for index, first in enumerate(occupancy)
            for second in occupancy[index + 1 :]
            if first["start_at"] < second["end_at"]
            and second["start_at"] < first["end_at"]
        )
        return (
            ProductionNodeRepository.payload_digest(occupancy),
            ProductionNodeRepository.payload_digest(downtime),
            conflict_count,
        )

    @staticmethod
    def _attach_fact_digests(db, rows, *, resource_column):
        for row in rows:
            occupancy_digest, downtime_digest, conflict_count = (
                ProductionNodeRepository._resource_fact_summary(
                    db,
                    resource_column=resource_column,
                    resource_id=row["id"],
                )
            )
            row["occupancy_digest"] = occupancy_digest
            row["downtime_digest"] = downtime_digest
            row["conflict_count"] = conflict_count
        return rows

    @staticmethod
    def list_legacy_resources(process_id=None, limit=500, db=None, *, full=False):
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
                   ),0) AS downtime_count
            FROM process_production_lines pl
            JOIN processes p ON p.id=pl.process_id
            """
            + where
            + " ORDER BY p.seq_order,p.id,pl.line_code,pl.id"
            + ("" if full else " LIMIT ?"),
            params + ([] if full else [bounded_limit]),
        )
        return ProductionNodeRepository._attach_fact_digests(
            db,
            ProductionNodeRepository._dict_rows(cursor),
            resource_column="process_line_id",
        )

    @staticmethod
    def list_nodes(process_id=None, status=None, limit=500, db=None, *, full=False):
        db = resolve_db(db)
        bounded_limit = ProductionNodeRepository._bounded_limit(limit)
        filters = []
        params = []
        if process_id not in (None, ""):
            filters.append("n.process_id=?")
            params.append(int(process_id))
        if status not in (None, ""):
            filters.append("n.status=?")
            params.append(str(status))
        where = " WHERE " + " AND ".join(filters) if filters else ""
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
                   ),0) AS downtime_count
            FROM production_nodes n
            JOIN processes p ON p.id=n.process_id
            """
            + where
            + " ORDER BY p.seq_order,p.id,n.node_code,n.id"
            + ("" if full else " LIMIT ?"),
            params + ([] if full else [bounded_limit]),
        )
        return ProductionNodeRepository._attach_fact_digests(
            db,
            ProductionNodeRepository._dict_rows(cursor),
            resource_column="production_node_id",
        )

    @staticmethod
    def list_active_nodes_for_process(process_id, db=None):
        """Return active node facts in deterministic order for allocation."""
        db = resolve_db(db)
        rows = ProductionNodeRepository._dict_rows(
            db.execute(
                "SELECT n.*,p.name AS process_name "
                "FROM production_nodes n JOIN processes p ON p.id=n.process_id "
                "WHERE n.process_id=? AND n.status='active' "
                "ORDER BY n.node_code,n.id",
                (process_id,),
            )
        )
        for row in rows:
            row["capabilities"] = ProductionNodeRepository.list_capabilities(
                row["id"], db=db
            )
        return rows

    @staticmethod
    def list_compatible_nodes(operation, order, at_time=None, db=None):
        """Resolve nodes by exact process and configured capability facts."""
        del at_time
        db = resolve_db(db)
        # Service callers may pass sqlite Row objects while policy evaluation
        # deliberately uses mapping helpers.  Normalize at this repository
        # boundary so the scheduler is independent of the storage row type.
        operation = dict(operation or {})
        order = dict(order or {})
        candidates = []
        for node in ProductionNodeRepository.list_active_nodes_for_process(
            operation.get("process_id"), db=db
        ):
            capabilities = node.pop("capabilities", [])
            if ProductionNodePolicy.matches_capabilities(
                node=node,
                capabilities=capabilities,
                operation=operation,
                order=order,
            ):
                node["capabilities"] = capabilities
                candidates.append(node)
        return candidates

    @staticmethod
    def list_node_occupancy(exclude_order_id, db=None):
        """Read node occupancy, ignoring soft-deleted, blocked and regenerated facts."""
        db = resolve_db(db)
        return db.execute(
            """
            SELECT ss.production_node_id, ss.segment_start_at AS start_at,
                   ss.segment_end_at AS end_at, ss.schedule_id,
                   s.id AS occupancy_id, s.locked
            FROM order_process_schedule_segments ss
            JOIN order_process_schedules s ON s.id=ss.schedule_id
            JOIN orders o ON o.id=s.order_id
            WHERE s.order_id != ? AND o.deleted_at IS NULL
              AND s.status != 'blocked' AND ss.production_node_id IS NOT NULL
            UNION ALL
            SELECT s.production_node_id,
                   CASE WHEN COALESCE(s.planned_start_at,'')<>''
                        THEN s.planned_start_at ELSE s.plan_start || ' 00:00' END,
                   CASE WHEN COALESCE(s.planned_end_at,'')<>''
                        THEN s.planned_end_at ELSE s.plan_end || ' 23:59' END,
                   s.id, s.id, s.locked
            FROM order_process_schedules s
            JOIN orders o ON o.id=s.order_id
            WHERE s.order_id != ? AND o.deleted_at IS NULL
              AND s.status != 'blocked' AND s.production_node_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM order_process_schedule_segments ss
                  WHERE ss.schedule_id=s.id
              )
            ORDER BY start_at,end_at,production_node_id,occupancy_id
            """,
            (exclude_order_id, exclude_order_id),
        ).fetchall()

    @staticmethod
    def list_node_calendar_overrides(node_id, start_at="", end_at="", db=None):
        db = resolve_db(db)
        where = ["production_node_id=?", "status='active'"]
        params = [node_id]
        if start_at:
            where.append("end_at>?" )
            params.append(start_at)
        if end_at:
            where.append("start_at<?")
            params.append(end_at)
        return db.execute(
            "SELECT * FROM production_node_calendar_overrides WHERE "
            + " AND ".join(where) + " ORDER BY start_at,end_at,id", params
        ).fetchall()

    @staticmethod
    def find_node(node_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT n.*,p.name AS process_name,c.calendar_code,c.calendar_name "
            "FROM production_nodes n "
            "JOIN processes p ON p.id=n.process_id "
            "JOIN schedule_calendars c ON c.id=n.calendar_id WHERE n.id=?",
            (node_id,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def actor_exists(actor_id, db=None):
        db = resolve_db(db)
        return bool(db.execute("SELECT 1 FROM users WHERE id=?", (actor_id,)).fetchone())

    @staticmethod
    def process_is_active(process_id, db=None):
        db = resolve_db(db)
        return bool(
            db.execute(
                "SELECT 1 FROM processes WHERE id=? AND status='active'",
                (process_id,),
            ).fetchone()
        )

    @staticmethod
    def calendar_is_active(calendar_id, db=None):
        db = resolve_db(db)
        return bool(
            db.execute(
                "SELECT 1 FROM schedule_calendars WHERE id=? AND status='active'",
                (calendar_id,),
            ).fetchone()
        )

    @staticmethod
    def node_code_exists(process_id, node_code, exclude_id=None, db=None):
        db = resolve_db(db)
        sql = "SELECT 1 FROM production_nodes WHERE process_id=? AND node_code=?"
        params = [process_id, node_code]
        if exclude_id is not None:
            sql += " AND id<>?"
            params.append(exclude_id)
        return bool(db.execute(sql, params).fetchone())

    @staticmethod
    def product_exists(product_id, db=None):
        db = resolve_db(db)
        return bool(db.execute("SELECT 1 FROM products WHERE id=?", (product_id,)).fetchone())

    @staticmethod
    def process_version_process_id(process_version_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT process_id FROM process_versions WHERE id=?",
            (process_version_id,),
        ).fetchone()
        return row["process_id"] if row else None

    @staticmethod
    def route_version_exists(route_version_id, db=None):
        db = resolve_db(db)
        return bool(
            db.execute(
                "SELECT 1 FROM process_route_versions WHERE id=?",
                (route_version_id,),
            ).fetchone()
        )

    @staticmethod
    def route_version_contains_process(
        route_version_id, process_id, process_version_id=None, db=None
    ):
        db = resolve_db(db)
        sql = (
            "SELECT 1 FROM process_route_version_items "
            "WHERE route_version_id=? AND process_id=?"
        )
        params = [route_version_id, process_id]
        if process_version_id is not None:
            sql += " AND process_version_id=?"
            params.append(process_version_id)
        return bool(db.execute(sql + " LIMIT 1", params).fetchone())

    @staticmethod
    def find_overlapping_active_override(node_id, start_at, end_at, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM production_node_calendar_overrides "
            "WHERE production_node_id=? AND status='active' "
            "AND start_at<? AND end_at>? ORDER BY id LIMIT 1",
            (node_id, end_at, start_at),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def list_capabilities(node_id, db=None):
        db = resolve_db(db)
        return ProductionNodeRepository._dict_rows(
            db.execute(
                "SELECT * FROM production_node_capabilities "
                "WHERE production_node_id=? ORDER BY id",
                (node_id,),
            )
        )

    @staticmethod
    def list_calendar_overrides(
        node_id, start_at="", end_at="", limit=500, db=None
    ):
        db = resolve_db(db)
        filters = ["production_node_id=?"]
        params = [node_id]
        if start_at:
            filters.append("end_at>?")
            params.append(start_at)
        if end_at:
            filters.append("start_at<?")
            params.append(end_at)
        params.append(ProductionNodeRepository._bounded_limit(limit))
        return ProductionNodeRepository._dict_rows(
            db.execute(
                "SELECT * FROM production_node_calendar_overrides WHERE "
                + " AND ".join(filters)
                + " ORDER BY start_at,end_at,id LIMIT ?",
                params,
            )
        )

    @staticmethod
    def find_calendar_override(override_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM production_node_calendar_overrides WHERE id=?",
            (override_id,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def find_audit_by_idempotency_key(idempotency_key, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM production_node_audit_events WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["before"] = json.loads(result.pop("before_json") or "{}")
        result["after"] = json.loads(result.pop("after_json") or "{}")
        return result

    @staticmethod
    def list_audit_events(node_id, limit=500, db=None):
        db = resolve_db(db)
        rows = ProductionNodeRepository._dict_rows(
            db.execute(
                "SELECT * FROM production_node_audit_events "
                "WHERE production_node_id=? ORDER BY id DESC LIMIT ?",
                (node_id, ProductionNodeRepository._bounded_limit(limit)),
            )
        )
        for row in rows:
            row["before"] = json.loads(row.pop("before_json") or "{}")
            row["after"] = json.loads(row.pop("after_json") or "{}")
        return rows

    @staticmethod
    def create_node(data, actor_id, db):
        cursor = db.execute(
            "INSERT INTO production_nodes "
            "(process_id,node_code,node_name,capacity_mode,status,calendar_id) "
            "VALUES (?,?,?,?,?,?)",
            (
                data["process_id"],
                data["node_code"],
                data["node_name"],
                data["capacity_mode"],
                data.get("status", "active"),
                data["calendar_id"],
            ),
        )
        return ProductionNodeRepository.find_node(cursor.lastrowid, db=db)

    @staticmethod
    def update_node(node_id, data, actor_id, db):
        del actor_id
        cursor = db.execute(
            "UPDATE production_nodes SET process_id=?,node_code=?,node_name=?,"
            "capacity_mode=?,status=?,calendar_id=?,row_version=row_version+1,"
            "updated_at=datetime('now','localtime') WHERE id=? AND row_version=?",
            (
                data["process_id"],
                data["node_code"],
                data["node_name"],
                data["capacity_mode"],
                data.get("status", "active"),
                data["calendar_id"],
                node_id,
                data["row_version"],
            ),
        )
        return ProductionNodeRepository.find_node(node_id, db=db) if cursor.rowcount else None

    @staticmethod
    def replace_capabilities(
        node_id, capabilities, actor_id, idempotency_key, reason, db
    ):
        del actor_id, idempotency_key, reason
        db.execute(
            "DELETE FROM production_node_capabilities WHERE production_node_id=?",
            (node_id,),
        )
        for capability in capabilities:
            db.execute(
                "INSERT INTO production_node_capabilities "
                "(production_node_id,product_id,product_family,material_code,"
                "specification,route_version_id,process_version_id,max_batch_quantity,"
                "batch_minutes,changeover_minutes,allow_mixed_orders,status) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    node_id,
                    capability.get("product_id"),
                    capability.get("product_family", ""),
                    capability.get("material_code", ""),
                    capability.get("specification", ""),
                    capability.get("route_version_id"),
                    capability.get("process_version_id"),
                    capability.get("max_batch_quantity"),
                    capability.get("batch_minutes"),
                    capability.get("changeover_minutes", 0),
                    int(bool(capability.get("allow_mixed_orders", False))),
                    capability.get("status", "active"),
                ),
            )
        return ProductionNodeRepository.list_capabilities(node_id, db=db)

    @staticmethod
    def create_calendar_override(node_id, data, actor_id, db):
        cursor = db.execute(
            "INSERT INTO production_node_calendar_overrides "
            "(production_node_id,start_at,end_at,override_type,reason,status,created_by) "
            "VALUES (?,?,?,?,?,'active',?)",
            (
                node_id,
                data["start_at"],
                data["end_at"],
                data["override_type"],
                data["reason"],
                actor_id,
            ),
        )
        return ProductionNodeRepository.find_calendar_override(cursor.lastrowid, db=db)

    @staticmethod
    def cancel_calendar_override(
        override_id, actor_id, reason, idempotency_key, db
    ):
        del actor_id, reason, idempotency_key
        cursor = db.execute(
            "UPDATE production_node_calendar_overrides SET status='cancelled' "
            "WHERE id=? AND status='active'",
            (override_id,),
        )
        return (
            ProductionNodeRepository.find_calendar_override(override_id, db=db)
            if cursor.rowcount
            else None
        )

    @staticmethod
    def append_audit_event(event, db):
        cursor = db.execute(
            "INSERT INTO production_node_audit_events "
            "(production_node_id,event_type,actor_id,reason,before_json,after_json,"
            "idempotency_key) VALUES (?,?,?,?,?,?,?)",
            (
                event.get("production_node_id"),
                event["event_type"],
                event.get("actor_id"),
                event.get("reason", ""),
                ProductionNodeRepository.canonical_payload(event.get("before", {})),
                ProductionNodeRepository.canonical_payload(event.get("after", {})),
                event["idempotency_key"],
            ),
        )
        return cursor.lastrowid

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
