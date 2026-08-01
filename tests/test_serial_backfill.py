"""Controlled serial-number cross-process backfill integration tests."""

import json
import uuid
from modules.db import clear_settings_cache, get_db
from modules.services.approval_service import ApprovalService


def _seed_serial_order(client):
    suffix = uuid.uuid4().hex[:6].upper()
    with client.application.app_context():
        db = get_db()
        worker = db.execute(
            "SELECT * FROM users WHERE username = 'testworker'"
        ).fetchone()
        admin = db.execute(
            "SELECT * FROM users WHERE username = 'testrunner'"
        ).fetchone()
        assert worker is not None and admin is not None

        process_ids = []
        for sequence, name in enumerate(
            (f"Backfill A {suffix}", f"Backfill B {suffix}", f"Backfill C {suffix}"),
            start=1,
        ):
            process_ids.append(
                db.execute(
                    "INSERT INTO processes "
                    "(name, description, category, seq_order, status, updated_at) "
                    "VALUES (?, 'serial backfill test', 'fixture', ?, 'active', "
                    "datetime('now','localtime'))",
                    (name, sequence),
                ).lastrowid
            )

        position_id = db.execute(
            "INSERT INTO positions (name, description, status) "
            "VALUES (?, 'serial backfill fixture', 'active')",
            (f"Backfill Position {suffix}",),
        ).lastrowid
        db.execute(
            "INSERT INTO position_processes (position_id, process_id) VALUES (?, ?)",
            (position_id, process_ids[2]),
        )
        db.execute(
            "INSERT INTO position_processes (position_id, process_id) VALUES (?, ?)",
            (position_id, process_ids[0]),
        )
        db.execute(
            "INSERT INTO position_processes (position_id, process_id) VALUES (?, ?)",
            (position_id, process_ids[1]),
        )
        db.execute("UPDATE users SET position_id = ? WHERE id = ?", (position_id, worker["id"]))
        db.execute(
            "UPDATE user_sessions SET active_position_id = ? WHERE user_id = ? AND is_active = 1",
            (position_id, worker["id"]),
        )

        order_no = f"TEST-BACKFILL-{suffix}"
        serial_no = f"{order_no}-001"
        order_id = db.execute(
            "INSERT INTO orders "
            "(order_no, customer, product_name, product_code, quantity, status, qr_mode) "
            "VALUES (?, 'Test Customer', 'Backfill Product', ?, 1, 'producing', 'serial')",
            (order_no, f"BF-{suffix}"),
        ).lastrowid
        for sequence, process_id in enumerate(process_ids, start=1):
            db.execute(
                "INSERT INTO order_processes "
                "(order_id, process_id, seq_order, status, completed, scrapped, rework) "
                "VALUES (?, ?, ?, 'pending', 0, 0, 0)",
                (order_id, process_id, sequence),
            )
        db.execute(
            "INSERT INTO product_items "
            "(serial_no, order_id, order_no, position_no, qr_content, status, current_process_id) "
            "VALUES (?, ?, ?, 1, ?, 'in_progress', ?)",
            (
                serial_no,
                order_id,
                order_no,
                json.dumps({"order_id": order_id, "serial_no": serial_no}),
                process_ids[0],
            ),
        )
        db.execute(
            "INSERT INTO system_settings (key, value, updated_at) "
            "VALUES ('serial_process_report_mode', 'controlled_backfill', "
            "datetime('now','localtime')) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "updated_at=excluded.updated_at"
        )
        db.commit()
        clear_settings_cache()
        return {
            "order_id": order_id,
            "order_no": order_no,
            "serial_no": serial_no,
            "process_ids": process_ids,
            "worker_id": worker["id"],
            "position_id": position_id,
            "admin": dict(admin),
        }


def _report(client, headers, fixture, process_id, **extra):
    payload = {
        "order_id": fixture["order_id"],
        "process_id": process_id,
        "quantity": 1,
        "serial_no": fixture["serial_no"],
        "report_type": "normal",
    }
    payload.update(extra)
    return client.post("/api/mobile/report", headers=headers, json=payload)


def test_controlled_backfill_waits_for_approval_and_reconciles_serial_progress(
    client, auth_headers, worker_auth_headers
):
    fixture = _seed_serial_order(client)
    first_process, second_process, third_process = fixture["process_ids"]

    scan = client.post(
        "/api/mobile/scan",
        headers=worker_auth_headers,
        json={"code": fixture["serial_no"]},
    )
    assert scan.status_code == 200, scan.get_json()
    processes = scan.get_json()["order"]["processes"]
    assert processes[0]["normal_reportable"] is True
    assert processes[2]["serial_backfill_reportable"] is True
    assert scan.get_json()["order"]["serial_backfill_selection_source"] == "position_manual"
    assert scan.get_json()["order"]["serial_backfill_candidate_count"] == 2

    backfill = _report(
        client,
        worker_auth_headers,
        fixture,
        third_process,
        serial_backfill=True,
    )
    assert backfill.status_code == 200, backfill.get_json()
    assert backfill.get_json()["serial_backfill"] is True
    assert backfill.get_json()["approval_required"] is True

    pending_scan = client.post(
        "/api/mobile/scan",
        headers=worker_auth_headers,
        json={"code": fixture["serial_no"]},
    )
    pending_processes = pending_scan.get_json()["order"]["processes"]
    assert pending_processes[2]["serial_report_status"] == "pending"
    assert pending_processes[2]["serial_backfill_reportable"] is False

    with client.application.app_context():
        db = get_db()
        work_record = db.execute(
            "SELECT * FROM work_records WHERE order_id = ? AND process_id = ?",
            (fixture["order_id"], third_process),
        ).fetchone()
        item = db.execute(
            "SELECT * FROM product_items WHERE serial_no = ?",
            (fixture["serial_no"],),
        ).fetchone()
        approval = db.execute(
            "SELECT * FROM approval_records WHERE work_record_id = ?",
            (work_record["id"],),
        ).fetchone()
        assert work_record["status"] == "pending"
        assert work_record["report_source"] == "serial_backfill"
        assert work_record["submit_position_id"]
        assert work_record["submit_position_name"]
        assert item["current_process_id"] == first_process
        assert approval["status"] == "pending"
        approval_id = approval["id"]

    ApprovalService.handle(
        approval_id,
        "approve",
        fixture["admin"],
        comment="补报事实已核实",
    )

    approved_scan = client.post(
        "/api/mobile/scan",
        headers=worker_auth_headers,
        json={"code": fixture["serial_no"]},
    )
    approved_processes = approved_scan.get_json()["order"]["processes"]
    assert approved_processes[2]["serial_report_status"] == "approved"
    assert approved_processes[0]["normal_reportable"] is True

    with client.application.app_context():
        item = get_db().execute(
            "SELECT * FROM product_items WHERE serial_no = ?",
            (fixture["serial_no"],),
        ).fetchone()
        assert item["status"] == "in_progress"
        assert item["current_process_id"] == first_process

    first_report = _report(
        client, worker_auth_headers, fixture, first_process
    )
    assert first_report.status_code == 200, first_report.get_json()
    with client.application.app_context():
        item = get_db().execute(
            "SELECT * FROM product_items WHERE serial_no = ?",
            (fixture["serial_no"],),
        ).fetchone()
        assert item["current_process_id"] == second_process

    second_report = _report(
        client, worker_auth_headers, fixture, second_process
    )
    assert second_report.status_code == 200, second_report.get_json()
    with client.application.app_context():
        db = get_db()
        item = db.execute(
            "SELECT * FROM product_items WHERE serial_no = ?",
            (fixture["serial_no"],),
        ).fetchone()
        assert item["status"] == "completed"
        assert item["current_process_id"] is None
        assert db.execute(
            "SELECT COUNT(*) FROM work_records WHERE order_id = ? "
            "AND serial_no = ? AND type = 'normal' AND status = 'approved'",
            (fixture["order_id"], fixture["serial_no"]),
        ).fetchone()[0] == 3
        assert db.execute(
            "SELECT COUNT(*) FROM inventory_logs WHERE order_id = ? AND type = 'in'",
            (fixture["order_id"],),
        ).fetchone()[0] == 1


def test_strict_serial_mode_rejects_cross_process_backfill(
    client, auth_headers, worker_auth_headers
):
    fixture = _seed_serial_order(client)
    with client.application.app_context():
        db = get_db()
        db.execute(
            "UPDATE system_settings SET value = 'strict' "
            "WHERE key = 'serial_process_report_mode'"
        )
        db.commit()
        clear_settings_cache()

    response = _report(
        client,
        worker_auth_headers,
        fixture,
        fixture["process_ids"][2],
        serial_backfill=True,
    )
    assert response.status_code == 400
    assert "未开启" in response.get_json()["error"]


def test_backfill_rejects_process_outside_active_position(
    client, worker_auth_headers
):
    fixture = _seed_serial_order(client)
    with client.application.app_context():
        db = get_db()
        other_position_id = db.execute(
            "INSERT INTO positions (name, description, status) "
            "VALUES ('Other Position', '', 'active')"
        ).lastrowid
        db.execute(
            "INSERT INTO position_processes (position_id, process_id) VALUES (?, ?)",
            (other_position_id, fixture["process_ids"][0]),
        )
        db.execute(
            "UPDATE user_sessions SET active_position_id = ? "
            "WHERE user_id = ? AND is_active = 1",
            (other_position_id, fixture["worker_id"]),
        )
        db.commit()

    response = _report(
        client,
        worker_auth_headers,
        fixture,
        fixture["process_ids"][2],
        serial_backfill=True,
    )
    assert response.status_code == 400
    assert "不属于当前岗位" in response.get_json()["error"]
