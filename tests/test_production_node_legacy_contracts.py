import sqlite3

from factories import TEST_PASS, TEST_USER, create_order, ensure_process
from modules.db import get_db


def seed_legacy_line_schedule(client):
    with client.application.app_context():
        db = get_db()
        process_id = ensure_process(db, "兼容性焊接", seq_order=91)
        process_version_id = db.execute(
            "SELECT current_effective_version_id FROM processes WHERE id=?",
            (process_id,),
        ).fetchone()[0]
        line_id = db.execute(
            "INSERT INTO process_production_lines "
            "(process_id,line_code,line_name,daily_minutes,status,remark) "
            "VALUES (?,?,?,?,'active',?)",
            (process_id, "LEGACY-WELD-01", "焊接1线", 540, "legacy contract fixture"),
        ).lastrowid
        order_id = create_order(db, [process_id], quantity=12, product_code="LEGACY-NODE-001")
        operation_id = db.execute(
            "SELECT id FROM order_processes WHERE order_id=?", (order_id,)
        ).fetchone()[0]
        run_id = db.execute(
            "INSERT INTO schedule_runs "
            "(schedule_run_key,order_id,status,requested_start_date,result_json,result_digest,completed_at) "
            "VALUES (?,?, 'completed', ?, '[]', 'legacy-result-digest', ?)",
            ("legacy-node-contract-v1", order_id, "2026-09-14", "2026-09-14 10:00:00"),
        ).lastrowid
        schedule_id = db.execute(
            "INSERT INTO order_process_schedules "
            "(order_id,order_process_id,process_id,process_line_id,seq_order,quantity,"
            "standard_minutes_per_unit,setup_minutes,difficulty_factor,planned_minutes,"
            "plan_start,plan_end,status,blocked_reason,schedule_run_key,route_version_id,"
            "process_version_id,process_name_snapshot,route_name_snapshot,schedule_run_id,"
            "planned_start_at,planned_end_at,occupied_minutes,capacity_snapshot_json,"
            "standard_match_scope,shift_snapshot_json,line_name_snapshot) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                order_id,
                operation_id,
                process_id,
                line_id,
                1,
                12,
                15,
                30,
                1,
                210,
                "2026-09-14",
                "2026-09-14",
                "planned",
                "",
                "legacy-node-contract-v1",
                None,
                process_version_id,
                "兼容性焊接",
                "",
                run_id,
                "2026-09-14 08:00",
                "2026-09-14 11:30",
                210,
                '{"daily_minutes":540}',
                "legacy:generic",
                "[]",
                "焊接1线",
            ),
        ).lastrowid
        segment_id = db.execute(
            "INSERT INTO order_process_schedule_segments "
            "(schedule_id,process_line_id,segment_start_at,segment_end_at,occupied_minutes,quantity) "
            "VALUES (?,?,?,?,?,?)",
            (
                schedule_id,
                line_id,
                "2026-09-14 08:00",
                "2026-09-14 11:30",
                210,
                12,
            ),
        ).lastrowid
        revision_id = db.execute(
            "INSERT INTO schedule_revisions "
            "(order_id,schedule_run_id,revision_no,status,source_run_key,result_digest) "
            "VALUES (?,?,1,'draft',?,?)",
            (order_id, run_id, "legacy-node-contract-v1", "legacy-revision-digest"),
        ).lastrowid
        revision_item_id = db.execute(
            "INSERT INTO schedule_revision_items "
            "(revision_id,source_schedule_id,order_process_id,process_id,process_line_id,"
            "seq_order,quantity,status,planned_start_at,planned_end_at,occupied_minutes,"
            "payload_json,payload_digest) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                revision_id,
                schedule_id,
                operation_id,
                process_id,
                line_id,
                1,
                12,
                "planned",
                "2026-09-14 08:00",
                "2026-09-14 11:30",
                210,
                '{"line_name":"焊接1线"}',
                "legacy-item-digest",
            ),
        ).lastrowid
        db.execute(
            "UPDATE order_process_schedules SET schedule_revision_id=? WHERE id=?",
            (revision_id, schedule_id),
        )
        downtime_id = db.execute(
            "INSERT INTO schedule_downtime_events "
            "(process_line_id,start_at,end_at,reason,status,source_type) "
            "VALUES (?,?,?,?,'active','manual')",
            (
                line_id,
                "2026-09-14 12:00",
                "2026-09-14 13:00",
                "legacy maintenance window",
            ),
        ).lastrowid
        db.commit()

    login = client.post(
        "/api/auth/login", json={"username": TEST_USER, "password": TEST_PASS}
    )
    token = (login.get_json() or {}).get("user", {}).get("token", "")
    return {
        "headers": {"Authorization": f"Bearer {token}"},
        "order_id": order_id,
        "operation_id": operation_id,
        "process_id": process_id,
        "process_version_id": process_version_id,
        "line_id": line_id,
        "run_id": run_id,
        "schedule_id": schedule_id,
        "segment_id": segment_id,
        "revision_id": revision_id,
        "revision_item_id": revision_item_id,
        "downtime_id": downtime_id,
    }


def test_legacy_schedule_projection_remains_readable(client):
    seeded = seed_legacy_line_schedule(client)
    response = client.get(
        f"/api/schedule/order/{seeded['order_id']}/operations",
        headers=seeded["headers"],
    )
    assert response.status_code == 200
    operation = response.get_json()["operations"][0]
    assert operation["process_line_id"] == seeded["line_id"]
    assert operation["line_name"] == "焊接1线"
    assert operation.get("production_node_id") is None


def test_legacy_schedule_fact_fingerprint_remains_stable(client):
    seeded = seed_legacy_line_schedule(client)
    with client.application.app_context():
        db = get_db()
        fingerprint = {
            "order_process_schedules": dict(
                db.execute(
                    "SELECT id,order_id,order_process_id,process_id,process_line_id,seq_order,"
                    "quantity,standard_minutes_per_unit,setup_minutes,difficulty_factor,"
                    "planned_minutes,plan_start,plan_end,planned_start_at,planned_end_at,"
                    "occupied_minutes,status,blocked_reason,route_version_id,process_version_id,"
                    "standard_id,standard_version,process_name_snapshot,route_name_snapshot,"
                    "schedule_run_key,schedule_run_id,schedule_revision_id,capacity_snapshot_json,"
                    "standard_match_scope,calendar_id,shift_snapshot_json,line_name_snapshot,"
                    "execution_mode,completed_quantity_snapshot,rework_quantity_snapshot,"
                    "remaining_quantity_snapshot,source_fact_digest "
                    "FROM order_process_schedules WHERE id=?",
                    (seeded["schedule_id"],),
                ).fetchone()
            ),
            "order_process_schedule_segments": dict(
                db.execute(
                    "SELECT id,schedule_id,process_line_id,segment_start_at,segment_end_at,"
                    "occupied_minutes,quantity FROM order_process_schedule_segments WHERE id=?",
                    (seeded["segment_id"],),
                ).fetchone()
            ),
            "schedule_revision_items": dict(
                db.execute(
                    "SELECT id,revision_id,source_schedule_id,order_process_id,process_id,"
                    "process_line_id,seq_order,quantity,status,planned_start_at,planned_end_at,"
                    "occupied_minutes,payload_digest FROM schedule_revision_items WHERE id=?",
                    (seeded["revision_item_id"],),
                ).fetchone()
            ),
            "schedule_downtime_events": dict(
                db.execute(
                    "SELECT id,process_line_id,start_at,end_at,reason,status,source_type "
                    "FROM schedule_downtime_events WHERE id=?",
                    (seeded["downtime_id"],),
                ).fetchone()
            ),
        }

        assert fingerprint == {
            "order_process_schedules": {
                "id": seeded["schedule_id"],
                "order_id": seeded["order_id"],
                "order_process_id": seeded["operation_id"],
                "process_id": seeded["process_id"],
                "process_line_id": seeded["line_id"],
                "seq_order": 1,
                "quantity": 12,
                "standard_minutes_per_unit": 15.0,
                "setup_minutes": 30.0,
                "difficulty_factor": 1.0,
                "planned_minutes": 210.0,
                "plan_start": "2026-09-14",
                "plan_end": "2026-09-14",
                "planned_start_at": "2026-09-14 08:00",
                "planned_end_at": "2026-09-14 11:30",
                "occupied_minutes": 210.0,
                "status": "planned",
                "blocked_reason": "",
                "route_version_id": None,
                "process_version_id": seeded["process_version_id"],
                "standard_id": None,
                "standard_version": None,
                "process_name_snapshot": "兼容性焊接",
                "route_name_snapshot": "",
                "schedule_run_key": "legacy-node-contract-v1",
                "schedule_run_id": seeded["run_id"],
                "schedule_revision_id": seeded["revision_id"],
                "capacity_snapshot_json": '{"daily_minutes":540}',
                "standard_match_scope": "legacy:generic",
                "calendar_id": None,
                "shift_snapshot_json": "[]",
                "line_name_snapshot": "焊接1线",
                "execution_mode": "internal",
                "completed_quantity_snapshot": 0,
                "rework_quantity_snapshot": 0,
                "remaining_quantity_snapshot": 0,
                "source_fact_digest": "",
            },
            "order_process_schedule_segments": {
                "id": seeded["segment_id"],
                "schedule_id": seeded["schedule_id"],
                "process_line_id": seeded["line_id"],
                "segment_start_at": "2026-09-14 08:00",
                "segment_end_at": "2026-09-14 11:30",
                "occupied_minutes": 210.0,
                "quantity": 12,
            },
            "schedule_revision_items": {
                "id": seeded["revision_item_id"],
                "revision_id": seeded["revision_id"],
                "source_schedule_id": seeded["schedule_id"],
                "order_process_id": seeded["operation_id"],
                "process_id": seeded["process_id"],
                "process_line_id": seeded["line_id"],
                "seq_order": 1,
                "quantity": 12,
                "status": "planned",
                "planned_start_at": "2026-09-14 08:00",
                "planned_end_at": "2026-09-14 11:30",
                "occupied_minutes": 210.0,
                "payload_digest": "legacy-item-digest",
            },
            "schedule_downtime_events": {
                "id": seeded["downtime_id"],
                "process_line_id": seeded["line_id"],
                "start_at": "2026-09-14 12:00",
                "end_at": "2026-09-14 13:00",
                "reason": "legacy maintenance window",
                "status": "active",
                "source_type": "manual",
            },
        }

        try:
            db.execute(
                "UPDATE schedule_revision_items SET quantity=13 WHERE id=?",
                (seeded["revision_item_id"],),
            )
        except sqlite3.IntegrityError as exc:
            assert "immutable" in str(exc)
        else:
            raise AssertionError("legacy revision item unexpectedly became mutable")
