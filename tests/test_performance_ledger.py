import json

import pytest

from modules.db import get_db
from modules.domain.errors import ConflictError
from modules.repositories.performance_ledger_repository import (
    PerformanceLedgerRepository,
)
from modules.services.performance_ledger_service import PerformanceLedgerService
from modules.services.performance_scoring_policy import PerformanceScoringPolicy


MONTH = "2026-07"
PERIOD_START = "2026-07-01 07:00:00"
PERIOD_END = "2026-08-01 07:00:00"
CUTOFF = "2026-08-02 08:00:00"


def _canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _actor(db, suffix="main"):
    user_id = db.execute(
        "INSERT INTO users (username,password,name,role,employee_no,status) "
        "VALUES (?,?,?,?,?,'active')",
        (
            "performance-ledger-actor-" + suffix,
            "hash",
            "绩效制单人-" + suffix,
            "worker",
            "PERF-LEDGER-ACTOR-" + suffix.upper(),
        ),
    ).lastrowid
    return {
        "id": user_id,
        "name": "绩效制单人-" + suffix,
        "_permissions": ["performance:prepare"],
    }


def _published_rule(db, actor_id, suffix="main"):
    defaults = PerformanceScoringPolicy.rules()
    return db.execute(
        "INSERT INTO performance_rule_versions ("
        "version_code,name,weights_json,warning_levels_json,scoring_parameters_json,"
        "status,effective_from_month,published_by,published_at"
        ") VALUES (?,?,?,?,?,'published','2026-01',?,?)",
        (
            "performance-ledger-rule-" + suffix,
            "绩效账本规则-" + suffix,
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
            "2026-06-01 08:00:00",
        ),
    ).lastrowid


def _position(db, suffix, *, target=True, actor_id=None):
    position_id = db.execute(
        "INSERT INTO positions (name,status) VALUES (?,'active')",
        ("绩效账本岗位-" + suffix,),
    ).lastrowid
    if target:
        db.execute(
            "INSERT INTO performance_position_target_versions ("
            "position_id,position_name_snapshot,target_output_qty,"
            "minimum_effective_work_days,effective_from_month,status,approved_by,approved_at"
            ") VALUES (?,?,100,1,'2026-01','approved',?,?)",
            (
                position_id,
                "绩效账本岗位-" + suffix,
                actor_id,
                "2026-06-01 08:00:00",
            ),
        )
    return position_id


def _department(db, suffix):
    return db.execute(
        "INSERT INTO departments (name,status) VALUES (?,'active')",
        ("绩效账本部门-" + suffix,),
    ).lastrowid


def _worker(db, suffix, position_id, department_id, *, assignment=True):
    user_id = db.execute(
        "INSERT INTO users (username,password,name,role,employee_no,status,"
        "position_id,department_id) VALUES (?,?,?,?,?,'active',?,?)",
        (
            "performance-ledger-worker-" + suffix,
            "hash",
            "绩效账本员工-" + suffix,
            "worker",
            "PERF-LEDGER-" + suffix.upper(),
            position_id,
            department_id,
        ),
    ).lastrowid
    if assignment:
        db.execute(
            "INSERT INTO performance_assignment_history ("
            "user_id,employee_name_snapshot,employee_no_snapshot,position_id,"
            "position_name_snapshot,department_id,department_name_snapshot,"
            "valid_from,valid_to,source_type,source_key"
            ") VALUES (?,?,?,?,?,?,?,'2026-06-01 07:00:00','','test',?)",
            (
                user_id,
                "绩效账本员工-" + suffix,
                "PERF-LEDGER-" + suffix.upper(),
                position_id,
                "绩效账本岗位-" + suffix.split("-")[0],
                department_id,
                "绩效账本部门-" + suffix,
                "test:performance-ledger:" + suffix,
            ),
        )
    return user_id


def _work(db, user_id, suffix, quantity=100, day=10):
    process_id = db.execute(
        "INSERT INTO processes (name,status) VALUES (?,'active')",
        ("绩效账本工序-" + suffix,),
    ).lastrowid
    order_id = db.execute(
        "INSERT INTO orders (order_no,product_name,product_code,quantity,status) "
        "VALUES (?,?,?,200,'producing')",
        (
            "PERF-LEDGER-ORDER-" + suffix.upper(),
            "绩效账本产品-" + suffix,
            "PERF-LEDGER-PRODUCT-" + suffix.upper(),
        ),
    ).lastrowid
    business_at = f"2026-07-{day:02d} 08:00:00"
    return db.execute(
        "INSERT INTO work_records (order_id,process_id,user_id,type,status,"
        "quantity,actual_completed_at,created_at) "
        "VALUES (?,?,?,'normal','approved',?,?,?)",
        (order_id, process_id, user_id, quantity, business_at, business_at),
    ).lastrowid


def _setup(db, suffix="main", workers=1, *, target=True, position_id=None):
    actor = _actor(db, suffix)
    rule_id = _published_rule(db, actor["id"], suffix)
    position_id = position_id or _position(
        db, suffix, target=target, actor_id=actor["id"]
    )
    department_id = _department(db, suffix)
    user_ids = []
    for index in range(workers):
        worker_suffix = f"{suffix}-{index + 1}"
        user_id = _worker(db, worker_suffix, position_id, department_id)
        _work(db, user_id, worker_suffix, quantity=100 - index * 10, day=10 + index)
        user_ids.append(user_id)
    db.commit()
    return actor, rule_id, position_id, department_id, user_ids


def _create(actor, key, month=MONTH, reason="生成可追溯绩效账本"):
    return PerformanceLedgerService.create_batch(
        {
            "production_month": month,
            "source_cutoff_at": CUTOFF,
            "idempotency_key": key,
            "revision_reason": reason,
        },
        actor,
    )


def test_create_batch_is_idempotent_and_freezes_batch_metadata(client):
    with client.application.app_context():
        db = get_db()
        actor, rule_id, _, _, _ = _setup(db, "idempotent")

        created = _create(actor, "performance-ledger:idempotent")
        replayed = _create(actor, "performance-ledger:idempotent")

        assert replayed["batch_id"] == created["batch_id"]
        assert replayed["idempotent_replay"] is True
        assert db.execute(
            "SELECT COUNT(*) FROM performance_batches WHERE idempotency_key=?",
            ("performance-ledger:idempotent",),
        ).fetchone()[0] == 1
        batch = db.execute(
            "SELECT * FROM performance_batches WHERE id=?", (created["batch_id"],)
        ).fetchone()
        assert batch["production_month"] == MONTH
        assert batch["version"] == 1
        assert batch["period_start"] == PERIOD_START
        assert batch["period_end"] == PERIOD_END
        assert batch["source_cutoff_at"] == CUTOFF
        assert batch["rule_version_id"] == rule_id
        assert batch["prepared_by"] == actor["id"]
        assert batch["prepared_by_name"] == actor["name"]
        assert batch["revision_reason"] == "生成可追溯绩效账本"
        assert len(batch["input_digest"]) == 64
        assert batch["row_version"] == 2
        assert db.execute(
            "SELECT COUNT(*) FROM performance_batch_events WHERE batch_id=?",
            (created["batch_id"],),
        ).fetchone()[0] == 1

        with pytest.raises(ConflictError, match="幂等键"):
            _create(actor, "performance-ledger:idempotent", month="2026-06")


def test_existing_legacy_v1_is_followed_by_v2_and_new_sources_change_digest(client):
    with client.application.app_context():
        db = get_db()
        actor, _, _, _, user_ids = _setup(db, "version")
        db.execute(
            "INSERT INTO performance_batches ("
            "production_month,version,period_start,period_end,source_cutoff_at,"
            "input_digest,idempotency_key,legacy_imported"
            ") VALUES (?,?,?,?,?,'legacy-input',?,1)",
            (
                MONTH,
                1,
                PERIOD_START,
                PERIOD_END,
                PERIOD_END,
                "legacy:performance:2026-07:v1:test",
            ),
        )
        db.commit()

        v2 = _create(actor, "performance-ledger:version:v2", reason="Legacy V1 修订")
        original_digest = v2["input_digest"]
        _work(db, user_ids[0], "version-later", quantity=5, day=20)
        db.commit()
        v3 = _create(actor, "performance-ledger:version:v3", reason="来源变化修订")

        assert v2["version"] == 2
        assert v3["version"] == 3
        assert v3["input_digest"] != original_digest
        assert db.execute(
            "SELECT input_digest FROM performance_batches WHERE id=?",
            (v2["batch_id"],),
        ).fetchone()[0] == original_digest


def test_initial_revisions_bind_targets_and_rank_only_complete_groups(client):
    with client.application.app_context():
        db = get_db()
        actor, rule_id, position_id, _, users = _setup(db, "ranking", workers=3)
        singleton_position = _position(
            db, "ranking-single", target=True, actor_id=actor["id"]
        )
        singleton_department = _department(db, "ranking-single")
        singleton = _worker(
            db,
            "ranking-single",
            singleton_position,
            singleton_department,
        )
        _work(db, singleton, "ranking-single", quantity=95, day=18)
        db.commit()

        result = _create(actor, "performance-ledger:ranking")
        rows = [
            dict(row)
            for row in db.execute(
                "SELECT * FROM performance_score_revisions WHERE batch_id=? "
                "ORDER BY user_id",
                (result["batch_id"],),
            ).fetchall()
        ]

        assert result["eligible_count"] == 4
        assert result["insufficient_data_count"] == 0
        assert len(rows) == 4
        assert {row["revision"] for row in rows} == {1}
        assert {row["rule_version_id"] for row in rows} == {rule_id}
        assert all(row["position_target_version_id"] for row in rows)
        ranked = [row for row in rows if row["position_id_snapshot"] == position_id]
        assert {row["rank_no"] for row in ranked} == {1, 2, 3}
        assert {row["rank_total"] for row in ranked} == {3}
        assert len({row["calculated_at"] for row in ranked}) == 1
        assert len({row["ranking_digest"] for row in ranked}) == 1
        assert len(ranked[0]["ranking_digest"]) == 64
        singleton_row = next(row for row in rows if row["user_id"] == singleton)
        assert singleton_row["rank_no"] is None
        assert singleton_row["rank_total"] is None
        assert {row["user_id"] for row in ranked} == set(users)


def test_missing_position_target_and_ambiguous_source_are_insufficient(client):
    with client.application.app_context():
        db = get_db()
        actor = _actor(db, "exceptions")
        _published_rule(db, actor["id"], "exceptions")
        department_id = _department(db, "exceptions")

        targetless_position = _position(
            db, "exceptions-targetless", target=False, actor_id=actor["id"]
        )
        missing_target_user = _worker(
            db,
            "exceptions-targetless",
            targetless_position,
            department_id,
        )
        _work(db, missing_target_user, "exceptions-targetless", day=11)

        missing_position_user = _worker(
            db,
            "exceptions-positionless",
            None,
            department_id,
        )
        _work(db, missing_position_user, "exceptions-positionless", day=12)

        valid_position = _position(
            db, "exceptions-valid", target=True, actor_id=actor["id"]
        )
        ambiguous_user = _worker(
            db,
            "exceptions-ambiguous",
            valid_position,
            department_id,
        )
        _work(db, ambiguous_user, "exceptions-ambiguous", day=13)
        db.execute(
            "INSERT INTO performance_data_exceptions ("
            "batch_id,user_id,exception_type,source_type,source_id,status,snapshot_json,created_at"
            ") VALUES (NULL,?,'ambiguous_quality_source','legacy_quality',8801,'pending',?,?)",
            (
                ambiguous_user,
                _canonical({"business_at": "2026-07-13 09:00:00"}),
                "2026-07-13 09:00:00",
            ),
        )
        db.commit()

        result = _create(actor, "performance-ledger:exceptions")
        rows = {
            row["user_id"]: dict(row)
            for row in db.execute(
                "SELECT * FROM performance_score_revisions WHERE batch_id=?",
                (result["batch_id"],),
            ).fetchall()
        }
        exception_types = {
            row[0]
            for row in db.execute(
                "SELECT exception_type FROM performance_data_exceptions WHERE batch_id=?",
                (result["batch_id"],),
            ).fetchall()
        }

        assert result["eligible_count"] == 0
        assert result["insufficient_data_count"] == 3
        assert result["missing_target_count"] == 1
        assert rows[missing_target_user]["eligibility_reason_code"] == "missing_position_target"
        assert rows[missing_position_user]["eligibility_reason_code"] == "missing_position"
        assert rows[ambiguous_user]["eligibility_reason_code"] == "unresolved_data_exception"
        for row in rows.values():
            assert row["total_score"] is None
            assert row["warning_level"] is None
            assert row["rank_no"] is None
            assert row["rank_total"] is None
        assert "missing_position_target" in exception_types
        assert "missing_position_snapshot" in exception_types
        assert "ambiguous_quality_source" in exception_types


def test_any_score_insert_failure_rolls_back_the_entire_batch(client, monkeypatch):
    with client.application.app_context():
        db = get_db()
        actor, _, _, _, _ = _setup(db, "rollback", workers=2)
        original = PerformanceLedgerRepository.insert_score_revision
        calls = {"count": 0}

        def fail_second(payload, txn):
            calls["count"] += 1
            if calls["count"] == 2:
                raise RuntimeError("forced score insert failure")
            return original(payload, txn)

        monkeypatch.setattr(
            PerformanceLedgerRepository,
            "insert_score_revision",
            staticmethod(fail_second),
        )

        with pytest.raises(RuntimeError, match="forced score insert failure"):
            _create(actor, "performance-ledger:rollback")

        assert db.execute(
            "SELECT COUNT(*) FROM performance_batches WHERE idempotency_key=?",
            ("performance-ledger:rollback",),
        ).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM performance_source_facts").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM performance_score_revisions").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM performance_batch_events").fetchone()[0] == 0
