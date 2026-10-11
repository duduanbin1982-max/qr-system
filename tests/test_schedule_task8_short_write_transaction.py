"""Task 8: deferred planning and short optimistic write transaction tests."""

from modules.services.schedule_capacity_service import ScheduleCapacityService


def test_generation_stale_input_is_audited_without_publishing(client, monkeypatch):
    with client.application.app_context():
        from factories import create_order
        from modules.db import get_db

        db = get_db()
        process = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()
        order_id = create_order(db, [process["id"]], quantity=1, product_code="TASK8-STALE")
        db.execute("UPDATE orders SET plan_start='2030-01-07' WHERE id=?", (order_id,))
        db.commit()

        original = ScheduleCapacityService._plan_generation_operations
        changed = {"done": False}

        def mutate_after_snapshot(**kwargs):
            result = original(**kwargs)
            if not changed["done"]:
                kwargs["txn"].execute(
                    "UPDATE orders SET quantity=quantity+1 WHERE id=?", (order_id,)
                )
                changed["done"] = True
            return result

        monkeypatch.setattr(
            ScheduleCapacityService,
            "_plan_generation_operations",
            staticmethod(mutate_after_snapshot),
        )
        response = ScheduleCapacityService.generate_order_schedule(
            order_id,
            start_date="2030-01-08",
            schedule_run_key="task8-stale-generation-v1",
            actor_id=1,
        )

        assert response["ok"] is False
        assert response["status"] == "STALE_INPUT"
        assert response["planning_summary"]["stale_input"] is True
        run = db.execute(
            "SELECT status,error_message FROM schedule_runs WHERE schedule_run_key=?",
            ("task8-stale-generation-v1",),
        ).fetchone()
        assert run["status"] == "failed"
        assert "STALE_INPUT" in run["error_message"]
        revision = db.execute(
            "SELECT status FROM schedule_revisions WHERE id=?",
            (response["schedule_revision_id"],),
        ).fetchone()
        assert revision["status"] == "cancelled"
        evidence = db.execute(
            "SELECT summary_json FROM schedule_revision_conflict_checks "
            "WHERE revision_id=? AND check_stage='planning'",
            (response["schedule_revision_id"],),
        ).fetchone()
        assert evidence is not None
        assert "STALE_INPUT" in evidence["summary_json"]


def test_generation_does_not_enter_immediate_lock_during_planning(client, monkeypatch):
    with client.application.app_context():
        from factories import create_order
        from modules.db import get_db

        db = get_db()
        process = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()
        order_id = create_order(db, [process["id"]], quantity=1, product_code="TASK8-DEFERRED")
        db.commit()

        observed = []
        original = ScheduleCapacityService._plan_generation_operations

        def observe(**kwargs):
            observed.append(kwargs["txn"].in_transaction)
            return original(**kwargs)

        monkeypatch.setattr(
            ScheduleCapacityService,
            "_plan_generation_operations",
            staticmethod(observe),
        )
        result = ScheduleCapacityService.generate_order_schedule(
            order_id,
            start_date="2030-01-08",
            schedule_run_key="task8-deferred-v1",
            actor_id=1,
        )
        assert result["ok"] is True
        run = db.execute(
            "SELECT input_digest FROM schedule_runs WHERE schedule_run_key=?",
            ("task8-deferred-v1",),
        ).fetchone()
        assert result["planning_summary"]["input_digest"] == run["input_digest"]
        assert observed == [True]


def test_planning_digest_excludes_run_and_revision_outputs(client):
    with client.application.app_context():
        from factories import create_order
        from modules.db import get_db
        from modules.repositories.schedule_planning_repository import (
            SchedulePlanningRepository,
        )

        db = get_db()
        process = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()
        order_id = create_order(db, [process["id"]], quantity=1, product_code="TASK8-DIGEST")
        db.commit()
        before = SchedulePlanningRepository.planning_input_digest(order_id, db=db)
        db.execute(
            "INSERT INTO schedule_runs "
            "(schedule_run_key,order_id,status,requested_start_date) "
            "VALUES ('digest-only-run',?,'started','2030-01-08')",
            (order_id,),
        )
        db.commit()
        after = SchedulePlanningRepository.planning_input_digest(order_id, db=db)
        assert after == before


def test_dynamic_replan_stale_input_is_audited_without_revision_write(client, monkeypatch):
    with client.application.app_context():
        from factories import create_process_route
        from modules import config
        from modules.db import get_db
        from modules.services.schedule_replan_service import ScheduleReplanService

        monkeypatch.setattr(config, "PRODUCTION_NODE_WRITE_ENABLED", True)
        db = get_db()
        process = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()
        route_id = create_process_route(db, [process["id"]], name="Task8 stale replan")
        order_id = db.execute(
            "INSERT INTO orders (order_no,product_name,product_code,quantity,status,plan_start,route_id) "
            "VALUES ('TASK8-REPLAN','Task8','TASK8-REPLAN',1,'producing','2030-01-08',?)",
            (route_id,),
        ).lastrowid
        db.execute(
            "INSERT INTO order_processes (order_id,process_id,seq_order,status) "
            "VALUES (?,?,1,'in_progress')", (order_id, process["id"]),
        )
        db.commit()

        original = ScheduleReplanService._plan_replan_operations

        def mutate_after_snapshot(**kwargs):
            result = original(**kwargs)
            kwargs["txn"].execute(
                "UPDATE orders SET quantity=quantity+1 WHERE id=?", (order_id,)
            )
            return result

        monkeypatch.setattr(
            ScheduleReplanService,
            "_plan_replan_operations",
            staticmethod(mutate_after_snapshot),
        )
        response = ScheduleCapacityService.dynamic_replan_order(
            order_id,
            start_at="2030-01-08 08:00",
            schedule_run_key="task8-stale-replan-v1",
            actor_id=1,
        )
        assert response["status"] == "STALE_INPUT"
        assert response["operations"] == []
