import sqlite3

import pytest

from modules import migrations
from modules.db import get_db
from modules.domain.errors import ConflictError
from modules.migration_performance import m056_versioned_performance_ledger
from modules.repositories.performance_assignment_repository import (
    PerformanceAssignmentRepository,
)
from modules.services.performance_assignment_service import (
    PerformanceAssignmentService,
)
from modules.services.user_service import UserService


def _organization(db, suffix):
    position_id = db.execute(
        "INSERT INTO positions (name, status) VALUES (?, 'active')",
        ("任职岗位" + suffix,),
    ).lastrowid
    department_id = db.execute(
        "INSERT INTO departments (name, status) VALUES (?, 'active')",
        ("任职部门" + suffix,),
    ).lastrowid
    db.commit()
    return position_id, department_id


def _set_time(monkeypatch, value):
    monkeypatch.setattr(
        PerformanceAssignmentService,
        "_current_timestamp",
        staticmethod(lambda: value),
    )


def _create_assigned_user(db, monkeypatch, suffix="一", at="2026-01-01 07:00:00"):
    position_id, department_id = _organization(db, suffix)
    _set_time(monkeypatch, at)
    user_id, _ = UserService.create_user(
        {
            "username": "assignment" + suffix,
            "name": "任职员工" + suffix,
            "employee_no": "ASSIGN-" + suffix,
            "password": "Worker123",
            "position_id": position_id,
            "department_id": department_id,
        }
    )
    return user_id, position_id, department_id


def test_position_and_department_change_closes_and_appends_in_same_transaction(
    client, monkeypatch
):
    with client.application.app_context():
        db = get_db()
        user_id, old_position, old_department = _create_assigned_user(db, monkeypatch)
        new_position, new_department = _organization(db, "二")
        _set_time(monkeypatch, "2026-02-01 07:00:00")

        UserService.update_user(
            user_id,
            {"position_id": new_position, "department_id": new_department},
        )

        rows = PerformanceAssignmentRepository.list_for_user(user_id, db=db)
        assert len(rows) == 2
        assert (rows[0]["position_id"], rows[0]["department_id"]) == (
            old_position,
            old_department,
        )
        assert rows[0]["valid_to"] == "2026-02-01 07:00:00"
        assert (rows[1]["position_id"], rows[1]["department_id"]) == (
            new_position,
            new_department,
        )
        assert rows[1]["valid_from"] == rows[0]["valid_to"]
        assert rows[1]["source_type"] == "assignment_changed"


def test_identity_change_preserves_old_snapshot_without_claiming_assignment_change(
    client, monkeypatch
):
    with client.application.app_context():
        db = get_db()
        user_id, position_id, department_id = _create_assigned_user(
            db, monkeypatch, "身份"
        )
        _set_time(monkeypatch, "2026-01-15 08:30:00")

        UserService.update_user(
            user_id,
            {"name": "任职员工新姓名", "employee_no": "ASSIGN-NEW"},
        )

        rows = PerformanceAssignmentRepository.list_for_user(user_id, db=db)
        assert [row["employee_name_snapshot"] for row in rows] == [
            "任职员工身份",
            "任职员工新姓名",
        ]
        assert [row["employee_no_snapshot"] for row in rows] == [
            "ASSIGN-身份",
            "ASSIGN-NEW",
        ]
        assert {(row["position_id"], row["department_id"]) for row in rows} == {
            (position_id, department_id)
        }
        assert rows[1]["source_type"] == "identity_snapshot_changed"


def test_assignment_failure_rolls_back_user_and_history(client, monkeypatch):
    with client.application.app_context():
        db = get_db()
        user_id, _, _ = _create_assigned_user(db, monkeypatch, "回滚")
        _set_time(monkeypatch, "2026-01-20 09:00:00")

        def fail_insert(*args, **kwargs):
            raise RuntimeError("assignment write failed")

        monkeypatch.setattr(
            PerformanceAssignmentRepository, "insert_assignment", fail_insert
        )
        with pytest.raises(RuntimeError, match="assignment write failed"):
            UserService.update_user(user_id, {"name": "不应保存的姓名"})

        user = db.execute("SELECT name FROM users WHERE id = ?", (user_id,)).fetchone()
        assignment = db.execute(
            "SELECT employee_name_snapshot, valid_to "
            "FROM performance_assignment_history WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        assert user["name"] == "任职员工回滚"
        assert tuple(assignment) == ("任职员工回滚", "")


def test_overlapping_assignment_interval_is_rejected(client, monkeypatch):
    with client.application.app_context():
        db = get_db()
        user_id, position_id, department_id = _create_assigned_user(
            db, monkeypatch, "重叠"
        )
        PerformanceAssignmentRepository.close_open_assignment(
            user_id, "2026-02-01 07:00:00", db=db
        )
        snapshot = PerformanceAssignmentRepository.user_snapshot(user_id, db=db)

        with pytest.raises(ConflictError, match="overlaps"):
            PerformanceAssignmentRepository.insert_assignment(
                {
                    **snapshot,
                    "valid_from": "2026-01-15 07:00:00",
                    "valid_to": "2026-02-15 07:00:00",
                    "source_type": "test",
                    "source_key": "test:overlap",
                    "created_by": None,
                },
                db=db,
            )

        assert snapshot["position_id"] == position_id
        assert snapshot["department_id"] == department_id


def test_historical_lookup_uses_half_open_intervals_and_never_current_user_fallback(
    client, monkeypatch
):
    with client.application.app_context():
        db = get_db()
        user_id, old_position, _ = _create_assigned_user(
            db, monkeypatch, "历史", "2026-01-01 07:00:00"
        )
        new_position, new_department = _organization(db, "当前")
        _set_time(monkeypatch, "2026-02-01 07:00:00")
        UserService.update_user(
            user_id,
            {"position_id": new_position, "department_id": new_department},
        )

        january = PerformanceAssignmentService.assignments_for_period(
            user_id, "2026-01-01 07:00:00", "2026-02-01 07:00:00", db=db
        )
        february = PerformanceAssignmentService.assignments_for_period(
            user_id, "2026-02-01 07:00:00", "2026-03-01 07:00:00", db=db
        )
        db.execute(
            "UPDATE users SET position_id = NULL, department_id = NULL WHERE id = ?",
            (user_id,),
        )

        january_again = PerformanceAssignmentService.assignments_for_period(
            user_id, "2026-01-01 07:00:00", "2026-02-01 07:00:00", db=db
        )
        assert [row["position_id"] for row in january] == [old_position]
        assert [row["position_id"] for row in february] == [new_position]
        assert [row["position_id"] for row in january_again] == [old_position]


def test_v56_current_baseline_is_not_backdated_into_unknown_history():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        for version, _, migrate in migrations.MIGRATIONS:
            if version >= 56:
                break
            migrate(db)
        user_id = db.execute(
            "INSERT INTO users (username,password,name,role,employee_no,status) "
            "VALUES ('baseline-worker','hash','基线员工','worker','BASE-1','active')"
        ).lastrowid

        m056_versioned_performance_ledger(db)

        baseline = db.execute(
            "SELECT * FROM performance_assignment_history WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        assert baseline["source_type"] == "current_baseline"
        assert baseline["source_key"] == "current_baseline:v56"
        unknown = PerformanceAssignmentService.assignments_for_period(
            user_id, "2025-01-01 07:00:00", "2025-02-01 07:00:00", db=db
        )
        assert unknown == []
    finally:
        db.close()


def test_reactivation_closes_existing_inactive_v56_baseline(client, monkeypatch):
    with client.application.app_context():
        db = get_db()
        position_id, department_id = _organization(db, "基线恢复")
        user_id = db.execute(
            "INSERT INTO users (username,password,name,role,employee_no,status,"
            "position_id,department_id) VALUES "
            "('inactive-baseline','hash','停用基线员工','worker','BASE-INACTIVE',"
            "'inactive',?,?)",
            (position_id, department_id),
        ).lastrowid
        db.execute(
            "INSERT INTO performance_assignment_history ("
            "user_id,employee_name_snapshot,employee_no_snapshot,position_id,"
            "position_name_snapshot,department_id,department_name_snapshot,valid_from,"
            "source_type,source_key) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                user_id,
                "停用基线员工",
                "BASE-INACTIVE",
                position_id,
                "任职岗位基线恢复",
                department_id,
                "任职部门基线恢复",
                "2026-01-01 07:00:00",
                "current_baseline",
                "current_baseline:v56",
            ),
        )
        db.commit()
        _set_time(monkeypatch, "2026-04-01 07:00:00")

        UserService.batch_update_status([user_id], "active")

        rows = PerformanceAssignmentRepository.list_for_user(user_id, db=db)
        assert [row["valid_to"] for row in rows] == ["2026-04-01 07:00:00", ""]
        assert rows[1]["source_type"] == "user_reactivated"


def test_inactive_workers_with_assignment_or_source_fact_remain_historical_candidates(
    client, monkeypatch
):
    with client.application.app_context():
        db = get_db()
        assigned_id, _, _ = _create_assigned_user(
            db, monkeypatch, "离职", "2026-03-01 07:00:00"
        )
        _set_time(monkeypatch, "2026-03-20 12:00:00")
        UserService.batch_update_status([assigned_id], "inactive")

        source_only_id = db.execute(
            "INSERT INTO users (username,password,name,role,employee_no,status) "
            "VALUES ('source-only','hash','仅来源员工','worker','SOURCE-1','inactive')"
        ).lastrowid
        batch_id = db.execute(
            "INSERT INTO performance_batches ("
            "production_month,version,period_start,period_end,idempotency_key"
            ") VALUES ('2026-03',1,'2026-03-01 07:00:00','2026-04-01 07:00:00',"
            "'test:assignment:candidates')"
        ).lastrowid
        db.execute(
            "INSERT INTO performance_source_facts ("
            "batch_id,fact_type,source_type,source_id,user_id,source_digest"
            ") VALUES (?,?,?,?,?,?)",
            (batch_id, "work", "work_records", 9001, source_only_id, "fact-9001"),
        )
        db.commit()

        candidates = PerformanceAssignmentService.candidate_user_ids(
            "2026-03-01 07:00:00", "2026-04-01 07:00:00", db=db
        )
        assert assigned_id in candidates
        assert source_only_id in candidates
