"""Persistence for schedule runs, immutable revisions and workflow state."""

import hashlib
import json
import sqlite3

from modules.repositories.context import resolve_db
from modules.domain.schedule_order_priority import ScheduleOrderPriorityPolicy


class ScheduleRevisionRepository:
    """Run ledgers, immutable revisions, revision items and publication workflow."""

    @staticmethod
    def find_shadow_run(shadow_run_key, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM production_node_shadow_runs WHERE shadow_run_key=?",
            (str(shadow_run_key or "").strip(),),
        ).fetchone()
    @staticmethod
    def create_shadow_run(
        shadow_run_key, order_id, requested_start_date, request_digest, result,
        operations, created_by, db=None, *, status="completed", error_message="",
    ):
        """Persist one immutable shadow result and its normalized facts."""
        db = resolve_db(db)
        encoded_result = json.dumps(
            result if result is not None else {}, ensure_ascii=False,
            sort_keys=True, separators=(",", ":"),
        )
        result_digest = hashlib.sha256(encoded_result.encode("utf-8")).hexdigest()
        cursor = db.execute(
            "INSERT INTO production_node_shadow_runs "
            "(shadow_run_key,order_id,requested_start_date,status,request_digest,"
            "result_digest,result_json,error_message,created_by) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                str(shadow_run_key or "").strip(), int(order_id),
                str(requested_start_date or ""), status, request_digest,
                result_digest, encoded_result, error_message or "", int(created_by),
            ),
        )
        run_id = cursor.lastrowid
        for operation in operations or ():
            payload_json = json.dumps(
                operation, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            payload_digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
            item_cursor = db.execute(
                "INSERT INTO production_node_shadow_items "
                "(shadow_run_id,order_process_id,process_id,route_version_id,"
                "process_version_id,standard_id,production_node_id,seq_order,quantity,"
                "status,blocked_code,blocked_reason,planned_start_at,planned_end_at,"
                "occupied_minutes,payload_json,payload_digest) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id, operation["order_process_id"], operation["process_id"],
                    operation.get("route_version_id"), operation.get("process_version_id"),
                    operation.get("standard_id"), operation.get("production_node_id"),
                    int(operation.get("seq_order") or 0), int(operation.get("quantity") or 0),
                    operation.get("status") or "blocked", operation.get("blocked_code") or "",
                    operation.get("blocked_reason") or "",
                    operation.get("planned_start_at") or "",
                    operation.get("planned_end_at") or "",
                    float(operation.get("occupied_minutes") or 0), payload_json, payload_digest,
                ),
            )
            item_id = item_cursor.lastrowid
            for segment in operation.get("segments") or ():
                db.execute(
                    "INSERT INTO production_node_shadow_segments "
                    "(shadow_item_id,production_node_id,segment_start_at,segment_end_at,"
                    "occupied_minutes,quantity,shift_id) VALUES (?,?,?,?,?,?,?)",
                    (
                        item_id, segment["production_node_id"], segment["start_at"],
                        segment["end_at"], float(segment.get("occupied_minutes") or 0),
                        int(segment.get("quantity") or 0), segment.get("shift_id"),
                    ),
                )
            for allocation in operation.get("allocations") or ():
                db.execute(
                    "INSERT INTO production_node_shadow_allocations "
                    "(shadow_item_id,production_node_id,quantity,serial_id,batch_key,"
                    "changeover_minutes,allocation_start_at,allocation_end_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (
                        item_id, allocation["production_node_id"],
                        int(allocation.get("quantity") or 0), allocation.get("serial_id"),
                        allocation.get("batch_key") or "",
                        float(allocation.get("changeover_minutes") or 0),
                        allocation.get("segment_start_at") or "",
                        allocation.get("segment_end_at") or "",
                    ),
                )
        return run_id, result_digest
    @staticmethod
    def get_shadow_run(run_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT r.*,u.name AS created_by_name FROM production_node_shadow_runs r "
            "LEFT JOIN users u ON u.id=r.created_by WHERE r.id=?",
            (int(run_id),),
        ).fetchone()
    @staticmethod
    def list_shadow_runs(order_id, limit=100, db=None):
        db = resolve_db(db)
        bounded = min(max(int(limit or 100), 1), 1000)
        return db.execute(
            "SELECT r.*,u.name AS created_by_name FROM production_node_shadow_runs r "
            "LEFT JOIN users u ON u.id=r.created_by WHERE r.order_id=? "
            "ORDER BY r.id DESC LIMIT ?",
            (int(order_id), bounded),
        ).fetchall()
    @staticmethod
    def shadow_run_result(run):
        if run is None:
            return {}
        try:
            result = json.loads(run["result_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            return {}
        return result if isinstance(result, dict) else {}
    @staticmethod
    def update_order_summary(order_id, start_date, end_date, db):
        db.execute(
            "UPDATE orders SET plan_start=?, plan_end=?, "
            "schedule_version=COALESCE(schedule_version,1)+1, "
            "updated_at=datetime('now','localtime') WHERE id=?",
            (start_date, end_date, order_id),
        )
    @staticmethod
    def clear_schedule_replan_flag(order_id, db):
        """Clear the pending replan marker only after a successful plan."""
        db.execute(
            "UPDATE orders SET schedule_replan_required=0,schedule_replan_reason='',"
            "updated_at=datetime('now','localtime') WHERE id=? AND deleted_at IS NULL",
            (order_id,),
        )
    @staticmethod
    def clear_order_schedules(order_id, db):
        """Clear only an unpublished compatibility projection.

        Once an order has a published current revision, its materialized rows
        are the formal execution projection and must survive draft generation.
        """
        current = db.execute(
            "SELECT current_schedule_revision_id FROM orders WHERE id=?",
            (int(order_id),),
        ).fetchone()
        current_id = current["current_schedule_revision_id"] if current else None
        if current_id is None:
            db.execute(
                "DELETE FROM order_process_schedules WHERE order_id=?",
                (int(order_id),),
            )
            return
        # Older releases could leave a draft compatibility projection beside
        # an unchanged published pointer. Preserve that evidence during draft
        # generation; the controlled publish transaction will rebuild the
        # projection from the approved immutable revision.
        return
    @staticmethod
    def create_revision(order_id, schedule_run_id, source_run_key, db, created_by=None,
                        *, replan_reason="", replan_source_digest="", replanned_at=""):
        row = db.execute(
            "SELECT COALESCE(MAX(revision_no),0)+1 AS next_revision FROM schedule_revisions WHERE order_id=?",
            (order_id,),
        ).fetchone()
        revision_no = int(row["next_revision"] if row else 1)
        order = db.execute(
            "SELECT priority_level,is_expedited,previous_priority_level,"
            "previous_is_expedited,priority_effective_at,priority_version,schedule_policy "
            "FROM orders WHERE id=? AND deleted_at IS NULL",
            (order_id,),
        ).fetchone()
        if order is None:
            raise ValueError("订单不存在")
        intent = ScheduleOrderPriorityPolicy.effective_intent(dict(order))
        cur = db.execute(
            "INSERT INTO schedule_revisions "
            "(order_id,schedule_run_id,revision_no,status,source_run_key,created_by,replan_reason,replan_source_digest,replanned_at,"
            "priority_level_snapshot,is_expedited_snapshot,priority_version_snapshot,priority_effective_at_snapshot,schedule_policy_snapshot) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (order_id, schedule_run_id, revision_no, "draft", source_run_key or "", created_by,
             replan_reason or "", replan_source_digest or "", replanned_at or "",
             intent["priority_level"], int(intent["is_expedited"]),
             int(order["priority_version"] or 1), order["priority_effective_at"] or "",
             order["schedule_policy"] or "auto"),
        )
        return cur.lastrowid
    @staticmethod
    def compute_revision_content_digest(revision_id, db=None):
        """Return the canonical digest for the immutable revision item set."""
        db = resolve_db(db)
        items = [
            {
                "order_process_id": int(row["order_process_id"]),
                "process_id": int(row["process_id"]),
                "seq_order": int(row["seq_order"] or 0),
                "payload_digest": row["payload_digest"] or "",
            }
            for row in db.execute(
                "SELECT order_process_id,process_id,seq_order,payload_digest "
                "FROM schedule_revision_items WHERE revision_id=? "
                "ORDER BY seq_order,order_process_id,id",
                (int(revision_id),),
            ).fetchall()
        ]
        encoded = json.dumps(
            items, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    @staticmethod
    def finalize_revision_content_digest(revision_id, db=None):
        db = resolve_db(db)
        digest = ScheduleRevisionRepository.compute_revision_content_digest(
            revision_id, db=db
        )
        cursor = db.execute(
            "UPDATE schedule_revisions SET content_digest=? "
            "WHERE id=? AND status='draft' AND approval_status IN ('draft','rejected')",
            (digest, int(revision_id)),
        )
        if cursor.rowcount != 1:
            raise ValueError("排程版本内容摘要已冻结")
        return digest
    @staticmethod
    def assert_revision_integrity(revision_id, db=None):
        """Verify item payloads, order ownership and the frozen content digest."""
        db = resolve_db(db)
        revision = db.execute(
            "SELECT id,order_id,content_digest FROM schedule_revisions WHERE id=?",
            (int(revision_id),),
        ).fetchone()
        if revision is None:
            raise ValueError("排程版本不存在")
        items = db.execute(
            "SELECT * FROM schedule_revision_items WHERE revision_id=? "
            "ORDER BY seq_order,order_process_id,id",
            (int(revision_id),),
        ).fetchall()
        if not items:
            raise ValueError("排程版本没有不可变条目，不能进入审批或发布")

        expected = {
            int(row["id"]): dict(row)
            for row in db.execute(
                "SELECT id,order_id,process_id,process_version_id FROM order_processes "
                "WHERE order_id=?",
                (revision["order_id"],),
            ).fetchall()
        }
        actual_ids = [int(item["order_process_id"]) for item in items]
        if len(actual_ids) != len(expected) or set(actual_ids) != set(expected):
            raise ValueError("排程版本条目与订单工序集合不一致")

        order = db.execute(
            "SELECT route_version_id FROM orders WHERE id=? AND deleted_at IS NULL",
            (revision["order_id"],),
        ).fetchone()
        if order is None:
            raise ValueError("排程版本所属订单不存在或已删除")
        for item in items:
            payload_json = item["payload_json"] or "{}"
            actual_payload_digest = hashlib.sha256(
                payload_json.encode("utf-8")
            ).hexdigest()
            if actual_payload_digest != (item["payload_digest"] or ""):
                raise ValueError(
                    f"排程版本条目 {item['id']} 内容摘要不一致"
                )
            operation = expected[int(item["order_process_id"])]
            if int(item["process_id"]) != int(operation["process_id"]):
                raise ValueError("排程版本条目的订单工序归属不一致")
            try:
                payload = json.loads(payload_json)
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"排程版本条目 {item['id']} 内容不是有效 JSON"
                ) from exc
            if not isinstance(payload, dict):
                raise ValueError(f"排程版本条目 {item['id']} 内容格式不正确")
            identity_checks = {
                "order_id": revision["order_id"],
                "order_process_id": item["order_process_id"],
                "process_id": item["process_id"],
                "route_version_id": order["route_version_id"],
                "process_version_id": operation["process_version_id"],
            }
            for field, expected_value in identity_checks.items():
                if payload.get(field) != expected_value:
                    raise ValueError(
                        f"排程版本条目 {item['id']} 的 {field} 快照不一致"
                    )

        computed = ScheduleRevisionRepository.compute_revision_content_digest(
            revision_id, db=db
        )
        if not revision["content_digest"] or revision["content_digest"] != computed:
            raise ValueError("排程版本内容摘要不一致，禁止审批或发布")
        return computed
    @staticmethod
    def publish_revision(revision_id, db, published_by, reason, idempotency_key):
        revision = db.execute(
            "SELECT id,order_id,status,approval_status FROM schedule_revisions WHERE id=?", (revision_id,)
        ).fetchone()
        if revision is None:
            raise ValueError("排程版本不存在")
        if revision["status"] != "draft":
            raise ValueError("排程版本当前状态不可发布")
        if revision["approval_status"] != "approved":
            raise ValueError("排程版本必须先经独立审批后才能发布")
        current = db.execute(
            "SELECT current_schedule_revision_id FROM orders WHERE id=?",
            (revision["order_id"],),
        ).fetchone()
        current_id = current["current_schedule_revision_id"] if current else None
        ScheduleRevisionRepository.materialize_revision_projection(
            revision_id, db=db
        )
        if current_id and current_id != revision_id:
            db.execute(
                "UPDATE schedule_revisions SET status='superseded',superseded_by=?,"
                "superseded_at=datetime('now','localtime') WHERE id=? AND status='published'",
                (revision_id, current_id),
            )
        db.execute(
            "UPDATE schedule_revisions SET status='published',published_by=?,"
            "published_at=datetime('now','localtime'),publication_reason=?,"
            "publication_idempotency_key=? WHERE id=?",
            (published_by, reason, idempotency_key, revision_id),
        )
        db.execute(
            "UPDATE orders SET current_schedule_revision_id=? WHERE id=?",
            (revision_id, revision["order_id"]),
        )
        projected = db.execute(
            "SELECT MIN(NULLIF(plan_start,'')) AS plan_start,"
            "MAX(NULLIF(plan_end,'')) AS plan_end "
            "FROM order_process_schedules WHERE order_id=? AND status<>'blocked'",
            (revision["order_id"],),
        ).fetchone()
        if projected and projected["plan_start"] and projected["plan_end"]:
            db.execute(
                "UPDATE orders SET plan_start=?,plan_end=?,"
                "schedule_version=COALESCE(schedule_version,1)+1,"
                "schedule_replan_required=0,schedule_replan_reason='',"
                "updated_at=datetime('now','localtime') WHERE id=?",
                (
                    projected["plan_start"],
                    projected["plan_end"],
                    revision["order_id"],
                ),
            )
    @staticmethod
    def materialize_revision_projection(revision_id, db=None):
        """Atomically rebuild the mutable execution projection from a revision."""
        db = resolve_db(db)
        revision = db.execute(
            "SELECT id,order_id FROM schedule_revisions WHERE id=?",
            (int(revision_id),),
        ).fetchone()
        if revision is None:
            raise ValueError("排程版本不存在")
        items = db.execute(
            "SELECT * FROM schedule_revision_items WHERE revision_id=? "
            "ORDER BY seq_order,id",
            (int(revision_id),),
        ).fetchall()
        if not items:
            raise ValueError("排程版本没有可发布条目")
        db.execute(
            "DELETE FROM order_process_schedules WHERE order_id=?",
            (revision["order_id"],),
        )
        for item in items:
            try:
                payload = json.loads(item["payload_json"] or "{}")
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError("排程版本条目内容不是有效 JSON") from exc
            if not isinstance(payload, dict):
                raise ValueError("排程版本条目内容格式不正确")
            payload = dict(payload)
            payload.pop("id", None)
            payload.pop("created_at", None)
            payload.pop("updated_at", None)
            payload["order_id"] = revision["order_id"]
            payload["order_process_id"] = item["order_process_id"]
            payload["process_id"] = item["process_id"]
            payload["schedule_revision_id"] = int(revision_id)
            payload["segments"] = [
                {
                    **segment,
                    "start_at": segment.get("start_at")
                    or segment.get("segment_start_at")
                    or "",
                    "end_at": segment.get("end_at")
                    or segment.get("segment_end_at")
                    or "",
                }
                for segment in (payload.get("segments") or [])
            ]
            payload["allocations"] = [
                {
                    **allocation,
                    "segment_start_at": allocation.get("segment_start_at")
                    or allocation.get("allocation_start_at")
                    or "",
                    "segment_end_at": allocation.get("segment_end_at")
                    or allocation.get("allocation_end_at")
                    or "",
                }
                for allocation in (payload.get("allocations") or [])
            ]
            ScheduleRevisionRepository.insert_operation_schedule(
                payload,
                db,
                force_projection=True,
                snapshot_revision=False,
            )
    @staticmethod
    def find_revision_item(revision_item_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT i.*,r.order_id,r.status AS revision_status,r.approval_status,"
            "r.created_by,r.revision_no FROM schedule_revision_items i "
            "JOIN schedule_revisions r ON r.id=i.revision_id WHERE i.id=?",
            (revision_item_id,),
        ).fetchone()
    @staticmethod
    def find_revision_order(revision_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT r.id AS revision_id,r.order_id,r.status AS revision_status,"
            "r.approval_status,o.order_no,o.deadline,o.plan_end,o.status AS order_status,"
            "o.quantity,o.completed,o.current_schedule_revision_id "
            "FROM schedule_revisions r JOIN orders o ON o.id=r.order_id "
            "WHERE r.id=? AND o.deleted_at IS NULL",
            (int(revision_id),),
        ).fetchone()
    @staticmethod
    def find_active_task_lock(revision_item_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM schedule_node_task_locks WHERE revision_item_id=? AND status='active'",
            (revision_item_id,),
        ).fetchone()
    @staticmethod
    def list_active_order_task_locks(order_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT l.*,i.order_process_id,i.revision_id,i.process_id,i.process_line_id,"
            "i.production_node_id AS item_production_node_id,i.seq_order,i.quantity,"
            "i.status AS item_status,i.planned_start_at,i.planned_end_at,"
            "i.occupied_minutes,i.payload_json,i.payload_digest,r.revision_no "
            "FROM schedule_node_task_locks l "
            "JOIN schedule_revision_items i ON i.id=l.revision_item_id "
            "JOIN schedule_revisions r ON r.id=i.revision_id "
            "WHERE r.order_id=? AND r.status IN ('draft','published') "
            "AND l.status='active' ORDER BY r.revision_no DESC,l.id DESC",
            (order_id,),
        ).fetchall()
    @staticmethod
    def find_revision_item_by_source_schedule(revision_id, source_schedule_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM schedule_revision_items "
            "WHERE revision_id=? AND source_schedule_id=? ORDER BY id DESC LIMIT 1",
            (revision_id, source_schedule_id),
        ).fetchone()
    @staticmethod
    def find_workflow_event(idempotency_key, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM schedule_node_workflow_events WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
    @staticmethod
    def create_workflow_event(*, revision_id, revision_item_id=None, event_type, actor_id,
                              reason, before_json, after_json, input_digest, idempotency_key, db):
        cursor = db.execute(
            "INSERT INTO schedule_node_workflow_events "
            "(revision_id,revision_item_id,event_type,actor_id,reason,before_json,after_json,input_digest,idempotency_key) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (revision_id, revision_item_id, event_type, actor_id, reason or '',
             before_json, after_json, input_digest, idempotency_key),
        )
        return db.execute(
            "SELECT * FROM schedule_node_workflow_events WHERE id=?", (cursor.lastrowid,)
        ).fetchone()
    @staticmethod
    def create_task_lock(revision_item_id, production_node_id, actor_id, reason, db):
        cursor = db.execute(
            "INSERT INTO schedule_node_task_locks "
            "(revision_item_id,production_node_id,locked_by,reason) VALUES (?,?,?,?)",
            (revision_item_id, production_node_id, actor_id, reason),
        )
        return db.execute(
            "SELECT * FROM schedule_node_task_locks WHERE id=?", (cursor.lastrowid,)
        ).fetchone()
    @staticmethod
    def release_task_lock(revision_item_id, actor_id, reason, db):
        cursor = db.execute(
            "UPDATE schedule_node_task_locks SET status='released',released_by=?,"
            "released_at=datetime('now','localtime'),release_reason=? "
            "WHERE revision_item_id=? AND status='active'",
            (actor_id, reason, revision_item_id),
        )
        return cursor.rowcount
    @staticmethod
    def transition_revision(revision_id, expected_status, new_status, actor_id, reason, db):
        field_prefix = {
            "submitted": "submitted",
            "approved": "approved",
            "rejected": "rejected",
        }[new_status]
        cursor = db.execute(
            f"UPDATE schedule_revisions SET approval_status=?,{field_prefix}_by=?,"
            f"{field_prefix}_at=datetime('now','localtime'),{field_prefix}_reason=? "
            "WHERE id=? AND approval_status=? AND status='draft'",
            (new_status, actor_id, reason, revision_id, expected_status),
        )
        return cursor.rowcount
    @staticmethod
    def clone_revision_with_override(revision_id, override_item_id=None, overrides=None,
                                     created_by=None, reason='', db=None):
        db = resolve_db(db)
        source = db.execute(
            "SELECT * FROM schedule_revisions WHERE id=?", (revision_id,)
        ).fetchone()
        if source is None:
            raise ValueError("排程版本不存在")
        next_no = db.execute(
            "SELECT COALESCE(MAX(revision_no),0)+1 FROM schedule_revisions WHERE order_id=?",
            (source['order_id'],),
        ).fetchone()[0]
        rev_columns = [r[1] for r in db.execute("PRAGMA table_info(schedule_revisions)").fetchall()]
        excluded = {'id','created_at','published_at','superseded_at','submitted_at','approved_at','rejected_at'}
        values = {c: source[c] for c in rev_columns if c not in excluded}
        values.update({
            'revision_no': next_no, 'status': 'draft', 'approval_status': 'draft',
            'created_by': created_by, 'published_by': None, 'superseded_by': None,
            'source_run_key': f"manual:{revision_id}:{next_no}",
            'result_digest': '', 'submitted_by': None, 'submitted_reason': '',
            'approved_by': None, 'approved_reason': '', 'rejected_by': None,
            'rejected_reason': '',
            'replan_reason': (
                reason or source['replan_reason']
                if 'replan_reason' in rev_columns else reason or ''
            ),
        })
        if 'content_digest' in rev_columns:
            values['content_digest'] = ''
        if 'publication_reason' in rev_columns:
            values['publication_reason'] = ''
        if 'publication_idempotency_key' in rev_columns:
            values['publication_idempotency_key'] = ''
        for timestamp_column in ('submitted_at', 'approved_at', 'rejected_at'):
            if timestamp_column in rev_columns:
                values[timestamp_column] = ''
        for risk_column, empty_value in {
            'deadline_snapshot': '',
            'projected_completion_at_snapshot': '',
            'risk_level': 'unassessed',
            'delay_minutes': 0,
            'risk_reason': '',
            'risk_assessed_at': '',
        }.items():
            if risk_column in rev_columns:
                values[risk_column] = empty_value
        cols = list(values)
        cur = db.execute(
            f"INSERT INTO schedule_revisions ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
            [values[c] for c in cols],
        )
        new_revision_id = cur.lastrowid
        item_columns = [r[1] for r in db.execute("PRAGMA table_info(schedule_revision_items)").fetchall()]
        item_id_map = {}
        source_items = db.execute(
            "SELECT * FROM schedule_revision_items WHERE revision_id=? ORDER BY seq_order,id",
            (revision_id,),
        ).fetchall()
        for item in source_items:
            item_values = {c: item[c] for c in item_columns if c not in {'id','revision_id','created_at'}}
            if 'row_version' in item_values:
                item_values['row_version'] = 1
            if item['id'] == override_item_id:
                item_values.update(overrides or {})
            item_values['revision_id'] = new_revision_id
            cols = list(item_values)
            item_cursor = db.execute(
                f"INSERT INTO schedule_revision_items ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
                [item_values[c] for c in cols],
            )
            item_id_map[item['id']] = item_cursor.lastrowid
        for source_item_id, target_item_id in item_id_map.items():
            lock = db.execute(
                "SELECT production_node_id,locked_by,reason FROM schedule_node_task_locks "
                "WHERE revision_item_id=? AND status='active'",
                (source_item_id,),
            ).fetchone()
            if lock:
                db.execute(
                    "INSERT INTO schedule_node_task_locks "
                    "(revision_item_id,production_node_id,locked_by,reason) VALUES (?,?,?,?)",
                    (target_item_id, lock['production_node_id'], lock['locked_by'], lock['reason']),
                )
        if 'content_digest' in rev_columns:
            ScheduleRevisionRepository.finalize_revision_content_digest(
                new_revision_id, db=db
            )
        return new_revision_id, item_id_map
    @staticmethod
    def list_revisions(order_id, db=None, limit=100):
        db = resolve_db(db)
        limit = min(max(int(limit or 100), 1), 1000)
        return db.execute(
            "SELECT * FROM schedule_revisions WHERE order_id=? ORDER BY revision_no DESC LIMIT ?",
            (order_id, limit),
        ).fetchall()
    @staticmethod
    def list_revision_items(revision_id, db=None, limit=1000):
        db = resolve_db(db)
        limit = min(max(int(limit or 1000), 1), 1000)
        return db.execute(
            "SELECT * FROM schedule_revision_items WHERE revision_id=? ORDER BY seq_order,id LIMIT ?",
            (revision_id, limit),
        ).fetchall()
    @staticmethod
    def list_latest_candidate_revision_items(limit=1000, db=None):
        db = resolve_db(db)
        limit = min(max(int(limit or 1000), 1), 1000)
        return db.execute(
            "SELECT i.*,r.order_id,r.status AS revision_status,"
            "r.approval_status AS revision_approval_status,r.revision_no,"
            "r.risk_level AS revision_risk_level,r.delay_minutes AS revision_delay_minutes,"
            "r.risk_reason AS revision_risk_reason,"
            "o.order_no,o.product_name,p.name AS process_name,"
            "CASE WHEN l.id IS NULL THEN 0 ELSE 1 END AS locked,"
            "l.id AS task_lock_id "
            "FROM schedule_revision_items i "
            "JOIN schedule_revisions r ON r.id=i.revision_id "
            "JOIN orders o ON o.id=r.order_id "
            "JOIN processes p ON p.id=i.process_id "
            "LEFT JOIN schedule_node_task_locks l "
            "ON l.revision_item_id=i.id AND l.status='active' "
            "WHERE r.status='draft' AND o.deleted_at IS NULL "
            "AND r.id=(SELECT candidate.id FROM schedule_revisions candidate "
            "WHERE candidate.order_id=r.order_id AND candidate.status='draft' "
            "ORDER BY candidate.revision_no DESC,candidate.id DESC LIMIT 1) "
            "AND COALESCE(o.current_schedule_revision_id,0)<>r.id "
            "ORDER BY r.order_id,i.seq_order,i.id LIMIT ?",
            (limit,),
        ).fetchall()
    @staticmethod
    def find_revision(revision_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT r.*,o.order_no,o.product_id,o.product_code,o.product_name "
            "FROM schedule_revisions r JOIN orders o ON o.id=r.order_id WHERE r.id=?",
            (revision_id,),
        ).fetchone()
    @staticmethod
    def revision_uses_production_nodes(revision_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT 1 FROM schedule_revision_items i "
            "LEFT JOIN order_process_schedules s ON s.id=i.source_schedule_id "
            "WHERE i.revision_id=? AND COALESCE(i.production_node_id,s.production_node_id) IS NOT NULL "
            "LIMIT 1",
            (int(revision_id),),
        ).fetchone()
        return row is not None
    @staticmethod
    def find_revision_by_run(schedule_run_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM schedule_revisions WHERE schedule_run_id=? ORDER BY id DESC LIMIT 1",
            (schedule_run_id,),
        ).fetchone()
    @staticmethod
    def find_run(schedule_run_key, db=None):
        db = resolve_db(db)
        return db.execute("SELECT * FROM schedule_runs WHERE schedule_run_key=?", (schedule_run_key,)).fetchone()
    @staticmethod
    def find_auto_plan_run(auto_plan_key, db=None):
        """Return the immutable automatic-plan attempt for an idempotency key."""
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM schedule_auto_plan_runs WHERE auto_plan_key=?",
            (str(auto_plan_key or "").strip(),),
        ).fetchone()
    @staticmethod
    def create_auto_plan_run(
        auto_plan_key, requested_start_date, input_digest, input_json,
        created_by=None, db=None,
    ):
        """Create an automatic-plan ledger row without overwriting history."""
        db = resolve_db(db)
        if isinstance(input_json, str):
            encoded_input = input_json
        else:
            encoded_input = json.dumps(
                input_json or {}, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            )
        cur = db.execute(
            "INSERT INTO schedule_auto_plan_runs "
            "(auto_plan_key,requested_start_date,status,input_digest,input_json,created_by) "
            "VALUES (?,?,?,?,?,?)",
            (
                str(auto_plan_key or "").strip(),
                str(requested_start_date or ""),
                "started",
                str(input_digest or ""),
                encoded_input,
                created_by,
            ),
        )
        return cur.lastrowid
    @staticmethod
    def complete_auto_plan_run(
        run_id, status, result, error_message="", db=None,
    ):
        """Freeze the result of an automatic-plan attempt with a digest."""
        db = resolve_db(db)
        if isinstance(result, str):
            encoded_result = result
        else:
            encoded_result = json.dumps(
                result if result is not None else {}, ensure_ascii=False,
                sort_keys=True, separators=(",", ":"),
            )
        digest = hashlib.sha256(encoded_result.encode("utf-8")).hexdigest()
        db.execute(
            "UPDATE schedule_auto_plan_runs SET status=?,result_json=?,"
            "result_digest=?,error_message=?,completed_at=datetime('now','localtime') "
            "WHERE id=?",
            (status, encoded_result, digest, error_message or "", run_id),
        )
        return digest
    @staticmethod
    def auto_plan_result(run):
        """Decode a stored automatic-plan result without trusting its shape."""
        if run is None:
            return {}
        try:
            result = json.loads(run["result_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            return {}
        return result if isinstance(result, dict) else {}
    @staticmethod
    def create_run(order_id, schedule_run_key, start_date, db, *, run_type="generate",
                   trigger_source="", input_digest="", replan_reason=""):
        cur = db.execute(
            "INSERT INTO schedule_runs "
            "(schedule_run_key,order_id,status,requested_start_date,run_type,trigger_source,input_digest,replan_reason) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (schedule_run_key, order_id, "started", start_date or "", run_type or "generate",
             trigger_source or "", input_digest or "", replan_reason or ""),
        )
        return cur.lastrowid
    @staticmethod
    def update_run_input(run_id, *, input_digest="", trigger_source="", replan_reason="", db=None):
        db = resolve_db(db)
        db.execute(
            "UPDATE schedule_runs SET input_digest=?,trigger_source=?,replan_reason=? WHERE id=?",
            (input_digest or "", trigger_source or "", replan_reason or "", run_id),
        )
    @staticmethod
    def complete_run(run_id, status, result, error_message="", db=None):
        db = resolve_db(db)
        payload = json.dumps(result or [], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        db.execute(
            "UPDATE schedule_runs SET status=?,result_json=?,result_digest=?,error_message=?,"
            "completed_at=datetime('now','localtime') WHERE id=?",
            (status, payload, digest, error_message or "", run_id),
        )
    @staticmethod
    def set_revision_digest(revision_id, digest, db):
        db.execute(
            "UPDATE schedule_revisions SET result_digest=? WHERE id=?",
            (digest, revision_id),
        )
    @staticmethod
    def cancel_revision(revision_id, db):
        db.execute(
            "UPDATE schedule_revisions SET status='cancelled' WHERE id=?",
            (revision_id,),
        )
    @staticmethod
    def run_result(run):
        try:
            result = json.loads(run["result_json"] or "[]")
        except (TypeError, json.JSONDecodeError):
            result = []
        return result if isinstance(result, list) else []
    @staticmethod
    def insert_operation_schedule(
        data, db, *, force_projection=False, snapshot_revision=True
    ):
        binding = db.execute(
            "SELECT o.route_id,o.route_version_id,o.current_schedule_revision_id,"
            "op.process_id,op.process_version_id "
            "FROM orders o JOIN order_processes op ON op.order_id=o.id AND op.id=? "
            "WHERE o.id=? AND o.deleted_at IS NULL",
            (data["order_process_id"], data["order_id"]),
        ).fetchone()
        if binding is None or binding["process_id"] != data["process_id"]:
            raise ValueError("订单、订单工序和工序归属关系不一致")
        if data.get("route_version_id") != binding["route_version_id"] or data.get("process_version_id") != binding["process_version_id"]:
            raise ValueError("订单—路线—工序版本绑定不一致")
        revision_id = data.get("schedule_revision_id")
        current_revision_id = binding["current_schedule_revision_id"]
        if (
            revision_id
            and current_revision_id
            and int(current_revision_id) != int(revision_id)
            and not force_projection
        ):
            ScheduleRevisionRepository.snapshot_revision_payload(
                data, int(revision_id), db
            )
            return None
        cur = db.execute(
            "INSERT INTO order_process_schedules (order_id,order_process_id,process_id,process_line_id,production_node_id,"
            "node_code_snapshot,node_name_snapshot,capacity_mode_snapshot,"
            "seq_order,quantity,standard_minutes_per_unit,setup_minutes,difficulty_factor,planned_minutes,plan_start,plan_end,"
            "status,blocked_reason,blocked_code,schedule_run_key,route_version_id,process_version_id,standard_id,standard_version,"
            "process_name_snapshot,route_name_snapshot,schedule_run_id,schedule_revision_id,planned_start_at,planned_end_at,occupied_minutes,"
            "capacity_snapshot_json,standard_match_scope,calendar_id,shift_snapshot_json,line_name_snapshot,execution_mode,"
            "completed_quantity_snapshot,rework_quantity_snapshot,remaining_quantity_snapshot,source_fact_digest) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (data["order_id"], data["order_process_id"], data["process_id"], data.get("process_line_id"),
             data.get("production_node_id"), data.get("node_code_snapshot", ""),
             data.get("node_name_snapshot", ""), data.get("capacity_mode_snapshot", ""),
             data.get("seq_order", 0), data.get("quantity", 0), data.get("standard_minutes_per_unit", 0),
             data.get("setup_minutes", 0), data.get("difficulty_factor", 1), data.get("planned_minutes", 0), data["plan_start"], data["plan_end"],
             data.get("status", "planned"), data.get("blocked_reason", ""), data.get("blocked_code", ""), data.get("schedule_run_key", ""),
             data.get("route_version_id"), data.get("process_version_id"), data.get("standard_id"), data.get("standard_version"),
            data.get("process_name_snapshot", ""), data.get("route_name_snapshot", ""), data.get("schedule_run_id"),
            data.get("schedule_revision_id"),
            data.get("planned_start_at", ""), data.get("planned_end_at", ""), data.get("occupied_minutes", 0),
             data.get("capacity_snapshot_json", "{}"), data.get("standard_match_scope", ""), data.get("calendar_id"),
             data.get("shift_snapshot_json", "[]"), data.get("line_name_snapshot", ""),
             data.get("execution_mode", "internal"),
             data.get("completed_quantity_snapshot", 0), data.get("rework_quantity_snapshot", 0),
             data.get("remaining_quantity_snapshot", data.get("quantity", 0)),
             data.get("source_fact_digest", "")),
        )
        segment_ids = []
        for segment in data.get("segments", ()):
            segment_cursor = db.execute(
                "INSERT INTO order_process_schedule_segments "
                "(schedule_id,process_line_id,production_node_id,segment_start_at,segment_end_at,occupied_minutes,shift_id,quantity) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (cur.lastrowid, segment.get("process_line_id", data.get("process_line_id")),
                 segment.get("production_node_id", data.get("production_node_id")),
                 segment["start_at"], segment["end_at"], segment["occupied_minutes"],
                 segment.get("shift_id"), segment.get("quantity", data.get("quantity", 0))),
            )
            segment_ids.append(segment_cursor.lastrowid)
        allocations = data.get("allocations", ())
        if allocations:
            try:
                for allocation in allocations:
                    node_id = allocation.get("production_node_id")
                    segment_id = None
                    for segment_id_candidate in segment_ids:
                        segment_row = db.execute(
                            "SELECT production_node_id,segment_start_at,segment_end_at "
                            "FROM order_process_schedule_segments WHERE id=?",
                            (segment_id_candidate,),
                        ).fetchone()
                        if not segment_row or segment_row["production_node_id"] != node_id:
                            continue
                        allocation_start = allocation.get("segment_start_at")
                        allocation_end = allocation.get("segment_end_at")
                        if not allocation_start or not allocation_end:
                            segment_id = segment_id_candidate
                            break
                        # One allocation may span multiple calendar segments;
                        # retain the first overlapping segment as its anchor.
                        if (
                            segment_row["segment_start_at"] < allocation_end
                            and segment_row["segment_end_at"] > allocation_start
                        ):
                            segment_id = segment_id_candidate
                            break
                    db.execute(
                        "INSERT INTO production_node_schedule_allocations "
                        "(schedule_id,segment_id,production_node_id,quantity,serial_id,batch_key,"
                        "changeover_minutes,allocation_start_at,allocation_end_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?)",
                        (cur.lastrowid, segment_id, node_id, int(allocation.get("quantity") or 0),
                         allocation.get("serial_id"), allocation.get("batch_key") or "",
                         float(allocation.get("changeover_minutes") or 0),
                         allocation.get("segment_start_at") or "", allocation.get("segment_end_at") or ""),
                    )
            except sqlite3.OperationalError:
                # V088 is additive; keep read-only V087 clones compatible.
                pass
        if data.get("schedule_revision_id") and snapshot_revision:
            ScheduleRevisionRepository.snapshot_revision_item(
                cur.lastrowid, data["schedule_revision_id"], db
            )
        return cur.lastrowid
    @staticmethod
    def snapshot_revision_payload(data, revision_id, db):
        """Persist a draft candidate without touching the formal projection."""
        payload = dict(data)
        payload.pop("id", None)
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        db.execute(
            "INSERT OR IGNORE INTO schedule_revision_items "
            "(revision_id,source_schedule_id,order_process_id,process_id,process_line_id,"
            "production_node_id,node_code_snapshot,node_name_snapshot,capacity_mode_snapshot,"
            "seq_order,quantity,status,planned_start_at,planned_end_at,occupied_minutes,"
            "payload_json,payload_digest,execution_mode,completed_quantity_snapshot,"
            "rework_quantity_snapshot,remaining_quantity_snapshot,source_fact_digest) "
            "VALUES (?,NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                int(revision_id),
                data["order_process_id"],
                data["process_id"],
                data.get("process_line_id"),
                data.get("production_node_id"),
                data.get("node_code_snapshot", ""),
                data.get("node_name_snapshot", ""),
                data.get("capacity_mode_snapshot", ""),
                data.get("seq_order", 0),
                data.get("quantity", 0),
                data.get("status", "planned"),
                data.get("planned_start_at", ""),
                data.get("planned_end_at", ""),
                data.get("occupied_minutes", 0),
                encoded,
                digest,
                data.get("execution_mode", "internal"),
                data.get("completed_quantity_snapshot", 0),
                data.get("rework_quantity_snapshot", 0),
                data.get("remaining_quantity_snapshot", data.get("quantity", 0)),
                data.get("source_fact_digest", ""),
            ),
        )
    @staticmethod
    def snapshot_revision_item(schedule_id, revision_id, db):
        row = db.execute(
            "SELECT * FROM order_process_schedules WHERE id=? AND schedule_revision_id=?",
            (schedule_id, revision_id),
        ).fetchone()
        if row is None:
            raise ValueError("排程事实与版本不一致")
        keys = set(row.keys())
        payload = dict(row)
        payload["segments"] = [
            dict(segment) for segment in db.execute(
                "SELECT * FROM order_process_schedule_segments WHERE schedule_id=? ORDER BY id",
                (schedule_id,),
            ).fetchall()
        ]
        try:
            payload["allocations"] = [
                dict(allocation) for allocation in db.execute(
                    "SELECT * FROM production_node_schedule_allocations "
                    "WHERE schedule_id=? ORDER BY id", (schedule_id,)
                ).fetchall()
            ]
        except sqlite3.OperationalError:
            payload["allocations"] = []
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        db.execute(
            "INSERT OR IGNORE INTO schedule_revision_items "
            "(revision_id,source_schedule_id,order_process_id,process_id,process_line_id,production_node_id,"
            "node_code_snapshot,node_name_snapshot,capacity_mode_snapshot,seq_order,quantity,status,"
            "planned_start_at,planned_end_at,occupied_minutes,payload_json,payload_digest,"
            "execution_mode,completed_quantity_snapshot,rework_quantity_snapshot,remaining_quantity_snapshot,source_fact_digest) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (revision_id, schedule_id, row["order_process_id"], row["process_id"], row["process_line_id"],
             row["production_node_id"] if "production_node_id" in keys else None,
             row["node_code_snapshot"] if "node_code_snapshot" in keys else "",
             row["node_name_snapshot"] if "node_name_snapshot" in keys else "",
             row["capacity_mode_snapshot"] if "capacity_mode_snapshot" in keys else "",
             row["seq_order"], row["quantity"], row["status"], row["planned_start_at"],
             row["planned_end_at"], row["occupied_minutes"], encoded, digest,
             row["execution_mode"] if "execution_mode" in keys else "internal",
             int(row["completed_quantity_snapshot"] or 0) if "completed_quantity_snapshot" in keys else 0,
             int(row["rework_quantity_snapshot"] or 0) if "rework_quantity_snapshot" in keys else 0,
             int(row["remaining_quantity_snapshot"] or row["quantity"] or 0) if "remaining_quantity_snapshot" in keys else int(row["quantity"] or 0),
             row["source_fact_digest"] if "source_fact_digest" in keys else ""),
        )
