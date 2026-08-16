import json
import logging

from factories import bind_order_process_versions, ensure_process_version
from modules.repositories.completion_focus_repository import CompletionFocusRepository
from modules.repositories.customer_repository import CustomerRepository
from modules.repositories.order_repository import OrderRepository
from modules.repositories.performance_fact_repository import PerformanceFactRepository
from modules.repositories.handoff_review_repository import HandoffReviewRepository
from modules.repositories.progress_repository import ProgressRepository
from modules.repositories.process_quality_evaluation_repository import (
    ProcessQualityEvaluationRepository,
)
from modules.repositories.process_quality_evaluation_task_repository import (
    ProcessQualityEvaluationTaskRepository,
)
from modules.repositories.quality_management.inspections import QualityInspectionRepository
from modules.repositories.quality_management.nonconformance import QualityNonconformanceRepository
from modules.repositories.quality_management.tasks import QualityTaskRepository
from modules.repositories.reports_repository import ReportsRepository
from modules.repositories.rework_repository import ReworkRepository
from modules.repositories.scan_repository import ScanRepository
from modules.repositories.stats_repository import StatsRepository
from modules.repositories.trace_repository import TraceRepository
from modules.repositories.wage_repository import WageRepository
from modules.repositories.work_time_repository import WorkTimeRepository


def _seed_history(db):
    process_id = db.execute(
        "INSERT INTO processes(name,description,category,seq_order,status) "
        "VALUES ('车削 V1','','机加工',1,'active')"
    ).lastrowid
    route_id = db.execute(
        "INSERT INTO process_routes(name,description,category,status) "
        "VALUES ('机加工路线 V1','','机加工','active')"
    ).lastrowid
    db.execute(
        "INSERT INTO process_route_items(route_id,process_id,seq_order,is_required) "
        "VALUES (?,?,1,1)",
        (route_id, process_id),
    )
    user_id = db.execute(
        "SELECT id FROM users WHERE status='active' ORDER BY id LIMIT 1"
    ).fetchone()["id"]
    order_id = db.execute(
        "INSERT INTO orders(order_no,product_name,product_code,quantity,status,route_id) "
        "VALUES ('HISTORY-V1','历史产品','HISTORY-P',10,'producing',?)",
        (route_id,),
    ).lastrowid
    db.execute(
        "INSERT INTO order_processes(order_id,process_id,seq_order,status) "
        "VALUES (?,?,1,'pending')",
        (order_id, process_id),
    )
    bind_order_process_versions(db, order_id)
    order_binding = db.execute(
        "SELECT route_version_id,route_name_snapshot FROM orders WHERE id=?",
        (order_id,),
    ).fetchone()
    process_binding = db.execute(
        "SELECT process_version_id,process_code_snapshot,process_name_snapshot,"
        "process_category_snapshot FROM order_processes WHERE order_id=? AND process_id=?",
        (order_id, process_id),
    ).fetchone()

    v1_id = ScanRepository.insert_work_record(
        {
            "order_id": order_id,
            "process_id": process_id,
            "user_id": user_id,
            "type": "normal",
            "quantity": 3,
        },
        db=db,
    )
    exact_fallback_id = db.execute(
        "INSERT INTO work_records(order_id,process_id,process_version_id,user_id,type,"
        "quantity,status,route_id,route_version_id,version_binding_source,created_at) "
        "VALUES (?,?,?,?, 'normal',2,'approved',?,?,'captured','2026-08-12 09:00:00')",
        (
            order_id,
            process_id,
            process_binding["process_version_id"],
            user_id,
            route_id,
            order_binding["route_version_id"],
        ),
    ).lastrowid

    db.execute(
        "UPDATE process_versions SET status='superseded' WHERE id=?",
        (process_binding["process_version_id"],),
    )
    db.execute(
        "UPDATE process_route_versions SET status='superseded' WHERE id=?",
        (order_binding["route_version_id"],),
    )
    process_v2_id = db.execute(
        "INSERT INTO process_versions(process_id,version,process_code_snapshot,name,"
        "category,description,seq_order,status,published_at) "
        "SELECT process_id,2,process_code_snapshot,'车削 V2',category,description,"
        "seq_order,'published',datetime('now','localtime') FROM process_versions WHERE id=?",
        (process_binding["process_version_id"],),
    ).lastrowid
    route_v2_id = db.execute(
        "INSERT INTO process_route_versions(process_route_id,version,route_code_snapshot,"
        "name,category,description,status,published_at) "
        "SELECT process_route_id,2,route_code_snapshot,'机加工路线 V2',category,description,"
        "'draft','' FROM process_route_versions WHERE id=?",
        (order_binding["route_version_id"],),
    ).lastrowid
    db.execute(
        "INSERT INTO process_route_version_items(route_version_id,process_id,"
        "process_version_id,seq_order,is_required) VALUES (?,?,?,1,1)",
        (route_v2_id, process_id, process_v2_id),
    )
    db.execute(
        "UPDATE process_route_versions SET status='published',"
        "published_at=datetime('now','localtime') WHERE id=?",
        (route_v2_id,),
    )
    db.execute(
        "UPDATE processes SET name='当前根工序',current_effective_version_id=? WHERE id=?",
        (process_v2_id, process_id),
    )
    db.execute(
        "UPDATE process_routes SET name='当前根路线',current_effective_version_id=? WHERE id=?",
        (route_v2_id, route_id),
    )
    legacy_id = db.execute(
        "INSERT INTO work_records(order_id,process_id,user_id,type,quantity,status,created_at) "
        "VALUES (?,?,?,'normal',1,'approved','2026-08-12 10:00:00')",
        (order_id, process_id, user_id),
    ).lastrowid
    db.execute(
        "UPDATE work_records SET created_at='2026-08-12 08:00:00' WHERE id=?",
        (v1_id,),
    )
    db.commit()
    return {
        "order_id": order_id,
        "process_id": process_id,
        "route_id": route_id,
        "user_id": user_id,
        "v1_id": v1_id,
        "exact_fallback_id": exact_fallback_id,
        "legacy_id": legacy_id,
        "process_v1_id": process_binding["process_version_id"],
        "route_v1_id": order_binding["route_version_id"],
    }


def test_history_readers_prefer_fact_snapshot_then_exact_version_then_legacy_root(client, caplog):
    with client.application.app_context():
        from modules.db import get_db

        db = get_db()
        ids = _seed_history(db)
        caplog.set_level(logging.WARNING, logger="qr-system.compatibility")

        daily = StatsRepository.get_daily_records("2026-08-12", "", 100, 0, db=db)
        daily_by_id = {row["id"]: row for row in daily}
        assert daily_by_id[ids["v1_id"]]["process_name"] == "车削 V1"
        assert daily_by_id[ids["v1_id"]]["route_name"] == "机加工路线 V1"
        assert daily_by_id[ids["exact_fallback_id"]]["process_name"] == "车削 V1"
        assert daily_by_id[ids["exact_fallback_id"]]["route_name"] == "机加工路线 V1"
        assert daily_by_id[ids["legacy_id"]]["process_name"] == "当前根工序"

        wage = {
            row["id"]: row
            for row in WageRepository.get_daily_report_rows("2026-08-12", db=db)
        }
        assert wage[ids["v1_id"]]["process_name"] == "车削 V1"
        assert wage[ids["exact_fallback_id"]]["process_name"] == "车削 V1"
        assert wage[ids["legacy_id"]]["process_name"] == "当前根工序"

        traced = {
            row["id"]: row
            for row in TraceRepository.find_work_records_by_order(
                ids["order_id"], db=db
            )
        }
        assert traced[ids["v1_id"]]["process_name"] == "车削 V1"
        assert traced[ids["legacy_id"]]["process_name"] == "当前根工序"

        performance = {
            row["id"]: row
            for row in PerformanceFactRepository.list_work_records(
                "2026-08-12 07:00:00", "2026-08-13 07:00:00", db=db
            )
        }
        assert performance[ids["v1_id"]]["process_name"] == "车削 V1"
        assert performance[ids["legacy_id"]]["process_name"] == "当前根工序"

        warning_payloads = [
            json.loads(record.message)
            for record in caplog.records
            if record.message.startswith("{")
        ]
        assert any(
            item.get("event") == "legacy_process_fact_read"
            and item.get("count", 0) >= 1
            for item in warning_payloads
        )


def test_versioned_report_aggregates_keep_historical_names_and_totals(client):
    with client.application.app_context():
        from modules.db import get_db

        db = get_db()
        ids = _seed_history(db)
        rows = ReportsRepository.fetch_quality_by_process(
            "wr.order_id=? AND wr.status='approved'",
            [ids["order_id"]],
            db=db,
        )
        output_by_name = {row["name"]: row["output"] for row in rows}

        assert output_by_name["车削 V1"] == 5
        assert output_by_name["当前根工序"] == 1
        assert sum(output_by_name.values()) == 6


def test_new_work_fact_marks_exact_binding_as_captured(client):
    with client.application.app_context():
        from modules.db import get_db

        db = get_db()
        ids = _seed_history(db)
        row = db.execute(
            "SELECT process_version_id,route_version_id,process_name_snapshot,"
            "route_name_snapshot,version_binding_source FROM work_records WHERE id=?",
            (ids["v1_id"],),
        ).fetchone()

        assert row["process_version_id"] == ids["process_v1_id"]
        assert row["route_version_id"] == ids["route_v1_id"]
        assert row["process_name_snapshot"] == "车削 V1"
        assert row["route_name_snapshot"] == "机加工路线 V1"
        assert row["version_binding_source"] == "captured"


def test_order_history_readers_fall_back_to_exact_bound_versions(client):
    with client.application.app_context():
        from modules.db import get_db

        db = get_db()
        ids = _seed_history(db)
        customer_id = db.execute(
            "INSERT INTO customers(name) VALUES ('历史客户')"
        ).lastrowid
        db.execute(
            "UPDATE orders SET customer_id=?,route_name_snapshot='' WHERE id=?",
            (customer_id, ids["order_id"]),
        )
        db.execute(
            "UPDATE order_processes SET process_name_snapshot='' WHERE order_id=?",
            (ids["order_id"],),
        )
        db.commit()

        order = OrderRepository.find_by_id(ids["order_id"], db=db)
        listed_orders, _ = OrderRepository.list_all(
            "o.id=?", [ids["order_id"]], 1, 20, db=db
        )
        customer_orders, _ = CustomerRepository.get_orders(
            customer_id, 1, 20, db=db
        )
        customer_processes = CustomerRepository.get_order_processes(
            ids["order_id"], db=db
        )
        progress_processes = ProgressRepository.list_processes(
            ids["order_id"], db=db
        )
        order_processes = OrderRepository.get_processes(ids["order_id"], db=db)
        listed_processes = OrderRepository.list_processes_for_orders(
            [ids["order_id"]], db=db
        )
        _, workpiece_processes, _ = OrderRepository.get_workpiece_progress_rows(
            ids["order_id"], db=db
        )
        scan_processes = ScanRepository.get_order_processes(ids["order_id"], db=db)
        focus_order = next(
            row
            for row in CompletionFocusRepository.list_orders(db=db)
            if row["id"] == ids["order_id"]
        )
        work_time_order = WorkTimeRepository.find_order(ids["order_id"], db=db)
        work_time_process = WorkTimeRepository.find_order_process(
            ids["order_id"], ids["process_id"], db=db
        )

        assert order["route_name"] == "机加工路线 V1"
        assert listed_orders[0]["route_name"] == "机加工路线 V1"
        assert customer_orders[0]["route_name"] == "机加工路线 V1"
        assert customer_processes[0]["process_name"] == "车削 V1"
        assert progress_processes[0]["process_name"] == "车削 V1"
        assert order_processes[0]["process_name"] == "车削 V1"
        assert listed_processes[0]["process_name"] == "车削 V1"
        assert workpiece_processes[0]["process_name"] == "车削 V1"
        assert scan_processes[0]["process_name"] == "车削 V1"
        assert focus_order["route_name"] == "机加工路线 V1"
        assert work_time_order["route_name"] == "机加工路线 V1"
        assert work_time_process["process_name"] == "车削 V1"


def test_rework_aggregates_and_export_keep_exact_process_versions(client):
    with client.application.app_context():
        from modules.db import get_db

        db = get_db()
        ids = _seed_history(db)
        rework_id = ReworkRepository.insert_rework_txn(
            ids["order_id"], ids["process_id"], ids["user_id"], 1, "返修", db
        )
        db.execute(
            "UPDATE rework_records SET process_name_snapshot='' WHERE id=?",
            (rework_id,),
        )
        db.commit()

        top = ReworkRepository.top_rework_processes(db=db)
        exported = ReworkRepository.find_all_for_export(db=db)

        assert top[0]["process_version_id"] == ids["process_v1_id"]
        assert top[0]["process_name"] == "车削 V1"
        assert exported[0]["process_name"] == "车削 V1"


def test_quality_and_handoff_facts_keep_order_bound_version_names(client):
    with client.application.app_context():
        from modules.db import get_db

        db = get_db()
        ids = _seed_history(db)

        handoff_id = HandoffReviewRepository.insert_review(
            {
                "order_id": ids["order_id"],
                "from_process_id": ids["process_id"],
                "to_process_id": ids["process_id"],
                "from_user_id": ids["user_id"],
                "evaluator_user_id": ids["user_id"],
                "source_work_record_id": ids["v1_id"],
                "rating": 5,
            },
            db,
        )
        quality_task_id = QualityTaskRepository.insert_task(
            {
                "task_no": "QT-HISTORY-V1",
                "trigger_key": "history-v1",
                "order_id": ids["order_id"],
                "process_id": ids["process_id"],
                "inspection_type": "in_process",
            },
            db,
        )
        inspection_id = QualityInspectionRepository.insert_inspection(
            {
                "task_id": quality_task_id,
                "order_id": ids["order_id"],
                "process_id": ids["process_id"],
                "inspection_type": "in_process",
                "result": "fail",
            },
            ids["user_id"],
            db,
        )
        ncr_id = QualityNonconformanceRepository.insert_ncr(
            {
                "ncr_no": "NCR-HISTORY-V1",
                "task_id": quality_task_id,
                "inspection_id": inspection_id,
                "order_id": ids["order_id"],
                "process_id": ids["process_id"],
                "responsible_process_id": ids["process_id"],
            },
            ids["user_id"],
            db,
        )
        ProcessQualityEvaluationTaskRepository.insert_task(
            {
                "trigger_work_record_id": ids["v1_id"],
                "order_id": ids["order_id"],
                "target_process_id": ids["process_id"],
                "evaluator_process_id": ids["process_id"],
                "target_work_record_id": ids["v1_id"],
                "target_user_id": ids["user_id"],
                "evaluator_user_id": ids["user_id"],
            },
            db,
        )
        evaluation_task_id = db.execute(
            "SELECT id FROM process_quality_evaluation_tasks "
            "WHERE trigger_work_record_id=? AND target_process_id=?",
            (ids["v1_id"], ids["process_id"]),
        ).fetchone()["id"]
        evaluation_id = ProcessQualityEvaluationRepository.insert_evaluation(
            {
                "task_id": evaluation_task_id,
                "order_id": ids["order_id"],
                "target_process_id": ids["process_id"],
                "evaluator_process_id": ids["process_id"],
                "target_work_record_id": ids["v1_id"],
                "trigger_work_record_id": ids["v1_id"],
                "target_user_id": ids["user_id"],
                "evaluator_user_id": ids["user_id"],
                "processing_quality": 5,
                "dimensional_accuracy": 5,
                "appearance_quality": 5,
                "process_continuity": 5,
                "cleanliness_protection": 5,
                "total_score": 100,
                "grade": "优秀",
            },
            db,
        )
        db.commit()

        handoff = HandoffReviewRepository.list_reviews(db=db)["items"][0]
        quality_task = QualityTaskRepository.task_by_id(quality_task_id, db=db)
        inspection = QualityInspectionRepository.inspection_by_id(inspection_id, db=db)
        ncr = QualityNonconformanceRepository.ncr_detail(ncr_id, db=db)
        evaluation = ProcessQualityEvaluationRepository.evaluation_by_id(
            evaluation_id, db=db
        )

        assert handoff["id"] == handoff_id
        assert handoff["from_process_name"] == "车削 V1"
        assert handoff["to_process_name"] == "车削 V1"
        assert quality_task["process_name"] == "车削 V1"
        assert inspection["process_name"] == "车削 V1"
        assert ncr["process_name"] == "车削 V1"
        assert ncr["responsible_process_name"] == "车削 V1"
        assert evaluation["target_process_name"] == "车削 V1"
        assert evaluation["evaluator_process_name"] == "车削 V1"
