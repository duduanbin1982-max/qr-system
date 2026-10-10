from datetime import datetime
import json
import sqlite3

import pytest

from modules.domain.schedule_planning import (
    PlanningFactsSnapshot,
    build_manifest,
    build_operation_context,
    decide_operation_planning,
    derive_stage_bundle,
    match_work_times,
    select_node_candidates,
    summarize_schedule_result,
)
from modules import config
from modules.services.schedule_capacity_service import ScheduleCapacityService


def _facts():
    return PlanningFactsSnapshot.create(
        order={"id": 7, "quantity": 3, "product_code": "PURE-PLAN"},
        operations=(
            {"order_process_id": 11, "process_id": 1, "seq_order": 1},
            {"order_process_id": 12, "process_id": 2, "seq_order": 2},
        ),
        cursor=datetime(2026, 10, 10, 8, 0),
        standard_as_of="2026-10-10",
        use_node_engine=True,
        occupancy={4: ((datetime(2026, 10, 10, 8), datetime(2026, 10, 10, 9)),)},
    )


def test_planning_facts_are_deeply_immutable():
    facts = _facts()
    assert isinstance(facts.operations, tuple)
    assert isinstance(facts.occupancy, dict) is False
    with pytest.raises(TypeError):
        facts.order["quantity"] = 4
    with pytest.raises(TypeError):
        facts.operations[0]["seq_order"] = 2


def test_operation_planning_gates_are_pure_and_ordered():
    context = build_operation_context(
        order={"id": 7, "quantity": 2},
        operation={
            "order_process_id": 11,
            "process_id": 1,
            "seq_order": 1,
            "process_name": "下料",
        },
        remaining_quantity=2,
        completed_quantity=0,
        rework_quantity=0,
        cursor=datetime(2026, 10, 10, 8),
        run_key="pure-gates",
        run_id=1,
        revision_id=2,
    )
    assert decide_operation_planning(context).disposition == "pending"
    assert decide_operation_planning(
        context, upstream_blocked=True
    ).blocked_code == "UPSTREAM_BLOCKED"
    external = decide_operation_planning(
        context,
        execution_policy={
            "execution_mode": "outsourced",
            "external_lead_minutes": 30,
        },
    )
    assert external.disposition == "external"
    assert external.external_lead_minutes == 30
    missing_standard = decide_operation_planning(
        context, standard_resolved=True
    )
    assert missing_standard.blocked_code == "MISSING_WORK_TIME_STANDARD"
    missing_candidate = decide_operation_planning(
        context,
        standard={"id": 3},
        standard_resolved=True,
        candidates=(),
    )
    assert missing_candidate.blocked_code == "NO_COMPATIBLE_NODE"
    ready = decide_operation_planning(
        context,
        standard={"id": 3},
        standard_resolved=True,
        candidates=({"id": 9, "capabilities": ["weld"]},),
    )
    assert ready.disposition == "allocation_ready"
    with pytest.raises(TypeError):
        ready.candidates[0]["id"] = 10


def test_operation_context_normalizes_sqlite_rows_at_domain_boundary():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    order = connection.execute(
        "SELECT 7 AS id, 2 AS quantity"
    ).fetchone()
    operation = connection.execute(
        "SELECT 11 AS order_process_id, 1 AS process_id, "
        "1 AS seq_order, '下料' AS process_name"
    ).fetchone()
    context = build_operation_context(
        order=order,
        operation=operation,
        remaining_quantity=2,
        completed_quantity=0,
        rework_quantity=0,
        cursor=datetime(2026, 10, 10, 8),
        run_key="sqlite-row-input",
        run_id=1,
        revision_id=2,
    )
    assert context.common["order_id"] == 7
    assert context.process_name == "下料"


def test_pure_stages_make_explicit_work_time_candidate_and_blocked_outputs():
    operations = [
        {"order_process_id": 11},
        {"order_process_id": 12},
    ]
    matches = match_work_times(
        operations,
        {11: {"id": 101, "version": 2, "match_scope": "exact"}},
    )
    candidates = select_node_candidates(
        operations,
        {11: ({"id": 4, "node_code": "WELD-01"},), 12: ()},
    )
    assert matches[0].match_scope == "exact"
    assert matches[1].blocked_code == "MISSING_WORK_TIME_STANDARD"
    assert candidates[0].candidates[0]["id"] == 4
    assert candidates[1].blocked_code == "NO_COMPATIBLE_NODE"


def test_stage_bundle_and_manifest_are_deterministic():
    facts = _facts()
    operations = (
        {
            "order_process_id": 11,
            "status": "planned",
            "quantity": 3,
            "standard_id": 101,
            "standard_version": 2,
            "standard_match_scope": "exact",
            "production_node_id": 4,
            "planned_minutes": 30,
            "occupied_minutes": 30,
            "allocations": ({"production_node_id": 4, "quantity": 3},),
            "nodes": ({"id": 4},),
        },
        {
            "order_process_id": 12,
            "status": "blocked",
            "quantity": 3,
            "blocked_code": "NO_COMPATIBLE_NODE",
            "blocked_reason": "没有满足能力要求的生产节点",
        },
    )
    bundle = derive_stage_bundle(facts, operations)
    manifest = build_manifest(
        input_digest=facts.input_digest,
        stage_outputs=bundle.manifest_stages(),
        result={"operations": operations},
    )
    assert set(manifest.stage_digests) == {
        "facts",
        "work_time_matches",
        "node_candidates",
        "allocations",
        "blocked",
        "conflicts",
        "risk",
    }
    assert manifest.as_dict() == build_manifest(
        input_digest=facts.input_digest,
        stage_outputs=bundle.manifest_stages(),
        result={"operations": operations},
    ).as_dict()


def test_result_summary_is_stable_and_captures_invariants():
    result = {
        "operations": [
            {
                "order_process_id": 11,
                "status": "planned",
                "quantity": 3,
                "production_node_id": 4,
                "planned_minutes": 30,
                "occupied_minutes": 30,
                "allocations": [{"production_node_id": 4, "quantity": 3}],
            },
            {
                "order_process_id": 12,
                "status": "planned",
                "quantity": 3,
                "execution_mode": "outsourced",
                "planned_minutes": 20,
                "occupied_minutes": 0,
            },
            {
                "order_process_id": 13,
                "status": "blocked",
                "blocked_code": "MISSING_WORK_TIME_STANDARD",
            },
        ],
        "conflicts": [],
        "risk": {"risk_level": "at_risk", "delay_minutes": 15},
    }
    first = summarize_schedule_result(result, input_digest="facts-1")
    second = summarize_schedule_result(result, input_digest="facts-1")
    assert first == second
    assert first["quantity_conserved"] is True
    assert first["external_operation_count"] == 1
    assert first["blocked_codes"] == {"MISSING_WORK_TIME_STANDARD": 1}
    assert first["risk_level"] == "at_risk"
    assert first["delay_minutes"] == 15


def test_generation_summary_is_replay_stable(client):
    with client.application.app_context():
        from factories import create_order
        from modules.db import get_db

        db = get_db()
        process = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()
        order_id = create_order(
            db,
            [process["id"]],
            quantity=1,
            product_code="PURE-PLAN-GENERATION",
        )
        db.execute("UPDATE orders SET plan_start='2030-01-07' WHERE id=?", (order_id,))
        db.commit()

        first = ScheduleCapacityService.generate_order_schedule(
            order_id,
            start_date="2030-01-08",
            schedule_run_key="pure-planning-generation-v1",
        )
        replay = ScheduleCapacityService.generate_order_schedule(
            order_id,
            start_date="2030-01-08",
            schedule_run_key="pure-planning-generation-v1",
        )
        assert first["planning_summary"] == replay["planning_summary"]
        assert first["planning_summary"]["quantity_conserved"] is True
        assert first["planning_summary"]["summary_digest"]
        assert first["planning_manifest"] == replay["planning_manifest"]
        run = db.execute(
            "SELECT result_json FROM schedule_runs WHERE schedule_run_key=?",
            ("pure-planning-generation-v1",),
        ).fetchone()
        assert isinstance(json.loads(run["result_json"]), list)
        evidence = db.execute(
            "SELECT summary_json FROM schedule_revision_conflict_checks "
            "WHERE revision_id=? AND check_stage='planning'",
            (first["schedule_revision_id"],),
        ).fetchone()
        assert evidence is not None
        assert json.loads(evidence["summary_json"])["planning_manifest"] == first[
            "planning_manifest"
        ]


def test_dynamic_replan_summary_is_replay_stable(client, monkeypatch):
    with client.application.app_context():
        from factories import create_process_route
        from modules.db import get_db

        monkeypatch.setattr(config, "PRODUCTION_NODE_ENGINE_ENABLED", True)
        monkeypatch.setattr(config, "PRODUCTION_NODE_WRITE_ENABLED", True)
        db = get_db()
        process_id = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()["id"]
        route_id = create_process_route(db, [process_id], name="Pure planning replan route")
        order_id = db.execute(
            "INSERT INTO orders "
            "(order_no,product_name,product_code,quantity,status,plan_start,route_id) "
            "VALUES ('PURE-REPLAN','Pure planning','PURE-REPLAN',2,'producing','2026-09-01',?)",
            (route_id,),
        ).lastrowid
        db.execute(
            "INSERT INTO order_processes (order_id,process_id,seq_order,status) "
            "VALUES (?,?,1,'in_progress')",
            (order_id, process_id),
        )
        route_version = db.execute(
            "SELECT current_effective_version_id FROM process_routes WHERE id=?",
            (route_id,),
        ).fetchone()[0]
        process_version = db.execute(
            "SELECT process_version_id FROM process_route_version_items "
            "WHERE route_version_id=? AND process_id=?",
            (route_version, process_id),
        ).fetchone()[0]
        db.execute(
            "INSERT INTO work_time_standards "
            "(route_id,route_version_id,process_id,process_version_id,"
            "standard_minutes_per_unit,setup_minutes,difficulty_factor,status,version) "
            "VALUES (?,?,?,?,10,0,1,'active',1)",
            (route_id, route_version, process_id, process_version),
        )
        db.commit()

        first = ScheduleCapacityService.dynamic_replan_order(
            order_id,
            start_at="2026-09-01 08:00",
            schedule_run_key="pure-planning-replan-v1",
            actor_id=1,
        )
        replay = ScheduleCapacityService.dynamic_replan_order(
            order_id,
            start_at="2026-09-01 08:00",
            schedule_run_key="pure-planning-replan-v1",
            actor_id=1,
        )
        assert first["planning_summary"] == replay["planning_summary"]
        assert first["planning_summary"]["quantity_conserved"] is True
        assert first["planning_manifest"] == replay["planning_manifest"]
        run = db.execute(
            "SELECT result_json FROM schedule_runs WHERE schedule_run_key=?",
            ("pure-planning-replan-v1",),
        ).fetchone()
        assert isinstance(json.loads(run["result_json"]), list)
