"""Shared planning primitives used by generation, replan, and revision flows.

The strategy is the stable public seam for reusable planning behavior.  The
implementation loads immutable repository facts and delegates to pure domain
policies; no service provider or private service calls participate.
"""


from modules.domain.production_time import (
    format_database_timestamp,
    parse_database_timestamp,
)
from modules.domain.schedule_pure_planner import SchedulePurePlanner
from modules.services.schedule_unit_of_work import ScheduleUnitOfWork
from modules.services.schedule_assessment_service import ScheduleAssessmentService
from modules.repositories.production_node_repository import ProductionNodeRepository
from modules.repositories.schedule_planning_repository import SchedulePlanningRepository


class SchedulePlanningStrategy:
    """Public planning seam backed by immutable facts and the pure planner."""

    @staticmethod
    def transaction(db=None):
        return ScheduleUnitOfWork.transaction(db)

    @staticmethod
    def read_transaction(db=None):
        return ScheduleUnitOfWork.read_transaction(db)

    @staticmethod
    def persist_operation_payload(payload, txn, *, persist=True):
        return ScheduleUnitOfWork.persist_operation_payload(payload, txn, persist=persist)

    @classmethod
    def parse_timestamp(cls, value):
        return parse_database_timestamp(value)

    @classmethod
    def format_timestamp(cls, value):
        return format_database_timestamp(value)

    @classmethod
    def find_standard(
        cls,
        db,
        route_id,
        route_version_id,
        process_id,
        process_version_id,
        product_id,
        product_code,
        as_of_date,
    ):
        standard = SchedulePlanningRepository.find_active_standard(
            route_id,
            route_version_id,
            process_id,
            process_version_id,
            product_id,
            product_code,
            as_of_date,
            db,
        )
        return dict(standard) if standard is not None else None

    @staticmethod
    def load_resource_facts(resource, db, *, use_node_engine):
        """Resolve all calendar facts once before entering the pure planner."""
        from modules.domain.schedule_planning import PlanningResourceFacts

        resource = dict(resource)
        calendar = SchedulePlanningRepository.get_calendar(
            resource.get("calendar_id"), db=db
        )
        if not calendar and not use_node_engine:
            calendar = SchedulePlanningRepository.get_calendar(db=db)
        calendar = dict(calendar) if calendar else {}
        shifts = (
            [
                dict(row)
                for row in SchedulePlanningRepository.list_calendar_shifts(
                    calendar["id"], db=db
                )
            ]
            if calendar
            else []
        )
        exceptions = (
            [
                dict(row)
                for row in SchedulePlanningRepository.list_calendar_exceptions(
                    calendar["id"], db=db
                )
            ]
            if calendar
            else []
        )
        overrides = (
            [
                dict(row)
                for row in ProductionNodeRepository.list_node_calendar_overrides(
                    resource["id"], db=db
                )
            ]
            if use_node_engine
            else []
        )
        if use_node_engine:
            resource["production_node_id"] = resource["id"]
        return PlanningResourceFacts(
            resource=resource,
            calendar=calendar,
            shifts=tuple(shifts),
            exceptions=tuple(exceptions),
            overrides=tuple(overrides),
        )

    @staticmethod
    def plan(facts, operation_facts, **kwargs):
        return SchedulePurePlanner.plan(facts, operation_facts, **kwargs)

    @staticmethod
    def calendar_snapshot(calendar, shifts):
        from modules.domain.schedule_planning import PlanningResourceFacts

        return SchedulePurePlanner.calendar_snapshot(PlanningResourceFacts({}, dict(calendar), tuple(dict(row) for row in shifts)))

    @staticmethod
    def allocate_on_line(db, calendar, shifts, daily_minutes, earliest, duration, occupied):
        from modules.domain.schedule_planning import PlanningResourceFacts

        facts = PlanningResourceFacts(
            resource={}, calendar=dict(calendar), shifts=tuple(dict(row) for row in shifts),
            exceptions=tuple(dict(row) for row in SchedulePlanningRepository.list_calendar_exceptions(calendar["id"], db=db)),
        )
        return SchedulePurePlanner.allocate_from_slots(
            SchedulePurePlanner.calendar_slots(facts, earliest, daily_minutes),
            earliest, duration, occupied,
        )

    @staticmethod
    def allocate_split_on_lines(db, lines, earliest, quantity, standard, occupancy):
        facts = tuple(SchedulePlanningStrategy.load_resource_facts(row, db, use_node_engine=False) for row in lines)
        return SchedulePurePlanner.allocate_lines(facts, earliest, quantity, standard, occupancy)

    @staticmethod
    def allocate_on_node(db, node, earliest, duration, occupancy):
        facts = SchedulePlanningStrategy.load_resource_facts(node, db, use_node_engine=True)
        return SchedulePurePlanner.allocate_resource(facts, earliest, duration, occupancy.get(node["id"], []))

    @staticmethod
    def allocate_split_on_nodes(db, nodes, earliest, quantity, standard, occupancy, *,
                                operation=None, order=None, serial_ids=None,
                                allocation_key_prefix="", return_allocations=False):
        facts = tuple(SchedulePlanningStrategy.load_resource_facts(row, db, use_node_engine=True) for row in nodes)
        segments, allocations = SchedulePurePlanner.allocate_nodes(
            facts, earliest, quantity, standard, occupancy, operation, order,
            serial_ids, allocation_key_prefix,
        )
        return (segments, allocations) if return_allocations else segments

    @staticmethod
    def assess_revision_conflicts(*args, **kwargs):
        return ScheduleAssessmentService.assess_revision_conflicts(*args, **kwargs)

    @staticmethod
    def assert_revision_conflict_gate(*args, **kwargs):
        return ScheduleAssessmentService.assert_revision_conflict_gate(*args, **kwargs)
