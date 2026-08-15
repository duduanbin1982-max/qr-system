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


def insert_published_process(db, name, sequence, created_by):
    process_id = db.execute("SELECT COALESCE(MAX(id),0)+1 FROM processes").fetchone()[0]
    process_code = f"E2E-PROC-{process_id:04d}"
    db.execute(
        "INSERT INTO processes ("
        "id,process_code,name,description,category,seq_order,status,lifecycle_status,"
        "row_version,created_by,updated_at) "
        "VALUES (?,?,?,'browser test process','e2e',?,'active','active',0,?,"
        "datetime('now','localtime'))",
        (process_id, process_code, name, sequence, created_by),
    )
    version_id = db.execute(
        "INSERT INTO process_versions ("
        "process_id,version,process_code_snapshot,name,category,description,seq_order,status,"
        "effective_from,revision_reason,legacy_baseline,prior_revision_unavailable,created_by,"
        "created_by_name,approved_by,approved_by_name,approved_at,published_at,idempotency_key) "
        "VALUES (?,1,?,?,?,'browser test process',?,'published',datetime('now','localtime'),"
        "'E2E fixture V1',0,0,?,'E2E Administrator',?,'E2E Administrator',"
        "datetime('now','localtime'),datetime('now','localtime'),?)",
        (
            process_id,
            process_code,
            name,
            "e2e",
            sequence,
            created_by,
            created_by,
            f"e2e:process:{process_id}:v1",
        ),
    ).lastrowid
    db.execute(
        "UPDATE processes SET current_effective_version_id=? WHERE id=?",
        (version_id, process_id),
    )
    return process_id


def insert_published_route(db, name, process_ids, created_by):
    route_id = db.execute("SELECT COALESCE(MAX(id),0)+1 FROM process_routes").fetchone()[0]
    route_code = f"E2E-ROUTE-{route_id:04d}"
    db.execute(
        "INSERT INTO process_routes ("
        "id,route_code,name,description,category,status,lifecycle_status,row_version,"
        "created_by,updated_at) "
        "VALUES (?,?,?,'browser test route','e2e','active','active',0,?,"
        "datetime('now','localtime'))",
        (route_id, route_code, name, created_by),
    )
    route_version_id = db.execute(
        "INSERT INTO process_route_versions ("
        "process_route_id,version,route_code_snapshot,name,category,description,status,"
        "revision_reason,legacy_baseline,prior_revision_unavailable,created_by,created_by_name,"
        "approved_by,approved_by_name,idempotency_key) "
        "VALUES (?,1,?,?,?,'browser test route','draft','E2E fixture V1',0,0,?,"
        "'E2E Administrator',?,'E2E Administrator',?)",
        (
            route_id,
            route_code,
            name,
            "e2e",
            created_by,
            created_by,
            f"e2e:route:{route_id}:v1",
        ),
    ).lastrowid
    for sequence, process_id in enumerate(process_ids, start=1):
        process_version_id = db.execute(
            "SELECT current_effective_version_id FROM processes WHERE id=?",
            (process_id,),
        ).fetchone()[0]
        legacy_item_id = db.execute(
            "INSERT INTO process_route_items ("
            "route_id,process_id,seq_order,is_required,required_audit) VALUES (?,?,?,1,0)",
            (route_id, process_id, sequence),
        ).lastrowid
        db.execute(
            "INSERT INTO process_route_version_items ("
            "route_version_id,process_id,process_version_id,seq_order,is_required,"
            "required_audit,legacy_route_item_id) VALUES (?,?,?,?,1,0,?)",
            (
                route_version_id,
                process_id,
                process_version_id,
                sequence,
                legacy_item_id,
            ),
        )
    db.execute(
        "UPDATE process_route_versions SET status='published',"
        "effective_from=datetime('now','localtime'),approved_at=datetime('now','localtime'),"
        "published_at=datetime('now','localtime') WHERE id=? AND status='draft'",
        (route_version_id,),
    )
    db.execute(
        "UPDATE process_routes SET current_effective_version_id=? WHERE id=?",
        (route_version_id, route_id),
    )
    return route_id


def insert_order(db, order_no, process_ids, *, status="producing", qr_mode="", route_id=None):
    route_version = None
    if route_id is not None:
        route_version = db.execute(
            "SELECT version.id,version.name FROM process_routes route "
            "JOIN process_route_versions version "
            "ON version.id=route.current_effective_version_id WHERE route.id=?",
            (route_id,),
        ).fetchone()
    cursor = db.execute(
        "INSERT INTO orders "
        "(order_no,customer,product_name,product_code,quantity,status,qr_mode,route_id,"
        "route_version_id,route_name_snapshot) "
        "VALUES (?,'E2E Customer','E2E Product','E2E-PRODUCT',1,?,?,?,?,?)",
        (
            order_no,
            status,
            qr_mode,
            route_id,
            route_version["id"] if route_version else None,
            route_version["name"] if route_version else "",
        ),
    )
    order_id = cursor.lastrowid
    for index, process_id in enumerate(process_ids):
        completed = 1 if status == "completed" or (qr_mode == "serial" and index == 0) else 0
        process_status = "completed" if completed else "pending"
        process_version = db.execute(
            "SELECT version.id,version.process_code_snapshot,version.name,version.category "
            "FROM processes process JOIN process_versions version "
            "ON version.id=process.current_effective_version_id WHERE process.id=?",
            (process_id,),
        ).fetchone()
        db.execute(
            "INSERT INTO order_processes "
            "(order_id,process_id,seq_order,status,completed,scrapped,rework,"
            "process_version_id,process_code_snapshot,process_name_snapshot,"
            "process_category_snapshot) VALUES (?,?,?,?,?,0,0,?,?,?,?)",
            (
                order_id,
                process_id,
                index + 1,
                process_status,
                completed,
                process_version["id"],
                process_version["process_code_snapshot"],
                process_version["name"],
                process_version["category"],
            ),
        )
    return order_id


def insert_work_record(db, order_id, process_id, user_id, serial_no):
    from modules.process_fact_projection import capture_process_fact_binding

    binding = capture_process_fact_binding(
        db,
        order_id=order_id,
        process_id=process_id,
    )
    return db.execute(
        "INSERT INTO work_records ("
        "order_id,process_id,user_id,type,quantity,serial_no,status,created_at,"
        "process_version_id,process_code_snapshot,process_name_snapshot,"
        "process_category_snapshot,route_id,route_version_id,route_name_snapshot,"
        "version_binding_source) "
        "VALUES (?,?,?,'normal',1,?,'approved',datetime('now','localtime'),?,?,?,?,?,?,?,?)",
        (
            order_id,
            process_id,
            user_id,
            serial_no,
            binding["process_version_id"],
            binding["process_code_snapshot"],
            binding["process_name_snapshot"],
            binding["process_category_snapshot"],
            binding["route_id"],
            binding["route_version_id"],
            binding["route_name_snapshot"],
            binding["version_binding_source"],
        ),
    ).lastrowid


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

        process_ids = [
            insert_published_process(db, name, sequence, admin_id)
            for sequence, name in enumerate(
                ("E2E Cutting", "E2E Welding", "E2E Drilling"), start=1
            )
        ]
        forbidden_process_id = insert_published_process(
            db, "E2E Restricted Process", 9, admin_id
        )

        route_id = insert_published_route(
            db, "E2E Standard Route", process_ids, admin_id
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
        insert_work_record(
            db,
            handoff_order_id,
            process_ids[0],
            previous_worker_id,
            "E2E-HANDOFF-001",
        )
        db.execute(
            "UPDATE order_processes SET status = 'completed', completed = 1 "
            "WHERE order_id = ? AND process_id = ?",
            (handoff_order_id, process_ids[1]),
        )
        trigger_work_record_id = insert_work_record(
            db,
            handoff_order_id,
            process_ids[1],
            worker_id,
            "E2E-HANDOFF-001",
        )
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
        insert_work_record(
            db,
            race_handoff_order_id,
            process_ids[0],
            previous_worker_id,
            "E2E-HANDOFF-RACE-001",
        )
        db.execute(
            "UPDATE order_processes SET status = 'completed', completed = 1 "
            "WHERE order_id = ? AND process_id = ?",
            (race_handoff_order_id, process_ids[1]),
        )
        race_trigger_work_record_id = insert_work_record(
            db,
            race_handoff_order_id,
            process_ids[1],
            race_worker_id,
            "E2E-HANDOFF-RACE-001",
        )
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
    app.run(
        host="127.0.0.1",
        port=int(os.environ.get("E2E_PORT", "4173")),
        debug=False,
        use_reloader=False,
        threaded=True,
    )
