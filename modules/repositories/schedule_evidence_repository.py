"""Persistence for conflicts, risks, replan differences and audit evidence."""

import hashlib
import json
import sqlite3

from modules.repositories.context import resolve_db


class ScheduleEvidenceRepository:
    """Conflict, risk, replan-difference and audit evidence."""

    @staticmethod
    def record_replan_trigger(
        order_id, trigger_type, source_type, source_id, reason, *,
        order_process_id=None, details=None, created_by=None, db=None,
    ):
        """Append immutable evidence and mark the order pending replan."""
        db = resolve_db(db)
        payload = details if isinstance(details, dict) else {}
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        digest_input = json.dumps(
            {
                "order_id": int(order_id),
                "order_process_id": int(order_process_id) if order_process_id else None,
                "trigger_type": str(trigger_type or "manual"),
                "source_type": str(source_type or "manual"),
                "source_id": int(source_id) if source_id is not None else None,
                "reason": str(reason or ""),
                "details": payload,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
        cursor = db.execute(
            "INSERT OR IGNORE INTO schedule_replan_triggers "
            "(order_id,order_process_id,trigger_type,source_type,source_id,reason,"
            "fact_digest,details_json,created_by) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                int(order_id), int(order_process_id) if order_process_id else None,
                str(trigger_type or "manual"), str(source_type or "manual"),
                int(source_id) if source_id is not None else None,
                str(reason or "").strip() or "生产事实发生变化",
                digest, encoded, created_by,
            ),
        )
        db.execute(
            "UPDATE orders SET schedule_replan_required=1,schedule_replan_reason=?,"
            "updated_at=datetime('now','localtime') WHERE id=? AND deleted_at IS NULL",
            (str(reason or "").strip() or "生产事实发生变化", int(order_id)),
        )
        if cursor.rowcount:
            return cursor.lastrowid
        row = db.execute(
            "SELECT id FROM schedule_replan_triggers WHERE order_id=? "
            "AND trigger_type=? AND source_type=? AND source_id IS ? AND fact_digest=?",
            (int(order_id), trigger_type, source_type, source_id, digest),
        ).fetchone()
        return row["id"] if row else None
    @staticmethod
    def list_replan_triggers(order_id, limit=200, db=None):
        db = resolve_db(db)
        limit = min(max(int(limit or 200), 1), 1000)
        return db.execute(
            "SELECT * FROM schedule_replan_triggers WHERE order_id=? "
            "ORDER BY created_at DESC,id DESC LIMIT ?",
            (int(order_id), limit),
        ).fetchall()
    @staticmethod
    def save_replan_evidence(
        revision_id, prior_revision_id, order_id, differences, summary, db=None,
    ):
        db = resolve_db(db)
        for item in differences:
            db.execute(
                "INSERT INTO schedule_replan_differences "
                "(revision_id,prior_revision_id,order_id,order_process_id,process_id,"
                "change_type,node_changed,quantity_delta,occupied_minutes_delta,"
                "start_delta_minutes,end_delta_minutes,before_json,after_json,evidence_digest) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    int(revision_id), prior_revision_id, int(order_id),
                    int(item["order_process_id"]), int(item["process_id"]),
                    item["change_type"], int(item["node_changed"]),
                    int(item["quantity_delta"]), float(item["occupied_minutes_delta"]),
                    int(item["start_delta_minutes"]), int(item["end_delta_minutes"]),
                    json.dumps(item["before"], ensure_ascii=False, sort_keys=True),
                    json.dumps(item["after"], ensure_ascii=False, sort_keys=True),
                    item["evidence_digest"],
                ),
            )
        encoded = json.dumps(
            summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        evidence_digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        db.execute(
            "INSERT INTO schedule_replan_summaries "
            "(revision_id,prior_revision_id,order_id,trigger_count,changed_operation_count,"
            "node_change_count,delayed_operation_count,advanced_operation_count,"
            "before_risk_level,after_risk_level,before_delay_minutes,after_delay_minutes,"
            "risk_change,summary_json,evidence_digest) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                int(revision_id), prior_revision_id, int(order_id),
                int(summary.get("trigger_count") or 0),
                int(summary.get("changed_operation_count") or 0),
                int(summary.get("node_change_count") or 0),
                int(summary.get("delayed_operation_count") or 0),
                int(summary.get("advanced_operation_count") or 0),
                summary.get("before_risk_level") or "none",
                summary.get("after_risk_level") or "none",
                int(summary.get("before_delay_minutes") or 0),
                int(summary.get("after_delay_minutes") or 0),
                summary.get("risk_change") or "unchanged",
                encoded, evidence_digest,
            ),
        )
        return evidence_digest
    @staticmethod
    def get_replan_evidence(revision_id, db=None):
        db = resolve_db(db)
        summary = db.execute(
            "SELECT * FROM schedule_replan_summaries WHERE revision_id=?",
            (int(revision_id),),
        ).fetchone()
        differences = db.execute(
            "SELECT d.*,p.name AS process_name FROM schedule_replan_differences d "
            "JOIN processes p ON p.id=d.process_id WHERE d.revision_id=? "
            "ORDER BY d.order_process_id,d.id",
            (int(revision_id),),
        ).fetchall()
        return summary, differences
    @staticmethod
    def set_revision_risk_snapshot(revision_id, risk, assessed_at, db):
        cursor = db.execute(
            "UPDATE schedule_revisions SET deadline_snapshot=?,"
            "projected_completion_at_snapshot=?,risk_level=?,delay_minutes=?,"
            "risk_reason=?,risk_assessed_at=? WHERE id=? AND risk_assessed_at=''",
            (
                risk.get("deadline", ""),
                risk.get("projected_completion_at", ""),
                risk.get("level", "unassessed"),
                max(int(risk.get("delay_minutes") or 0), 0),
                risk.get("reason", ""),
                assessed_at,
                revision_id,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("排程版本风险快照已冻结")
    @staticmethod
    def list_revision_conflict_items(revision_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT i.*,r.order_id,p.name AS process_name,"
            "CASE WHEN l.id IS NULL THEN 0 ELSE 1 END AS locked "
            "FROM schedule_revision_items i "
            "JOIN schedule_revisions r ON r.id=i.revision_id "
            "JOIN processes p ON p.id=i.process_id "
            "LEFT JOIN schedule_node_task_locks l "
            "ON l.revision_item_id=i.id AND l.status='active' "
            "WHERE i.revision_id=? ORDER BY i.seq_order,i.id",
            (int(revision_id),),
        ).fetchall()
    @staticmethod
    def record_revision_conflict_check(
        revision_id, check_stage, input_digest, summary, conflicts, db=None
    ):
        db = resolve_db(db)
        existing = db.execute(
            "SELECT * FROM schedule_revision_conflict_checks "
            "WHERE revision_id=? AND check_stage=? AND input_digest=?",
            (int(revision_id), str(check_stage), str(input_digest)),
        ).fetchone()
        if existing is not None:
            return existing
        conflict_rows = list(conflicts or ())
        encoded = json.dumps(
            conflict_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        result_digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        cursor = db.execute(
            "INSERT INTO schedule_revision_conflict_checks "
            "(revision_id,check_stage,input_digest,blocking_count,warning_count,"
            "summary_json,result_digest) VALUES (?,?,?,?,?,?,?)",
            (
                int(revision_id), str(check_stage), str(input_digest),
                int(summary.get("blocking_count") or 0),
                int(summary.get("warning_count") or 0),
                json.dumps(summary, ensure_ascii=False, sort_keys=True),
                result_digest,
            ),
        )
        check_id = cursor.lastrowid
        for conflict in conflict_rows:
            first = conflict.get("first") or {}
            second = conflict.get("second") or {}
            production_node_id = (
                first.get("production_node_id")
                or second.get("production_node_id")
            )
            process_line_id = (
                first.get("process_line_id") or second.get("process_line_id")
            )
            db.execute(
                "INSERT INTO schedule_revision_conflicts "
                "(check_id,revision_id,conflict_type,severity,production_node_id,"
                "process_line_id,first_order_id,second_order_id,"
                "first_order_process_id,second_order_process_id,"
                "first_revision_item_id,second_revision_item_id,"
                "first_schedule_id,second_schedule_id,overlap_start_at,"
                "overlap_end_at,overlap_minutes,first_locked,second_locked,"
                "reason,details_json,evidence_digest) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    check_id, int(revision_id), conflict.get("conflict_type") or "unknown",
                    conflict.get("severity") or "blocking", production_node_id,
                    process_line_id, first.get("order_id"), second.get("order_id"),
                    first.get("order_process_id"), second.get("order_process_id"),
                    first.get("revision_item_id"), second.get("revision_item_id"),
                    first.get("schedule_id"), second.get("schedule_id"),
                    conflict.get("overlap_start_at") or "",
                    conflict.get("overlap_end_at") or "",
                    max(int(conflict.get("overlap_minutes") or 0), 0),
                    int(bool(conflict.get("first_locked"))),
                    int(bool(conflict.get("second_locked"))),
                    conflict.get("reason") or "排程冲突",
                    json.dumps(
                        conflict.get("details") or {},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    conflict.get("evidence_digest") or "",
                ),
            )
        return db.execute(
            "SELECT * FROM schedule_revision_conflict_checks WHERE id=?",
            (check_id,),
        ).fetchone()
    @staticmethod
    def record_revision_risk_assessment(
        revision_id, assessment_stage, risk, details, evidence_digest, db=None
    ):
        db = resolve_db(db)
        existing = db.execute(
            "SELECT * FROM schedule_revision_risk_assessments "
            "WHERE revision_id=? AND assessment_stage=?",
            (int(revision_id), str(assessment_stage)),
        ).fetchone()
        if existing is not None:
            return existing
        db.execute(
            "INSERT INTO schedule_revision_risk_assessments "
            "(revision_id,assessment_stage,deadline_snapshot,"
            "projected_completion_at_snapshot,risk_level,delay_minutes,"
            "slack_minutes,blocked_count,conflict_count,primary_risk_source,"
            "bottleneck_process,bottleneck_node,risk_reason,"
            "suggested_actions_json,details_json,evidence_digest) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                int(revision_id), str(assessment_stage), risk.get("deadline") or "",
                risk.get("projected_completion_at") or "", risk.get("level") or "none",
                max(int(risk.get("delay_minutes") or 0), 0),
                risk.get("slack_minutes"), max(int(risk.get("blocked_count") or 0), 0),
                max(int(risk.get("conflict_count") or 0), 0),
                risk.get("primary_source") or "", risk.get("bottleneck_process") or "",
                risk.get("bottleneck_node") or "", risk.get("reason") or "",
                json.dumps(
                    risk.get("suggested_actions") or [],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                json.dumps(details or {}, ensure_ascii=False, sort_keys=True),
                str(evidence_digest),
            ),
        )
        return db.execute(
            "SELECT * FROM schedule_revision_risk_assessments "
            "WHERE revision_id=? AND assessment_stage=?",
            (int(revision_id), str(assessment_stage)),
        ).fetchone()
    @staticmethod
    def list_revision_conflicts(revision_id, check_stage=None, db=None):
        db = resolve_db(db)
        params = [int(revision_id)]
        stage_clause = ""
        if check_stage:
            stage_clause = " AND check_row.check_stage=?"
            params.append(str(check_stage))
        else:
            stage_clause = (
                " AND check_row.id=(SELECT latest.id "
                "FROM schedule_revision_conflict_checks latest "
                "WHERE latest.revision_id=? ORDER BY latest.id DESC LIMIT 1)"
            )
            params.append(int(revision_id))
        return db.execute(
            "SELECT conflict.*,check_row.check_stage,check_row.blocking_count,"
            "check_row.warning_count,check_row.result_digest AS check_digest "
            "FROM schedule_revision_conflicts conflict "
            "JOIN schedule_revision_conflict_checks check_row "
            "ON check_row.id=conflict.check_id "
            "WHERE conflict.revision_id=?" + stage_clause
            + " ORDER BY conflict.severity DESC,conflict.id",
            params,
        ).fetchall()
    @staticmethod
    def find_revision_risk_assessment(revision_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM schedule_revision_risk_assessments "
            "WHERE revision_id=? ORDER BY id DESC LIMIT 1",
            (int(revision_id),),
        ).fetchone()
    @staticmethod
    def list_schedule_conflicts(db=None):
        """Find published overlaps using node-native, segment-first facts."""
        db = resolve_db(db)
        try:
            return db.execute(
                """
                SELECT
                    CASE WHEN a.production_node_id IS NOT NULL THEN 'production_node'
                         ELSE 'legacy_line' END AS resource_type,
                    COALESCE(a.production_node_id,a.process_line_id) AS resource_id,
                    a.production_node_id,a.process_line_id,
                    COALESCE(NULLIF(a.node_name,''),NULLIF(b.node_name,''),'') AS node_name,
                    a.order_id AS first_order_id,b.order_id AS second_order_id,
                    a.order_process_id AS first_order_process_id,
                    b.order_process_id AS second_order_process_id,
                    a.schedule_id AS first_schedule_id,b.schedule_id AS second_schedule_id,
                    a.start_at AS first_start_at,a.end_at AS first_end_at,
                    b.start_at AS second_start_at,b.end_at AS second_end_at,
                    CAST((julianday(MIN(a.end_at,b.end_at))-
                          julianday(MAX(a.start_at,b.start_at)))*1440 AS INTEGER)
                        AS overlap_minutes,
                    CASE WHEN a.locked=1 OR b.locked=1 THEN 1 ELSE 0 END AS locked
                FROM schedule_effective_capacity_intervals a
                JOIN schedule_effective_capacity_intervals b
                  ON a.fact_key < b.fact_key
                 AND ((a.production_node_id IS NOT NULL
                       AND a.production_node_id=b.production_node_id)
                      OR (a.production_node_id IS NULL
                          AND b.production_node_id IS NULL
                          AND a.process_line_id=b.process_line_id))
                 AND a.start_at < b.end_at
                 AND b.start_at < a.end_at
                WHERE a.capacity_mode='exclusive' OR b.capacity_mode='exclusive'
                ORDER BY resource_type,resource_id,a.start_at,a.fact_key
                """
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    @staticmethod
    def list_schedule_conflicts_by_order(db=None):
        rows = [
            dict(row)
            for row in ScheduleEvidenceRepository.list_schedule_conflicts(db=db)
        ]
        result = {}
        for row in rows:
            for key in ("first_order_id", "second_order_id"):
                order_id = row.get(key)
                if order_id in (None, ""):
                    continue
                result.setdefault(int(order_id), []).append(row)
        return result
    @staticmethod
    def list_schedule_risk_inputs(limit=1000, db=None):
        """Return one precision delivery-risk input row per live order."""
        db = resolve_db(db)
        limit = min(max(int(limit or 1000), 1), 1000)
        try:
            return db.execute(
                """
                SELECT o.id AS order_id, o.order_no, o.deadline, o.plan_end,
                       o.status AS order_status, o.quantity, o.completed,
                       COALESCE(MAX(CASE WHEN s.status != 'blocked'
                                         THEN NULLIF(s.planned_end_at,'') END), '')
                           AS projected_completion_at,
                       COALESCE(SUM(CASE WHEN s.status='blocked' THEN 1 ELSE 0 END),0)
                           AS blocked_count,
                       COALESCE(GROUP_CONCAT(CASE WHEN s.status='blocked'
                                                  THEN NULLIF(s.blocked_reason,'') END, '；'),'')
                           AS blocked_reasons,
                       COALESCE((
                           SELECT COUNT(DISTINCT CASE
                               WHEN first_fact.order_id=o.id THEN first_fact.fact_key
                               ELSE second_fact.fact_key
                           END)
                           FROM schedule_effective_capacity_intervals first_fact
                           JOIN schedule_effective_capacity_intervals second_fact
                             ON first_fact.fact_key < second_fact.fact_key
                            AND ((first_fact.production_node_id IS NOT NULL
                                  AND first_fact.production_node_id=second_fact.production_node_id)
                                 OR (first_fact.production_node_id IS NULL
                                     AND second_fact.production_node_id IS NULL
                                     AND first_fact.process_line_id=second_fact.process_line_id))
                            AND first_fact.start_at < second_fact.end_at
                            AND second_fact.start_at < first_fact.end_at
                           WHERE (first_fact.capacity_mode='exclusive'
                                  OR second_fact.capacity_mode='exclusive')
                             AND (first_fact.order_id=o.id OR second_fact.order_id=o.id)
                       ),0) AS conflict_count
                FROM orders o
                JOIN order_process_schedules s ON s.order_id=o.id
                WHERE o.deleted_at IS NULL
                GROUP BY o.id
                ORDER BY o.order_no DESC,o.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    @staticmethod
    def find_schedule_risk_input(order_id, db=None):
        """Return the precise delivery-risk input for one live order."""
        db = resolve_db(db)
        try:
            return db.execute(
                """
                SELECT o.id AS order_id, o.order_no, o.deadline, o.plan_end,
                       o.status AS order_status, o.quantity, o.completed,
                       COALESCE(MAX(CASE WHEN s.status != 'blocked'
                                         THEN NULLIF(s.planned_end_at,'') END), '')
                           AS projected_completion_at,
                       COALESCE(SUM(CASE WHEN s.status='blocked' THEN 1 ELSE 0 END),0)
                           AS blocked_count,
                       COALESCE(GROUP_CONCAT(CASE WHEN s.status='blocked'
                                                  THEN NULLIF(s.blocked_reason,'') END, '；'),'')
                           AS blocked_reasons,
                       COALESCE((
                           SELECT COUNT(DISTINCT CASE
                               WHEN first_fact.order_id=o.id THEN first_fact.fact_key
                               ELSE second_fact.fact_key
                           END)
                           FROM schedule_effective_capacity_intervals first_fact
                           JOIN schedule_effective_capacity_intervals second_fact
                             ON first_fact.fact_key < second_fact.fact_key
                            AND ((first_fact.production_node_id IS NOT NULL
                                  AND first_fact.production_node_id=second_fact.production_node_id)
                                 OR (first_fact.production_node_id IS NULL
                                     AND second_fact.production_node_id IS NULL
                                     AND first_fact.process_line_id=second_fact.process_line_id))
                            AND first_fact.start_at < second_fact.end_at
                            AND second_fact.start_at < first_fact.end_at
                           WHERE (first_fact.capacity_mode='exclusive'
                                  OR second_fact.capacity_mode='exclusive')
                             AND (first_fact.order_id=o.id OR second_fact.order_id=o.id)
                       ),0) AS conflict_count
                FROM orders o
                JOIN order_process_schedules s ON s.order_id=o.id
                WHERE o.id=? AND o.deleted_at IS NULL
                GROUP BY o.id
                """,
                (order_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            return None
