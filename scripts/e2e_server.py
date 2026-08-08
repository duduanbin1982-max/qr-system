#!/usr/bin/env python3
"""Run the real application against an isolated database for browser tests."""

import atexit
import json
import os
import sqlite3
import sys
from datetime import datetime
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
    from modules.services.performance_scoring_policy import PerformanceScoringPolicy
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
        race_worker_id = ensure_user(
            db, "e2eraceworker", TEST_HASH, "E2E Race Worker", "worker", "E2E-WORKER-003", "worker-group"
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
        production_month = datetime.now().strftime("%Y-%m")
        rules = PerformanceScoringPolicy.rules()
        db.execute(
            "INSERT INTO performance_rule_versions ("
            "version_code,name,weights_json,warning_levels_json,scoring_parameters_json,"
            "status,effective_from_month,created_by,created_by_name,published_by,published_by_name,published_at"
            ") VALUES (?,?,?,?,?,'published','2000-01',?,?,?, ?,datetime('now','localtime'))",
            (
                "e2e-performance-rule",
                "E2E 绩效规则",
                json.dumps(rules["weights"], ensure_ascii=False),
                json.dumps(rules["warning_levels"], ensure_ascii=False),
                json.dumps({
                    "work_days_target": rules["work_days_target"],
                    "handoff": rules["handoff"],
                    "improvement": rules["improvement"],
                }, ensure_ascii=False),
                admin_id,
                "E2E Administrator",
                admin_id,
                "E2E Administrator",
            ),
        )
        db.execute(
            "INSERT INTO performance_position_target_versions ("
            "position_id,position_name_snapshot,target_output_qty,minimum_effective_work_days,"
            "effective_from_month,status,created_by,created_by_name,approved_by,approved_by_name,approved_at"
            ") VALUES (?,?,1,1,?,'approved',?,?,?, ?,datetime('now','localtime'))",
            (
                position_id,
                "E2E Production Position",
                production_month,
                admin_id,
                "E2E Administrator",
                admin_id,
                "E2E Administrator",
            ),
        )
        for employee_id, employee_name, employee_no in (
            (worker_id, "E2E Current Worker", "E2E-WORKER-001"),
            (previous_worker_id, "E2E Previous Worker", "E2E-WORKER-002"),
        ):
            db.execute(
                "INSERT INTO performance_assignment_history ("
                "user_id,employee_name_snapshot,employee_no_snapshot,position_id,"
                "position_name_snapshot,valid_from,source_type,source_key,created_by"
                ") VALUES (?,?,?,?,?,'2000-01-01 00:00:00','e2e','e2e-assignment-' || ?,?)",
                (
                    employee_id,
                    employee_name,
                    employee_no,
                    position_id,
                    "E2E Production Position",
                    employee_id,
                    admin_id,
                ),
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
            db.execute(
                "INSERT OR IGNORE INTO user_processes (user_id, process_id) VALUES (?, ?)",
                (race_worker_id, process_id),
            )

        db.execute(
            "INSERT INTO inventory "
            "(product_model, product_name, specification, quantity, safe_stock, location, unit, remark) "
            "VALUES ('E2E-SHIP-MODEL', 'E2E Shipment Product', 'browser test item', 10, 1, 'E2E-A1', '件', '')"
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

        race_handoff_order_id = insert_order(
            db, "E2E-HANDOFF-RACE-ORDER", process_ids, qr_mode="serial", route_id=route_id
        )
        insert_serial(
            db,
            race_handoff_order_id,
            "E2E-HANDOFF-RACE-ORDER",
            "E2E-HANDOFF-RACE-001",
            process_ids[1],
        )
        db.execute(
            "INSERT INTO work_records "
            "(order_id, process_id, user_id, type, quantity, serial_no, status, created_at) "
            "VALUES (?, ?, ?, 'normal', 1, 'E2E-HANDOFF-RACE-001', 'approved', datetime('now','localtime'))",
            (race_handoff_order_id, process_ids[0], previous_worker_id),
        )
        db.execute(
            "UPDATE order_processes SET status = 'completed', completed = 1 "
            "WHERE order_id = ? AND process_id = ?",
            (race_handoff_order_id, process_ids[1]),
        )
        race_trigger_work_record_id = db.execute(
            "INSERT INTO work_records "
            "(order_id, process_id, user_id, type, quantity, serial_no, status, created_at) "
            "VALUES (?, ?, ?, 'normal', 1, 'E2E-HANDOFF-RACE-001', 'approved', datetime('now','localtime'))",
            (race_handoff_order_id, process_ids[1], race_worker_id),
        ).lastrowid
        ProcessQualityEvaluationService.generate_tasks(
            WorkReportCommand(
                report_type="normal",
                order_id=race_handoff_order_id,
                process_id=process_ids[1],
                user_id=race_worker_id,
                user_name="E2E Race Worker",
                quantity=1,
                serial_no="E2E-HANDOFF-RACE-001",
            ),
            race_trigger_work_record_id,
            db,
        )
        db.execute(
            "UPDATE product_items SET current_process_id = ? "
            "WHERE serial_no = 'E2E-HANDOFF-RACE-001'",
            (process_ids[2],),
        )

        insert_order(db, "E2E-QUALITY-GATE-ORDER", [process_ids[1]])
        insert_order(db, "E2E-QUALITY-RACE-GATE-ORDER", [process_ids[1]])

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
