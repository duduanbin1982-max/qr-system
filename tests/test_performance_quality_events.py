import json

import pytest

from factories import WORKER_HASH, create_order, ensure_process, ensure_user
from modules.db import get_db
from modules.domain.work_report import WorkReportCommand
from modules.repositories.performance_fact_repository import PerformanceFactRepository
from modules.services.performance_quality_event_service import (
    PerformanceQualityEventService,
)
from modules.services.quality_service import QualityService
from modules.services.rework_service import ReworkService
from modules.services.work_report_writer import WorkReportWriter


def _context(db, suffix="event"):
    process_id = ensure_process(db, "绩效质量事件工序-" + suffix)
    order_id = create_order(db, [process_id], quantity=20)
    user_id = ensure_user(
        db,
        "performance-quality-" + suffix,
        WORKER_HASH,
        "绩效质量员工-" + suffix,
        "worker",
        "PERF-QUALITY-" + suffix.upper(),
        "员工组",
    )
    return order_id, process_id, user_id


def _source_event_id(db, source_type, source_id):
    row = db.execute(
        "SELECT quality_event_id FROM performance_quality_event_sources "
        "WHERE source_type=? AND source_id=?",
        (source_type, source_id),
    ).fetchone()
    return row["quality_event_id"] if row else None


def test_stable_source_is_idempotent_and_explicit_relation_reuses_event(client):
    with client.application.app_context():
        db = get_db()
        order_id, process_id, user_id = _context(db, "idempotent")
        first = PerformanceQualityEventService.record_event(
            event_type="scrap",
            source_type="scrap_record",
            source_id=101,
            quantity=2,
            order_id=order_id,
            process_id=process_id,
            user_id=user_id,
            snapshot={"reason": "尺寸超差"},
        )
        retried = PerformanceQualityEventService.record_event(
            event_type="scrap",
            source_type="scrap_record",
            source_id=101,
            quantity=999,
            order_id=order_id,
            process_id=process_id,
            user_id=user_id,
            snapshot={"reason": "重试不得改写"},
        )
        related = PerformanceQualityEventService.record_event(
            event_type="rework",
            source_type="rework_record",
            source_id=202,
            quantity=2,
            order_id=order_id,
            process_id=process_id,
            user_id=user_id,
            related_sources=[("scrap_record", 101)],
        )

        assert first["id"] == retried["id"] == related["id"]
        persisted = db.execute(
            "SELECT event_type,quantity,snapshot_json FROM performance_quality_events "
            "WHERE id=?",
            (first["id"],),
        ).fetchone()
        assert persisted["event_type"] == "scrap"
        assert persisted["quantity"] == 2
        assert json.loads(persisted["snapshot_json"])["reason"] == "尺寸超差"
        assert db.execute(
            "SELECT COUNT(*) FROM performance_quality_event_sources "
            "WHERE quality_event_id=?",
            (first["id"],),
        ).fetchone()[0] == 2
        listed = PerformanceFactRepository.list_quality_events(
            "2000-01-01 00:00:00", "2100-01-01 00:00:00", db=db
        )
        listed_event = next(item for item in listed if item["id"] == first["id"])
        assert listed_event["quantity"] == 2
        assert {
            (source["source_type"], source["source_id"])
            for source in listed_event["sources"]
        } == {("scrap_record", 101), ("rework_record", 202)}


def test_similarity_never_auto_merges_and_historical_candidate_becomes_exception(client):
    with client.application.app_context():
        db = get_db()
        order_id, process_id, user_id = _context(db, "ambiguous")
        common = {
            "event_type": "rework",
            "quantity": 3,
            "order_id": order_id,
            "process_id": process_id,
            "user_id": user_id,
            "business_at": "2026-07-01 08:00:00",
            "snapshot": {"reason": "同样描述"},
        }
        first = PerformanceQualityEventService.record_event(
            source_type="legacy_rework", source_id=1, **common
        )
        second = PerformanceQualityEventService.record_event(
            source_type="legacy_rework", source_id=2, **common
        )
        exception = PerformanceQualityEventService.record_historical_ambiguity(
            source_type="legacy_rework",
            source_id=3,
            candidates=[
                {"source_type": "legacy_rework", "source_id": 1},
                {"source_type": "legacy_rework", "source_id": 2},
            ],
            snapshot={"order_id": order_id, "quantity": 3},
            user_id=user_id,
        )

        assert first["id"] != second["id"]
        assert exception["exception_type"] == "ambiguous_quality_source"
        assert exception["status"] == "pending"
        assert _source_event_id(db, "legacy_rework", 3) is None


def test_scrap_report_creates_canonical_event_in_same_transaction(client):
    with client.application.app_context():
        db = get_db()
        order_id, process_id, user_id = _context(db, "scrap")
        WorkReportWriter.execute_report_write(
            WorkReportCommand(
                report_type="scrap",
                order_id=order_id,
                process_id=process_id,
                user_id=user_id,
                user_name="报废员工",
                quantity=2,
                remark="报废测试",
            )
        )
        scrap = db.execute(
            "SELECT * FROM scrap_records WHERE order_id=?", (order_id,)
        ).fetchone()
        event_id = _source_event_id(db, "scrap_record", scrap["id"])
        event = db.execute(
            "SELECT * FROM performance_quality_events WHERE id=?", (event_id,)
        ).fetchone()
        assert event["event_type"] == "scrap"
        assert event["quantity"] == 2
        assert event["user_id"] == user_id


def test_quality_event_failure_rolls_back_scrap_report(client, monkeypatch):
    class FailingQualityEventService:
        @staticmethod
        def record_event(**kwargs):
            raise RuntimeError("quality event write failed")

    with client.application.app_context():
        db = get_db()
        order_id, process_id, user_id = _context(db, "rollback")
        monkeypatch.setattr(
            WorkReportWriter, "quality_event_service", FailingQualityEventService
        )
        with pytest.raises(RuntimeError, match="quality event write failed"):
            WorkReportWriter.execute_report_write(
                WorkReportCommand(
                    report_type="scrap",
                    order_id=order_id,
                    process_id=process_id,
                    user_id=user_id,
                    user_name="回滚员工",
                    quantity=2,
                )
            )
        assert db.execute("SELECT COUNT(*) FROM scrap_records").fetchone()[0] == 0
        assert db.execute(
            "SELECT scrapped FROM order_processes WHERE order_id=? AND process_id=?",
            (order_id, process_id),
        ).fetchone()[0] == 0


def test_ncr_derived_rework_reuses_inspection_event(client):
    with client.application.app_context():
        db = get_db()
        order_id, process_id, user_id = _context(db, "ncr")
        inspection_id = db.execute(
            "INSERT INTO quality_inspections ("
            "order_id,process_id,inspection_type,inspector_id,quantity_checked,"
            "quantity_passed,quantity_failed,result,defect_quantity"
            ") VALUES (?,?,'in_process',?,2,0,2,'scrap',2)",
            (order_id, process_id, user_id),
        ).lastrowid
        ncr_id = db.execute(
            "INSERT INTO quality_nonconformances ("
            "ncr_no,inspection_id,order_id,process_id,defect_quantity,"
            "responsible_user_id,status"
            ") VALUES (?,?,?,?,?,?,'open')",
            ("NCR-PERF-QUALITY", inspection_id, order_id, process_id, 2, user_id),
        ).lastrowid
        db.commit()
        original = PerformanceQualityEventService.record_event(
            event_type="inspection_failed",
            source_type="quality_inspection",
            source_id=inspection_id,
            quantity=2,
            order_id=order_id,
            process_id=process_id,
            user_id=user_id,
            related_sources=[("quality_ncr", ncr_id)],
        )
        rework_id = ReworkService.create_rework(
            order_id,
            process_id,
            user_id,
            2,
            "NCR返工",
            source_ncr_id=ncr_id,
        )

        assert _source_event_id(db, "rework_record", rework_id) == original["id"]
        assert db.execute(
            "SELECT COUNT(DISTINCT quality_event_id) "
            "FROM performance_quality_event_sources WHERE source_type IN ("
            "'quality_inspection','quality_ncr','rework_record')"
        ).fetchone()[0] == 1


def test_failed_legacy_inspection_uses_target_worker_not_inspector(client):
    with client.application.app_context():
        db = get_db()
        order_id, process_id, worker_id = _context(db, "inspection-worker")
        inspector_id = ensure_user(
            db,
            "performance-quality-inspector",
            WORKER_HASH,
            "绩效质检员",
            "qc_inspector",
            "PERF-QUALITY-INSPECTOR",
        )
        work_record_id = db.execute(
            "INSERT INTO work_records (order_id,process_id,user_id,type,quantity,status) "
            "VALUES (?,?,?,'normal',2,'approved')",
            (order_id, process_id, worker_id),
        ).lastrowid
        db.commit()
        inspection_id = QualityService.create_inspection(
            {
                "order_id": order_id,
                "process_id": process_id,
                "inspection_type": "in_process",
                "quantity_checked": 2,
                "quantity_passed": 0,
                "quantity_failed": 2,
                "target_work_record_id": work_record_id,
            },
            inspector_id,
        )
        event = db.execute(
            "SELECT event.* FROM performance_quality_events event "
            "JOIN performance_quality_event_sources source "
            "ON source.quality_event_id=event.id "
            "WHERE source.source_type='quality_inspection' AND source.source_id=?",
            (inspection_id,),
        ).fetchone()
        assert event["user_id"] == worker_id
        assert event["user_id"] != inspector_id
