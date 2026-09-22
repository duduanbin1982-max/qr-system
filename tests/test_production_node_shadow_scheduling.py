import json
import sqlite3
import uuid

import pytest

from factories import create_order, create_process_route
from modules import config
from modules.db import get_db
from modules.domain.errors import ProductionNodeWriteDisabledError
from modules.domain.production_node_scheduling import NodeSchedulingError
from modules.migration_production_nodes import m090_production_node_shadow_ledger
from modules.repositories.schedule_capacity_repository import ScheduleCapacityRepository
from modules.services.schedule_capacity_service import ScheduleCapacityService


def _seed_order(db, *, quantity=3, unit_minutes=60):
    process = db.execute(
        "SELECT id FROM processes WHERE name='焊接'"
    ).fetchone()
    route_id = create_process_route(
        db, [process["id"]], name=f"Shadow Route {uuid.uuid4().hex[:8]}"
    )
    order_id = create_order(
        db, [process["id"]], quantity=quantity,
        product_code=f"SHADOW-{uuid.uuid4().hex[:8].upper()}",
    )
    db.execute(
        "UPDATE orders SET route_id=?,plan_start='2026-09-19' WHERE id=?",
        (route_id, order_id),
    )
    route_version_id = db.execute(
        "SELECT current_effective_version_id FROM process_routes WHERE id=?",
        (route_id,),
    ).fetchone()[0]
    process_version_id = db.execute(
        "SELECT process_version_id FROM process_route_version_items "
        "WHERE route_version_id=? AND process_id=?",
        (route_version_id, process["id"]),
    ).fetchone()[0]
    db.execute(
        "INSERT INTO work_time_standards "
        "(route_id,route_version_id,process_id,process_version_id,"
        "standard_minutes_per_unit,setup_minutes,difficulty_factor,status,version) "
        "VALUES (?,?,?,?,?,0,1,'active',1)",
        (route_id, route_version_id, process["id"], process_version_id, unit_minutes),
    )
    node = db.execute(
        "SELECT id FROM production_nodes WHERE process_id=? ORDER BY id LIMIT 1",
        (process["id"],),
    ).fetchone()
    db.execute(
        "UPDATE production_nodes SET status=CASE WHEN id=? THEN 'active' ELSE 'inactive' END "
        "WHERE process_id=?",
        (node["id"], process["id"]),
    )
    db.commit()
    return order_id, node["id"]


def _actor_id(db):
    return db.execute(
        "SELECT id FROM users WHERE username='testrunner'"
    ).fetchone()[0]


def _node_create_payload(db):
    process_id = db.execute(
        "SELECT id FROM processes WHERE status='active' ORDER BY id LIMIT 1"
    ).fetchone()[0]
    calendar_id = db.execute(
        "SELECT id FROM schedule_calendars WHERE status='active' ORDER BY id LIMIT 1"
    ).fetchone()[0]
    suffix = uuid.uuid4().hex[:8]
    return {
        "process_id": process_id,
        "node_code": f"WRITE-GATE-{suffix}",
        "node_name": f"Write Gate {suffix}",
        "capacity_mode": "exclusive",
        "calendar_id": calendar_id,
        "row_version": 1,
        "reason": "verify disabled write gate",
        "idempotency_key": f"write-gate-{uuid.uuid4().hex}",
    }


def test_disabled_flag_rejects_node_api_and_shadow_service_without_writes(
    client, auth_headers, monkeypatch,
):
    monkeypatch.setattr(config, "PRODUCTION_NODE_WRITE_ENABLED", False)
    with client.application.app_context():
        db = get_db()
        order_id, _ = _seed_order(db)
        actor_id = _actor_id(db)
        payload = _node_create_payload(db)
        node_count = db.execute("SELECT COUNT(*) FROM production_nodes").fetchone()[0]
        digest = ScheduleCapacityRepository.formal_schedule_digest(order_id, db=db)

    response = client.post("/api/production-nodes", headers=auth_headers, json=payload)
    assert response.status_code == 409
    assert response.get_json()["code"] == "PRODUCTION_NODE_WRITE_DISABLED"

    with client.application.app_context():
        db = get_db()
        with pytest.raises(ProductionNodeWriteDisabledError):
            ScheduleCapacityService.generate_shadow_order_schedule(
                order_id, "shadow-disabled-001", actor_id=actor_id, db=db
            )
        assert db.execute("SELECT COUNT(*) FROM production_nodes").fetchone()[0] == node_count
        assert db.execute(
            "SELECT COUNT(*) FROM production_node_shadow_runs"
        ).fetchone()[0] == 0
        assert ScheduleCapacityRepository.formal_schedule_digest(order_id, db=db) == digest


def test_shadow_plan_uses_node_engine_and_preserves_formal_schedule(
    client, monkeypatch,
):
    monkeypatch.setattr(config, "PRODUCTION_NODE_QUERY_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_WRITE_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_ENGINE_ENABLED", False)
    with client.application.app_context():
        db = get_db()
        order_id, node_id = _seed_order(db, quantity=3)
        actor_id = _actor_id(db)
        formal = ScheduleCapacityService.generate_order_schedule(
            order_id,
            start_date="2026-09-19",
            schedule_run_key=f"formal-{uuid.uuid4().hex}",
            actor_id=actor_id,
            db=db,
        )
        assert formal["operations"][0]["production_node_id"] is None
        before = ScheduleCapacityRepository.formal_schedule_digest(order_id, db=db)
        formal_run_count = db.execute(
            "SELECT COUNT(*) FROM schedule_runs WHERE order_id=?", (order_id,)
        ).fetchone()[0]

        result = ScheduleCapacityService.generate_shadow_order_schedule(
            order_id,
            "shadow-isolation-001",
            start_date="2026-09-19",
            actor_id=actor_id,
            db=db,
        )

        assert result["shadow_only"] is True
        assert result["engine"] == "production_node"
        assert result["operations"][0]["production_node_id"] == node_id
        assert ScheduleCapacityRepository.formal_schedule_digest(order_id, db=db) == before
        assert db.execute(
            "SELECT COUNT(*) FROM schedule_runs WHERE order_id=?", (order_id,)
        ).fetchone()[0] == formal_run_count
        official = db.execute(
            "SELECT production_node_id,schedule_run_key FROM order_process_schedules "
            "WHERE order_id=?", (order_id,)
        ).fetchone()
        assert official["production_node_id"] is None
        assert official["schedule_run_key"] == formal["schedule_run_key"]
        assert db.execute(
            "SELECT COUNT(*) FROM production_node_shadow_runs WHERE order_id=?",
            (order_id,),
        ).fetchone()[0] == 1
        assert db.execute(
            "SELECT COUNT(*) FROM production_node_shadow_items WHERE shadow_run_id=?",
            (result["shadow_run_id"],),
        ).fetchone()[0] == 1
        assert config.PRODUCTION_NODE_ENGINE_ENABLED is False


def test_shadow_plan_accepts_node_without_legacy_line_and_keeps_formal_facts(
    client, monkeypatch,
):
    monkeypatch.setattr(config, "PRODUCTION_NODE_QUERY_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_WRITE_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_ENGINE_ENABLED", False)
    with client.application.app_context():
        db = get_db()
        order_id, mapped_node_id = _seed_order(db, quantity=2)
        mapped = db.execute(
            "SELECT process_id,calendar_id FROM production_nodes WHERE id=?",
            (mapped_node_id,),
        ).fetchone()
        db.execute(
            "UPDATE production_nodes SET status='inactive' WHERE process_id=?",
            (mapped["process_id"],),
        )
        node_id = db.execute(
            "INSERT INTO production_nodes "
            "(process_id,node_code,node_name,capacity_mode,status,calendar_id,"
            "legacy_process_line_id) VALUES (?,?,?,'exclusive','active',?,NULL)",
            (
                mapped["process_id"],
                "SHADOW-NATIVE-01",
                "影子节点原生01",
                mapped["calendar_id"],
            ),
        ).lastrowid
        db.commit()
        before = ScheduleCapacityRepository.formal_schedule_digest(order_id, db=db)

        result = ScheduleCapacityService.generate_shadow_order_schedule(
            order_id,
            "shadow-node-native-001",
            start_date="2026-09-19",
            actor_id=_actor_id(db),
            db=db,
        )

        operation = result["operations"][0]
        assert operation["production_node_id"] == node_id
        assert operation["process_line_id"] is None
        assert all(
            segment["production_node_id"] == node_id
            and segment["process_line_id"] is None
            for segment in operation["segments"]
        )
        assert ScheduleCapacityRepository.formal_schedule_digest(order_id, db=db) == before
        assert db.execute(
            "SELECT COUNT(*) FROM production_node_shadow_segments segment "
            "JOIN production_node_shadow_items item ON item.id=segment.shadow_item_id "
            "WHERE item.shadow_run_id=? AND segment.production_node_id=?",
            (result["shadow_run_id"], node_id),
        ).fetchone()[0] > 0


def test_shadow_plan_is_idempotent_and_rejects_changed_input(client, monkeypatch):
    monkeypatch.setattr(config, "PRODUCTION_NODE_QUERY_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_WRITE_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_ENGINE_ENABLED", False)
    with client.application.app_context():
        db = get_db()
        order_id, _ = _seed_order(db, quantity=4, unit_minutes=30)
        actor_id = _actor_id(db)
        first = ScheduleCapacityService.generate_shadow_order_schedule(
            order_id, "shadow-idempotent-001", start_date="2026-09-19",
            actor_id=actor_id, db=db,
        )
        replay = ScheduleCapacityService.generate_shadow_order_schedule(
            order_id, "shadow-idempotent-001", start_date="2026-09-19",
            actor_id=actor_id, db=db,
        )
        assert replay["idempotent_replay"] is True
        assert replay["shadow_run_id"] == first["shadow_run_id"]
        assert db.execute(
            "SELECT COUNT(*) FROM production_node_shadow_runs WHERE shadow_run_key=?",
            ("shadow-idempotent-001",),
        ).fetchone()[0] == 1
        with pytest.raises(NodeSchedulingError, match="幂等键"):
            ScheduleCapacityService.generate_shadow_order_schedule(
                order_id, "shadow-idempotent-001", start_date="2026-09-20",
                actor_id=actor_id, db=db,
            )


def test_shadow_facts_are_conflict_free_conserved_and_immutable(client, monkeypatch):
    monkeypatch.setattr(config, "PRODUCTION_NODE_QUERY_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_WRITE_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_ENGINE_ENABLED", False)
    with client.application.app_context():
        db = get_db()
        order_id, _ = _seed_order(db, quantity=5, unit_minutes=120)
        actor_id = _actor_id(db)
        result = ScheduleCapacityService.generate_shadow_order_schedule(
            order_id, "shadow-conflict-001", start_date="2026-09-19",
            actor_id=actor_id, db=db,
        )
        operation = result["operations"][0]
        assert sum(item["quantity"] for item in operation["allocations"]) == 5
        intervals = sorted(
            (item["start_at"], item["end_at"])
            for item in operation["segments"]
        )
        assert all(current[0] >= previous[1] for previous, current in zip(intervals, intervals[1:]))

        m090_production_node_shadow_ledger(db)
        db.commit()
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(
                "UPDATE production_node_shadow_runs SET status='failed' WHERE id=?",
                (result["shadow_run_id"],),
            )
        db.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(
                "DELETE FROM production_node_shadow_runs WHERE id=?",
                (result["shadow_run_id"],),
            )
        db.rollback()


def test_shadow_plan_api_lists_and_reads_isolated_result(
    client, auth_headers, monkeypatch,
):
    monkeypatch.setattr(config, "PRODUCTION_NODE_QUERY_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_WRITE_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_ENGINE_ENABLED", False)
    with client.application.app_context():
        db = get_db()
        order_id, _ = _seed_order(db)

    created = client.post(
        f"/api/schedule/order/{order_id}/shadow-plan",
        headers=auth_headers,
        json={"shadow_run_key": "shadow-api-001", "start_date": "2026-09-19"},
    )
    assert created.status_code == 200, created.get_json()
    run_id = created.get_json()["shadow_run_id"]
    listed = client.get(
        f"/api/schedule/order/{order_id}/shadow-runs", headers=auth_headers
    )
    assert listed.status_code == 200
    assert listed.get_json()["runs"][0]["id"] == run_id
    detail = client.get(
        f"/api/schedule/shadow-runs/{run_id}", headers=auth_headers
    )
    assert detail.status_code == 200
    assert detail.get_json()["shadow_only"] is True
    assert detail.get_json()["operations"]


def test_disabled_flag_rejects_node_revision_workflow_but_not_legacy_generation(
    client, auth_headers, monkeypatch,
):
    monkeypatch.setattr(config, "PRODUCTION_NODE_QUERY_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_WRITE_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_ENGINE_ENABLED", True)
    with client.application.app_context():
        db = get_db()
        order_id, _ = _seed_order(db)
        result = ScheduleCapacityService.generate_order_schedule(
            order_id,
            start_date="2026-09-19",
            schedule_run_key="node-revision-gate-formal-001",
            actor_id=_actor_id(db),
            db=db,
        )
        revision_id = result["schedule_revision_id"]
        assert result["operations"][0]["production_node_id"] is not None

    monkeypatch.setattr(config, "PRODUCTION_NODE_WRITE_ENABLED", False)
    response = client.post(
        f"/api/schedule/revisions/{revision_id}/submit",
        headers=auth_headers,
        json={
            "reason": "node write gate verification",
            "idempotency_key": "node-revision-gate-submit-001",
        },
    )
    assert response.status_code == 409
    assert response.get_json()["code"] == "PRODUCTION_NODE_WRITE_DISABLED"
