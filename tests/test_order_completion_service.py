import uuid

from modules.db import get_db
from modules.services.order_completion_service import OrderCompletionService
from modules.services.order_service import OrderService
from modules.services.approval_service import ApprovalService
from modules.services.work_report_writer import WorkReportWriter


def _seed_completed_serial_order(client, quantity=2, status="producing"):
    suffix = uuid.uuid4().hex[:8].upper()
    with client.application.app_context():
        db = get_db()
        process_id = db.execute(
            "INSERT INTO processes (name, description, category, seq_order, status, updated_at) "
            "VALUES (?, 'completion fixture', 'fixture', 1, 'active', datetime('now','localtime'))",
            (f"Completion Process {suffix}",),
        ).lastrowid
        order_id = db.execute(
            "INSERT INTO orders (order_no, customer, product_name, product_code, quantity, "
            "completed, status, qr_mode, extra_fields) "
            "VALUES (?, 'Test Customer', 'Completion Product', ?, ?, 0, ?, 'serial', ?)",
            (f"TEST-COMP-{suffix}", f"COMP-{suffix}", quantity, status, '{"status":"pending"}'),
        ).lastrowid
        db.execute(
            "INSERT INTO order_processes "
            "(order_id, process_id, seq_order, status, completed, scrapped, rework) "
            "VALUES (?, ?, 1, 'completed', ?, 0, 0)",
            (order_id, process_id, quantity),
        )
        for position in range(1, quantity + 1):
            serial_no = f"TEST-COMP-{suffix}-{position:03d}"
            db.execute(
                "INSERT INTO product_items "
                "(serial_no, order_id, qr_content, status, position_no, completed_at) "
                "VALUES (?, ?, ?, 'completed', ?, datetime('now','localtime'))",
                (serial_no, order_id, serial_no, position),
            )
        db.commit()
    return order_id, process_id


def _order_state(client, order_id):
    with client.application.app_context():
        row = get_db().execute(
            "SELECT status, completed FROM orders WHERE id = ?", (order_id,)
        ).fetchone()
        return dict(row)


def test_reconcile_completes_serial_order_and_ignores_extra_fields_status(client):
    order_id, _ = _seed_completed_serial_order(client)

    with client.application.app_context():
        result = OrderCompletionService.reconcile(
            order_id, trigger="pytest_completion", actor_id=1
        )
        audit = get_db().execute(
            "SELECT action, detail FROM audit_logs WHERE target_type = 'order' "
            "AND target_id = ? ORDER BY id DESC LIMIT 1",
            (order_id,),
        ).fetchone()

    assert result["changed"] is True
    assert _order_state(client, order_id) == {"status": "completed", "completed": 2}
    assert audit["action"] == "order_status_reconciled"
    assert "pytest_completion" in audit["detail"]


def test_reopen_does_not_immediately_recomplete_order(client):
    order_id, _ = _seed_completed_serial_order(client, status="completed")

    with client.application.app_context():
        OrderService.reopen_order(order_id, "修正路线")

    assert _order_state(client, order_id)["status"] == "producing"


def test_structure_update_recompletes_reopened_order(client):
    order_id, process_id = _seed_completed_serial_order(client, status="completed")

    with client.application.app_context():
        OrderService.reopen_order(order_id, "修正路线")
        OrderService.update_order(
            order_id,
            {"process_ids": [process_id]},
            user_id=1,
            user_name="Admin",
        )

    assert _order_state(client, order_id) == {"status": "completed", "completed": 2}


def test_new_pending_process_keeps_reopened_order_active(client):
    order_id, process_id = _seed_completed_serial_order(client, status="completed")
    suffix = uuid.uuid4().hex[:8].upper()

    with client.application.app_context():
        db = get_db()
        pending_process_id = db.execute(
            "INSERT INTO processes (name, description, category, seq_order, status, updated_at) "
            "VALUES (?, 'completion fixture', 'fixture', 2, 'active', datetime('now','localtime'))",
            (f"Pending Completion Process {suffix}",),
        ).lastrowid
        db.commit()
        OrderService.reopen_order(order_id, "新增遗漏工序")
        OrderService.update_order(
            order_id,
            {"process_ids": [process_id, pending_process_id]},
            user_id=1,
            user_name="Admin",
        )

    assert _order_state(client, order_id) == {"status": "producing", "completed": 2}


def test_pending_serial_report_advances_only_after_approval(client):
    suffix = uuid.uuid4().hex[:8].upper()
    with client.application.app_context():
        db = get_db()
        worker = db.execute(
            "SELECT id, COALESCE(name, username, '') AS name FROM users ORDER BY id LIMIT 1"
        ).fetchone()
        process_id = db.execute(
            "INSERT INTO processes (name, description, category, seq_order, status, updated_at) "
            "VALUES (?, 'approval fixture', 'fixture', 1, 'active', datetime('now','localtime'))",
            (f"Approval Completion Process {suffix}",),
        ).lastrowid
        order_id = db.execute(
            "INSERT INTO orders (order_no, customer, product_name, product_code, quantity, "
            "completed, status, qr_mode) "
            "VALUES (?, 'Test Customer', 'Approval Product', ?, 1, 0, 'producing', 'serial')",
            (f"TEST-APPROVAL-COMP-{suffix}", f"APPROVAL-COMP-{suffix}"),
        ).lastrowid
        db.execute(
            "INSERT INTO order_processes "
            "(order_id, process_id, seq_order, status, completed, scrapped, rework) "
            "VALUES (?, ?, 1, 'pending', 0, 0, 0)",
            (order_id, process_id),
        )
        serial_no = f"TEST-APPROVAL-COMP-{suffix}-001"
        db.execute(
            "INSERT INTO product_items "
            "(serial_no, order_id, qr_content, status, position_no, current_process_id) "
            "VALUES (?, ?, ?, 'in_progress', 1, ?)",
            (serial_no, order_id, serial_no, process_id),
        )
        db.commit()

        WorkReportWriter.execute_report_write(
            "normal",
            order_id,
            process_id,
            worker["id"],
            worker["name"],
            1,
            "",
            serial_no,
            True,
        )

        before = db.execute(
            "SELECT status, current_process_id FROM product_items WHERE serial_no = ?",
            (serial_no,),
        ).fetchone()
        approval_id = db.execute(
            "SELECT ar.id FROM approval_records ar "
            "JOIN work_records wr ON wr.id = ar.work_record_id "
            "WHERE wr.order_id = ?",
            (order_id,),
        ).fetchone()["id"]
        assert dict(before) == {"status": "in_progress", "current_process_id": process_id}
        assert _order_state(client, order_id) == {"status": "producing", "completed": 0}

        ApprovalService.handle(
            approval_id,
            "approve",
            {"id": worker["id"], "name": worker["name"]},
            "approved in test",
        )

        after = db.execute(
            "SELECT status, current_process_id FROM product_items WHERE serial_no = ?",
            (serial_no,),
        ).fetchone()
        process = db.execute(
            "SELECT status, completed FROM order_processes "
            "WHERE order_id = ? AND process_id = ?",
            (order_id, process_id),
        ).fetchone()

    assert dict(after) == {"status": "completed", "current_process_id": None}
    assert dict(process) == {"status": "completed", "completed": 1}
    assert _order_state(client, order_id) == {"status": "completed", "completed": 1}
