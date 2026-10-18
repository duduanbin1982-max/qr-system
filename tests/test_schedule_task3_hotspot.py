"""Task 3 contracts for the shared immutable schedule planner."""

from datetime import datetime
from dataclasses import replace
import ast
import json
from pathlib import Path

import pytest

from modules.domain.schedule_planning import (
    PlanningDecision,
    PlanningEvidence,
    PlanningFactsSnapshot,
    PlanningOperationFacts,
    PlanningResourceFacts,
    build_planning_evidence,
)
from modules.services.schedule_planning_strategy import SchedulePlanningStrategy
from modules.domain.production_time import parse_database_timestamp
from modules.domain.schedule_pure_planner import SchedulePurePlanner


ROOT = Path(__file__).resolve().parents[1]


def _source(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def test_pure_planner_has_no_service_repository_or_database_dependency():
    source = _source("modules/domain/schedule_pure_planner.py")
    forbidden = (
        "modules.services",
        "modules.repositories",
        "modules.db",
        "sqlite3",
        ".execute(",
        ".commit(",
        ".rollback(",
    )
    assert not [item for item in forbidden if item in source]


def test_generation_and_replan_use_the_same_public_planner_seam():
    generation = _source("modules/services/schedule_capacity_service.py")
    replan = _source("modules/services/schedule_replan_service.py")
    assert generation.count("def _plan_generation_operations") == 1
    assert replan.count("def _plan_replan_operations") == 1
    assert "SchedulePlanningStrategy.plan(" in generation
    assert "SchedulePlanningStrategy.plan(" in replan
    assert "capacity_service._" not in replan


def test_planning_fact_and_decision_objects_are_deeply_immutable():
    resource = PlanningResourceFacts(
        resource={"id": 4, "capabilities": [{"code": "weld"}]},
        calendar={"id": 1, "weekly_workdays": "1,2,3,4,5"},
        shifts=({"id": 1, "start_minute": 480, "end_minute": 1020},),
    )
    operation = PlanningOperationFacts(
        operation={"order_process_id": 9, "process_id": 2},
        remaining_quantity=2,
        completed_quantity=0,
        rework_quantity=0,
        execution_policy={},
        standard={"id": 3, "standard_minutes_per_unit": 10},
        resources=(resource,),
        previous={},
        locked_task={},
    )
    decision = PlanningDecision(
        operations=({"order_process_id": 9, "segments": [{"quantity": 2}]},),
        conflicts=(),
        blocked=False,
        final_cursor=datetime(2026, 10, 13, 8),
    )
    with pytest.raises(TypeError):
        resource.resource["id"] = 5
    with pytest.raises(TypeError):
        operation.standard["id"] = 4
    with pytest.raises(TypeError):
        decision.operations[0]["order_process_id"] = 10
    assert decision.operation_dicts()[0]["segments"][0]["quantity"] == 2


def test_evidence_stays_outside_legacy_result_list():
    facts = PlanningFactsSnapshot.create(
        order={"id": 7, "quantity": 2},
        operations=({"order_process_id": 9, "process_id": 2},),
        cursor=datetime(2026, 10, 13, 8),
        standard_as_of="2026-10-13",
        use_node_engine=True,
    )
    operations = [{
        "order_process_id": 9,
        "status": "planned",
        "quantity": 2,
        "production_node_id": 4,
        "standard_id": 3,
        "allocations": [{"production_node_id": 4, "quantity": 2}],
    }]
    evidence = build_planning_evidence(
        facts,
        operations,
        input_digest="facts-digest",
    )
    assert isinstance(evidence, PlanningEvidence)
    assert evidence.summary_dict()["quantity_conserved"] is True
    assert "operations" not in evidence.as_dict()
    assert hasattr(SchedulePlanningStrategy, "plan")


def test_planner_repeatability_conserves_quantity_and_preserves_frozen_inputs():
    start = parse_database_timestamp("2026-10-16 16:30")
    calendar = {"id": 1, "weekly_workdays": "1,2,3,4,5"}
    shifts = ({"id": 1, "start_minute": 480, "end_minute": 1020},)
    resources = tuple(PlanningResourceFacts(
        resource={"id": node_id, "production_node_id": node_id, "process_id": 1,
                  "status": "active", "capacity_mode": "exclusive",
                  "node_code": f"N{node_id}", "node_name": f"Node {node_id}"},
        calendar=calendar, shifts=shifts,
        overrides=({"override_type": "downtime", "start_at": "2026-10-19 08:00",
                    "end_at": "2026-10-19 10:00"},),
    ) for node_id in (4, 5))
    order = {"id": 7, "quantity": 10, "route_id": 9, "route_version_id": 11}
    operation = {"order_process_id": 12, "process_id": 1, "process_version_id": 13,
                 "seq_order": 1, "process_name": "weld"}
    standard = {"id": 20, "version": 1, "process_id": 1, "route_id": 9,
                "route_version_id": 11, "process_version_id": 13,
                "standard_minutes_per_unit": 100, "setup_minutes": 10, "difficulty_factor": 1}
    facts = PlanningFactsSnapshot.create(order=order, operations=(operation,), cursor=start,
        standard_as_of="2026-10-16", use_node_engine=True)
    inputs = (PlanningOperationFacts(operation, 10, 0, 0, {}, None, resources, {}, {},
                                    standard_candidates=(standard,)),)
    before = facts.as_dict()
    args = {"run_key": "pure-repeat", "run_id": 1, "revision_id": 2}
    first = SchedulePurePlanner.plan(facts, inputs, **args)
    second = SchedulePurePlanner.plan(facts, inputs, **args)
    assert first.operation_dicts() == second.operation_dicts()
    assert facts.as_dict() == before
    assert not first.blocked
    segments = first.operation_dicts()[0]["segments"]
    assert sum(row["quantity"] for row in segments) == 10
    assert len({row["production_node_id"] for row in segments}) == 2
    for row in segments:
        begin, end = map(parse_database_timestamp, (row["start_at"], row["end_at"]))
        assert begin.weekday() < 5 and end.weekday() < 5
        assert not (begin < parse_database_timestamp("2026-10-19 10:00")
                    and end > parse_database_timestamp("2026-10-19 08:00"))
    for node_id in (4, 5):
        intervals = sorted((row["start_at"], row["end_at"]) for row in segments
                           if row["production_node_id"] == node_id)
        assert all(left[1] <= right[0] for left, right in zip(intervals, intervals[1:]))
    with pytest.raises(TypeError):
        inputs[0].standard_candidates[0]["standard_minutes_per_unit"] = 0

    # A capability mismatch is decided by the same pure candidate stage.
    incompatible = tuple(replace(row, resource={**dict(row.resource), "capabilities": [
        {"product_id": 999, "status": "active"},
    ]}) for row in resources)
    mismatch = SchedulePurePlanner.plan(facts, (replace(inputs[0], resources=incompatible),), **args)
    assert mismatch.operation_dicts()[0]["blocked_code"] == "NO_COMPATIBLE_NODE"
    external = SchedulePurePlanner.plan(facts, (replace(inputs[0],
        execution_policy={"execution_mode": "outsourced", "external_lead_minutes": 60},
        standard_candidates=(), resources=()),), **args)
    assert external.operation_dicts()[0]["occupied_minutes"] == 0
    assert external.operation_dicts()[0]["segments"] == []


def test_planning_strategy_no_longer_calls_a_capacity_private_provider():
    source = _source("modules/services/schedule_planning_strategy.py")
    assert "_capacity_service" not in source
    assert "importlib" not in source
    assert "._assess_revision_conflicts(" not in source
    assert "SchedulePurePlanner." in source


def test_pure_stage_size_and_service_private_dependencies_do_not_regress():
    tree = ast.parse(_source("modules/domain/schedule_pure_planner.py"))
    sizes = {node.name: node.end_lineno - node.lineno + 1 for node in ast.walk(tree)
             if isinstance(node, ast.FunctionDef)}
    assert sizes["plan"] <= 60
    assert max(sizes.values()) <= 120
    for name in ("schedule_planning_strategy.py", "schedule_replan_service.py",
                 "schedule_revision_service.py"):
        source = _source(f"modules/services/{name}")
        assert "ScheduleCapacityService._" not in source


def test_node_with_missing_calendar_does_not_borrow_the_legacy_default(monkeypatch):
    from modules.repositories.schedule_planning_repository import SchedulePlanningRepository
    from modules.repositories.production_node_repository import ProductionNodeRepository

    monkeypatch.setattr(SchedulePlanningRepository, "get_calendar",
        lambda calendar_id=None, **kwargs: None if calendar_id else {"id": 1})
    monkeypatch.setattr(SchedulePlanningRepository, "list_calendar_shifts",
        lambda *args, **kwargs: [{"id": 1, "start_minute": 480, "end_minute": 1020}])
    monkeypatch.setattr(SchedulePlanningRepository, "list_calendar_exceptions",
        lambda *args, **kwargs: [])
    monkeypatch.setattr(ProductionNodeRepository, "list_node_calendar_overrides",
        lambda *args, **kwargs: [])
    node = SchedulePlanningStrategy.load_resource_facts({"id": 4, "calendar_id": 999},
                                                       None, use_node_engine=True)
    legacy = SchedulePlanningStrategy.load_resource_facts({"id": 4, "calendar_id": 999},
                                                         None, use_node_engine=False)
    assert not node.calendar and not node.shifts
    assert legacy.calendar["id"] == 1


def _overtime_resource(node_id=4, start_at="2026-10-18 08:00"):
    return PlanningResourceFacts(
        resource={
            "id": node_id, "production_node_id": node_id, "process_id": 1,
            "status": "active", "capacity_mode": "exclusive",
        },
        calendar={"id": 1, "weekly_workdays": "1,2,3,4,5"},
        shifts=({"id": 1, "start_minute": 480, "end_minute": 1020},),
        overrides=({
            "override_type": "overtime", "start_at": start_at,
            "end_at": "2026-10-18 12:00",
        },),
    )


def _plan_overtime_resources(resources, mode):
    order = {"id": 7, "quantity": 2, "route_id": 9, "route_version_id": 11}
    operation = {
        "order_process_id": 12, "process_id": 1, "route_version_id": 11,
        "process_version_id": 13, "seq_order": 1, "process_name": "weld",
    }
    standard = {
        "id": 20, "version": 1, "process_id": 1, "route_id": 9,
        "route_version_id": 11, "process_version_id": 13,
        "standard_minutes_per_unit": 10, "setup_minutes": 0,
        "difficulty_factor": 1,
    }
    facts = PlanningFactsSnapshot.create(
        order=order, operations=(operation,),
        cursor=parse_database_timestamp("2026-10-18 08:00"),
        standard_as_of="2026-10-18", use_node_engine=True,
    )
    inputs = (PlanningOperationFacts(
        operation, 2, 0, 0, {}, None, resources, {}, {},
        standard_candidates=(standard,),
    ),)
    return SchedulePurePlanner.plan(
        facts, inputs, run_key="calendar-regression", run_id=0, revision_id=0,
        mode=mode,
    )


@pytest.mark.parametrize("mode", ["generation", "replan"])
@pytest.mark.parametrize("invalid_fact", ["calendar", "shifts"])
def test_missing_node_calendar_or_shifts_blocks_even_with_overtime(mode, invalid_fact):
    resource = replace(
        _overtime_resource(),
        **{invalid_fact: {} if invalid_fact == "calendar" else ()},
    )
    decision = _plan_overtime_resources((resource,), mode)
    operation = decision.operation_dicts()[0]

    assert decision.blocked, "加班不能绕过节点日历和班次前置条件"
    assert operation["status"] == "blocked"
    assert operation["blocked_code"] == "NODE_CALENDAR_UNAVAILABLE"
    assert operation["occupied_minutes"] == 0
    assert operation["segments"] == []
    assert operation["allocations"] == []


@pytest.mark.parametrize("mode", ["generation", "replan"])
def test_valid_node_calendar_keeps_sunday_overtime_capacity(mode):
    decision = _plan_overtime_resources((_overtime_resource(),), mode)
    operation = decision.operation_dicts()[0]

    assert not decision.blocked, "有效日历和班次允许在周末增加加班产能"
    assert operation["status"] == "planned"
    assert operation["planned_start_at"] == "2026-10-18 08:00"
    assert operation["planned_end_at"] == "2026-10-18 08:20"
    assert operation["segments"][0]["shift_id"] is None
    assert sum(item["quantity"] for item in operation["allocations"]) == 2


@pytest.mark.parametrize("mode", ["generation", "replan"])
def test_invalid_calendar_node_cannot_win_over_valid_node(mode):
    invalid = replace(_overtime_resource(), calendar={})
    valid = _overtime_resource(node_id=5, start_at="2026-10-18 09:00")
    decision = _plan_overtime_resources((invalid, valid), mode)
    operation = decision.operation_dicts()[0]

    assert not decision.blocked, "应继续使用日历有效的其他候选节点"
    assert operation["production_node_id"] == 5
    assert operation["planned_start_at"] == "2026-10-18 09:00"
    assert {item["production_node_id"] for item in operation["segments"]} == {5}
    assert sum(item["quantity"] for item in operation["allocations"]) == 2


@pytest.fixture
def scheduled_node_calendar_case(client, monkeypatch):
    from factories import bind_order_process_versions, create_order, create_process_route
    from modules import config
    from modules.db import get_db
    from modules.services.schedule_capacity_service import ScheduleCapacityService

    for flag in (
        "PRODUCTION_NODE_QUERY_ENABLED", "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED",
        "PRODUCTION_NODE_WRITE_ENABLED", "PRODUCTION_NODE_ENGINE_ENABLED",
    ):
        monkeypatch.setattr(config, flag, True)
    with client.application.app_context():
        db = get_db()
        process_id = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()[0]
        node = dict(db.execute(
            "SELECT * FROM production_nodes WHERE process_id=? AND status='active' "
            "ORDER BY id LIMIT 1", (process_id,),
        ).fetchone())
        route_id = create_process_route(db, [process_id])
        order_id = create_order(db, [process_id], quantity=2)
        db.execute(
            "UPDATE orders SET route_id=?,plan_start='2026-10-13',status='producing' "
            "WHERE id=?", (route_id, order_id),
        )
        bind_order_process_versions(db, order_id)
        bindings = db.execute(
            "SELECT o.route_version_id,op.process_version_id FROM orders o "
            "JOIN order_processes op ON op.order_id=o.id WHERE o.id=?", (order_id,),
        ).fetchone()
        db.execute(
            "INSERT INTO work_time_standards "
            "(route_id,route_version_id,process_id,process_version_id,"
            "standard_minutes_per_unit,setup_minutes,difficulty_factor,status,version) "
            "VALUES (?,?,?,?,10,0,1,'active',1)",
            (route_id, bindings["route_version_id"], process_id, bindings["process_version_id"]),
        )
        actor_id = db.execute("SELECT id FROM users WHERE username='testrunner'").fetchone()[0]
        db.commit()
        prior = ScheduleCapacityService.generate_order_schedule(
            order_id, start_date="2026-10-13", schedule_run_key="calendar-prior",
            actor_id=actor_id,
        )
        assert prior["operations"][0]["status"] == "planned"
        yield db, order_id, node, actor_id, prior["schedule_revision_id"]


@pytest.mark.parametrize("mode", ["generation", "replan"])
@pytest.mark.parametrize("invalid_fact", ["inactive_calendar", "inactive_shifts"])
def test_schedule_entrypoints_persist_calendar_block_and_preserve_prior_revision(
    scheduled_node_calendar_case, mode, invalid_fact,
):
    from modules.services.schedule_capacity_service import ScheduleCapacityService

    db, order_id, node, actor_id, prior_revision_id = scheduled_node_calendar_case
    prior_items = [dict(row) for row in db.execute(
        "SELECT * FROM schedule_revision_items WHERE revision_id=? ORDER BY id",
        (prior_revision_id,),
    )]
    if invalid_fact == "inactive_calendar":
        db.execute("UPDATE schedule_calendars SET status='inactive' WHERE id=?", (node["calendar_id"],))
    else:
        db.execute("UPDATE schedule_shifts SET status='inactive' WHERE calendar_id=?", (node["calendar_id"],))
    db.execute(
        "INSERT INTO production_node_calendar_overrides "
        "(production_node_id,start_at,end_at,override_type,reason,created_by) "
        "VALUES (?,'2026-10-18 08:00','2026-10-18 12:00','overtime','calendar test',?)",
        (node["id"], actor_id),
    )
    db.commit()
    run_key = f"calendar-{mode}-{invalid_fact}"
    if mode == "generation":
        result = ScheduleCapacityService.generate_order_schedule(
            order_id, start_date="2026-10-18", schedule_run_key=run_key, actor_id=actor_id,
        )
    else:
        result = ScheduleCapacityService.dynamic_replan_order(
            order_id, start_at="2026-10-18T08:00:00+08:00",
            schedule_run_key=run_key, reason="verify invalid calendar", actor_id=actor_id,
        )

    operation = result["operations"][0]
    assert operation["status"] == "blocked", "正式服务入口也必须阻断无效日历的加班分配"
    assert operation["blocked_code"] == "NODE_CALENDAR_UNAVAILABLE"
    assert operation["segments"] == operation["allocations"] == []
    stored = db.execute(
        "SELECT result_json FROM schedule_runs WHERE schedule_run_key=?", (run_key,),
    ).fetchone()[0]
    assert isinstance(json.loads(stored), list), "运行结果仍应兼容历史列表格式"
    assert json.loads(stored)[0]["blocked_code"] == "NODE_CALENDAR_UNAVAILABLE"
    assert [dict(row) for row in db.execute(
        "SELECT * FROM schedule_revision_items WHERE revision_id=? ORDER BY id",
        (prior_revision_id,),
    )] == prior_items, "旧排程版本项目必须保持不变"
