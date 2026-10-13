"""Load and persist assessment facts; conflict and risk decisions are pure."""

import hashlib
import json
from modules.domain.production_time import format_database_timestamp, resolve_planning_now
from modules.domain.production_node_scheduling import NodeSchedulingError
from modules.domain.schedule_planning import PlanningAssessmentFacts
from modules.domain.schedule_planning_assessment import SchedulePlanningAssessment
from modules.repositories.schedule_evidence_repository import ScheduleEvidenceRepository
from modules.repositories.schedule_planning_repository import SchedulePlanningRepository
from modules.repositories.schedule_revision_repository import ScheduleRevisionRepository


class ScheduleAssessmentService:
    @staticmethod
    def revision_operations(revision_id, db):
        operations = []
        for row in ScheduleEvidenceRepository.list_revision_conflict_items(
            revision_id, db=db
        ):
            item = dict(row)
            try:
                payload = json.loads(item.get("payload_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            operation = dict(payload)
            operation.update({
                "revision_item_id": item["id"],
                "order_id": item["order_id"],
                "order_process_id": item["order_process_id"],
                "process_id": item["process_id"],
                "process_name": item.get("process_name") or payload.get("process_name") or "",
                "seq_order": item.get("seq_order") or payload.get("seq_order") or 0,
                "status": item.get("status") or payload.get("status") or "blocked",
                "production_node_id": item.get("production_node_id") or payload.get("production_node_id"),
                "process_line_id": item.get("process_line_id") or payload.get("process_line_id"),
                "planned_start_at": item.get("planned_start_at") or payload.get("planned_start_at") or "",
                "planned_end_at": item.get("planned_end_at") or payload.get("planned_end_at") or "",
                "occupied_minutes": item.get("occupied_minutes") or payload.get("occupied_minutes") or 0,
                "execution_mode": item.get("execution_mode") or payload.get("execution_mode") or "internal",
                "locked": bool(item.get("locked")),
            })
            operations.append(operation)
        return operations

    @staticmethod
    def revision_conflict_input(revision_id, db):
        order = ScheduleRevisionRepository.find_revision_order(revision_id, db=db)
        if order is None:
            raise ValueError("排程版本所属订单不存在")
        operations = ScheduleAssessmentService.revision_operations(revision_id, db)
        candidate = ScheduleAssessmentService._candidate_capacity_intervals(operations)
        occupied = [
            dict(row)
            for row in SchedulePlanningRepository.list_effective_capacity_intervals(
                exclude_order_id=order["order_id"], db=db
            )
        ]
        unavailable = [
            dict(row)
            for row in SchedulePlanningRepository.list_capacity_unavailability(db=db)
        ]
        snapshot = {
            "revision_id": int(revision_id),
            "order_id": int(order["order_id"]),
            "operations": operations,
            "candidate_intervals": candidate,
            "occupied_intervals": occupied,
            "unavailable_intervals": unavailable,
        }
        encoded = json.dumps(
            snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return (
            dict(order), operations, candidate, occupied, unavailable,
            hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        )

    @staticmethod
    def assess_revision_conflicts(
        revision_id, check_stage, db, *, freeze_risk=False, persist=True,
        planning_now=None,
    ):
        (
            order, operations, candidate, occupied, unavailable, input_digest,
        ) = ScheduleAssessmentService.revision_conflict_input(revision_id, db)
        facts = PlanningAssessmentFacts(
            order, tuple(operations), tuple(candidate), tuple(occupied), tuple(unavailable),
            resolve_planning_now(planning_now),
        )
        pure = SchedulePlanningAssessment.assess(facts)
        conflicts, summary = pure["conflicts"], pure["summary"]
        check = None
        if persist:
            check = ScheduleEvidenceRepository.record_revision_conflict_check(
                revision_id, check_stage, input_digest, summary, conflicts, db=db
            )

        risk = None
        if freeze_risk:
            risk, projected_count = SchedulePlanningAssessment.deadline_risk(
                facts, conflicts, summary
            )
            assessed_at = format_database_timestamp(facts.now)
            ScheduleEvidenceRepository.set_revision_risk_snapshot(
                revision_id, risk, assessed_at, db
            )
            evidence_payload = {
                "risk": risk,
                "conflict_check_digest": check["result_digest"] if check else "",
                "input_digest": input_digest,
            }
            evidence_json = json.dumps(
                evidence_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            ScheduleEvidenceRepository.record_revision_risk_assessment(
                revision_id,
                "generation",
                risk,
                {
                    "conflict_summary": summary,
                    "conflicts": conflicts,
                    "projected_operation_count": projected_count,
                },
                hashlib.sha256(evidence_json.encode("utf-8")).hexdigest(),
                db=db,
            )
        return {
            "check": dict(check) if check else None,
            "summary": summary,
            "conflicts": conflicts,
            "risk": risk,
        }

    @staticmethod
    def assert_revision_conflict_gate(revision_id, check_stage, db):
        assessment = ScheduleAssessmentService.assess_revision_conflicts(
            revision_id, check_stage, db, freeze_risk=False
        )
        if assessment["summary"]["blocking_count"]:
            raise NodeSchedulingError(
                "SCHEDULE_CONFLICT_GATE_FAILED",
                "排程版本存在生产节点冲突，禁止进入下一审批或发布状态",
                {
                    "revision_id": int(revision_id),
                    "check_stage": check_stage,
                    **assessment["summary"],
                    "conflicts": assessment["conflicts"][:20],
                },
            )
        return assessment

    _candidate_capacity_intervals = staticmethod(SchedulePlanningAssessment.candidate_capacity_intervals)
