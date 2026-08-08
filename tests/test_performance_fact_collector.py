import hashlib
import json

import pytest

from factories import WORKER_HASH, ensure_process, ensure_user
from modules.db import get_db
from modules.repositories.performance_fact_repository import PerformanceFactRepository
from modules.services.performance_fact_collector import PerformanceFactCollector


PERIOD_START = "2026-08-01 07:00:00"
PERIOD_END = "2026-09-01 07:00:00"
CUTOFF = "2026-09-02 08:00:00"


def _batch(db, suffix="main"):
    return db.execute(
        "INSERT INTO performance_batches ("
        "production_month,version,period_start,period_end,source_cutoff_at,"
        "idempotency_key) VALUES ('2026-08',?,?,?,?,?)",
        (
            int(db.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM performance_batches "
                "WHERE production_month='2026-08'"
            ).fetchone()[0]),
            PERIOD_START,
            PERIOD_END,
            CUTOFF,
            "test:performance:facts:" + suffix,
        ),
    ).lastrowid


def _worker(db, suffix, *, status="active", assignment=True):
    position_id = db.execute(
        "INSERT INTO positions (name,status) VALUES (?, 'active')",
        ("绩效事实岗位-" + suffix,),
    ).lastrowid
    department_id = db.execute(
        "INSERT INTO departments (name,status) VALUES (?, 'active')",
        ("绩效事实部门-" + suffix,),
    ).lastrowid
    user_id = ensure_user(
        db,
        "performance-fact-" + suffix,
        WORKER_HASH,
        "绩效事实员工-" + suffix,
        "worker",
        "PERF-FACT-" + suffix.upper(),
    )
    db.execute(
        "UPDATE users SET position_id=?,department_id=?,status=? WHERE id=?",
        (position_id, department_id, status, user_id),
    )
    if assignment:
        db.execute(
            "INSERT INTO performance_assignment_history ("
            "user_id,employee_name_snapshot,employee_no_snapshot,position_id,"
            "position_name_snapshot,department_id,department_name_snapshot,"
            "valid_from,valid_to,source_type,source_key) "
            "VALUES (?,?,?,?,?,?,?,'2026-07-01 07:00:00','',?,?)",
            (
                user_id,
                "绩效事实员工-" + suffix,
                "PERF-FACT-" + suffix.upper(),
                position_id,
                "绩效事实岗位-" + suffix,
                department_id,
                "绩效事实部门-" + suffix,
                "test",
                "test:performance-fact:" + suffix,
            ),
        )
    return user_id, position_id, department_id


def _order(db, suffix):
    product_id = db.execute(
        "INSERT INTO products (product_name,product_code) VALUES (?,?)",
        ("绩效事实产品-" + suffix, "PERF-PRODUCT-" + suffix.upper()),
    ).lastrowid
    order_id = db.execute(
        "INSERT INTO orders (order_no,product_id,product_name,product_code,"
        "quantity,status) VALUES (?,?,?,?,20,'producing')",
        (
            "PERF-ORDER-" + suffix.upper(),
            product_id,
            "绩效事实产品快照-" + suffix,
            "PERF-PRODUCT-" + suffix.upper(),
        ),
    ).lastrowid
    return order_id, product_id


def _quality_event(
    db,
    *,
    event_type,
    source_type,
    source_id,
    business_at,
    user_id,
    order_id,
    process_id,
    quantity=1,
    snapshot=None,
    related_sources=(),
):
    snapshot_json = json.dumps(snapshot or {}, ensure_ascii=False, sort_keys=True)
    event_id = db.execute(
        "INSERT INTO performance_quality_events ("
        "event_type,quantity,order_id,process_id,user_id,business_at,snapshot_json,event_digest,created_at"
        ") VALUES (?,?,?,?,?,?,?,?,?)",
        (
            event_type,
            quantity,
            order_id,
            process_id,
            user_id,
            business_at,
            snapshot_json,
            hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest(),
            business_at,
        ),
    ).lastrowid
    for mapped_type, mapped_id in ((source_type, source_id), *related_sources):
        db.execute(
            "INSERT INTO performance_quality_event_sources ("
            "quality_event_id,source_type,source_id) VALUES (?,?,?)",
            (event_id, mapped_type, mapped_id),
        )
    return event_id


def test_collector_uses_half_open_0700_boundaries_for_work_and_quality(client):
    with client.application.app_context():
        db = get_db()
        user_id, _, _ = _worker(db, "boundary")
        order_id, _ = _order(db, "boundary")
        process_id = ensure_process(db, "绩效事实边界工序")
        excluded_work = db.execute(
            "INSERT INTO work_records (order_id,process_id,user_id,type,status,"
            "quantity,actual_completed_at,created_at) VALUES (?,?,?,'normal','approved',1,?,?)",
            (order_id, process_id, user_id, "2026-08-01 06:59:59", "2026-08-01 06:59:59"),
        ).lastrowid
        included_work = db.execute(
            "INSERT INTO work_records (order_id,process_id,user_id,type,status,"
            "quantity,actual_completed_at,created_at) VALUES (?,?,?,'normal','approved',2,?,?)",
            (order_id, process_id, user_id, PERIOD_START, PERIOD_START),
        ).lastrowid
        after_cutoff_work = db.execute(
            "INSERT INTO work_records (order_id,process_id,user_id,type,status,"
            "quantity,actual_completed_at,created_at) VALUES (?,?,?,'normal','approved',9,?,?)",
            (order_id, process_id, user_id, "2026-08-20 08:00:00", "2026-09-03 08:00:00"),
        ).lastrowid
        late_approved_work = db.execute(
            "INSERT INTO work_records (order_id,process_id,user_id,type,status,"
            "quantity,actual_completed_at,created_at) VALUES (?,?,?,'normal','approved',8,?,?)",
            (order_id, process_id, user_id, "2026-08-21 08:00:00", "2026-08-21 08:00:00"),
        ).lastrowid
        db.execute(
            "INSERT INTO approval_records (work_record_id,status,created_at,processed_at) "
            "VALUES (?,'approved','2026-08-21 08:01:00','2026-09-03 08:00:00')",
            (late_approved_work,),
        )
        excluded_quality = _quality_event(
            db,
            event_type="rework",
            source_type="rework_record",
            source_id=7001,
            business_at="2026-08-01 06:59:59",
            user_id=user_id,
            order_id=order_id,
            process_id=process_id,
        )
        included_quality = _quality_event(
            db,
            event_type="scrap",
            source_type="scrap_record",
            source_id=7002,
            business_at=PERIOD_START,
            user_id=user_id,
            order_id=order_id,
            process_id=process_id,
        )
        batch_id = _batch(db, "boundary")

        result = PerformanceFactCollector.collect(batch_id, db=db)

        sources = {(row["source_type"], row["source_id"]) for row in result["facts"]}
        canonical_ids = {row["canonical_event_id"] for row in result["facts"]}
        assert ("work_record", included_work) in sources
        assert ("work_record", excluded_work) not in sources
        assert ("work_record", after_cutoff_work) not in sources
        assert ("work_record", late_approved_work) not in sources
        assert included_quality in canonical_ids
        assert excluded_quality not in canonical_ids
        assert all(PERIOD_START <= row["business_at"] < PERIOD_END for row in result["facts"])
        included_payload = json.loads(
            next(
                row
                for row in result["facts"]
                if row["source_type"] == "work_record"
                and row["source_id"] == included_work
            )["payload_json"]
        )
        assert included_payload["production_day"] == "2026-08-01"


def test_collector_freezes_all_supported_sources_and_includes_inactive_workers(client):
    with client.application.app_context():
        db = get_db()
        user_id, position_id, department_id = _worker(
            db, "sources", status="inactive"
        )
        assigned_only_id, _, _ = _worker(db, "assigned-only")
        order_id, product_id = _order(db, "sources")
        process_id = ensure_process(db, "绩效事实来源工序")
        work_id = db.execute(
            "INSERT INTO work_records (order_id,process_id,user_id,type,status,"
            "quantity,actual_completed_at,created_at) VALUES (?,?,?,'normal','approved',3,?,?)",
            (order_id, process_id, user_id, "2026-08-10 08:00:00", "2026-08-10 08:01:00"),
        ).lastrowid
        work_time_id = db.execute(
            "INSERT INTO work_time_records (order_id,order_no,product_code,product_name,"
            "process_id,process_name,user_id,user_name,quantity,standard_minutes,start_time,"
            "end_time,effective_minutes,status,review_status,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'completed','approved',?)",
            (
                order_id,
                "PERF-ORDER-SOURCES",
                "PERF-PRODUCT-SOURCES",
                "工时产品快照",
                process_id,
                "工时工序快照",
                user_id,
                "工时员工快照",
                3,
                30,
                "2026-08-10 08:00:00",
                "2026-08-10 08:30:00",
                30,
                "2026-08-10 08:31:00",
            ),
        ).lastrowid
        handoff_event_id = _quality_event(
            db,
            event_type="process_handoff",
            source_type="process_quality_evaluation",
            source_id=7101,
            business_at="2026-08-10 09:00:00",
            user_id=user_id,
            order_id=order_id,
            process_id=process_id,
            snapshot={"status": "confirmed", "rating": 4.5},
            related_sources=(("process_handoff_review", 7102),),
        )
        plan_id = db.execute(
            "INSERT INTO performance_improvement_plans_v2 ("
            "user_id,employee_name_snapshot,employee_no_snapshot,production_month,"
            "status,updated_at,created_at) VALUES (?,?,?,'2026-07','active',?,?)",
            (
                user_id,
                "绩效事实员工-sources",
                "PERF-FACT-SOURCES",
                "2026-08-15 10:00:00",
                "2026-08-01 08:00:00",
            ),
        ).lastrowid
        plan_event_id = db.execute(
            "INSERT INTO performance_plan_events ("
            "plan_id,event_type,from_status,to_status,reassessment_round,payload_json,created_at"
            ") VALUES (?,'activated','draft','active',0,?,'2026-08-15 10:00:00')",
            (plan_id, json.dumps({"reason": "事件时点原因"}, ensure_ascii=False)),
        ).lastrowid
        db.execute(
            "UPDATE performance_improvement_plans_v2 SET reason='事件后可变正文' "
            "WHERE id=?",
            (plan_id,),
        )
        batch_id = _batch(db, "sources")

        result = PerformanceFactCollector.collect(batch_id, db=db)

        facts = {(row["fact_type"], row["source_type"], row["source_id"]): row for row in result["facts"]}
        assert user_id in result["candidate_user_ids"]
        assert assigned_only_id in result["candidate_user_ids"]
        assert any(
            row["fact_type"] == "assignment"
            and row["user_id"] == assigned_only_id
            for row in result["facts"]
        )
        assert ("work", "work_record", work_id) in facts
        assert ("work_time", "work_time_record", work_time_id) in facts
        assert ("quality_event", "performance_quality_event", handoff_event_id) in facts
        assert ("plan_status", "performance_plan_event", plan_event_id) in facts
        for row in facts.values():
            assert row["business_at"]
            assert len(row["source_digest"]) == 64
            assert json.loads(row["payload_json"])
        work = facts[("work", "work_record", work_id)]
        assert work["position_id_snapshot"] == position_id
        assert work["department_id_snapshot"] == department_id
        assert work["product_id"] == product_id
        handoff = json.loads(
            facts[("quality_event", "performance_quality_event", handoff_event_id)]["payload_json"]
        )
        assert handoff["rating"] == 4.5
        assert len(handoff["sources"]) == 2
        plan = json.loads(
            facts[("plan_status", "performance_plan_event", plan_event_id)][
                "payload_json"
            ]
        )
        assert plan["reason"] == "事件时点原因"


def test_quality_sources_are_deduplicated_and_ambiguity_becomes_batch_exception(client):
    with client.application.app_context():
        db = get_db()
        user_id, _, _ = _worker(db, "quality")
        order_id, _ = _order(db, "quality")
        process_id = ensure_process(db, "绩效事实质量工序")
        event_id = _quality_event(
            db,
            event_type="rework",
            source_type="quality_inspection",
            source_id=7201,
            business_at="2026-08-12 08:00:00",
            user_id=user_id,
            order_id=order_id,
            process_id=process_id,
            related_sources=(("quality_ncr", 7202), ("rework_record", 7203)),
        )
        pending_event_id = _quality_event(
            db,
            event_type="process_handoff",
            source_type="process_quality_evaluation",
            source_id=7205,
            business_at="2026-08-12 08:10:00",
            user_id=user_id,
            order_id=order_id,
            process_id=process_id,
            snapshot={"status": "pending_verification", "total_score": 50},
        )
        exception_id = db.execute(
            "INSERT INTO performance_data_exceptions ("
            "batch_id,user_id,exception_type,source_type,source_id,status,snapshot_json,created_at"
            ") VALUES (NULL,?,'ambiguous_quality_source','legacy_quality',7204,'pending',?,?)",
            (
                user_id,
                json.dumps(
                    {
                        "candidates": [
                            {
                                "source_type": "quality_inspection",
                                "source_id": 7201,
                            }
                        ]
                    }
                ),
                "2026-08-12 08:31:00",
            ),
        ).lastrowid
        db.execute(
            "UPDATE performance_data_exceptions SET status='resolved',"
            "resolved_at='2026-09-03 08:00:00' WHERE id=?",
            (exception_id,),
        )
        batch_id = _batch(db, "quality")

        result = PerformanceFactCollector.collect(batch_id, db=db)

        quality_facts = [row for row in result["facts"] if row["fact_type"] == "quality_event"]
        assert [row["canonical_event_id"] for row in quality_facts] == [event_id]
        assert pending_event_id not in {
            row["canonical_event_id"] for row in quality_facts
        }
        assert any(
            row["exception_type"] == "ambiguous_quality_source"
            and row["source_id"] == 7204
            for row in result["exceptions"]
        )


def test_missing_assignment_never_uses_current_position_and_saved_snapshot_is_idempotent(client):
    with client.application.app_context():
        db = get_db()
        user_id, current_position_id, _ = _worker(
            db, "missing-assignment", assignment=False
        )
        order_id, _ = _order(db, "missing-assignment")
        process_id = ensure_process(db, "绩效事实缺任职工序")
        work_id = db.execute(
            "INSERT INTO work_records (order_id,process_id,user_id,type,status,quantity,created_at) "
            "VALUES (?,?,?,'normal','approved',4,'2026-08-18 08:00:00')",
            (order_id, process_id, user_id),
        ).lastrowid
        batch_id = _batch(db, "missing-assignment")

        first = PerformanceFactCollector.collect(batch_id, db=db)
        saved = next(
            row
            for row in first["facts"]
            if row["source_type"] == "work_record" and row["source_id"] == work_id
        )
        assert saved["position_id_snapshot"] is None
        assert saved["position_id_snapshot"] != current_position_id
        assert any(
            row["exception_type"] == "missing_assignment_history"
            for row in first["exceptions"]
        )

        db.execute("UPDATE work_records SET quantity=99 WHERE id=?", (work_id,))
        second = PerformanceFactCollector.collect(batch_id, db=db)
        persisted = PerformanceFactRepository.list_batch_facts(batch_id, db=db)

        assert second["input_json"] == first["input_json"]
        assert second["input_digest"] == first["input_digest"]
        assert next(
            row
            for row in persisted
            if row["source_type"] == "work_record" and row["source_id"] == work_id
        )["quantity"] == 4
        with pytest.raises(Exception, match="immutable"):
            db.execute(
                "UPDATE performance_source_facts SET quantity=100 WHERE batch_id=?",
                (batch_id,),
            )


def test_identical_sources_and_cutoff_produce_identical_cross_batch_digest(client):
    with client.application.app_context():
        db = get_db()
        user_id, _, _ = _worker(db, "repeatable")
        order_id, _ = _order(db, "repeatable")
        process_id = ensure_process(db, "绩效事实摘要工序")
        db.execute(
            "INSERT INTO work_records (order_id,process_id,user_id,type,status,quantity,created_at) "
            "VALUES (?,?,?,'normal','approved',5,'2026-08-20 08:00:00')",
            (order_id, process_id, user_id),
        )
        first_batch = _batch(db, "repeatable-first")
        second_batch = _batch(db, "repeatable-second")

        first = PerformanceFactCollector.collect(first_batch, db=db)
        second = PerformanceFactCollector.collect(second_batch, db=db)

        assert first["input_json"] == second["input_json"]
        assert first["input_digest"] == second["input_digest"]
