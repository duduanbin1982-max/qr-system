"""Schedule operations adapter. Internal APIs never escape this module."""
from contextlib import contextmanager
from threading import RLock

from .operations_dto import ScheduleOperationError, detach_result


_FLAG_LOCK = RLock()
_SCHEDULE_FLAGS = frozenset({
    "PRODUCTION_NODE_QUERY_ENABLED",
    "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED",
    "PRODUCTION_NODE_WRITE_ENABLED",
    "PRODUCTION_NODE_ENGINE_ENABLED",
    "LEGACY_PROCESS_LINE_WRITE_BLOCKED",
})


def _schedule_call(callback, *args, **kwargs):
    from modules.domain.production_node_scheduling import NodeSchedulingError

    try:
        return detach_result(callback(*args, **kwargs))
    except NodeSchedulingError as error:
        raise ScheduleOperationError(error.code, error.message, error.details) from error


class ScheduleOperations:
    @staticmethod
    @contextmanager
    def schedule_flags(**values):
        """CLI replica overrides are scoped and restored, including failures."""
        if set(values) - _SCHEDULE_FLAGS or any(type(value) is not bool for value in values.values()):
            raise ValueError("invalid schedule flag override")
        from modules import config

        with _FLAG_LOCK:
            previous = {name: getattr(config, name, False) for name in values}
            try:
                for name, value in values.items():
                    setattr(config, name, value)
                yield
            finally:
                for name, value in previous.items():
                    setattr(config, name, value)

    @staticmethod
    def approved_production_node_counts():
        from modules.migration_production_nodes import APPROVED_PRODUCTION_NODE_COUNTS

        return dict(APPROVED_PRODUCTION_NODE_COUNTS)

    @staticmethod
    def production_node_defaults():
        from modules.schedule_capacity_config import DEFAULT_DAILY_MINUTES, DEFAULT_PROCESS_LINE_COUNTS

        return {"daily_minutes": DEFAULT_DAILY_MINUTES, "process_node_counts": dict(DEFAULT_PROCESS_LINE_COUNTS)}

    @staticmethod
    def generate_shadow_order_schedule(*args, **kwargs):
        from modules.services.schedule_capacity_service import ScheduleCapacityService

        return _schedule_call(ScheduleCapacityService.generate_shadow_order_schedule, *args, **kwargs)

    @staticmethod
    def auto_plan_orders(*args, **kwargs):
        from modules.services.schedule_capacity_service import ScheduleCapacityService

        return _schedule_call(ScheduleCapacityService.auto_plan_orders, *args, **kwargs)

    @staticmethod
    def generate_order_schedule(*args, **kwargs):
        from modules.services.schedule_capacity_service import ScheduleCapacityService

        return _schedule_call(ScheduleCapacityService.generate_order_schedule, *args, **kwargs)

    @staticmethod
    def dynamic_replan_order(*args, **kwargs):
        from modules.services.schedule_capacity_service import ScheduleCapacityService

        return _schedule_call(ScheduleCapacityService.dynamic_replan_order, *args, **kwargs)

    @staticmethod
    def create_downtime_event(*args, **kwargs):
        from modules.services.schedule_capacity_service import ScheduleCapacityService

        return _schedule_call(ScheduleCapacityService.create_downtime_event, *args, **kwargs)

    @staticmethod
    def submit_revision(*args, **kwargs):
        from modules.services.schedule_capacity_service import ScheduleCapacityService

        return _schedule_call(ScheduleCapacityService.submit_revision, *args, **kwargs)

    @staticmethod
    def approve_revision(*args, **kwargs):
        from modules.services.schedule_capacity_service import ScheduleCapacityService

        return _schedule_call(ScheduleCapacityService.approve_revision, *args, **kwargs)

    @staticmethod
    def reject_revision(*args, **kwargs):
        from modules.services.schedule_capacity_service import ScheduleCapacityService

        return _schedule_call(ScheduleCapacityService.reject_revision, *args, **kwargs)

    @staticmethod
    def publish_revision(*args, **kwargs):
        from modules.services.schedule_capacity_service import ScheduleCapacityService

        return _schedule_call(ScheduleCapacityService.publish_revision, *args, **kwargs)

    @staticmethod
    def assert_revision_conflict_gate(*args, **kwargs):
        from modules.services.schedule_planning_strategy import SchedulePlanningStrategy

        return _schedule_call(SchedulePlanningStrategy.assert_revision_conflict_gate, *args, **kwargs)

    @staticmethod
    def formal_schedule_digest(*args, **kwargs):
        from modules.repositories.schedule_planning_repository import SchedulePlanningRepository

        return _schedule_call(SchedulePlanningRepository.formal_schedule_digest, *args, **kwargs)

    @staticmethod
    def list_schedulable_orders(*args, **kwargs):
        from modules.repositories.schedule_planning_repository import SchedulePlanningRepository

        return _schedule_call(SchedulePlanningRepository.list_schedulable_orders, *args, **kwargs)

    @staticmethod
    def list_calendars(*args, **kwargs):
        from modules.repositories.schedule_planning_repository import SchedulePlanningRepository

        return _schedule_call(SchedulePlanningRepository.list_calendars, *args, **kwargs)

    @staticmethod
    def list_capacity_overrides(*args, **kwargs):
        from modules.repositories.schedule_planning_repository import SchedulePlanningRepository

        return _schedule_call(SchedulePlanningRepository.list_capacity_overrides, *args, **kwargs)

    @staticmethod
    def list_capacity_unavailability(*args, **kwargs):
        from modules.repositories.schedule_planning_repository import SchedulePlanningRepository

        return _schedule_call(SchedulePlanningRepository.list_capacity_unavailability, *args, **kwargs)

    @staticmethod
    def list_schedule_allocations(*args, **kwargs):
        from modules.repositories.schedule_planning_repository import SchedulePlanningRepository

        return _schedule_call(SchedulePlanningRepository.list_schedule_allocations, *args, **kwargs)

    @staticmethod
    def list_schedule_segments(*args, **kwargs):
        from modules.repositories.schedule_planning_repository import SchedulePlanningRepository

        return _schedule_call(SchedulePlanningRepository.list_schedule_segments, *args, **kwargs)

    @staticmethod
    def list_scheduled_operations(*args, **kwargs):
        from modules.repositories.schedule_planning_repository import SchedulePlanningRepository

        return _schedule_call(SchedulePlanningRepository.list_scheduled_operations, *args, **kwargs)

    @staticmethod
    def list_line_loads(*args, **kwargs):
        from modules.repositories.schedule_planning_repository import SchedulePlanningRepository

        return _schedule_call(SchedulePlanningRepository.list_line_loads, *args, **kwargs)

    @staticmethod
    def find_schedule_revision(*args, **kwargs):
        from modules.repositories.schedule_revision_repository import ScheduleRevisionRepository

        return _schedule_call(ScheduleRevisionRepository.find_revision, *args, **kwargs)

    @staticmethod
    def assert_revision_integrity(*args, **kwargs):
        from modules.repositories.schedule_revision_repository import ScheduleRevisionRepository

        return _schedule_call(ScheduleRevisionRepository.assert_revision_integrity, *args, **kwargs)

    @staticmethod
    def list_latest_candidate_revision_items(*args, **kwargs):
        from modules.repositories.schedule_revision_repository import ScheduleRevisionRepository

        return _schedule_call(ScheduleRevisionRepository.list_latest_candidate_revision_items, *args, **kwargs)

    @staticmethod
    def list_schedule_conflicts(*args, **kwargs):
        from modules.repositories.schedule_evidence_repository import ScheduleEvidenceRepository

        return _schedule_call(ScheduleEvidenceRepository.list_schedule_conflicts, *args, **kwargs)

    @staticmethod
    def list_schedule_risk_inputs(*args, **kwargs):
        from modules.repositories.schedule_evidence_repository import ScheduleEvidenceRepository

        return _schedule_call(ScheduleEvidenceRepository.list_schedule_risk_inputs, *args, **kwargs)

    @staticmethod
    def get_replan_evidence(*args, **kwargs):
        from modules.repositories.schedule_evidence_repository import ScheduleEvidenceRepository

        return _schedule_call(ScheduleEvidenceRepository.get_replan_evidence, *args, **kwargs)

    @staticmethod
    def list_replan_triggers(*args, **kwargs):
        from modules.repositories.schedule_evidence_repository import ScheduleEvidenceRepository

        return _schedule_call(ScheduleEvidenceRepository.list_replan_triggers, *args, **kwargs)

    @staticmethod
    def list_production_nodes(*args, **kwargs):
        from modules.repositories.production_node_repository import ProductionNodeRepository

        return _schedule_call(ProductionNodeRepository.list_nodes, *args, **kwargs)

    @staticmethod
    def evaluate_deadline_risk(*args, **kwargs):
        from modules.domain.schedule_deadline_risk import ScheduleDeadlineRiskPolicy

        return _schedule_call(ScheduleDeadlineRiskPolicy.evaluate, *args, **kwargs)

    @staticmethod
    def create_rework(*args, **kwargs):
        from modules.services.rework_service import ReworkService

        return _schedule_call(ReworkService.create_rework, *args, **kwargs)
