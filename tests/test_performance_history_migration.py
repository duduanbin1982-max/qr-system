import json

import pytest

from factories import ensure_process_version
from modules.db import get_db
from modules.services.performance_history_migration_service import (
    PerformanceHistoryMigrationService,
)
from modules.services.performance_quality_event_service import (
    PerformanceQualityEventService,
)
from modules.services.performance_scoring_policy import PerformanceScoringPolicy


MONTH = "2026-06"
PERIOD_START = "2026-06-01 07:00:00"
PERIOD_END = "2026-07-01 07:00:00"


def _canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _actor(db):
    actor_id = db.execute(
        "INSERT INTO users (username,password,name,role,employee_no,status) "
        "VALUES ('performance-history-preparer','hash','历史绩效制单人','admin',"
        "'PERF-HISTORY-PREP','active')"
    ).lastrowid
    return actor_id


def _rule(db, actor_id):
    defaults = PerformanceScoringPolicy.rules()
    return db.execute(
        "INSERT INTO performance_rule_versions ("
        "version_code,name,weights_json,warning_levels_json,scoring_parameters_json,"
        "status,effective_from_month,published_by,published_at"
        ") VALUES ('history-rule-v1','历史绩效规则',?,?,?,'published','2026-01',?,"
        "'2026-05-01 08:00:00')",
        (
            _canonical(defaults["weights"]),
            _canonical(defaults["warning_levels"]),
            _canonical(
                {
                    "work_days_target": defaults["work_days_target"],
                    "handoff": defaults["handoff"],
                    "improvement": defaults["improvement"],
                }
            ),
            actor_id,
        ),
    ).lastrowid


def _position(db, name, actor_id, *, with_target):
    position_id = db.execute(
        "INSERT INTO positions (name,status) VALUES (?,'active')", (name,)
    ).lastrowid
    if with_target:
        db.execute(
            "INSERT INTO performance_position_target_versions ("
            "position_id,position_name_snapshot,target_output_qty,"
            "minimum_effective_work_days,effective_from_month,status,approved_by,"
            "approved_by_name,approved_at"
            ") VALUES (?,?,100,1,'2026-01','approved',?,'历史绩效批准人',"
            "'2026-05-01 08:00:00')",
            (position_id, name, actor_id),
        )
    return position_id


def _worker(db, suffix, position_id, department_id):
    return db.execute(
        "INSERT INTO users (username,password,name,role,employee_no,status,"
        "position_id,department_id) VALUES (?,?,?,?,?,'active',?,?)",
        (
            "performance-history-" + suffix,
            "hash",
            "历史绩效员工-" + suffix,
            "worker",
            "PERF-HISTORY-" + suffix.upper(),
            position_id,
            department_id,
        ),
    ).lastrowid


def _assignment(db, user_id, suffix, position_id, position_name, department_id):
    db.execute(
        "INSERT INTO performance_assignment_history ("
        "user_id,employee_name_snapshot,employee_no_snapshot,position_id,"
        "position_name_snapshot,department_id,department_name_snapshot,valid_from,"
        "valid_to,source_type,source_key"
        ") VALUES (?,?,?,?,?,?,?,'2026-01-01 07:00:00','','manual_confirmation',?)",
        (
            user_id,
            "历史绩效员工-" + suffix,
            "PERF-HISTORY-" + suffix.upper(),
            position_id,
            position_name,
            department_id,
            "历史绩效部门",
            "history-confirmation:" + suffix,
        ),
    )


def _work(db, user_id, process_id, order_id, business_at, quantity=10):
    return db.execute(
        "INSERT INTO work_records (order_id,process_id,user_id,type,status,quantity,"
        "actual_completed_at,created_at) VALUES (?,?,?,'normal','approved',?,?,?)",
        (order_id, process_id, user_id, quantity, business_at, business_at),
    ).lastrowid


def _legacy_score(
    db,
    batch_id,
    user_id,
    legacy_score_id,
    *,
    position_id,
    position_name,
    unavailable=False,
    total_score=80,
):
    return db.execute(
        "INSERT INTO performance_score_revisions ("
        "batch_id,user_id,revision,employee_name_snapshot,employee_no_snapshot,"
        "role_type_snapshot,position_id_snapshot,position_name_snapshot,"
        "eligibility_status,output_qty,report_count,work_days,total_score,"
        "manual_score,score_details_json,input_digest,calculated_at,created_by_name,"
        "legacy_score_id,legacy_score_json,prior_revisions_unavailable"
        ") VALUES (?,?,1,?,?, 'worker',?,?,'eligible',100,1,1,?,10,'{}',?,"
        "'2026-07-01 08:00:00','legacy import',?,?,?)",
        (
            batch_id,
            user_id,
            "历史绩效员工-" + str(legacy_score_id),
            "PERF-HISTORY-" + str(legacy_score_id),
            position_id,
            position_name,
            total_score,
            "legacy-score:" + str(legacy_score_id),
            legacy_score_id,
            _canonical(
                {
                    "id": legacy_score_id,
                    "user_id": user_id,
                    "year_month": MONTH,
                    "total_score": total_score,
                }
            ),
            int(unavailable),
        ),
    ).lastrowid


def _seed_history(db):
    actor_id = _actor(db)
    _rule(db, actor_id)
    department_id = db.execute(
        "INSERT INTO departments (name,status) VALUES ('历史绩效部门','active')"
    ).lastrowid
    target_position = _position(
        db, "历史有目标岗位", actor_id, with_target=True
    )
    no_target_position = _position(
        db, "历史无目标岗位", actor_id, with_target=False
    )
    confirmed_user = _worker(db, "confirmed", target_position, department_id)
    missing_user = _worker(db, "missing", target_position, department_id)
    no_target_user = _worker(db, "no-target", no_target_position, department_id)
    _assignment(
        db,
        confirmed_user,
        "confirmed",
        target_position,
        "历史有目标岗位",
        department_id,
    )
    _assignment(
        db,
        no_target_user,
        "no-target",
        no_target_position,
        "历史无目标岗位",
        department_id,
    )

    process_id = db.execute(
        "INSERT INTO processes (name,status) VALUES ('历史绩效工序','active')"
    ).lastrowid
    ensure_process_version(db, process_id)
    order_id = db.execute(
        "INSERT INTO orders (order_no,product_name,product_code,quantity,status) "
        "VALUES ('PERF-HISTORY-ORDER','历史绩效产品','PERF-HISTORY-PRODUCT',"
        "100,'producing')"
    ).lastrowid
    cross_work_id = _work(
        db, confirmed_user, process_id, order_id, "2026-07-01 06:30:00", 20
    )
    _work(db, missing_user, process_id, order_id, "2026-06-15 08:00:00", 10)
    _work(db, no_target_user, process_id, order_id, "2026-06-16 08:00:00", 10)

    cross_quality_id = db.execute(
        "INSERT INTO process_quality_evaluations ("
        "order_id,target_process_id,evaluator_process_id,target_work_record_id,"
        "target_user_id,evaluator_user_id,quantity,processing_quality,"
        "dimensional_accuracy,appearance_quality,process_continuity,"
        "cleanliness_protection,total_score,grade,status,created_at,updated_at"
        ") VALUES (?,?,?,?,?,?,1,3,3,3,3,3,60,'C','confirmed',"
        "'2026-07-01 06:45:00','2026-07-01 06:45:00')",
        (
            order_id,
            process_id,
            process_id,
            cross_work_id,
            confirmed_user,
            actor_id,
        ),
    ).lastrowid
    ambiguity = PerformanceQualityEventService.record_historical_ambiguity(
        source_type="historical_quality",
        source_id=902,
        candidates=[
            {"source_type": "historical_quality", "source_id": 901},
            {"source_type": "historical_quality", "source_id": 903},
        ],
        snapshot={"business_at": "2026-06-20 08:00:00"},
        db=db,
    )

    legacy_batch_id = db.execute(
        "INSERT INTO performance_batches ("
        "production_month,version,period_start,period_end,source_cutoff_at,"
        "input_digest,idempotency_key,status,prepared_by_name,revision_reason,"
        "legacy_imported"
        ") VALUES (?,1,?,?,?,'legacy-history-input','legacy:history:2026-06',"
        "'draft','legacy import','Legacy V1',1)",
        (MONTH, PERIOD_START, PERIOD_END, PERIOD_END),
    ).lastrowid
    _legacy_score(
        db,
        legacy_batch_id,
        confirmed_user,
        1001,
        position_id=target_position,
        position_name="历史有目标岗位",
        unavailable=True,
        total_score=95,
    )
    _legacy_score(
        db,
        legacy_batch_id,
        missing_user,
        1002,
        position_id=None,
        position_name="",
        total_score=75,
    )
    _legacy_score(
        db,
        legacy_batch_id,
        no_target_user,
        1003,
        position_id=no_target_position,
        position_name="历史无目标岗位",
        total_score=70,
    )
    legacy_records = [
        {"legacy_score_id": 1001},
        {"legacy_score_id": 1002},
        {"legacy_score_id": 1003},
    ]
    db.execute(
        "INSERT INTO performance_migration_manifests ("
        "production_month,legacy_batch_id,source_score_count,overwritten_score_count,"
        "missing_position_count,records_json,manifest_sha256"
        ") VALUES (?,?,3,1,1,?,?)",
        (
            MONTH,
            legacy_batch_id,
            _canonical(legacy_records),
            "legacy-manifest-history",
        ),
    )
    db.execute(
        "UPDATE performance_batches SET status='supervisor_review' WHERE id=?",
        (legacy_batch_id,),
    )
    db.execute(
        "UPDATE performance_batches SET status='approval_pending' WHERE id=?",
        (legacy_batch_id,),
    )
    db.execute(
        "UPDATE performance_batches SET status='approved',approved_by=?,"
        "approved_by_name='legacy import',approved_at='2026-07-01 08:00:00' "
        "WHERE id=?",
        (actor_id, legacy_batch_id),
    )
    db.commit()
    return {
        "actor_id": actor_id,
        "legacy_batch_id": legacy_batch_id,
        "confirmed_user": confirmed_user,
        "missing_user": missing_user,
        "no_target_user": no_target_user,
        "process_id": process_id,
        "order_id": order_id,
        "cross_work_id": cross_work_id,
        "cross_quality_id": cross_quality_id,
        "ambiguity_id": ambiguity["id"],
    }


def _expected_counts():
    return {
        "overwritten_score_count": 1,
        "missing_position_count": 1,
        "cross_month_work_count": 1,
        "cross_month_quality_count": 1,
    }


def _manifest_projection(plan):
    month = plan["months"][0]
    return {
        "manifest_sha256": plan["manifest_sha256"],
        "month_manifest_sha256": month["manifest_sha256"],
        "record_count": len(month["records"]),
        "stable_keys": [record["stable_key"] for record in month["records"]],
        "classifications": {
            record["stable_key"]: record["classification"]
            for record in month["records"]
        },
        "cross_month_work_user_ids": month["cross_month_work_user_ids"],
        "cross_month_quality_user_ids": month["cross_month_quality_user_ids"],
        "multi_source_quality_user_ids": month["multi_source_quality_user_ids"],
        "missing_target_user_ids": month["missing_target_user_ids"],
    }


def _payroll_counts(db):
    return {
        table: db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
        for table in (
            "payroll_batches",
            "payroll_employee_lines",
            "payroll_adjustments",
            "payroll_detail_lines",
            "payroll_events",
        )
    }


def test_preflight_reports_stable_sorted_manifest_and_all_audit_classes(client):
    with client.application.app_context():
        db = get_db()
        seeded = _seed_history(db)

        first = PerformanceHistoryMigrationService.analyze(db, MONTH, MONTH)
        second = PerformanceHistoryMigrationService.analyze(db, MONTH, MONTH)

        assert first["manifest_sha256"] == second["manifest_sha256"]
        assert first["totals"] == {
            "legacy_score_count": 3,
            "overwritten_score_count": 1,
            "missing_position_count": 1,
            "cross_month_work_count": 1,
            "cross_month_quality_count": 1,
            "quality_ambiguity_count": 1,
            "missing_target_count": 1,
        }
        month = first["months"][0]
        assert month["legacy_batch_id"] == seeded["legacy_batch_id"]
        assert month["legacy_manifest_sha256"] == "legacy-manifest-history"
        assert month["cross_month_work_ids"] == [seeded["cross_work_id"]]
        assert month["cross_month_quality_ids"] == [seeded["cross_quality_id"]]
        assert month["quality_ambiguity_ids"] == [seeded["ambiguity_id"]]
        stable_keys = [record["stable_key"] for record in month["records"]]
        assert stable_keys == sorted(stable_keys)
        assert len(month["manifest_sha256"]) == 64


def test_history_manifest_matches_exact_pre_refactor_characterization(client):
    with client.application.app_context():
        db = get_db()
        seeded = _seed_history(db)
        actual = _manifest_projection(
            PerformanceHistoryMigrationService.analyze(db, MONTH, MONTH)
        )

        assert actual == {
            "manifest_sha256": "5978dbcd4cecfd76272d60da9ef0557a5fff8503720de8a67e20906119a5c368",
            "month_manifest_sha256": "308b9601d94c8685aa1b873d162b958b486bd3f9a42cc00e06302aff2c6ab9c5",
            "record_count": 13,
            "stable_keys": [
                "assignment_history:00000000000000000006",
                "assignment_history:00000000000000000007",
                "legacy_manifest:00000000000000000001",
                "legacy_score:00000000000000001001",
                "legacy_score:00000000000000001002",
                "legacy_score:00000000000000001003",
                "position_target:00000000000000000001",
                "process_quality_evaluation:00000000000000000001",
                "quality_ambiguity_historical_quality:00000000000000000902",
                "rule_version:00000000000000000001",
                "work_record:00000000000000000001",
                "work_record:00000000000000000002",
                "work_record:00000000000000000003",
            ],
            "classifications": {
                "assignment_history:00000000000000000006": "historical_assignment_snapshot",
                "assignment_history:00000000000000000007": "historical_assignment_snapshot",
                "legacy_manifest:00000000000000000001": "legacy_v1_manifest",
                "legacy_score:00000000000000001001": "prior_revisions_unavailable",
                "legacy_score:00000000000000001002": "missing_position_snapshot",
                "legacy_score:00000000000000001003": "missing_position_target",
                "position_target:00000000000000000001": "approved_position_target",
                "process_quality_evaluation:00000000000000000001": "production_month_boundary",
                "quality_ambiguity_historical_quality:00000000000000000902": "quality_source_confirmation_required",
                "rule_version:00000000000000000001": "published_rule",
                "work_record:00000000000000000001": "production_month_boundary",
                "work_record:00000000000000000002": "production_month_work",
                "work_record:00000000000000000003": "production_month_work",
            },
            "cross_month_work_user_ids": [seeded["confirmed_user"]],
            "cross_month_quality_user_ids": [seeded["confirmed_user"]],
            "multi_source_quality_user_ids": [],
            "missing_target_user_ids": [seeded["no_target_user"]],
        }


def test_apply_generates_only_reviewable_v2_and_is_idempotent(client):
    with client.application.app_context():
        db = get_db()
        seeded = _seed_history(db)
        payroll_before = _payroll_counts(db)

        applied = PerformanceHistoryMigrationService.apply(
            db,
            MONTH,
            MONTH,
            seeded["actor_id"],
            _expected_counts(),
        )
        month = applied["months"][0]
        batch = month["batch"]
        assert batch["version"] == 2
        assert batch["status"] == "draft"
        assert batch["supersedes_batch_id"] == seeded["legacy_batch_id"]
        assert batch["legacy_imported"] == 0
        assert month["idempotent_replay"] is False
        assert month["quality_backfill"] == {
            "mapped_quality_evaluation_count": 1,
            "mapped_scrap_count": 0,
            "mapped_rework_count": 0,
            "mapped_quality_inspection_count": 0,
            "created_quality_ambiguity_count": 0,
        }
        mapped_quality = db.execute(
            "SELECT quality_event_id FROM performance_quality_event_sources "
            "WHERE source_type='process_quality_evaluation' AND source_id=?",
            (seeded["cross_quality_id"],),
        ).fetchone()
        assert mapped_quality is not None
        assert month["comparison"]["rows"]
        assert month["comparison"]["reason_counts"]
        event = db.execute(
            "SELECT * FROM performance_batch_events WHERE id=?", (month["event_id"],)
        ).fetchone()
        payload = json.loads(event["payload_json"])
        assert payload["migration_manifest_sha256"] == applied["plan"][
            "months"
        ][0]["manifest_sha256"]
        assert payload["batch_input_digest"] == batch["input_digest"]
        assert payload["records"] == applied["plan"]["months"][0]["records"]

        missing_score = db.execute(
            "SELECT * FROM performance_score_revisions WHERE batch_id=? AND user_id=?",
            (batch["id"], seeded["missing_user"]),
        ).fetchone()
        assert missing_score["eligibility_status"] == "insufficient_data"
        assert missing_score["position_id_snapshot"] is None
        no_target_score = db.execute(
            "SELECT * FROM performance_score_revisions WHERE batch_id=? AND user_id=?",
            (batch["id"], seeded["no_target_user"]),
        ).fetchone()
        assert no_target_score["eligibility_status"] == "insufficient_data"
        assert _payroll_counts(db) == payroll_before

        replayed = PerformanceHistoryMigrationService.apply(
            db,
            MONTH,
            MONTH,
            seeded["actor_id"],
            _expected_counts(),
        )
        replay_month = replayed["months"][0]
        assert replay_month["batch"]["id"] == batch["id"]
        assert replay_month["idempotent_replay"] is True
        assert db.execute(
            "SELECT COUNT(*) FROM performance_batches WHERE production_month=?",
            (MONTH,),
        ).fetchone()[0] == 2
        assert db.execute(
            "SELECT COUNT(*) FROM performance_batch_events WHERE "
            "event_type='historical_revision_generated'"
        ).fetchone()[0] == 1


def test_apply_rejects_count_mismatch_and_stale_manifest_without_partial_writes(client):
    with client.application.app_context():
        db = get_db()
        seeded = _seed_history(db)
        wrong = dict(_expected_counts())
        wrong["overwritten_score_count"] = 64
        with pytest.raises(RuntimeError, match="历史绩效审计基线不一致"):
            PerformanceHistoryMigrationService.apply(
                db, MONTH, MONTH, seeded["actor_id"], wrong
            )
        assert db.execute(
            "SELECT COUNT(*) FROM performance_batches WHERE production_month=?",
            (MONTH,),
        ).fetchone()[0] == 1

        first = PerformanceHistoryMigrationService.apply(
            db,
            MONTH,
            MONTH,
            seeded["actor_id"],
            _expected_counts(),
        )
        batch_id = first["months"][0]["batch"]["id"]
        _work(
            db,
            seeded["confirmed_user"],
            seeded["process_id"],
            seeded["order_id"],
            "2026-06-25 08:00:00",
            1,
        )
        db.commit()

        with pytest.raises(RuntimeError, match="迁移清单与当前来源不一致"):
            PerformanceHistoryMigrationService.apply(
                db,
                MONTH,
                MONTH,
                seeded["actor_id"],
                _expected_counts(),
            )
        assert db.execute(
            "SELECT COUNT(*) FROM performance_batches WHERE production_month=?",
            (MONTH,),
        ).fetchone()[0] == 2
        assert db.execute(
            "SELECT id FROM performance_batches WHERE production_month=? AND version=2",
            (MONTH,),
        ).fetchone()[0] == batch_id


def test_unattributed_historical_quality_never_auto_maps_similar_candidates(client):
    with client.application.app_context():
        db = get_db()
        seeded = _seed_history(db)
        ambiguous_evaluation_id = db.execute(
            "INSERT INTO process_quality_evaluations ("
            "order_id,target_process_id,evaluator_process_id,target_user_id,"
            "evaluator_user_id,quantity,processing_quality,dimensional_accuracy,"
            "appearance_quality,process_continuity,cleanliness_protection,total_score,"
            "grade,status,created_at,updated_at"
            ") VALUES (?,?,?,NULL,?,1,3,3,3,3,3,60,'C','confirmed',"
            "'2026-06-20 09:00:00','2026-06-20 09:00:00')",
            (
                seeded["order_id"],
                seeded["process_id"],
                seeded["process_id"],
                seeded["actor_id"],
            ),
        ).lastrowid
        db.commit()

        preflight = PerformanceHistoryMigrationService.analyze(db, MONTH, MONTH)
        assert preflight["totals"]["quality_ambiguity_count"] == 2
        manifest_sha256 = preflight["manifest_sha256"]
        applied = PerformanceHistoryMigrationService.apply(
            db,
            MONTH,
            MONTH,
            seeded["actor_id"],
            _expected_counts(),
        )
        assert applied["months"][0]["quality_backfill"] == {
            "mapped_quality_evaluation_count": 1,
            "mapped_scrap_count": 0,
            "mapped_rework_count": 0,
            "mapped_quality_inspection_count": 0,
            "created_quality_ambiguity_count": 1,
        }
        assert db.execute(
            "SELECT 1 FROM performance_quality_event_sources "
            "WHERE source_type='process_quality_evaluation' AND source_id=?",
            (ambiguous_evaluation_id,),
        ).fetchone() is None
        exception = db.execute(
            "SELECT * FROM performance_data_exceptions WHERE batch_id IS NULL "
            "AND source_type='process_quality_evaluation' AND source_id=?",
            (ambiguous_evaluation_id,),
        ).fetchone()
        assert exception["status"] == "pending"
        assert len(json.loads(exception["snapshot_json"])["candidates"]) == 3
        after = PerformanceHistoryMigrationService.analyze(db, MONTH, MONTH)
        assert after["manifest_sha256"] == manifest_sha256
        assert after["totals"]["quality_ambiguity_count"] == 2


def test_historical_scrap_rework_and_inspection_sources_are_controlled(client):
    with client.application.app_context():
        db = get_db()
        seeded = _seed_history(db)
        scrap_id = db.execute(
            "INSERT INTO scrap_records (order_id,process_id,user_id,quantity,reason,"
            "created_at) VALUES (?,?,?,?,?,'2026-06-21 08:00:00')",
            (
                seeded["order_id"],
                seeded["process_id"],
                seeded["confirmed_user"],
                2,
                "历史报废",
            ),
        ).lastrowid
        rework_id = db.execute(
            "INSERT INTO rework_records (order_id,process_id,user_id,quantity,reason,"
            "created_at) VALUES (?,?,?,?,?,'2026-06-22 08:00:00')",
            (
                seeded["order_id"],
                seeded["process_id"],
                seeded["confirmed_user"],
                2,
                "历史返工",
            ),
        ).lastrowid
        unique_order_id = db.execute(
            "INSERT INTO orders (order_no,product_name,product_code,quantity,status) "
            "VALUES ('PERF-HISTORY-UNIQUE','唯一员工产品','PERF-HISTORY-UNIQUE',"
            "100,'producing')"
        ).lastrowid
        _work(
            db,
            seeded["confirmed_user"],
            seeded["process_id"],
            unique_order_id,
            "2026-06-23 08:00:00",
            5,
        )
        mapped_inspection_id = db.execute(
            "INSERT INTO quality_inspections ("
            "order_id,process_id,quantity_checked,quantity_passed,quantity_failed,"
            "result,defect_quantity,inspected_at,created_at"
            ") VALUES (?,?,5,4,1,'fail',1,'2026-06-23 09:00:00',"
            "'2026-06-23 09:00:00')",
            (unique_order_id, seeded["process_id"]),
        ).lastrowid
        ambiguous_inspection_id = db.execute(
            "INSERT INTO quality_inspections ("
            "order_id,process_id,quantity_checked,quantity_passed,quantity_failed,"
            "result,defect_quantity,inspected_at,created_at"
            ") VALUES (?,?,5,4,1,'fail',1,'2026-06-24 09:00:00',"
            "'2026-06-24 09:00:00')",
            (seeded["order_id"], seeded["process_id"]),
        ).lastrowid
        db.commit()

        before = PerformanceHistoryMigrationService.analyze(db, MONTH, MONTH)
        applied = PerformanceHistoryMigrationService.apply(
            db,
            MONTH,
            MONTH,
            seeded["actor_id"],
            _expected_counts(),
        )
        assert applied["months"][0]["quality_backfill"] == {
            "mapped_quality_evaluation_count": 1,
            "mapped_scrap_count": 1,
            "mapped_rework_count": 1,
            "mapped_quality_inspection_count": 1,
            "created_quality_ambiguity_count": 1,
        }
        for source_type, source_id in (
            ("scrap_record", scrap_id),
            ("rework_record", rework_id),
            ("quality_inspection", mapped_inspection_id),
        ):
            assert db.execute(
                "SELECT 1 FROM performance_quality_event_sources "
                "WHERE source_type=? AND source_id=?",
                (source_type, source_id),
            ).fetchone() is not None
        assert db.execute(
            "SELECT 1 FROM performance_quality_event_sources "
            "WHERE source_type='quality_inspection' AND source_id=?",
            (ambiguous_inspection_id,),
        ).fetchone() is None
        assert db.execute(
            "SELECT 1 FROM performance_data_exceptions WHERE batch_id IS NULL "
            "AND source_type='quality_inspection' AND source_id=?",
            (ambiguous_inspection_id,),
        ).fetchone() is not None
        after = PerformanceHistoryMigrationService.analyze(db, MONTH, MONTH)
        assert after["manifest_sha256"] == before["manifest_sha256"]


def test_known_production_baseline_contract_accepts_64_30_5_11():
    plan = {
        "totals": {
            "overwritten_score_count": 64,
            "missing_position_count": 30,
            "cross_month_work_count": 5,
            "cross_month_quality_count": 11,
        }
    }
    expected = {
        "overwritten_score_count": 64,
        "missing_position_count": 30,
        "cross_month_work_count": 5,
        "cross_month_quality_count": 11,
    }
    PerformanceHistoryMigrationService.validate_counts(plan, expected)
