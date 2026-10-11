"""排程版本人工操作与审批发布工作流。

该服务只负责排程版本的人工变更、状态转换、幂等和审计。
容量分配、自动排程和动态重排仍由 :mod:`schedule_capacity_service` 负责。
通过运行时依赖注入调用容量服务中的通用事务、时间和冲突策略，避免模块循环依赖，
并保持历史 API 的行为兼容。
"""

import hashlib
import json

from modules import config
from modules.domain.errors import ProductionNodeWriteDisabledError
from modules.domain.production_node_scheduling import NodeSchedulingError, ProductionNodePolicy
from modules.repositories.production_node_repository import ProductionNodeRepository
from modules.repositories.schedule_planning_repository import SchedulePlanningRepository
from modules.repositories.schedule_revision_repository import ScheduleRevisionRepository
from modules.services.schedule_planning_strategy import SchedulePlanningStrategy
from modules.services.schedule_workflow_evidence import ScheduleWorkflowEvidence


class ScheduleRevisionService:
    """锁定、调整、审批和发布排程版本的应用服务。"""

    @staticmethod
    def _assert_node_write_enabled():
        if not getattr(config, "PRODUCTION_NODE_WRITE_ENABLED", False):
            raise ProductionNodeWriteDisabledError("生产节点写入尚未启用")

    @staticmethod
    def _workflow_input(reason, idempotency_key, actor_id):
        return ScheduleWorkflowEvidence.normalize_input(
            reason, idempotency_key, actor_id
        )

    @staticmethod
    def _workflow_digest(payload):
        return ScheduleWorkflowEvidence.digest(payload)

    @staticmethod
    def _workflow_replay(db, key, digest):
        return ScheduleWorkflowEvidence.replay(db, key, digest)

    @staticmethod
    def _record_workflow_event(
        db, *, revision_id, revision_item_id, event_type, actor_id,
        reason, before, after, digest, key,
    ):
        return ScheduleWorkflowEvidence.record(
            db,
            revision_id=revision_id,
            revision_item_id=revision_item_id,
            event_type=event_type,
            actor_id=actor_id,
            reason=reason,
            before=before,
            after=after,
            digest=digest,
            idempotency_key=key,
        )

    @classmethod
    def lock_schedule_item(
        cls, revision_item_id, reason, idempotency_key, actor_id, db=None,
        *, capacity_service,
    ):
        cls._assert_node_write_enabled()
        reason, key, actor = cls._workflow_input(reason, idempotency_key, actor_id)
        payload = {
            "action": "lock", "revision_item_id": int(revision_item_id),
            "reason": reason, "actor_id": actor,
        }
        digest = cls._workflow_digest(payload)
        with SchedulePlanningStrategy.transaction(db) as txn:
            replay = cls._workflow_replay(txn, key, digest)
            if replay:
                return replay
            item = ScheduleRevisionRepository.find_revision_item(revision_item_id, db=txn)
            if item is None:
                raise ValueError("排程条目不存在")
            if item["revision_status"] in ("superseded", "cancelled"):
                raise NodeSchedulingError("REVISION_STATE_CONFLICT", "当前排程版本不可锁定")
            if item["production_node_id"] is None or item["status"] != "planned":
                raise NodeSchedulingError(
                    "NO_COMPATIBLE_NODE", "只有已分配内部生产节点的排程任务可锁定"
                )
            if ScheduleRevisionRepository.find_active_task_lock(revision_item_id, db=txn):
                raise NodeSchedulingError("LOCKED_TASK_CONFLICT", "排程条目已锁定")
            lock = ScheduleRevisionRepository.create_task_lock(
                revision_item_id, item["production_node_id"], actor, reason, txn
            )
            return cls._record_workflow_event(
                txn, revision_id=item["revision_id"], revision_item_id=revision_item_id,
                event_type="lock", actor_id=actor, reason=reason, before={},
                after={"lock": dict(lock)}, digest=digest, key=key,
            )

    @classmethod
    def unlock_schedule_item(
        cls, revision_item_id, reason, idempotency_key, actor_id, db=None,
        *, capacity_service,
    ):
        cls._assert_node_write_enabled()
        reason, key, actor = cls._workflow_input(reason, idempotency_key, actor_id)
        payload = {
            "action": "unlock", "revision_item_id": int(revision_item_id),
            "reason": reason, "actor_id": actor,
        }
        digest = cls._workflow_digest(payload)
        with SchedulePlanningStrategy.transaction(db) as txn:
            replay = cls._workflow_replay(txn, key, digest)
            if replay:
                return replay
            item = ScheduleRevisionRepository.find_revision_item(revision_item_id, db=txn)
            if item is None:
                raise ValueError("排程条目不存在")
            active_lock = ScheduleRevisionRepository.find_active_task_lock(
                revision_item_id, db=txn
            )
            if active_lock is None:
                raise NodeSchedulingError("LOCKED_TASK_CONFLICT", "排程条目当前未锁定")
            ScheduleRevisionRepository.release_task_lock(
                revision_item_id, actor, reason, txn
            )
            return cls._record_workflow_event(
                txn, revision_id=item["revision_id"], revision_item_id=revision_item_id,
                event_type="unlock", actor_id=actor, reason=reason,
                before={"lock": dict(active_lock)}, after={"status": "released"},
                digest=digest, key=key,
            )

    @classmethod
    def adjust_schedule_item(
        cls, revision_item_id, production_node_id, planned_start_at,
        reason, row_version, idempotency_key, actor_id, db=None,
        *, capacity_service,
    ):
        cls._assert_node_write_enabled()
        reason, key, actor = cls._workflow_input(reason, idempotency_key, actor_id)
        try:
            revision_item_id = int(revision_item_id)
            node_id = int(production_node_id)
            expected_row_version = int(row_version)
        except (TypeError, ValueError) as exc:
            raise ValueError("排程条目、生产节点和行版本必须为正整数") from exc
        start = SchedulePlanningStrategy.parse_timestamp(planned_start_at)
        if start is None:
            raise ValueError("计划开始时间格式不正确")
        payload = {
            "action": "adjust", "revision_item_id": revision_item_id,
            "production_node_id": node_id,
            "planned_start_at": SchedulePlanningStrategy.format_timestamp(start),
            "row_version": expected_row_version, "reason": reason, "actor_id": actor,
        }
        digest = cls._workflow_digest(payload)
        with SchedulePlanningStrategy.transaction(db) as txn:
            replay = cls._workflow_replay(txn, key, digest)
            if replay:
                return replay
            item = ScheduleRevisionRepository.find_revision_item(revision_item_id, db=txn)
            if item is None:
                raise ValueError("排程条目不存在")
            if int(item["row_version"] or 1) != expected_row_version:
                raise NodeSchedulingError(
                    "ROW_VERSION_CONFLICT", "排程条目已被其他操作修改",
                    {"expected": expected_row_version, "actual": item["row_version"]},
                )
            if item["revision_status"] not in ("draft", "published"):
                raise NodeSchedulingError("REVISION_STATE_CONFLICT", "当前排程版本不可调整")
            if item["revision_status"] == "draft" and item["approval_status"] not in ("draft", "rejected"):
                raise NodeSchedulingError("REVISION_STATE_CONFLICT", "已提交审批的排程版本不可调整")
            if ScheduleRevisionRepository.find_active_task_lock(revision_item_id, db=txn):
                raise NodeSchedulingError("LOCKED_TASK_CONFLICT", "锁定排程条目不能移动")
            node = ProductionNodeRepository.find_node(node_id, db=txn)
            if node is None or node.get("status") != "active" or node.get("process_id") != item["process_id"]:
                raise NodeSchedulingError("NO_COMPATIBLE_NODE", "生产节点与排程工序不匹配")
            source_schedule = SchedulePlanningRepository.find_schedule(
                item["source_schedule_id"], db=txn
            )
            order = SchedulePlanningRepository.find_order(item["order_id"], txn)
            if order is None:
                raise ValueError("排程所属订单不存在")
            if source_schedule is None:
                try:
                    operation = json.loads(item["payload_json"] or "{}")
                except (TypeError, json.JSONDecodeError) as exc:
                    raise ValueError("排程候选来源内容不完整") from exc
                if not isinstance(operation, dict):
                    raise ValueError("排程候选来源内容不完整")
            else:
                operation = dict(source_schedule)
            policy_order = dict(order)
            policy_order["process_version_id"] = operation.get("process_version_id")
            standard = SchedulePlanningRepository.find_standard(
                operation.get("standard_id"), db=txn
            )
            capabilities = ProductionNodeRepository.list_capabilities(node_id, db=txn)
            ProductionNodePolicy.validate_node(
                node=node, capabilities=capabilities, operation=operation,
                order=policy_order, standard=dict(standard) if standard else None,
                quantity=max(int(item["quantity"] or 0), 1),
            )
            calendar = SchedulePlanningRepository.get_calendar(node["calendar_id"], db=txn)
            shifts = SchedulePlanningRepository.list_calendar_shifts(node["calendar_id"], db=txn)
            if calendar is None or not shifts:
                raise NodeSchedulingError("NODE_CALENDAR_UNAVAILABLE", "生产节点日历没有可用时间")
            occupied = []
            for row in SchedulePlanningRepository.list_node_occupancy_for_adjustment(
                node_id, item["source_schedule_id"], db=txn
            ):
                occupied.append({
                    "id": f"{row['fact_type']}:{row['id']}",
                    "production_node_id": node_id,
                    "start_at": row["start_at"], "end_at": row["end_at"],
                    "locked": bool(row["locked"]),
                })
            for override in ProductionNodeRepository.list_node_calendar_overrides(node_id, db=txn):
                if override["override_type"] != "overtime":
                    occupied.append({
                        "id": f"calendar_override:{override['id']}",
                        "production_node_id": node_id,
                        "start_at": override["start_at"], "end_at": override["end_at"],
                        "locked": False,
                    })
            duration = max(float(item["occupied_minutes"] or 0), 1.0)
            segments = SchedulePlanningStrategy.allocate_on_line(
                txn, calendar, shifts, None, start, duration, []
            )
            if not segments or SchedulePlanningStrategy.parse_timestamp(
                segments[0]["start_at"]
            ) != start:
                raise NodeSchedulingError("NODE_CALENDAR_UNAVAILABLE", "指定开始时间不在生产节点可用日历内")
            for segment in segments:
                ProductionNodePolicy.validate_node(
                    node=node, capabilities=capabilities, operation=operation,
                    order=policy_order, standard=dict(standard) if standard else None,
                    requested_start_at=segment["start_at"], requested_end_at=segment["end_at"],
                    calendar_intervals=[segment], calendar_available=True,
                    occupancy=occupied, quantity=max(int(item["quantity"] or 0), 1),
                    batch_orders=[item["order_id"]],
                )
            end = SchedulePlanningStrategy.parse_timestamp(segments[-1]["end_at"])
            segment_payload = [
                {**segment, "production_node_id": node_id,
                 "process_line_id": node.get("legacy_process_line_id")}
                for segment in segments
            ]
            try:
                source_payload = json.loads(item["payload_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                source_payload = {}
            source_payload.update({
                "production_node_id": node_id,
                "process_line_id": node.get("legacy_process_line_id"),
                "node_code_snapshot": node.get("node_code") or "",
                "node_name_snapshot": node.get("node_name") or "",
                "capacity_mode_snapshot": node.get("capacity_mode") or "",
                "planned_start_at": SchedulePlanningStrategy.format_timestamp(start),
                "planned_end_at": SchedulePlanningStrategy.format_timestamp(end),
                "plan_start": start.strftime("%Y-%m-%d"),
                "plan_end": end.strftime("%Y-%m-%d"),
                "segments": segment_payload,
            })
            encoded_payload = json.dumps(
                source_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            new_revision_id, item_map = ScheduleRevisionRepository.clone_revision_with_override(
                item["revision_id"], override_item_id=revision_item_id,
                overrides={
                    "production_node_id": node_id,
                    "process_line_id": node.get("legacy_process_line_id"),
                    "node_code_snapshot": node.get("node_code") or "",
                    "node_name_snapshot": node.get("node_name") or "",
                    "capacity_mode_snapshot": node.get("capacity_mode") or "",
                    "planned_start_at": SchedulePlanningStrategy.format_timestamp(start),
                    "planned_end_at": SchedulePlanningStrategy.format_timestamp(end),
                    "payload_json": encoded_payload,
                    "payload_digest": hashlib.sha256(encoded_payload.encode("utf-8")).hexdigest(),
                },
                created_by=actor, reason=reason, db=txn,
            )
            SchedulePlanningStrategy.assess_revision_conflicts(
                new_revision_id, "generation", txn, freeze_risk=True
            )
            new_item_id = item_map[revision_item_id]
            after = {
                "source_revision_id": item["revision_id"], "revision_id": new_revision_id,
                "revision_item_id": new_item_id, "production_node_id": node_id,
                "planned_start_at": SchedulePlanningStrategy.format_timestamp(start),
                "planned_end_at": SchedulePlanningStrategy.format_timestamp(end),
                "approval_status": "draft",
            }
            return cls._record_workflow_event(
                txn, revision_id=new_revision_id, revision_item_id=new_item_id,
                event_type="adjust", actor_id=actor, reason=reason,
                before={"revision_id": item["revision_id"], "revision_item_id": revision_item_id},
                after=after, digest=digest, key=key,
            )

    @classmethod
    def _transition_revision(
        cls, revision_id, target_status, reason, idempotency_key, actor_id,
        db=None, *, capacity_service,
    ):
        reason, key, actor = cls._workflow_input(reason, idempotency_key, actor_id)
        try:
            revision_id = int(revision_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("排程版本 ID 不正确") from exc
        payload = {
            "action": target_status, "revision_id": revision_id,
            "reason": reason, "actor_id": actor,
        }
        digest = cls._workflow_digest(payload)
        with SchedulePlanningStrategy.transaction(db) as txn:
            replay = cls._workflow_replay(txn, key, digest)
            if replay:
                return replay
            revision = ScheduleRevisionRepository.find_revision(revision_id, db=txn)
            if revision is None:
                raise ValueError("排程版本不存在")
            if ScheduleRevisionRepository.revision_uses_production_nodes(revision_id, db=txn):
                cls._assert_node_write_enabled()
            if revision["status"] != "draft":
                raise NodeSchedulingError("REVISION_STATE_CONFLICT", "只有草稿排程版本可执行审批流程")
            current = revision["approval_status"]
            expected = {
                "submitted": ("draft", "rejected"),
                "approved": ("submitted",),
                "rejected": ("submitted",),
            }[target_status]
            if current not in expected:
                raise NodeSchedulingError(
                    "REVISION_STATE_CONFLICT", "排程版本审批状态不允许当前操作",
                    {"approval_status": current, "target_status": target_status},
                )
            if target_status in ("submitted", "approved"):
                try:
                    ScheduleRevisionRepository.assert_revision_integrity(revision_id, db=txn)
                except ValueError as exc:
                    raise NodeSchedulingError("REVISION_INTEGRITY_FAILED", str(exc)) from exc
                SchedulePlanningStrategy.assert_revision_conflict_gate(
                    revision_id, "submit" if target_status == "submitted" else "approve", txn
                )
            if target_status == "approved" and revision["created_by"] == actor:
                raise NodeSchedulingError("INDEPENDENT_APPROVER_REQUIRED", "排程版本创建人不能批准自己的版本")
            changed = ScheduleRevisionRepository.transition_revision(
                revision_id, current, target_status, actor, reason, txn
            )
            if changed != 1:
                raise NodeSchedulingError("REVISION_STATE_CONFLICT", "排程版本状态已发生变化")
            after_revision = dict(ScheduleRevisionRepository.find_revision(revision_id, db=txn))
            return cls._record_workflow_event(
                txn, revision_id=revision_id, revision_item_id=None,
                event_type={"submitted": "submit", "approved": "approve", "rejected": "reject"}[target_status],
                actor_id=actor, reason=reason, before={"approval_status": current},
                after=after_revision, digest=digest, key=key,
            )

    @classmethod
    def submit_revision(
        cls, revision_id, reason, idempotency_key, actor_id, db=None,
        *, capacity_service,
    ):
        return cls._transition_revision(
            revision_id, "submitted", reason, idempotency_key, actor_id,
            db=db, capacity_service=capacity_service,
        )

    @classmethod
    def approve_revision(
        cls, revision_id, reason, idempotency_key, actor_id, db=None,
        *, capacity_service,
    ):
        return cls._transition_revision(
            revision_id, "approved", reason, idempotency_key, actor_id,
            db=db, capacity_service=capacity_service,
        )

    @classmethod
    def reject_revision(
        cls, revision_id, reason, idempotency_key, actor_id, db=None,
        *, capacity_service,
    ):
        return cls._transition_revision(
            revision_id, "rejected", reason, idempotency_key, actor_id,
            db=db, capacity_service=capacity_service,
        )

    @classmethod
    def publish_revision(
        cls, revision_id, reason, idempotency_key, actor_id, db=None,
        *, capacity_service,
    ):
        reason, key, actor = cls._workflow_input(reason, idempotency_key, actor_id)
        try:
            revision_id = int(revision_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("排程版本 ID 不正确") from exc
        payload = {
            "action": "publish", "revision_id": revision_id,
            "reason": reason, "actor_id": actor,
        }
        digest = cls._workflow_digest(payload)
        with SchedulePlanningStrategy.transaction(db) as txn:
            replay = cls._workflow_replay(txn, key, digest)
            if replay:
                return replay
            revision = ScheduleRevisionRepository.find_revision(revision_id, db=txn)
            if revision is None:
                raise ValueError("排程版本不存在")
            if ScheduleRevisionRepository.revision_uses_production_nodes(revision_id, db=txn):
                cls._assert_node_write_enabled()
            if revision["status"] != "draft":
                raise NodeSchedulingError(
                    "REVISION_STATE_CONFLICT", "排程版本当前状态不可发布",
                    {"revision_id": revision_id, "status": revision["status"]},
                )
            if revision["approval_status"] != "approved":
                raise NodeSchedulingError(
                    "REVISION_STATE_CONFLICT", "排程版本必须先经独立审批后才能发布",
                    {"revision_id": revision_id, "approval_status": revision["approval_status"]},
                )
            try:
                ScheduleRevisionRepository.assert_revision_integrity(revision_id, db=txn)
            except ValueError as exc:
                raise NodeSchedulingError("REVISION_INTEGRITY_FAILED", str(exc)) from exc
            SchedulePlanningStrategy.assert_revision_conflict_gate(
                revision_id, "publish", txn
            )
            before = dict(revision)
            ScheduleRevisionRepository.publish_revision(
                revision_id, txn, published_by=actor, reason=reason, idempotency_key=key
            )
            published = ScheduleRevisionRepository.find_revision(revision_id, db=txn)
            return cls._record_workflow_event(
                txn, revision_id=revision_id, revision_item_id=None,
                event_type="publish", actor_id=actor, reason=reason,
                before=before, after=dict(published), digest=digest, key=key,
            )
