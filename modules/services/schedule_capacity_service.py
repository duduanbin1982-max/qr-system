"""工序级、多产线、工时驱动的排程策略。"""

import hashlib
import json

from modules.services import BaseService
from modules.services.schedule_query_service import ScheduleQueryService
from modules.services.schedule_unit_of_work import ScheduleUnitOfWork
from modules.services.schedule_assessment_service import ScheduleAssessmentService
from modules.domain.schedule_planning_assessment import SchedulePlanningAssessment
from modules.domain.schedule_pure_planner import SchedulePurePlanner
from modules import config
from modules.domain.schedule_planning import (
    PlanningFactsSnapshot,
    build_planning_evidence,
    decode_run_result_payload,
    summarize_schedule_result,
)
from modules.domain.production_node_scheduling import NodeSchedulingError
from modules.domain.schedule_capacity_allocation import ScheduleCapacityAllocationPolicy
from modules.domain.errors import NotFoundError, ProductionNodeWriteDisabledError
from modules.domain.production_time import (
    format_database_timestamp,
    parse_api_timestamp,
    parse_database_timestamp,
    parse_production_date,
    resolve_planning_now,
)
from modules.repositories.schedule_evidence_repository import ScheduleEvidenceRepository
from modules.repositories.schedule_planning_repository import SchedulePlanningRepository
from modules.repositories.schedule_revision_repository import ScheduleRevisionRepository
from modules.repositories.production_node_repository import ProductionNodeRepository
from modules.services.production_node_service import ProductionNodeService
from modules.services.schedule_planning_strategy import SchedulePlanningStrategy
from modules.services.schedule_workflow_evidence import ScheduleWorkflowEvidence


class ScheduleCapacityService:
    DEFAULT_DAILY_MINUTES = 540

    @staticmethod
    def _assert_node_write_enabled():
        if not getattr(config, "PRODUCTION_NODE_WRITE_ENABLED", False):
            raise ProductionNodeWriteDisabledError("生产节点写入尚未启用")

    @staticmethod
    def _limit(value, default=500):
        return ScheduleQueryService.limit(value, default)

    @staticmethod
    def list_lines(process_id=None, limit=500):
        return ScheduleQueryService.list_lines(process_id, limit)

    @staticmethod
    def list_calendars():
        return ScheduleQueryService.list_calendars()

    @staticmethod
    def list_schedulable_orders(limit=500, now=None):
        return ScheduleQueryService.list_schedulable_orders(limit, now)

    @staticmethod
    def auto_plan_orders(
        start_date=None, auto_plan_key="", limit=100, actor_id=None, db=None,
        planning_now=None,
    ):
        """Generate schedules for the immutable priority queue as one ledgered run.

        The queue snapshot is hashed before any schedule is generated.  Reusing
        a key with the same input replays the stored result; reusing it with a
        different queue or start date is rejected so an audit record can never
        be silently overwritten.
        """
        run_key = str(auto_plan_key or "").strip()
        if not run_key:
            raise ValueError("自动排程幂等键不能为空")
        bounded_limit = ScheduleCapacityService._limit(limit, default=100)
        effective_now = resolve_planning_now(planning_now)
        if start_date in (None, ""):
            effective_start = effective_now.strftime("%Y-%m-%d")
        else:
            effective_start = ScheduleCapacityService._date(start_date, "计划开始日期").strftime("%Y-%m-%d")

        response = None
        failure = None
        with ScheduleCapacityService._transaction(db) as txn:
            queue = SchedulePlanningRepository.list_schedulable_orders(
                bounded_limit, db=txn, now=effective_now,
            )
            input_snapshot = {
                "start_date": effective_start,
                "limit": bounded_limit,
                "orders": [
                    {
                        "order_id": int(order["id"]),
                        "effective_priority_level": int(order.get("effective_priority_level") or 3),
                        "effective_is_expedited": int(order.get("effective_is_expedited") or 0),
                        "priority_version": int(order.get("priority_version") or 1),
                        "schedule_policy": order.get("schedule_policy") or "auto",
                    }
                    for order in queue
                ],
            }
            input_json = json.dumps(
                input_snapshot, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            )
            input_digest = hashlib.sha256(input_json.encode("utf-8")).hexdigest()
            prior_run = ScheduleRevisionRepository.find_auto_plan_run(run_key, db=txn)
            if prior_run:
                if prior_run["input_digest"] != input_digest:
                    raise ValueError("自动排程幂等键已被不同输入使用")
                stored = ScheduleRevisionRepository.auto_plan_result(prior_run)
                return {
                    **stored,
                    "ok": prior_run["status"] == "completed",
                    "auto_plan_key": run_key,
                    "status": prior_run["status"],
                    "idempotent_replay": True,
                    "input_digest": input_digest,
                    "error": prior_run["error_message"] or "",
                }

            run_id = ScheduleRevisionRepository.create_auto_plan_run(
                run_key, effective_start, input_digest, input_json,
                created_by=actor_id, db=txn,
            )
            results = []
            errors = []
            # Keep generated exclusive-node segments visible to later orders
            # in this queue. Published compatibility rows are intentionally
            # preserved, so they cannot represent a newly generated draft.
            batch_occupancy = {}
            queue_order_ids = tuple(int(order["id"]) for order in queue)
            published_order_ids = {
                int(row["id"])
                for row in txn.execute(
                    "SELECT id FROM orders WHERE current_schedule_revision_id IS NOT NULL"
                ).fetchall()
            }.intersection(queue_order_ids)
            for order in queue:
                order_id = int(order["id"])
                order_run_key = f"{run_key}:{order_id}"
                try:
                    generated = ScheduleCapacityService.generate_order_schedule(
                        order_id,
                        start_date=effective_start,
                        schedule_run_key=order_run_key,
                        actor_id=actor_id,
                        db=txn,
                        planning_now=effective_now,
                        additional_occupancy=batch_occupancy,
                    )
                    if order_id in published_order_ids:
                        occupancy_key = (
                            "production_node_id"
                            if getattr(config, "PRODUCTION_NODE_ENGINE_ENABLED", False)
                            else "process_line_id"
                        )
                        for resource_id, intervals in (
                            ScheduleCapacityService._exclusive_batch_occupancy(
                                generated, occupancy_key
                            ).items()
                        ):
                            batch_occupancy.setdefault(resource_id, []).extend(intervals)
                    results.append({
                        "order_id": order_id,
                        "order_no": order.get("order_no") or "",
                        "status": generated.get("status", "completed"),
                        "ok": bool(generated.get("ok")),
                        "schedule_run_key": generated.get("schedule_run_key", order_run_key),
                        "schedule_revision_id": generated.get("schedule_revision_id"),
                        "revision_status": generated.get("revision_status"),
                        "operations": generated.get("operations", []),
                    })
                except Exception as exc:
                    message = str(exc) or "自动排程失败"
                    errors.append({"order_id": order_id, "order_no": order.get("order_no") or "", "error": message})
                    results.append({
                        "order_id": order_id,
                        "order_no": order.get("order_no") or "",
                        "status": "failed",
                        "ok": False,
                        "schedule_run_key": order_run_key,
                        "error": message,
                        "operations": [],
                    })

            overall_status = "failed" if errors else "completed"
            result = {
                "ok": not errors,
                "auto_plan_key": run_key,
                "status": overall_status,
                "idempotent_replay": False,
                "input_digest": input_digest,
                "queue_count": len(queue),
                "failed_count": len(errors),
                "orders": results,
            }
            error_message = "; ".join(item["error"] for item in errors)
            ScheduleRevisionRepository.complete_auto_plan_run(
                run_id, overall_status, result, error_message=error_message, db=txn,
            )
            response = result
        if failure:
            raise ValueError(failure)
        return response

    @staticmethod
    def _date(value, label):
        return parse_production_date(value, label)

    @staticmethod
    def _duration_minutes(quantity, standard):
        return ScheduleCapacityAllocationPolicy.duration_minutes(quantity, standard)

    @staticmethod
    def _find_standard(
        db, route_id, route_version_id, process_id, process_version_id,
        product_id, product_code, as_of_date,
    ):
        standard = SchedulePlanningRepository.find_active_standard(
            route_id, route_version_id, process_id, process_version_id,
            product_id, product_code, as_of_date, db,
        )
        # SQLite rows support keyed indexing but not ``get``.  Planning stages
        # and payload builders consume mapping semantics, so normalize the
        # repository fact once at this service boundary (including blocked
        # outcomes where the standard is retained in the diagnostic payload).
        return dict(standard) if standard is not None else None

    @staticmethod
    def _transaction(db=None):
        return ScheduleUnitOfWork.transaction(db)

    @staticmethod
    def _read_transaction(db=None):
        return ScheduleUnitOfWork.read_transaction(db)

    @staticmethod
    def _parse_timestamp(value):
        return parse_database_timestamp(value)

    @staticmethod
    def _format_timestamp(value):
        """Serialize timestamps without losing fractional-minute precision."""
        return format_database_timestamp(value)

    @staticmethod
    def _revision_operations(revision_id, db):
        return ScheduleAssessmentService.revision_operations(revision_id, db)

    _candidate_capacity_intervals = staticmethod(SchedulePlanningAssessment.candidate_capacity_intervals)

    @staticmethod
    def _revision_conflict_input(revision_id, db):
        return ScheduleAssessmentService.revision_conflict_input(revision_id, db)

    @staticmethod
    def _assess_revision_conflicts(revision_id, check_stage, db, *, freeze_risk=False, persist=True, planning_now=None):
        return ScheduleAssessmentService.assess_revision_conflicts(revision_id, check_stage, db, freeze_risk=freeze_risk, persist=persist, planning_now=planning_now)

    @staticmethod
    def _assert_revision_conflict_gate(revision_id, check_stage, db):
        return ScheduleAssessmentService.assert_revision_conflict_gate(revision_id, check_stage, db)

    @staticmethod
    def _merge_intervals(intervals):
        """Merge overlapping/touching occupancy intervals before allocation."""
        return ScheduleCapacityAllocationPolicy.merge_intervals(intervals)

    @staticmethod
    def _calendar_snapshot(calendar, shifts):
        return SchedulePlanningStrategy.calendar_snapshot(calendar, shifts)

    @staticmethod
    def _calendar_slots(db, calendar, shifts, start_date, daily_minutes=None, max_days=3660):
        from modules.domain.schedule_planning import PlanningResourceFacts

        facts = PlanningResourceFacts({}, dict(calendar), tuple(dict(row) for row in shifts),
            tuple(dict(row) for row in SchedulePlanningRepository.list_calendar_exceptions(calendar["id"], db=db)))
        return SchedulePurePlanner.calendar_slots(facts, start_date, daily_minutes, max_days)

    @staticmethod
    def _allocate_on_line(db, calendar, shifts, daily_minutes, earliest, duration, occupied):
        return SchedulePlanningStrategy.allocate_on_line(db, calendar, shifts, daily_minutes, earliest, duration, occupied)

    @staticmethod
    def _allocate_from_slots(slots, earliest, duration, occupied):
        return SchedulePurePlanner.allocate_from_slots(slots, earliest, duration, occupied)

    @staticmethod
    def _allocate_split_on_lines(db, lines, earliest, quantity, standard, occupancy):
        return SchedulePlanningStrategy.allocate_split_on_lines(db, lines, earliest, quantity, standard, occupancy)

    @staticmethod
    def _add_segments_to_occupancy(occupancy, line_id, segments):
        bucket = occupancy.setdefault(line_id, [])
        for segment in segments:
            bucket.append((
                ScheduleCapacityService._parse_timestamp(segment["start_at"]),
                ScheduleCapacityService._parse_timestamp(segment["end_at"]),
            ))

    @staticmethod
    def _add_segments_to_node_occupancy(occupancy, production_node_id, segments):
        """Add node-native intervals while keeping the old line helper intact."""
        bucket = occupancy.setdefault(production_node_id, [])
        for segment in segments:
            bucket.append((
                ScheduleCapacityService._parse_timestamp(segment["start_at"]),
                ScheduleCapacityService._parse_timestamp(segment["end_at"]),
            ))

    @staticmethod
    def _allocate_on_node(db, node, earliest, duration, occupancy):
        return SchedulePlanningStrategy.allocate_on_node(db, node, earliest, duration, occupancy)

    @staticmethod
    def _allocate_split_on_nodes(db, nodes, earliest, quantity, standard, occupancy, *, operation=None, order=None, serial_ids=None, allocation_key_prefix="", return_allocations=False):
        return SchedulePlanningStrategy.allocate_split_on_nodes(
            db, nodes, earliest, quantity, standard, occupancy, operation=operation, order=order,
            serial_ids=serial_ids, allocation_key_prefix=allocation_key_prefix,
            return_allocations=return_allocations,
        )

    @staticmethod
    def _prepare_generation_request(
        order_id, start_date, schedule_run_key, txn, *, persist_bindings=True,
        planning_now=None,
    ):
        order = SchedulePlanningRepository.ensure_order_version_bindings(
            order_id, txn, persist=persist_bindings
        )
        if not order:
            raise ValueError("订单不存在")
        operations = [
            dict(row)
            for row in SchedulePlanningRepository.find_order_operations(order_id, db=txn)
        ]
        if not persist_bindings:
            bindings = SchedulePlanningRepository.resolve_order_operation_bindings(
                order_id, order["route_version_id"], txn
            )
            for operation in operations:
                operation.update(bindings.get(int(operation["order_process_id"]), {}))
                operation["route_version_id"] = order["route_version_id"]
                operation["route_name_snapshot"] = order["route_name_snapshot"]
        if not operations:
            raise ValueError("订单没有工序，无法生成排程")
        order_serial_ids = SchedulePlanningRepository.list_order_serial_ids(order_id, db=txn)
        cursor = ScheduleCapacityService._date(
            start_date or order["plan_start"], "计划开始日期"
        )
        # Standards are effective for this planning run, not retroactively for
        # an old plan start retained by an in-progress order.
        effective_now = resolve_planning_now(planning_now)
        standard_as_of = max(cursor.date(), effective_now.date()).strftime("%Y-%m-%d")
        run_key = (
            schedule_run_key
            or effective_now.strftime("schedule-%Y%m%d%H%M%S")
        ).strip()
        if not run_key:
            raise ValueError("排程幂等键不能为空")
        return {
            "order": order,
            "operations": operations,
            "order_serial_ids": order_serial_ids,
            "cursor": cursor,
            "standard_as_of": standard_as_of,
            "run_key": run_key,
        }

    @staticmethod
    def _replay_generation_if_present(order_id, run_key, txn):
        prior_run = ScheduleRevisionRepository.find_run(run_key, txn)
        if not prior_run:
            return None
        if prior_run["order_id"] != order_id:
            raise ValueError("排程幂等键已被其他订单使用")
        replay_payload = decode_run_result_payload(prior_run)
        replay = replay_payload["operations"]
        revision = ScheduleRevisionRepository.find_revision_by_run(
            prior_run["id"], db=txn
        )
        planning_summary = None
        planning_manifest = None
        if revision:
            evidence = ScheduleEvidenceRepository.get_planning_evidence(
                revision["id"], db=txn
            )
            if evidence:
                planning_summary = evidence.get("planning_summary")
                planning_manifest = evidence.get("planning_manifest")
        return {
            "ok": prior_run["status"] == "completed",
            "order_id": order_id,
            "schedule_run_key": run_key,
            "idempotent_replay": True,
            "status": prior_run["status"],
            "error": prior_run["error_message"] or "",
            "schedule_revision_id": revision["id"] if revision else None,
            "revision_status": revision["status"] if revision else None,
            "operations": replay,
            "planning_summary": planning_summary or replay_payload.get("planning_summary") or summarize_schedule_result(
                {"operations": replay},
                input_digest=(
                    prior_run["input_digest"]
                    if "input_digest" in prior_run.keys()
                    else ""
                ),
            ),
            "planning_manifest": planning_manifest or replay_payload.get("planning_manifest") or {},
        }

    @staticmethod
    def _create_generation_ledger(order_id, run_key, cursor, actor_id, txn):
        run_id = ScheduleRevisionRepository.create_run(
            order_id, run_key, cursor.strftime("%Y-%m-%d"), txn
        )
        # Create the revision before the savepoint so a failed generation is
        # retained as an auditable cancelled revision.
        revision_id = ScheduleRevisionRepository.create_revision(
            order_id, run_id, run_key, txn, created_by=actor_id,
        )
        return run_id, revision_id

    @staticmethod
    def _load_generation_occupancy(order_id, use_node_engine, txn):
        occupancy = {}
        occupancy_rows = (
            ProductionNodeRepository.list_node_occupancy(order_id, db=txn)
            if use_node_engine
            else SchedulePlanningRepository.list_line_occupancy(order_id, txn)
        )
        occupancy_key = "production_node_id" if use_node_engine else "process_line_id"
        for row in occupancy_rows:
            start_at = ScheduleCapacityService._parse_timestamp(row["start_at"])
            end_at = ScheduleCapacityService._parse_timestamp(row["end_at"])
            resource_id = row[occupancy_key]
            if resource_id is not None and start_at and end_at and end_at > start_at:
                occupancy.setdefault(int(resource_id), []).append((start_at, end_at))
        return occupancy

    @staticmethod
    def _exclusive_batch_occupancy(generated, occupancy_key):
        """Return only valid intervals assigned to exclusive-capacity nodes."""
        additions = {}
        for operation in generated.get("operations") or ():
            if operation.get("status") != "planned":
                continue
            if operation.get("execution_mode") in {"outsourced", "non_scheduled"}:
                continue
            node_modes = {
                int(node["production_node_id"]): node.get("capacity_mode") or "exclusive"
                for node in operation.get("nodes") or ()
                if node.get("production_node_id") not in (None, "")
            }
            if operation.get("production_node_id") not in (None, ""):
                node_modes.setdefault(
                    int(operation["production_node_id"]),
                    operation.get("capacity_mode_snapshot") or "exclusive",
                )
            for segment in operation.get("segments") or ():
                resource_id = segment.get(occupancy_key)
                if resource_id in (None, ""):
                    resource_id = operation.get(occupancy_key)
                if resource_id in (None, ""):
                    continue
                resource_id = int(resource_id)
                capacity_mode = node_modes.get(
                    resource_id,
                    operation.get("capacity_mode_snapshot") or "exclusive",
                )
                if capacity_mode != "exclusive":
                    continue
                start = ScheduleCapacityService._parse_timestamp(
                    segment.get("start_at") or segment.get("segment_start_at")
                )
                end = ScheduleCapacityService._parse_timestamp(
                    segment.get("end_at") or segment.get("segment_end_at")
                )
                if start and end and end > start:
                    additions.setdefault(resource_id, []).append((start, end))
        return additions

    @staticmethod
    def _finalize_generation(
        *,
        order_id,
        order,
        result,
        blocked,
        run_id,
        revision_id,
        run_key,
        facts_snapshot,
        txn,
        input_digest=None,
        planning_now=None,
    ):
        planned = [
            row for row in result
            if row.get("status") == "planned"
            and (row.get("process_line_id") or row.get("production_node_id"))
        ]
        if planned and not order["current_schedule_revision_id"]:
            first_start = min(row["plan_start"] for row in planned)
            last_end = max(row["plan_end"] for row in planned)
            ScheduleRevisionRepository.update_order_summary(
                order_id, first_start, last_end, txn
            )
        revision_payload = json.dumps(
            result, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        revision_digest = hashlib.sha256(revision_payload.encode("utf-8")).hexdigest()
        ScheduleRevisionRepository.set_revision_digest(
            revision_id, revision_digest, txn
        )
        ScheduleRevisionRepository.finalize_revision_content_digest(
            revision_id, db=txn
        )
        conflict_assessment = SchedulePlanningStrategy.assess_revision_conflicts(
            revision_id, "generation", txn, freeze_risk=True,
            planning_now=planning_now,
        )
        effective_input_digest = input_digest or facts_snapshot.input_digest
        evidence = build_planning_evidence(
            facts_snapshot,
            result,
            input_digest=effective_input_digest,
            conflicts=conflict_assessment["conflicts"],
            risk=conflict_assessment["risk"],
        )
        summary = evidence.summary_dict()
        manifest = evidence.manifest
        ScheduleEvidenceRepository.save_planning_evidence(
            revision_id,
            summary,
            manifest.as_dict(),
            db=txn,
        )
        ScheduleRevisionRepository.clear_initial_schedule_replan_flag(
            order_id,
            blocked=blocked,
            current_revision_id=order["current_schedule_revision_id"],
            db=txn,
        )
        ScheduleRevisionRepository.complete_run(run_id, "completed", result, db=txn)
        return {
            "ok": True,
            "order_id": order_id,
            "schedule_run_key": run_key,
            "idempotent_replay": False,
            "status": "completed",
            "schedule_revision_id": revision_id,
            "revision_status": "draft",
            "operations": result,
            "conflicts": conflict_assessment["conflicts"],
            "risk": conflict_assessment["risk"],
            "planning_summary": summary,
            "planning_manifest": manifest.as_dict(),
        }

    @staticmethod
    def _fail_generation(*, run_id, revision_id, error, txn):
        txn.execute("ROLLBACK TO SAVEPOINT schedule_generation")
        txn.execute("RELEASE SAVEPOINT schedule_generation")
        ScheduleRevisionRepository.cancel_revision(revision_id, txn)
        ScheduleRevisionRepository.complete_run(
            run_id, "failed", [], str(error), db=txn
        )

    @staticmethod
    def persist_operation_payload(payload, txn, *, persist=True):
        return ScheduleUnitOfWork.persist_operation_payload(payload, txn, persist=persist)

    @staticmethod
    def _materialize_generation_result(result, run_id, revision_id, run_key, txn):
        """Materialize a read-planned result during the short write phase."""
        materialized = []
        for raw in result:
            payload = dict(raw)
            payload.pop("id", None)
            payload["schedule_run_id"] = run_id
            payload["schedule_revision_id"] = revision_id
            payload["schedule_run_key"] = run_key
            payload = ScheduleCapacityService.persist_operation_payload(
                payload, txn, persist=True
            )
            materialized.append(payload)
        return materialized

    @staticmethod
    def _record_stale_generation(
        *, order_id, run_key, cursor, actor_id, expected_digest, actual_digest, txn
    ):
        """Keep a failed stale-input attempt fully auditable without publishing it."""
        run_id, revision_id = ScheduleCapacityService._create_generation_ledger(
            order_id, run_key, cursor, actor_id, txn
        )
        ScheduleRevisionRepository.update_run_input(
            run_id, input_digest=expected_digest, trigger_source="planning_facts", db=txn
        )
        summary = {
            "status": "STALE_INPUT",
            "blocked": True,
            "stale_input": True,
            "expected_digest": expected_digest,
            "actual_digest": actual_digest,
            "reason": "规划期间业务事实发生变化，未写入排程版本",
        }
        manifest = {
            "input_digest": expected_digest,
            "status": "STALE_INPUT",
            "actual_digest": actual_digest,
        }
        ScheduleEvidenceRepository.save_planning_evidence(
            revision_id, summary, manifest, db=txn
        )
        ScheduleRevisionRepository.cancel_revision(revision_id, txn)
        ScheduleRevisionRepository.complete_run(
            run_id,
            "failed",
            [],
            "STALE_INPUT: 规划事实已变化",
            db=txn,
        )
        return {
            "ok": False,
            "order_id": order_id,
            "schedule_run_key": run_key,
            "status": "STALE_INPUT",
            "error": "STALE_INPUT: 规划事实已变化",
            "schedule_revision_id": revision_id,
            "revision_status": "cancelled",
            "operations": [],
            "planning_summary": summary,
            "planning_manifest": manifest,
        }
    @staticmethod
    def _plan_generation_operations(
        *,
        order_id,
        order,
        operations,
        order_serial_ids,
        cursor,
        standard_as_of,
        run_key,
        run_id,
        revision_id,
        use_node_engine,
        occupancy,
        txn,
        persist=True,
    ):
        """Delegate generation decisions to the shared immutable pure planner."""
        from modules.services.schedule_planning_facts import (
            SchedulePlanningFactsLoader,
        )

        facts = PlanningFactsSnapshot.create(
            order={**dict(order), "id": order_id},
            operations=tuple(dict(item) for item in operations),
            order_serial_ids=tuple(order_serial_ids),
            cursor=cursor,
            standard_as_of=standard_as_of,
            use_node_engine=use_node_engine,
            occupancy=occupancy,
        )
        operation_facts = SchedulePlanningFactsLoader.generation(
            dict(facts.order),
            tuple(dict(item) for item in facts.operations),
            cursor,
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
            mode="generation",
        )
        return decision.operation_dicts(), decision.blocked, decision.final_cursor

    @staticmethod
    def generate_order_schedule(order_id, start_date=None, schedule_run_key="", db=None,
                                actor_id=None, use_node_engine_override=None,
                                planning_now=None, additional_occupancy=None):
        # Phase 1: a deferred read snapshot.  No schedule rows or ledgers are
        # written while matching standards and allocating capacity.
        use_node_engine = (
            bool(getattr(config, "PRODUCTION_NODE_ENGINE_ENABLED", False))
            if use_node_engine_override is None
            else bool(use_node_engine_override)
        )
        with ScheduleCapacityService._read_transaction(db) as snapshot_db:
            request = ScheduleCapacityService._prepare_generation_request(
                order_id,
                start_date,
                schedule_run_key,
                snapshot_db,
                persist_bindings=False,
                planning_now=planning_now,
            )
            order = request["order"]
            operations = request["operations"]
            order_serial_ids = request["order_serial_ids"]
            cursor = request["cursor"]
            standard_as_of = request["standard_as_of"]
            run_key = request["run_key"]
            replay = ScheduleCapacityService._replay_generation_if_present(
                order_id, run_key, snapshot_db
            )
            if replay is not None:
                return replay
            planning_digest = SchedulePlanningRepository.planning_input_digest(
                order_id, db=snapshot_db
            )
            occupancy = ScheduleCapacityService._load_generation_occupancy(
                order_id, use_node_engine, snapshot_db
            )
            for resource_id, intervals in (additional_occupancy or {}).items():
                occupancy.setdefault(int(resource_id), []).extend(intervals)
            planning_occupancy = occupancy
            facts_snapshot = PlanningFactsSnapshot.create(
                order=dict(order),
                operations=tuple(dict(item) for item in operations),
                order_serial_ids=tuple(order_serial_ids),
                cursor=cursor,
                standard_as_of=standard_as_of,
                use_node_engine=use_node_engine,
                occupancy=occupancy,
            )
            result, blocked, _ = ScheduleCapacityService._plan_generation_operations(
                order_id=order_id,
                order=order,
                operations=operations,
                order_serial_ids=order_serial_ids,
                cursor=cursor,
                standard_as_of=standard_as_of,
                run_key=run_key,
                run_id=0,
                revision_id=0,
                use_node_engine=use_node_engine,
                occupancy=occupancy,
                txn=snapshot_db,
                persist=False,
            )

        # Phase 2: short BEGIN IMMEDIATE.  Re-check the business facts before
        # replacing the compatibility projection and saving all evidence.
        failure = None
        response = None
        with ScheduleCapacityService._transaction(db) as txn:
            replay = ScheduleCapacityService._replay_generation_if_present(
                order_id, run_key, txn
            )
            if replay is not None:
                return replay
            actual_digest = SchedulePlanningRepository.planning_input_digest(
                order_id, db=txn
            )
            if actual_digest != planning_digest:
                return ScheduleCapacityService._record_stale_generation(
                    order_id=order_id,
                    run_key=run_key,
                    cursor=cursor,
                    actor_id=actor_id,
                    expected_digest=planning_digest,
                    actual_digest=actual_digest,
                    txn=txn,
                )
            request = ScheduleCapacityService._prepare_generation_request(
                order_id, start_date, schedule_run_key, txn, persist_bindings=True,
                planning_now=planning_now,
            )
            order = request["order"]
            run_id, revision_id = ScheduleCapacityService._create_generation_ledger(
                order_id, run_key, cursor, actor_id, txn
            )
            try:
                txn.execute("SAVEPOINT schedule_generation")
                ScheduleRevisionRepository.clear_order_schedules(order_id, txn)
                result = ScheduleCapacityService._materialize_generation_result(
                    result, run_id, revision_id, run_key, txn
                )
                facts_snapshot = PlanningFactsSnapshot.create(
                    order=dict(order),
                    operations=tuple(dict(item) for item in request["operations"]),
                    order_serial_ids=tuple(request["order_serial_ids"]),
                    cursor=cursor,
                    standard_as_of=request["standard_as_of"],
                    use_node_engine=use_node_engine,
                    occupancy=planning_occupancy,
                )
                ScheduleRevisionRepository.update_run_input(
                    run_id,
                    input_digest=planning_digest,
                    trigger_source="planning_facts",
                    db=txn,
                )
                response = ScheduleCapacityService._finalize_generation(
                    order_id=order_id,
                    order=order,
                    result=result,
                    blocked=blocked,
                    run_id=run_id,
                    revision_id=revision_id,
                    run_key=run_key,
                    facts_snapshot=facts_snapshot,
                    txn=txn,
                    input_digest=planning_digest,
                    planning_now=planning_now,
                )
                txn.execute("RELEASE SAVEPOINT schedule_generation")
            except Exception as exc:
                ScheduleCapacityService._fail_generation(
                    run_id=run_id, revision_id=revision_id, error=exc, txn=txn
                )
                failure = str(exc)
        if failure:
            raise ValueError(failure)
        return response

    @staticmethod
    def _shadow_operation_payload(operation, shadow_run_key):
        """Remove temporary formal-ledger identifiers from a shadow result."""
        payload = dict(operation)
        for key in ("id", "schedule_run_id", "schedule_revision_id"):
            payload.pop(key, None)
        payload["schedule_run_key"] = shadow_run_key
        payload["shadow_only"] = True
        payload["segments"] = [
            {
                key: value
                for key, value in dict(segment).items()
                if key not in {"id", "schedule_id"}
            }
            for segment in operation.get("segments") or ()
        ]
        payload["allocations"] = [
            {
                key: value
                for key, value in dict(allocation).items()
                if key not in {"id", "schedule_id", "segment_id"}
            }
            for allocation in operation.get("allocations") or ()
        ]
        return payload

    @staticmethod
    def _validate_shadow_operations(operations):
        """Reject quantity loss, serial splitting, and exclusive-node overlap."""
        intervals = {}
        for operation in operations:
            if operation.get("status") != "planned":
                continue
            if operation.get("execution_mode", "internal") in {"outsourced", "non_scheduled"}:
                continue
            node_id = operation.get("production_node_id")
            if node_id is None:
                raise NodeSchedulingError(
                    "NO_COMPATIBLE_NODE", "影子排程的内部工序未分配生产节点",
                    {"order_process_id": operation.get("order_process_id")},
                )
            allocations = operation.get("allocations") or []
            if allocations:
                allocated = sum(int(item.get("quantity") or 0) for item in allocations)
                expected = int(operation.get("quantity") or 0)
                if allocated != expected:
                    raise NodeSchedulingError(
                        "QUANTITY_CONSERVATION_FAILED", "影子排程分配数量不守恒",
                        {
                            "order_process_id": operation.get("order_process_id"),
                            "expected": expected, "actual": allocated,
                        },
                    )
                serial_nodes = {}
                for allocation in allocations:
                    serial_id = str(allocation.get("serial_id") or "").strip()
                    if not serial_id:
                        continue
                    serial_nodes.setdefault(serial_id, set()).add(
                        int(allocation["production_node_id"])
                    )
                split_serials = sorted(
                    serial_id for serial_id, node_ids in serial_nodes.items()
                    if len(node_ids) != 1
                )
                if split_serials:
                    raise NodeSchedulingError(
                        "SERIAL_ITEM_SPLIT_FORBIDDEN", "序列件不能跨生产节点排程",
                        {"serial_ids": split_serials},
                    )
            for segment in operation.get("segments") or ():
                segment_node_id = segment.get("production_node_id")
                start = ScheduleCapacityService._parse_timestamp(segment.get("start_at"))
                end = ScheduleCapacityService._parse_timestamp(segment.get("end_at"))
                if segment_node_id is None or start is None or end is None or end <= start:
                    raise NodeSchedulingError(
                        "NODE_SHADOW_FACT_INVALID", "影子排程分段事实不完整",
                        {"order_process_id": operation.get("order_process_id")},
                    )
                intervals.setdefault(int(segment_node_id), []).append(
                    (start, end, operation.get("order_process_id"))
                )
        for node_id, node_intervals in intervals.items():
            node_intervals.sort(key=lambda item: (item[0], item[1], item[2] or 0))
            for previous, current in zip(node_intervals, node_intervals[1:]):
                if current[0] < previous[1]:
                    raise NodeSchedulingError(
                        "NODE_CAPACITY_CONFLICT", "影子排程存在生产节点时间冲突",
                        {
                            "production_node_id": node_id,
                            "first_order_process_id": previous[2],
                            "second_order_process_id": current[2],
                        },
                    )

    @staticmethod
    def generate_shadow_order_schedule(
        order_id, shadow_run_key, start_date=None, actor_id=None, db=None,
    ):
        """Compute with the node engine while keeping formal schedules unchanged."""
        ScheduleCapacityService._assert_node_write_enabled()
        key = str(shadow_run_key or "").strip()
        if len(key) < 8 or len(key) > 128:
            raise ValueError("影子排程幂等键长度必须为8到128个字符")
        try:
            actor = int(actor_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("影子排程必须记录实际操作人") from exc
        if actor <= 0:
            raise ValueError("影子排程必须记录实际操作人")

        with ScheduleCapacityService._transaction(db) as txn:
            order = SchedulePlanningRepository.find_order(order_id, txn)
            if order is None:
                raise ValueError("订单不存在")
            effective_start = ScheduleCapacityService._date(
                start_date or order["plan_start"], "计划开始日期"
            ).strftime("%Y-%m-%d")
            formal_digest = SchedulePlanningRepository.formal_schedule_digest(
                order_id, db=txn
            )
            request_payload = {
                "algorithm": "production-node-shadow-v1",
                "order_id": int(order_id),
                "start_date": effective_start,
                "formal_schedule_digest": formal_digest,
            }
            encoded_request = json.dumps(
                request_payload, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            )
            request_digest = hashlib.sha256(encoded_request.encode("utf-8")).hexdigest()
            prior = ScheduleRevisionRepository.find_shadow_run(key, db=txn)
            if prior is not None:
                if prior["request_digest"] != request_digest:
                    raise NodeSchedulingError(
                        "IDEMPOTENCY_CONFLICT", "影子排程幂等键已被不同输入使用",
                        {"shadow_run_key": key},
                    )
                stored = ScheduleRevisionRepository.shadow_run_result(prior)
                return {
                    **stored,
                    "shadow_run_id": int(prior["id"]),
                    "result_digest": prior["result_digest"],
                    "idempotent_replay": True,
                }

            txn.execute("SAVEPOINT production_node_shadow_compute")
            try:
                generated = ScheduleCapacityService.generate_order_schedule(
                    order_id,
                    start_date=effective_start,
                    schedule_run_key=f"shadow:{key}",
                    actor_id=actor,
                    db=txn,
                    use_node_engine_override=True,
                )
                operations = [
                    ScheduleCapacityService._shadow_operation_payload(operation, key)
                    for operation in generated.get("operations") or ()
                ]
                ScheduleCapacityService._validate_shadow_operations(operations)
            finally:
                txn.execute("ROLLBACK TO SAVEPOINT production_node_shadow_compute")
                txn.execute("RELEASE SAVEPOINT production_node_shadow_compute")

            after_digest = SchedulePlanningRepository.formal_schedule_digest(
                order_id, db=txn
            )
            if after_digest != formal_digest:
                raise NodeSchedulingError(
                    "SHADOW_ISOLATION_FAILED", "影子排程改变了正式排程事实",
                    {"before": formal_digest, "after": after_digest},
                )
            result = {
                "ok": True,
                "shadow_only": True,
                "engine": "production_node",
                "order_id": int(order_id),
                "shadow_run_key": key,
                "requested_start_date": effective_start,
                "status": "completed",
                "request_digest": request_digest,
                "formal_schedule_digest": formal_digest,
                "idempotent_replay": False,
                "operations": operations,
            }
            run_id, result_digest = ScheduleRevisionRepository.create_shadow_run(
                key, order_id, effective_start, request_digest, result, operations,
                actor, db=txn,
            )
            result["shadow_run_id"] = run_id
            result["result_digest"] = result_digest
            # The stored JSON intentionally excludes database-generated ids;
            # callers receive them as envelope metadata only.
            return result

    @staticmethod
    def list_shadow_runs(order_id, limit=100, db=None):
        bounded = ScheduleCapacityService._limit(limit, default=100)
        with ScheduleCapacityService._transaction(db) as txn:
            if SchedulePlanningRepository.find_order(order_id, txn) is None:
                raise ValueError("订单不存在")
            runs = [
                dict(row) for row in ScheduleRevisionRepository.list_shadow_runs(
                    order_id, bounded, db=txn
                )
            ]
            for run in runs:
                run.pop("result_json", None)
            return {"ok": True, "order_id": int(order_id), "runs": runs}

    @staticmethod
    def get_shadow_run(run_id, db=None):
        with ScheduleCapacityService._transaction(db) as txn:
            run = ScheduleRevisionRepository.get_shadow_run(run_id, db=txn)
            if run is None:
                raise NotFoundError("影子排程运行不存在")
            result = ScheduleRevisionRepository.shadow_run_result(run)
            return {
                **result,
                "shadow_run_id": int(run["id"]),
                "result_digest": run["result_digest"],
                "created_by": run["created_by"],
                "created_by_name": run["created_by_name"] or "",
                "created_at": run["created_at"],
                "completed_at": run["completed_at"],
            }

    @staticmethod
    def _locked_task_segments(lock, payload):
        return SchedulePurePlanner.locked_task_segments(lock, payload)

    @staticmethod
    def dynamic_replan_order(order_id, start_at=None, schedule_run_key="", reason="", db=None,
                             actor_id=None):
        from modules.services.schedule_replan_service import ScheduleReplanService

        return ScheduleReplanService.dynamic_replan_order(
            order_id,
            start_at=start_at,
            schedule_run_key=schedule_run_key,
            reason=reason,
            db=db,
            actor_id=actor_id,
            capacity_service=ScheduleCapacityService,
        )

    @staticmethod
    def list_downtime_events(production_node_id=None, process_line_id=None, start_at="",
                             end_at="", limit=1000, db=None):
        limit = ScheduleCapacityService._limit(limit, default=1000)
        if production_node_id not in (None, ""):
            if isinstance(production_node_id, bool):
                raise ValueError("生产节点参数不正确")
            try:
                production_node_id = int(production_node_id)
            except (TypeError, ValueError) as exc:
                raise ValueError("生产节点参数不正确") from exc
            if production_node_id <= 0:
                raise ValueError("生产节点参数不正确")
            # Node-native filters take precedence when both are supplied.
            process_line_id = None
        elif process_line_id not in (None, ""):
            if isinstance(process_line_id, bool):
                raise ValueError("Legacy 产线参数不正确")
            try:
                process_line_id = int(process_line_id)
            except (TypeError, ValueError) as exc:
                raise ValueError("Legacy 产线参数不正确") from exc
            if process_line_id <= 0:
                raise ValueError("Legacy 产线参数不正确")

        if start_at:
            start_at = format_database_timestamp(
                parse_api_timestamp(start_at, "停机查询开始时间")
            )
        if end_at:
            end_at = format_database_timestamp(
                parse_api_timestamp(end_at, "停机查询结束时间")
            )

        with ScheduleCapacityService._transaction(db) as txn:
            rows = [dict(row) for row in SchedulePlanningRepository.list_downtime_events(
                process_line_id=process_line_id,
                production_node_id=production_node_id,
                start_at=start_at,
                end_at=end_at,
                limit=limit,
                db=txn,
            )]
            if (
                process_line_id not in (None, "")
                and bool(getattr(config, "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED", False))
            ):
                mapped_node = ProductionNodeRepository.find_node_by_legacy_line_id(
                    process_line_id, db=txn
                )
                node_rows = []
                if mapped_node:
                    node_rows = [
                        dict(row)
                        for row in SchedulePlanningRepository.list_downtime_events(
                            production_node_id=mapped_node["id"],
                            start_at=start_at,
                            end_at=end_at,
                            limit=limit,
                            db=txn,
                        )
                    ]

                def normalized(events):
                    return [
                        {
                            "id": int(item["id"]),
                            "start_at": item["start_at"],
                            "end_at": item["end_at"],
                            "reason": item.get("reason") or "",
                            "status": item.get("status") or "",
                        }
                        for item in events
                    ]

                legacy_payload = {"events": normalized(rows)}
                node_payload = {"events": normalized(node_rows)}
                ProductionNodeRepository.record_compatibility_observation(
                    scope="downtime_legacy_filter",
                    source_id=process_line_id,
                    legacy_payload=legacy_payload,
                    node_payload=node_payload,
                    difference={
                        "legacy_filter_used": True,
                        "process_line_id": process_line_id,
                        "production_node_id": mapped_node["id"] if mapped_node else None,
                        "legacy_event_ids": [item["id"] for item in legacy_payload["events"]],
                        "node_event_ids": [item["id"] for item in node_payload["events"]],
                    },
                    db=txn,
                )
        return {"ok": True, "events": rows}

    @staticmethod
    def create_downtime_event(production_node_id, start_at, end_at, reason="", created_by=None,
                              db=None):
        ScheduleCapacityService._assert_node_write_enabled()
        start = parse_database_timestamp(start_at)
        end = parse_database_timestamp(end_at)
        if not start or not end or end <= start:
            raise ValueError("停机开始和结束时间必须有效且结束时间晚于开始时间")
        reason = str(reason or "").strip()
        if len(reason) > 512:
            raise ValueError("停机原因不能超过 512 个字符")
        with ScheduleCapacityService._transaction(db) as txn:
            node = ProductionNodeService.resolve_downtime_target(
                production_node_id, txn
            )
            event_id = SchedulePlanningRepository.create_downtime_event(
                node["id"],
                ScheduleCapacityService._format_timestamp(start),
                ScheduleCapacityService._format_timestamp(end), reason, created_by,
                process_line_id=node.get("legacy_process_line_id"), db=txn,
            )
            row = SchedulePlanningRepository.find_downtime_event(event_id, db=txn)
            affected_order_ids = SchedulePlanningRepository.affected_order_ids_for_downtime(
                node["id"],
                ScheduleCapacityService._format_timestamp(start),
                ScheduleCapacityService._format_timestamp(end),
                db=txn,
            )
            for order_id in affected_order_ids:
                ScheduleEvidenceRepository.record_replan_trigger(
                    order_id,
                    "downtime_created",
                    "schedule_downtime_event",
                    event_id,
                    "生产节点新增停机时段",
                    details={
                        "production_node_id": int(node["id"]),
                        "start_at": ScheduleCapacityService._format_timestamp(start),
                        "end_at": ScheduleCapacityService._format_timestamp(end),
                        "reason": reason,
                    },
                    created_by=created_by,
                    db=txn,
                )
        return {"ok": True, "event": dict(row), "affected_order_ids": affected_order_ids}

    @staticmethod
    def cancel_downtime_event(event_id, actor_id=None):
        ScheduleCapacityService._assert_node_write_enabled()
        try:
            event_id = int(event_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("停机事件 ID 不正确") from exc
        with BaseService.transaction() as txn:
            event = SchedulePlanningRepository.find_downtime_event(event_id, db=txn)
            if event is None or event["status"] != "active":
                raise ValueError("停机事件不存在或已取消")
            affected_order_ids = SchedulePlanningRepository.affected_order_ids_for_downtime(
                event["production_node_id"], event["start_at"], event["end_at"], db=txn
            )
            if SchedulePlanningRepository.cancel_downtime_event(event_id, db=txn) != 1:
                raise ValueError("停机事件不存在或已取消")
            for order_id in affected_order_ids:
                ScheduleEvidenceRepository.record_replan_trigger(
                    order_id,
                    "downtime_cancelled",
                    "schedule_downtime_event",
                    event_id,
                    "生产节点停机时段已取消",
                    details={
                        "production_node_id": int(event["production_node_id"]),
                        "start_at": event["start_at"],
                        "end_at": event["end_at"],
                    },
                    created_by=actor_id,
                    db=txn,
                )
        return {"ok": True, "event_id": event_id, "status": "cancelled",
                "affected_order_ids": affected_order_ids}

    @staticmethod
    def list_order_schedule(order_id, limit=500):
        return ScheduleQueryService.list_order_schedule(order_id, limit)

    @staticmethod
    def list_order_revisions(order_id, limit=100):
        return ScheduleQueryService.list_order_revisions(order_id, limit)

    @staticmethod
    def get_revision(revision_id, limit=1000):
        return ScheduleQueryService.get_revision(revision_id, limit)

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
    def _record_workflow_event(db, *, revision_id, revision_item_id, event_type,
                               actor_id, reason, before, after, digest, key):
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

    # Compatibility facade: the revision workflow now lives in
    # ScheduleRevisionService. Keep historical callers stable while ensuring
    # runtime behavior is implemented by the extracted workflow service.
    @staticmethod
    def lock_schedule_item(revision_item_id, reason, idempotency_key, actor_id, db=None):
        from modules.services.schedule_revision_service import ScheduleRevisionService

        return ScheduleRevisionService.lock_schedule_item(
            revision_item_id, reason, idempotency_key, actor_id, db=db,
            capacity_service=ScheduleCapacityService,
        )

    @staticmethod
    def unlock_schedule_item(revision_item_id, reason, idempotency_key, actor_id, db=None):
        from modules.services.schedule_revision_service import ScheduleRevisionService

        return ScheduleRevisionService.unlock_schedule_item(
            revision_item_id, reason, idempotency_key, actor_id, db=db,
            capacity_service=ScheduleCapacityService,
        )

    @staticmethod
    def adjust_schedule_item(
        revision_item_id, production_node_id, planned_start_at,
        reason, row_version, idempotency_key, actor_id, db=None,
    ):
        from modules.services.schedule_revision_service import ScheduleRevisionService

        return ScheduleRevisionService.adjust_schedule_item(
            revision_item_id, production_node_id, planned_start_at,
            reason, row_version, idempotency_key, actor_id, db=db,
            capacity_service=ScheduleCapacityService,
        )

    @staticmethod
    def submit_revision(revision_id, reason, idempotency_key, actor_id, db=None):
        from modules.services.schedule_revision_service import ScheduleRevisionService

        return ScheduleRevisionService.submit_revision(
            revision_id, reason, idempotency_key, actor_id, db=db,
            capacity_service=ScheduleCapacityService,
        )

    @staticmethod
    def approve_revision(revision_id, reason, idempotency_key, actor_id, db=None):
        from modules.services.schedule_revision_service import ScheduleRevisionService

        return ScheduleRevisionService.approve_revision(
            revision_id, reason, idempotency_key, actor_id, db=db,
            capacity_service=ScheduleCapacityService,
        )

    @staticmethod
    def reject_revision(revision_id, reason, idempotency_key, actor_id, db=None):
        from modules.services.schedule_revision_service import ScheduleRevisionService

        return ScheduleRevisionService.reject_revision(
            revision_id, reason, idempotency_key, actor_id, db=db,
            capacity_service=ScheduleCapacityService,
        )

    @staticmethod
    def publish_revision(revision_id, reason, idempotency_key, actor_id, db=None):
        from modules.services.schedule_revision_service import ScheduleRevisionService

        return ScheduleRevisionService.publish_revision(
            revision_id, reason, idempotency_key, actor_id, db=db,
            capacity_service=ScheduleCapacityService,
        )

    @staticmethod
    def list_schedules(limit=500):
        return ScheduleQueryService.list_schedules(limit)

    @staticmethod
    def audit_schedule_capacity(limit=1000, now=None):
        return ScheduleQueryService.audit_schedule_capacity(limit, now)
