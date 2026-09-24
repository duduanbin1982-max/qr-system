from datetime import datetime

from modules.services.schedule_capacity_service import ScheduleCapacityService


def test_generation_request_normalizes_planning_facts(client):
    with client.application.app_context():
        from modules.db import get_db
        from factories import create_order

        db = get_db()
        process = db.execute(
            "SELECT id FROM processes WHERE name='下料'"
        ).fetchone()
        order_id = create_order(
            db,
            [process["id"]],
            quantity=1,
            product_code="GENERATION-USE-CASE-01",
        )
        db.execute(
            "UPDATE orders SET plan_start='2030-01-07' WHERE id=?",
            (order_id,),
        )
        db.commit()

        request = ScheduleCapacityService._prepare_generation_request(
            order_id,
            "2030-01-08",
            "generation-use-case-request-v1",
            db,
        )

        assert request["order"]["id"] == order_id
        assert request["operations"]
        assert request["order_serial_ids"] == []
        assert request["cursor"] == datetime(2030, 1, 8)
        assert request["run_key"] == "generation-use-case-request-v1"
        assert request["standard_as_of"] >= "2030-01-08"


def test_generation_replay_phase_is_isolated_from_new_run(client):
    with client.application.app_context():
        from modules.db import get_db
        from factories import create_order

        db = get_db()
        process = db.execute(
            "SELECT id FROM processes WHERE name='下料'"
        ).fetchone()
        order_id = create_order(
            db,
            [process["id"]],
            quantity=1,
            product_code="GENERATION-USE-CASE-02",
        )
        db.execute(
            "UPDATE orders SET plan_start='2030-01-07' WHERE id=?",
            (order_id,),
        )
        db.commit()

        assert ScheduleCapacityService._replay_generation_if_present(
            order_id,
            "generation-use-case-new-key",
            db,
        ) is None


def test_generation_occupancy_phase_ignores_invalid_intervals(client):
    with client.application.app_context():
        from modules.db import get_db

        db = get_db()
        occupancy = ScheduleCapacityService._load_generation_occupancy(
            -999999,
            True,
            db,
        )

        assert occupancy == {}
