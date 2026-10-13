"""Repository adapters that resolve immutable facts for the pure planner."""

from modules.domain.schedule_dynamic_replan import ScheduleDynamicReplanPolicy
from modules.domain.schedule_planning import PlanningOperationFacts
from modules.repositories.production_node_repository import ProductionNodeRepository
from modules.repositories.schedule_planning_repository import SchedulePlanningRepository
from modules.services.schedule_planning_strategy import SchedulePlanningStrategy


class SchedulePlanningFactsLoader:
    """Load persistence facts without making any planning decision."""

    @staticmethod
    def _resources(operation, order, cursor, use_node_engine, db):
        if use_node_engine:
            rows = ProductionNodeRepository.list_active_nodes_for_process(
                operation["process_id"], db=db
            )
        else:
            rows = [
                dict(row)
                for row in SchedulePlanningRepository.list_process_lines(
                    operation["process_id"], db=db
                )
                if row["status"] == "active"
            ]
        return tuple(
            SchedulePlanningStrategy.load_resource_facts(
                row, db, use_node_engine=use_node_engine
            )
            for row in rows
        )

    @staticmethod
    def generation(order, operations, cursor, standard_as_of, use_node_engine, db):
        result = []
        quantity = int(order.get("quantity") or 0)
        for raw in operations:
            operation = dict(raw)
            completed = max(int(operation.get("completed") or 0), 0)
            rework = max(int(operation.get("rework") or 0), 0)
            remaining = max(quantity - completed, 0) + rework
            result.append(
                PlanningOperationFacts(
                    operation=operation,
                    remaining_quantity=remaining,
                    completed_quantity=completed,
                    rework_quantity=rework,
                    execution_policy=dict(
                        SchedulePlanningRepository.find_execution_policy(
                            operation.get("route_version_id"),
                            operation.get("process_version_id"),
                            db,
                        )
                        or {}
                    ),
                    standard=None,
                    standard_candidates=tuple(dict(row) for row in SchedulePlanningRepository.list_active_standard_candidates(operation["process_id"], db)),
                    resources=SchedulePlanningFactsLoader._resources(
                        operation, order, cursor, use_node_engine, db
                    ),
                    previous={},
                    locked_task={},
                )
            )
        return tuple(result)

    @staticmethod
    def replan(
        order,
        context,
        active_locks,
        cursor,
        standard_as_of,
        use_node_engine,
        db,
    ):
        prior_by_operation = {
            int(row["order_process_id"]): dict(row)
            for row in context["prior_schedules"]
        }
        result = []
        for raw in context["operations"]:
            operation = dict(raw)
            baseline = ScheduleDynamicReplanPolicy.operation_baseline(operation)
            lock = dict(active_locks.get(int(operation["order_process_id"])) or {})
            overrides = (
                [
                    dict(row)
                    for row in ProductionNodeRepository.list_node_calendar_overrides(
                        lock["production_node_id"], db=db
                    )
                ]
                if use_node_engine and lock.get("production_node_id") is not None
                else []
            )
            result.append(
                PlanningOperationFacts(
                    operation=operation,
                    remaining_quantity=baseline["remaining_quantity"],
                    completed_quantity=baseline["completed_quantity"],
                    rework_quantity=baseline["rework_quantity"],
                    execution_policy=dict(
                        SchedulePlanningRepository.find_execution_policy(
                            operation.get("route_version_id")
                            or order.get("route_version_id"),
                            operation.get("process_version_id"),
                            db,
                        )
                        or {}
                    ),
                    standard=None,
                    standard_candidates=tuple(dict(row) for row in SchedulePlanningRepository.list_active_standard_candidates(operation["process_id"], db)),
                    resources=SchedulePlanningFactsLoader._resources(
                        operation, order, cursor, use_node_engine, db
                    ),
                    previous=prior_by_operation.get(
                        int(operation["order_process_id"]), {}
                    ),
                    locked_task=lock,
                    locked_overrides=tuple(overrides),
                    downtime=tuple(dict(row) for row in context["downtime"]),
                )
            )
        return tuple(result)


__all__ = ["SchedulePlanningFactsLoader"]
