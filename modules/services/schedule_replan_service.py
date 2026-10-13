"""Dynamic replan orchestration for production scheduling.

The service keeps production facts, lock recovery, planning, risk comparison,
and evidence persistence in one transaction while delegating capacity
decisions to the shared pure planner and persistence to repositories.
"""

import hashlib
import json

from modules import config
from modules.domain.production_node_scheduling import NodeSchedulingError
from modules.domain.production_time import parse_database_timestamp, production_now
from modules.domain.schedule_dynamic_replan import ScheduleDynamicReplanPolicy
from modules.domain.schedule_pure_planner import SchedulePurePlanner
from modules.domain.schedule_planning import (
    PlanningFactsSnapshot,
    PlanningOperationFacts,
    OperationPlanningContext,
    build_planning_evidence,
    decode_run_result_payload,
    summarize_schedule_result,
)
from modules.repositories.production_node_repository import ProductionNodeRepository
from modules.repositories.schedule_evidence_repository import ScheduleEvidenceRepository
from modules.repositories.schedule_planning_repository import SchedulePlanningRepository
from modules.repositories.schedule_revision_repository import ScheduleRevisionRepository
from modules.services.schedule_planning_strategy import SchedulePlanningStrategy


class ScheduleReplanService:
    @staticmethod
    def _replan_start(value):
        if not value:
            return production_now().replace(second=0, microsecond=0)
        parsed = parse_database_timestamp(value)
        if parsed is None:
            raise ValueError("重排开始时间必须使用有效的 ISO 8601 格式")
        return parsed

    @staticmethod
    def _add_downtime_to_occupancy(occupancy, downtime, resource_key="process_line_id", capacity_service=None):
        if capacity_service is None:
            raise ValueError("动态重排必须由容量服务提供时间解析器")
        for event in downtime:
            event = dict(event)
            start = SchedulePlanningStrategy.parse_timestamp(event.get("start_at"))
            end = SchedulePlanningStrategy.parse_timestamp(event.get("end_at"))
            resource_id = event.get(resource_key)
            if resource_id is None or not start or not end or end <= start:
                continue
            occupancy.setdefault(int(resource_id), []).append((start, end))

    @staticmethod
    def _latest_locks_by_operation(active_locks):
        """Collapse copied locks to the newest immutable revision per operation."""
        result = {}
        for row in active_locks:
            lock = dict(row)
            operation_id = int(lock["order_process_id"])
            result.setdefault(operation_id, lock)
        return result

    @staticmethod
    def _locked_task_segments(lock, payload):
        from modules.domain.schedule_pure_planner import SchedulePurePlanner

        return SchedulePurePlanner.locked_task_segments(lock, payload)

    @staticmethod
    def _locked_task_allocations(payload):
        from modules.domain.schedule_pure_planner import SchedulePurePlanner

        return SchedulePurePlanner.locked_task_allocations(payload)

    @staticmethod
    def _locked_task_conflict(lock, downtime, cursor, db, capacity_service):
        overrides = tuple(dict(row) for row in ProductionNodeRepository.list_node_calendar_overrides(lock.get("production_node_id"), db=db))
        return SchedulePurePlanner.locked_conflict(lock, tuple(dict(row) for row in downtime), overrides, cursor)

    @staticmethod
    def _copy_active_lock_to_schedule(lock, schedule_id, revision_id, db):
        item = ScheduleRevisionRepository.find_revision_item_by_source_schedule(
            revision_id, schedule_id, db=db
        )
        if item is None:
            raise ValueError("新排程版本缺少锁定任务快照")
        ScheduleRevisionRepository.create_task_lock(
            item["id"], lock["production_node_id"], lock["locked_by"],
            lock.get("reason") or "动态重排保留锁定任务", db
        )
        return dict(item)

    @staticmethod
    def _prepare_request(start_at, schedule_run_key, reason, capacity_service):
        """Validate and normalize the dynamic replan request."""
        start = ScheduleReplanService._replan_start(start_at)
        standard_as_of = start.strftime("%Y-%m-%d")
        reason = str(reason or "").strip()
        if len(reason) > 512:
            raise ValueError("重排原因不能超过 512 个字符")
        run_key = str(schedule_run_key or "").strip()
        if not run_key:
            raise ValueError("排程幂等键不能为空")
        return {
            "start": start,
            "standard_as_of": standard_as_of,
            "reason": reason,
            "run_key": run_key,
        }

    @staticmethod
    def _load_replan_facts(order_id, txn, use_node_engine, *, persist_bindings=True):
        """Load immutable production facts used by one replan attempt."""
        active_lock_rows = ScheduleRevisionRepository.list_active_order_task_locks(
            order_id, db=txn
        )
        if active_lock_rows and not use_node_engine:
            raise NodeSchedulingError(
                "LOCKED_TASK_CONFLICT",
                "Legacy 排程引擎不能保留生产节点锁定任务",
                {
                    "order_id": order_id,
                    "revision_item_ids": [
                        row["revision_item_id"] for row in active_lock_rows
                    ],
                },
            )
        active_locks = ScheduleReplanService._latest_locks_by_operation(
            active_lock_rows
        )
        # Resolve legacy orders to immutable route/process bindings before any
        # revision fact is written.
        bound_order = SchedulePlanningRepository.ensure_order_version_bindings(
            order_id, txn, persist=persist_bindings
        )
        if not bound_order:
            raise ValueError("订单不存在")
        context = SchedulePlanningRepository.dynamic_replan_order_context(
            order_id, db=txn, use_nodes=use_node_engine
        )
        if not context:
            raise ValueError("订单不存在")
        if not persist_bindings:
            bindings = SchedulePlanningRepository.resolve_order_operation_bindings(
                order_id, bound_order["route_version_id"], txn
            )
            context["order"] = {
                **dict(context["order"]),
                "route_version_id": bound_order["route_version_id"],
                "route_name_snapshot": bound_order["route_name_snapshot"],
            }
            for operation in context["operations"]:
                operation.update(bindings.get(int(operation["order_process_id"]), {}))
                operation["route_version_id"] = bound_order["route_version_id"]
                operation["route_name_snapshot"] = bound_order["route_name_snapshot"]
        return {
            "context": context,
            "order": context["order"],
            "active_locks": active_locks,
            "order_serial_ids": SchedulePlanningRepository.list_order_serial_ids(
                order_id, db=txn
            ),
        }

    @staticmethod
    def _replay_existing_run(order_id, run_key, prior_run, txn):
        """Return the immutable result for a previously completed/failed run."""
        if not prior_run:
            return None
        if prior_run["order_id"] != order_id:
            raise ValueError("排程幂等键已被其他订单使用")
        revision = ScheduleRevisionRepository.find_revision_by_run(
            prior_run["id"], db=txn
        )
        replay_payload = decode_run_result_payload(prior_run)
        replay_operations = replay_payload["operations"]
        evidence_summary = None
        evidence_differences = []
        if revision:
            stored_summary, stored_differences = (
                ScheduleEvidenceRepository.get_replan_evidence(
                    revision["id"], db=txn
                )
            )
            evidence_summary = dict(stored_summary) if stored_summary else None
            evidence_differences = [dict(item) for item in stored_differences]
        return {
            "ok": prior_run["status"] == "completed",
            "order_id": order_id,
            "schedule_run_key": run_key,
            "idempotent_replay": True,
            "status": prior_run["status"],
            "error": prior_run["error_message"] or "",
            "input_digest": (
                prior_run["input_digest"]
                if "input_digest" in prior_run.keys()
                else ""
            ),
            "schedule_revision_id": revision["id"] if revision else None,
            "revision_status": revision["status"] if revision else None,
            "operations": replay_operations,
            "conflicts": [
                {
                    key: item.get(key)
                    for key in (
                        "code",
                        "revision_item_id",
                        "source_revision_item_id",
                        "production_node_id",
                        "requires_manual_unlock",
                        "reason",
                        "conflict_type",
                        "downtime_event_id",
                        "calendar_override_id",
                    )
                    if item.get(key) is not None
                }
                for item in replay_operations
                if item.get("code") == "LOCKED_TASK_CONFLICT"
            ],
            "replan_summary": evidence_summary,
            "differences": evidence_differences,
            "planning_summary": (
                (evidence_summary or {}).get("planning_summary")
                or replay_payload.get("planning_summary")
                or summarize_schedule_result(
                {"operations": replay_operations},
                input_digest=(
                    prior_run["input_digest"]
                    if "input_digest" in prior_run.keys()
                    else ""
                ),
                )
            ),
            "planning_manifest": (
                (evidence_summary or {}).get("planning_manifest")
                or replay_payload.get("planning_manifest")
                or {}
            ),
        }

    @staticmethod
    def _create_replan_ledger(
        order_id,
        request,
        facts,
        run_key,
        actor_id,
        txn,
        capacity_service,
        input_digest_override=None,
    ):
        """Create the run/revision ledger before entering the savepoint."""
        context = facts["context"]
        order = facts["order"]
        active_locks = facts["active_locks"]
        snapshot, input_digest = ScheduleDynamicReplanPolicy.build_input_snapshot(
            order=order,
            operations=context["operations"],
            downtime=context["downtime"],
            occupancy=context["occupancy"],
            reason=request["reason"],
            as_of=SchedulePlanningStrategy.format_timestamp(request["start"]),
            locked_tasks=list(active_locks.values()),
            work_reports=context["work_reports"],
            scrap_records=context["scrap_records"],
            rework_records=context["rework_records"],
            current_revision=context["current_revision"],
            current_revision_items=context["current_revision_items"],
            replan_triggers=context["replan_triggers"],
        )
        input_digest = input_digest_override or input_digest
        run_id = ScheduleRevisionRepository.create_run(
            order_id,
            run_key,
            request["start"].strftime("%Y-%m-%d"),
            txn,
            run_type="dynamic_replan",
            trigger_source="production_facts",
            input_digest=input_digest,
            replan_reason=request["reason"],
        )
        revision_id = ScheduleRevisionRepository.create_revision(
            order_id,
            run_id,
            run_key,
            txn,
            created_by=actor_id,
            replan_reason=request["reason"],
            replan_source_digest=input_digest,
            replanned_at=SchedulePlanningStrategy.format_timestamp(request["start"]),
        )
        return {
            "snapshot": snapshot,
            "input_digest": input_digest,
            "run_id": run_id,
            "revision_id": revision_id,
        }

    @staticmethod
    def _load_replan_occupancy(
        order_id, context, active_locks, use_node_engine, txn, capacity_service,
        *, clear_projection=True
    ):
        """Reset the projection and load occupancy/downtime/lock constraints."""
        if clear_projection:
            ScheduleRevisionRepository.clear_order_schedules(order_id, txn)
        occupancy = {}
        occupancy_rows = (
            ProductionNodeRepository.list_node_occupancy(order_id, db=txn)
            if use_node_engine
            else SchedulePlanningRepository.list_line_occupancy(order_id, txn)
        )
        occupancy_key = "production_node_id" if use_node_engine else "process_line_id"
        for row in occupancy_rows:
            begin = SchedulePlanningStrategy.parse_timestamp(row["start_at"])
            end = SchedulePlanningStrategy.parse_timestamp(row["end_at"])
            resource_id = row[occupancy_key]
            if resource_id is not None and begin and end and end > begin:
                occupancy.setdefault(int(resource_id), []).append((begin, end))
        ScheduleReplanService._add_downtime_to_occupancy(
            occupancy,
            context["downtime"],
            resource_key=occupancy_key,
            capacity_service=capacity_service,
        )
        if use_node_engine:
            for lock in active_locks.values():
                lock_start = SchedulePlanningStrategy.parse_timestamp(
                    lock.get("planned_start_at")
                )
                lock_end = SchedulePlanningStrategy.parse_timestamp(
                    lock.get("planned_end_at")
                )
                node_id = lock.get("production_node_id")
                if (
                    node_id is not None
                    and lock_start
                    and lock_end
                    and lock_end > lock_start
                ):
                    occupancy.setdefault(int(node_id), []).append(
                        (lock_start, lock_end)
                    )
        return occupancy

    @staticmethod
    def _restore_locked_task(*, operation, common, locked_task, context, cursor,
                             revision_id, txn, capacity_service, persist=True):
        """Compatibility adapter; lock decisions are owned by the pure planner."""
        facts = PlanningOperationFacts(
            operation=operation, remaining_quantity=int(common.get("quantity") or 0),
            completed_quantity=0, rework_quantity=0, execution_policy={}, standard=None,
            resources=(), previous={}, locked_task=locked_task,
            downtime=tuple(dict(row) for row in context["downtime"]),
            locked_overrides=tuple(dict(row) for row in ProductionNodeRepository.list_node_calendar_overrides(locked_task.get("production_node_id"), db=txn)),
        )
        planning_context = OperationPlanningContext(common, facts.remaining_quantity, 0, 0,
            operation.get("process_name_snapshot") or operation.get("process_name") or "", "", cursor)
        result, conflict, end = SchedulePurePlanner.restore_locked_task(facts, planning_context, cursor, True)
        if persist:
            result["id"] = ScheduleRevisionRepository.insert_operation_schedule(result, txn)
            item = ScheduleReplanService._copy_active_lock_to_schedule(locked_task, result["id"], revision_id, txn)
            result["revision_item_id"] = item["id"]
        else:
            result.pop("id", None)
        return result, conflict, end

    @staticmethod
    def _plan_replan_operations(
        *,
        order_id,
        order,
        context,
        active_locks,
        order_serial_ids,
        start,
        standard_as_of,
        run_key,
        run_id,
        revision_id,
        input_digest,
        use_node_engine,
        occupancy,
        txn,
        capacity_service,
        persist=True,
    ):
        """Delegate replan decisions to the shared immutable pure planner."""
        from modules.services.schedule_planning_facts import (
            SchedulePlanningFactsLoader,
        )

        facts = PlanningFactsSnapshot.create(
            order={**dict(order), "id": order_id},
            operations=tuple(dict(item) for item in context["operations"]),
            order_serial_ids=tuple(order_serial_ids),
            cursor=start,
            standard_as_of=standard_as_of,
            use_node_engine=use_node_engine,
            occupancy=occupancy,
        )
        operation_facts = SchedulePlanningFactsLoader.replan(
            dict(facts.order),
            context,
            active_locks,
            start,
            standard_as_of,
            use_node_engine,
            txn,
        )
        decision = SchedulePlanningStrategy.plan(
            facts,
            operation_facts,
            run_key=run_key,
            run_id=run_id,
            revision_id=revision_id,
            mode="replan",
            source_fact_digest=input_digest,
        )
        return (
            decision.operation_dicts(),
            decision.conflict_dicts(),
            decision.blocked,
        )

    @staticmethod
    def _finalize_replan(
        *,
        order_id,
        order,
        context,
        result,
        conflicts,
        blocked,
        run_id,
        revision_id,
        run_key,
        input_digest,
        snapshot,
        reason,
        txn,
        capacity_service,
        facts_snapshot,
    ):
        """Persist immutable differences, risk changes, evidence, and run status."""
        planned = [
            item
            for item in result
            if item.get("status") == "planned"
            and (item.get("process_line_id") or item.get("production_node_id"))
        ]
        if planned and not order.get("current_schedule_revision_id"):
            ScheduleRevisionRepository.update_order_summary(
                order_id,
                min(item["plan_start"] for item in planned),
                max(item["plan_end"] for item in planned),
                txn,
            )
        result_json = json.dumps(
            result, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        ScheduleRevisionRepository.set_revision_digest(
            revision_id, hashlib.sha256(result_json.encode("utf-8")).hexdigest(), txn
        )
        ScheduleRevisionRepository.finalize_revision_content_digest(
            revision_id, db=txn
        )
        conflict_assessment = SchedulePlanningStrategy.assess_revision_conflicts(
            revision_id, "replan", txn, freeze_risk=True
        )
        after_items = [
            dict(item)
            for item in ScheduleRevisionRepository.list_revision_items(
                revision_id, db=txn
            )
        ]
        differences = ScheduleDynamicReplanPolicy.build_differences(
            context["current_revision_items"], after_items
        )
        before_risk = context["current_revision"] or {}
        after_risk = conflict_assessment["risk"] or {}
        changed = [
            item for item in differences if item["change_type"] != "unchanged"
        ]
        replan_summary = {
            "prior_revision_id": order.get("current_schedule_revision_id"),
            "revision_id": revision_id,
            "trigger_count": len(context["replan_triggers"]),
            "changed_operation_count": len(changed),
            "node_change_count": sum(item["node_changed"] for item in changed),
            "delayed_operation_count": sum(
                1 for item in changed if item["end_delta_minutes"] > 0
            ),
            "advanced_operation_count": sum(
                1 for item in changed if item["end_delta_minutes"] < 0
            ),
            "before_risk_level": before_risk.get("risk_level") or "none",
            "after_risk_level": after_risk.get("risk_level") or "none",
            "before_delay_minutes": int(before_risk.get("delay_minutes") or 0),
            "after_delay_minutes": int(after_risk.get("delay_minutes") or 0),
            "risk_change": ScheduleDynamicReplanPolicy.risk_change(
                before_risk, after_risk
            ),
            "blocked": bool(blocked),
            "trigger_reasons": list(
                dict.fromkeys(
                    item.get("reason") or "生产事实发生变化"
                    for item in context["replan_triggers"][:20]
                )
            ),
        }
        planning_evidence = build_planning_evidence(
            facts_snapshot,
            result,
            input_digest=input_digest,
            conflicts=tuple(conflicts) + tuple(conflict_assessment["conflicts"]),
            risk=conflict_assessment["risk"],
            extra_stages={"differences": differences},
            algorithm="schedule-pure-planning-replan-v1",
        )
        planning_summary = planning_evidence.summary_dict()
        planning_manifest = planning_evidence.manifest
        replan_summary.update({
            "planning_summary": planning_summary,
            "planning_manifest": planning_manifest.as_dict(),
        })
        ScheduleEvidenceRepository.save_replan_evidence(
            revision_id,
            order.get("current_schedule_revision_id"),
            order_id,
            differences,
            replan_summary,
            db=txn,
        )
        ScheduleRevisionRepository.complete_run(run_id, "completed", result, db=txn)
        return {
            "ok": True,
            "order_id": order_id,
            "schedule_run_key": run_key,
            "idempotent_replay": False,
            "status": "completed",
            "input_digest": input_digest,
            "schedule_revision_id": revision_id,
            "revision_status": "draft",
            "replan_reason": reason,
            "input_snapshot": snapshot,
            "operations": result,
            "conflicts": conflicts,
            "revision_conflicts": conflict_assessment["conflicts"],
            "risk": conflict_assessment["risk"],
            "replan_summary": replan_summary,
            "differences": differences,
            "planning_summary": planning_summary,
            "planning_manifest": planning_manifest.as_dict(),
        }

    @staticmethod
    def _fail_replan(*, run_id, revision_id, error, txn):
        """Keep a failed run auditable while cancelling the new revision."""
        txn.execute("ROLLBACK TO SAVEPOINT dynamic_schedule_replan")
        txn.execute("RELEASE SAVEPOINT dynamic_schedule_replan")
        ScheduleRevisionRepository.cancel_revision(revision_id, txn)
        ScheduleRevisionRepository.complete_run(
            run_id, "failed", [], str(error), db=txn
        )

    @staticmethod
    def _build_replan_input(facts, request):
        context = facts["context"]
        return ScheduleDynamicReplanPolicy.build_input_snapshot(
            order=facts["order"], operations=context["operations"],
            downtime=context["downtime"], occupancy=context["occupancy"],
            reason=request["reason"],
            as_of=SchedulePlanningStrategy.format_timestamp(request["start"]),
            locked_tasks=list(facts["active_locks"].values()),
            work_reports=context["work_reports"], scrap_records=context["scrap_records"],
            rework_records=context["rework_records"],
            current_revision=context["current_revision"],
            current_revision_items=context["current_revision_items"],
            replan_triggers=context["replan_triggers"],
        )

    @staticmethod
    def _materialize_replan_result(result, run_id, revision_id, run_key, facts, txn):
        materialized = []
        for raw in result:
            payload = dict(raw)
            payload.pop("id", None)
            payload.update({
                "schedule_run_id": run_id,
                "schedule_revision_id": revision_id,
                "schedule_run_key": run_key,
            })
            payload = SchedulePlanningStrategy.persist_operation_payload(payload, txn, persist=True)
            if raw.get("locked"):
                lock = facts["active_locks"].get(int(raw["order_process_id"]))
                if lock:
                    item = ScheduleReplanService._copy_active_lock_to_schedule(
                        lock, payload["id"], revision_id, txn
                    )
                    payload["revision_item_id"] = item["id"]
                    payload["source_revision_item_id"] = lock["revision_item_id"]
            materialized.append(payload)
        return materialized

    @staticmethod
    def _record_stale_replan(*, order_id, run_key, request, facts, actor_id,
                             expected_digest, actual_digest, txn, capacity_service):
        ledger = ScheduleReplanService._create_replan_ledger(
            order_id, request, facts, run_key, actor_id, txn, capacity_service,
            input_digest_override=expected_digest,
        )
        summary = {
            "status": "STALE_INPUT", "stale_input": True,
            "expected_digest": expected_digest, "actual_digest": actual_digest,
            "reason": "重排期间业务事实发生变化，未写入排程版本",
        }
        manifest = {"input_digest": expected_digest, "status": "STALE_INPUT"}
        ScheduleEvidenceRepository.save_planning_evidence(
            ledger["revision_id"], summary, manifest, db=txn
        )
        ScheduleRevisionRepository.cancel_revision(ledger["revision_id"], txn)
        ScheduleRevisionRepository.complete_run(
            ledger["run_id"], "failed", [], "STALE_INPUT: 重排事实已变化", db=txn
        )
        return {
            "ok": False, "order_id": order_id, "schedule_run_key": run_key,
            "status": "STALE_INPUT", "error": "STALE_INPUT: 重排事实已变化",
            "schedule_revision_id": ledger["revision_id"],
            "revision_status": "cancelled", "operations": [],
            "planning_summary": summary, "planning_manifest": manifest,
        }

    @staticmethod
    def dynamic_replan_order(
        order_id,
        start_at=None,
        schedule_run_key="",
        reason="",
        db=None,
        actor_id=None,
        capacity_service=None,
    ):
        """Replan through one transaction with explicit use-case phases."""
        if capacity_service is None:
            raise ValueError("动态重排必须通过 ScheduleCapacityService 入口调用")
        request = ScheduleReplanService._prepare_request(
            start_at, schedule_run_key, reason, capacity_service
        )
        use_node_engine = bool(getattr(config, "PRODUCTION_NODE_ENGINE_ENABLED", False))
        with SchedulePlanningStrategy.read_transaction(db) as snapshot_db:
            prior_run = ScheduleRevisionRepository.find_run(request["run_key"], snapshot_db)
            replay = ScheduleReplanService._replay_existing_run(
                order_id, request["run_key"], prior_run, snapshot_db
            )
            if replay is not None:
                return replay
            facts = ScheduleReplanService._load_replan_facts(
                order_id, snapshot_db, use_node_engine, persist_bindings=False
            )
            planning_digest = SchedulePlanningRepository.planning_input_digest(
                order_id, db=snapshot_db
            )
            occupancy = ScheduleReplanService._load_replan_occupancy(
                order_id, facts["context"], facts["active_locks"], use_node_engine,
                snapshot_db, capacity_service, clear_projection=False
            )
            facts_snapshot = PlanningFactsSnapshot.create(
                order=dict(facts["order"]),
                operations=tuple(dict(item) for item in facts["context"]["operations"]),
                order_serial_ids=tuple(facts["order_serial_ids"]),
                cursor=request["start"], standard_as_of=request["standard_as_of"],
                use_node_engine=use_node_engine, occupancy=occupancy,
            )
            _, policy_input_digest = ScheduleReplanService._build_replan_input(facts, request)
            result, conflicts, blocked = ScheduleReplanService._plan_replan_operations(
                order_id=order_id, order=facts["order"], context=facts["context"],
                active_locks=facts["active_locks"], order_serial_ids=facts["order_serial_ids"],
                start=request["start"], standard_as_of=request["standard_as_of"],
                run_key=request["run_key"], run_id=0, revision_id=0,
                input_digest=policy_input_digest, use_node_engine=use_node_engine,
                occupancy=occupancy, txn=snapshot_db, capacity_service=capacity_service,
                persist=False,
            )

        failure = None
        response = None
        with SchedulePlanningStrategy.transaction(db) as txn:
            prior_run = ScheduleRevisionRepository.find_run(request["run_key"], txn)
            replay = ScheduleReplanService._replay_existing_run(
                order_id, request["run_key"], prior_run, txn
            )
            if replay is not None:
                return replay
            actual_digest = SchedulePlanningRepository.planning_input_digest(order_id, db=txn)
            facts_write = ScheduleReplanService._load_replan_facts(
                order_id, txn, use_node_engine, persist_bindings=True
            )
            if actual_digest != planning_digest:
                return ScheduleReplanService._record_stale_replan(
                    order_id=order_id, run_key=request["run_key"], request=request,
                    facts=facts_write, actor_id=actor_id, expected_digest=planning_digest,
                    actual_digest=actual_digest, txn=txn, capacity_service=capacity_service,
                )
            ledger = ScheduleReplanService._create_replan_ledger(
                order_id, request, facts_write, request["run_key"], actor_id, txn,
                capacity_service, input_digest_override=planning_digest,
            )
            try:
                txn.execute("SAVEPOINT dynamic_schedule_replan")
                ScheduleReplanService._load_replan_occupancy(
                    order_id, facts_write["context"], facts_write["active_locks"],
                    use_node_engine, txn, capacity_service, clear_projection=True
                )
                result = ScheduleReplanService._materialize_replan_result(
                    result, ledger["run_id"], ledger["revision_id"],
                    request["run_key"], facts_write, txn
                )
                revision_ids = {
                    int(item["order_process_id"]): item.get("revision_item_id")
                    for item in result if item.get("revision_item_id") is not None
                }
                conflicts = [
                    {
                        **{
                            key: value for key, value in conflict.items()
                            if key != "order_process_id"
                        },
                        "revision_item_id": conflict.get("revision_item_id")
                        or revision_ids.get(int(conflict.get("order_process_id") or 0)),
                    }
                    for conflict in conflicts
                ]
                response = ScheduleReplanService._finalize_replan(
                    order_id=order_id, order=facts_write["order"],
                    context=facts_write["context"], result=result, conflicts=conflicts,
                    blocked=blocked, run_id=ledger["run_id"], revision_id=ledger["revision_id"],
                    run_key=request["run_key"], input_digest=ledger["input_digest"],
                    snapshot=ledger["snapshot"], reason=request["reason"], txn=txn,
                    capacity_service=capacity_service, facts_snapshot=facts_snapshot,
                )
                txn.execute("RELEASE SAVEPOINT dynamic_schedule_replan")
            except Exception as exc:
                ScheduleReplanService._fail_replan(
                    run_id=ledger["run_id"], revision_id=ledger["revision_id"],
                    error=exc, txn=txn
                )
                failure = str(exc)
        if failure:
            raise ValueError(failure)
        return response
