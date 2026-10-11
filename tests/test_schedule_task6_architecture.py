"""Task 6 contracts for shared planning and workflow evidence seams."""

from pathlib import Path

from modules.services.schedule_planning_strategy import SchedulePlanningStrategy
from modules.services.schedule_workflow_evidence import ScheduleWorkflowEvidence


ROOT = Path(__file__).resolve().parents[1]


def _source(name):
    return (ROOT / "modules" / "services" / name).read_text(encoding="utf-8")


def test_revision_and_replan_services_do_not_reach_through_capacity_private_api():
    revision_source = _source("schedule_revision_service.py")
    replan_source = _source("schedule_replan_service.py")
    assert "capacity_service._" not in revision_source
    assert "capacity_service._" not in replan_source
    assert "SchedulePlanningStrategy" in revision_source
    assert "SchedulePlanningStrategy" in replan_source


def test_workflow_evidence_is_single_shared_implementation():
    capacity_source = _source("schedule_capacity_service.py")
    revision_source = _source("schedule_revision_service.py")
    assert "ScheduleWorkflowEvidence" in capacity_source
    assert "ScheduleWorkflowEvidence" in revision_source
    assert "find_workflow_event" not in revision_source
    assert "create_workflow_event" not in revision_source


def test_planning_strategy_exposes_shared_allocation_and_conflict_seams():
    expected = {
        "transaction",
        "parse_timestamp",
        "format_timestamp",
        "find_standard",
        "allocate_on_line",
        "allocate_split_on_nodes",
        "allocate_split_on_lines",
        "assess_revision_conflicts",
        "assert_revision_conflict_gate",
    }
    assert expected <= set(dir(SchedulePlanningStrategy))


def test_workflow_evidence_preserves_normalization_and_digest_contract():
    assert ScheduleWorkflowEvidence.normalize_input(
        "  adjust  ", "task6-workflow-key", "1000"
    ) == ("adjust", "task6-workflow-key", 1000)
    payload = {"action": "adjust", "revision_item_id": 7}
    assert ScheduleWorkflowEvidence.digest(payload) == ScheduleWorkflowEvidence.digest(
        {"revision_item_id": 7, "action": "adjust"}
    )
