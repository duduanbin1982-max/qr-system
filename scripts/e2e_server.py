#!/usr/bin/env python3
"""Run the real application against an isolated database for browser tests."""

import atexit
import json
import os
import sqlite3
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = PROJECT_ROOT / "tests"
E2E_DB = Path(os.environ.get("E2E_DB_PATH", "/tmp/qr_system_e2e.db"))

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(TESTS_ROOT))
os.environ["DB_PATH"] = str(E2E_DB)
os.environ["SECRET_KEY"] = "e2e-only-secret-key"
os.environ["ENABLE_SWAGGER"] = "false"


def remove_database():
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(E2E_DB) + suffix)
        candidate.unlink(missing_ok=True)


def insert_order(db, order_no, process_ids, *, status="producing", qr_mode="", route_id=None):
    cursor = db.execute(
        "INSERT INTO orders "
        "(order_no, customer, product_name, product_code, quantity, status, qr_mode, route_id) "
        "VALUES (?, 'E2E Customer', 'E2E Product', 'E2E-PRODUCT', 1, ?, ?, ?)",
        (order_no, status, qr_mode, route_id),
    )
    order_id = cursor.lastrowid
    for index, process_id in enumerate(process_ids):
        completed = 1 if status == "completed" or (qr_mode == "serial" and index == 0) else 0
        process_status = "completed" if completed else "pending"
        db.execute(
            "INSERT INTO order_processes "
            "(order_id, process_id, seq_order, status, completed, scrapped, rework) "
            "VALUES (?, ?, ?, ?, ?, 0, 0)",
            (order_id, process_id, index + 1, process_status, completed),
        )
    return order_id


def insert_serial(db, order_id, order_no, serial_no, current_process_id, status="in_progress"):
    db.execute(
        "INSERT INTO product_items "
        "(serial_no, order_id, order_no, position_no, qr_content, status, current_process_id) "
        "VALUES (?, ?, ?, 1, ?, ?, ?)",
        (
            serial_no,
            order_id,
            order_no,
            json.dumps({"order_id": order_id, "serial_no": serial_no}),
            status,
            current_process_id,
        ),
    )


def prepare_database():
    remove_database()
    from modules.domain.work_report import WorkReportCommand
    from modules.migrations import run_migrations
    from modules.services.process_quality_evaluation_service import ProcessQualityEvaluationService
    from factory_auth import TEST_HASH, ensure_user

    db = sqlite3.connect(E2E_DB)
    db.row_factory = sqlite3.Row
    try:
        run_migrations(db)
        admin_id = ensure_user(
            db, "e2eadmin", TEST_HASH, "E2E Administrator", "admin", "E2E-ADMIN-001"
        )
        worker_id = ensure_user(
            db, "e2eworker", TEST_HASH, "E2E Current Worker", "worker", "E2E-WORKER-001", "worker-group"
        )
        previous_worker_id = ensure_user(
            db, "e2eprevious", TEST_HASH, "E2E Previous Worker", "worker", "E2E-WORKER-002", "worker-group"
        )
        position_id = db.execute(
            "INSERT INTO positions (name, description, status) "
            "VALUES ('E2E Production Position', 'browser test position', 'active')"
        ).lastrowid
        db.execute(
            "UPDATE users SET position_id = ? WHERE id IN (?, ?)",
            (position_id, worker_id, previous_worker_id),
        )

        process_ids = []
        for sequence, name in enumerate(("E2E Cutting", "E2E Welding", "E2E Drilling"), start=1):
            process_ids.append(
                db.execute(
                    "INSERT INTO processes "
                    "(name, description, category, seq_order, status, updated_at) "
                    "VALUES (?, 'browser test process', 'e2e', ?, 'active', datetime('now','localtime'))",
                    (name, sequence),
                ).lastrowid
            )
        forbidden_process_id = db.execute(
            "INSERT INTO processes "
            "(name, description, category, seq_order, status, updated_at) "
            "VALUES ('E2E Restricted Process', 'browser test process', 'e2e', 9, 'active', datetime('now','localtime'))"
        ).lastrowid

        route_id = db.execute(
            "INSERT INTO process_routes (name, description, status, category, updated_at) "
            "VALUES ('E2E Standard Route', 'browser test route', 'active', 'e2e', datetime('now','localtime'))"
        ).lastrowid
        for sequence, process_id in enumerate(process_ids, start=1):
            db.execute(
                "INSERT INTO process_route_items (route_id, process_id, seq_order, required_audit) "
                "VALUES (?, ?, ?, 0)",
                (route_id, process_id, sequence),
            )

        for process_id in process_ids[1:]:
            db.execute(
                "INSERT OR IGNORE INTO user_processes (user_id, process_id) VALUES (?, ?)",
                (worker_id, process_id),
            )

        insert_order(db, "E2E-ORDER-001", process_ids, route_id=route_id)

        handoff_order_id = insert_order(
            db, "E2E-HANDOFF-ORDER", process_ids, qr_mode="serial", route_id=route_id
        )
        insert_serial(
            db,
            handoff_order_id,
            "E2E-HANDOFF-ORDER",
            "E2E-HANDOFF-001",
            process_ids[1],
        )
        db.execute(
            "INSERT INTO work_records "
            "(order_id, process_id, user_id, type, quantity, serial_no, status, created_at) "
            "VALUES (?, ?, ?, 'normal', 1, 'E2E-HANDOFF-001', 'approved', datetime('now','localtime'))",
            (handoff_order_id, process_ids[0], previous_worker_id),
        )
        db.execute(
            "UPDATE order_processes SET status = 'completed', completed = 1 "
            "WHERE order_id = ? AND process_id = ?",
            (handoff_order_id, process_ids[1]),
        )
        trigger_work_record_id = db.execute(
            "INSERT INTO work_records "
            "(order_id, process_id, user_id, type, quantity, serial_no, status, created_at) "
            "VALUES (?, ?, ?, 'normal', 1, 'E2E-HANDOFF-001', 'approved', datetime('now','localtime'))",
            (handoff_order_id, process_ids[1], worker_id),
        ).lastrowid
        ProcessQualityEvaluationService.generate_tasks(
            WorkReportCommand(
                report_type="normal",
                order_id=handoff_order_id,
                process_id=process_ids[1],
                user_id=worker_id,
                user_name="E2E Current Worker",
                quantity=1,
                serial_no="E2E-HANDOFF-001",
            ),
            trigger_work_record_id,
            db,
        )
        db.execute(
            "UPDATE product_items SET current_process_id = ? WHERE serial_no = 'E2E-HANDOFF-001'",
            (process_ids[2],),
        )

        insert_order(db, "E2E-QUALITY-GATE-ORDER", [process_ids[1]])

        completed_order_id = insert_order(
            db, "E2E-COMPLETE-ORDER", [process_ids[0]], status="completed", qr_mode="serial", route_id=route_id
        )
        insert_serial(
            db,
            completed_order_id,
            "E2E-COMPLETE-ORDER",
            "E2E-COMPLETE-001",
            process_ids[0],
            status="completed",
        )

        forbidden_order_id = insert_order(
            db, "E2E-FORBIDDEN-ORDER", [forbidden_process_id], qr_mode="serial"
        )
        insert_serial(
            db,
            forbidden_order_id,
            "E2E-FORBIDDEN-ORDER",
            "E2E-FORBIDDEN-001",
            forbidden_process_id,
        )
        db.commit()
        return {"admin_id": admin_id, "worker_id": worker_id}
    finally:
        db.close()


prepare_database()
atexit.register(remove_database)

from server import app


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=4173, debug=False, use_reloader=False, threaded=True)
