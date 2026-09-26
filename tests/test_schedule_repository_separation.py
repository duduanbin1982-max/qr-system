"""Contracts for the incremental scheduling repository separation."""

from __future__ import annotations

import inspect

import pytest

from modules.repositories.schedule_capacity_repository import (
    ScheduleCapacityRepository,
)
from modules.repositories.schedule_evidence_repository import (
    ScheduleEvidenceRepository,
)
from modules.repositories.schedule_planning_repository import (
    SchedulePlanningRepository,
)
from modules.repositories.schedule_revision_repository import (
    ScheduleRevisionRepository,
)


PLANNING_METHODS = {
    "affected_order_ids_for_downtime",
    "cancel_downtime_event",
    "create_downtime_event",
    "dynamic_replan_order_context",
    "ensure_default_lines",
    "ensure_order_version_bindings",
    "find_active_standard",
    "find_downtime_event",
    "find_execution_policy",
    "find_line",
    "find_order",
    "find_order_operations",
    "find_schedule",
    "find_standard",
    "formal_schedule_digest",
    "get_calendar",
    "get_calendar_exception",
    "line_available_dates",
    "list_calendar_shifts",
    "list_calendars",
    "list_capacity_overrides",
    "list_capacity_unavailability",
    "list_downtime_events",
    "list_effective_capacity_intervals",
    "list_line_loads",
    "list_line_occupancy",
    "list_node_occupancy_for_adjustment",
    "list_order_serial_ids",
    "list_process_lines",
    "list_schedulable_orders",
    "list_schedule_allocations",
    "list_schedule_segments",
    "list_scheduled_operations",
}

REVISION_METHODS = {
    "assert_revision_integrity",
    "auto_plan_result",
    "cancel_revision",
    "clear_order_schedules",
    "clear_schedule_replan_flag",
    "clone_revision_with_override",
    "complete_auto_plan_run",
    "complete_run",
    "compute_revision_content_digest",
    "create_auto_plan_run",
    "create_revision",
    "create_run",
    "create_shadow_run",
    "create_task_lock",
    "create_workflow_event",
    "finalize_revision_content_digest",
    "find_active_task_lock",
    "find_auto_plan_run",
    "find_revision",
    "find_revision_by_run",
    "find_revision_item",
    "find_revision_item_by_source_schedule",
    "find_revision_order",
    "find_run",
    "find_shadow_run",
    "find_workflow_event",
    "get_shadow_run",
    "insert_operation_schedule",
    "list_active_order_task_locks",
    "list_latest_candidate_revision_items",
    "list_revision_items",
    "list_revisions",
    "list_shadow_runs",
    "materialize_revision_projection",
    "publish_revision",
    "release_task_lock",
    "revision_uses_production_nodes",
    "run_result",
    "set_revision_digest",
    "shadow_run_result",
    "snapshot_revision_item",
    "snapshot_revision_payload",
    "transition_revision",
    "update_order_summary",
    "update_run_input",
}

EVIDENCE_METHODS = {
    "find_revision_risk_assessment",
    "find_schedule_risk_input",
    "get_replan_evidence",
    "list_replan_triggers",
    "list_revision_conflict_items",
    "list_revision_conflicts",
    "list_schedule_conflicts",
    "list_schedule_conflicts_by_order",
    "list_schedule_risk_inputs",
    "record_replan_trigger",
    "record_revision_conflict_check",
    "record_revision_risk_assessment",
    "save_replan_evidence",
    "set_revision_risk_snapshot",
}

REPOSITORY_METHODS = {
    SchedulePlanningRepository: PLANNING_METHODS,
    ScheduleRevisionRepository: REVISION_METHODS,
    ScheduleEvidenceRepository: EVIDENCE_METHODS,
}


def _static_methods(repository):
    return {
        name
        for name, descriptor in vars(repository).items()
        if isinstance(descriptor, staticmethod)
    }


def test_repository_responsibilities_are_complete_and_disjoint():
    actual_sets = []
    for repository, expected_methods in REPOSITORY_METHODS.items():
        actual_methods = _static_methods(repository)
        assert actual_methods == expected_methods
        actual_sets.append(actual_methods)

    assert not (actual_sets[0] & actual_sets[1])
    assert not (actual_sets[0] & actual_sets[2])
    assert not (actual_sets[1] & actual_sets[2])
    assert _static_methods(ScheduleCapacityRepository) == set().union(*actual_sets)


def test_compatibility_facade_preserves_public_signatures():
    for repository, methods in REPOSITORY_METHODS.items():
        for method_name in methods:
            assert inspect.signature(
                getattr(ScheduleCapacityRepository, method_name)
            ) == inspect.signature(getattr(repository, method_name))


@pytest.mark.parametrize(
    ("repository", "method_name", "args", "kwargs"),
    [
        (SchedulePlanningRepository, "find_order", (17, object()), {}),
        (ScheduleRevisionRepository, "find_revision", (23,), {"db": object()}),
        (ScheduleEvidenceRepository, "list_schedule_conflicts", (), {"db": object()}),
    ],
)
def test_compatibility_facade_delegates_arguments_and_results(
    monkeypatch, repository, method_name, args, kwargs
):
    calls = []
    result = object()

    def replacement(*received_args, **received_kwargs):
        calls.append((received_args, received_kwargs))
        return result

    monkeypatch.setattr(repository, method_name, staticmethod(replacement))

    assert getattr(ScheduleCapacityRepository, method_name)(*args, **kwargs) is result
    assert calls == [(args, kwargs)]


def test_compatibility_facade_preserves_repository_errors(monkeypatch):
    class ExpectedRepositoryError(RuntimeError):
        pass

    transaction = object()

    def fail(*, db=None):
        assert db is transaction
        raise ExpectedRepositoryError("repository failure")

    monkeypatch.setattr(
        ScheduleEvidenceRepository,
        "list_schedule_conflicts",
        staticmethod(fail),
    )

    with pytest.raises(ExpectedRepositoryError, match="repository failure"):
        ScheduleCapacityRepository.list_schedule_conflicts(db=transaction)
