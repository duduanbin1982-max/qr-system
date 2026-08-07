import json
import sqlite3

import pytest

from modules.db import get_db
from modules.repositories.performance_assignment_repository import (
    PerformanceAssignmentRepository,
)
from modules.services.performance_assignment_department_service import (
    PerformanceAssignmentDepartmentService,
)
from modules.services.performance_fact_collector import PerformanceFactCollector


def _actor(db, suffix, permission):
    user_id = db.execute(
        "INSERT INTO users (username,password,name,role,employee_no,status) "
        "VALUES (?,?,?,?,?,'active')",
        (
            "department-revision-" + suffix,
            "hash",
            "部门修订" + suffix,
            "worker",
            "DEPT-REV-" + suffix,
        ),
    ).lastrowid
    db.commit()
    return {
        "id": user_id,
        "name": "部门修订" + suffix,
        "_permissions": [permission],
    }


def _assignment(db):
    position_id = db.execute(
        "INSERT INTO positions (name,status) VALUES ('部门补充岗位','active')"
    ).lastrowid
    user_id = db.execute(
        "INSERT INTO users (username,password,name,role,employee_no,status,position_id) "
        "VALUES ('department-revision-worker','hash','部门补充员工','worker',"
        "'DEPT-REV-WORKER','active',?)",
        (position_id,),
    ).lastrowid
    assignment_id = db.execute(
        "INSERT INTO performance_assignment_history ("
        "user_id,employee_name_snapshot,employee_no_snapshot,position_id,"
        "position_name_snapshot,valid_from,valid_to,source_type,source_key) "
        "VALUES (?,?,?,?,?,'2026-06-01 07:00:00','2026-08-01 07:00:00',"
        "'manual_history_confirmation','department-revision:test')",
        (user_id, "部门补充员工", "DEPT-REV-WORKER", position_id, "部门补充岗位"),
    ).lastrowid
    department_a = db.execute(
        "INSERT INTO departments (name,status) VALUES ('部门补充甲','active')"
    ).lastrowid
    department_b = db.execute(
        "INSERT INTO departments (name,status) VALUES ('部门补充乙','active')"
    ).lastrowid
    db.commit()
    return user_id, assignment_id, department_a, department_b


def _create_and_approve(assignment_id, department_id, key, preparer, approver):
    draft = PerformanceAssignmentDepartmentService.create_revision(
        {
            "assignment_id": assignment_id,
            "department_id": department_id,
            "reason": "业务负责人确认历史部门归属",
            "source_type": "manual_history_confirmation",
            "source_key": key,
        },
        preparer,
    )
    return PerformanceAssignmentDepartmentService.approve_revision(
        draft["id"], approver, draft["row_version"]
    )


def test_approved_department_revision_overlays_assignment_and_frozen_fact(client):
    with client.application.app_context():
        db = get_db()
        user_id, assignment_id, department_id, _ = _assignment(db)
        preparer = _actor(db, "制单", "performance:prepare")
        approver = _actor(db, "批准", "performance:approve")

        approved = _create_and_approve(
            assignment_id,
            department_id,
            "department-revision:approved",
            preparer,
            approver,
        )
        raw = db.execute(
            "SELECT department_id,department_name_snapshot "
            "FROM performance_assignment_history WHERE id=?",
            (assignment_id,),
        ).fetchone()
        assert raw["department_id"] is None
        assert raw["department_name_snapshot"] == ""

        effective = PerformanceAssignmentRepository.assignment_at(
            user_id, "2026-07-15 12:00:00", db=db
        )
        assert effective["department_id"] == department_id
        assert effective["department_name_snapshot"] == "部门补充甲"
        assert effective["department_revision_id"] == approved["id"]
        assert effective["original_department_id"] is None

        batch_id = db.execute(
            "INSERT INTO performance_batches ("
            "production_month,version,period_start,period_end,source_cutoff_at,"
            "idempotency_key) VALUES ('2026-07',2,'2026-07-01 07:00:00',"
            "'2026-08-01 07:00:00','2026-08-07 12:00:00',"
            "'test:department-revision:fact')"
        ).lastrowid
        db.commit()
        collected = PerformanceFactCollector.collect(batch_id)
        assignment_fact = next(
            fact
            for fact in collected["facts"]
            if fact["fact_type"] == "assignment" and fact["user_id"] == user_id
        )
        payload = json.loads(assignment_fact["payload_json"])
        assert assignment_fact["department_id_snapshot"] == department_id
        assert payload["department_revision_id"] == approved["id"]
        assert payload["department_revision"] == 1


def test_new_approved_revision_supersedes_old_without_mutating_assignment(client):
    with client.application.app_context():
        db = get_db()
        user_id, assignment_id, department_a, department_b = _assignment(db)
        preparer = _actor(db, "版本制单", "performance:prepare")
        approver = _actor(db, "版本批准", "performance:approve")
        first = _create_and_approve(
            assignment_id,
            department_a,
            "department-revision:v1",
            preparer,
            approver,
        )
        second = _create_and_approve(
            assignment_id,
            department_b,
            "department-revision:v2",
            preparer,
            approver,
        )

        rows = PerformanceAssignmentDepartmentService.list_revisions(
            assignment_id, db=db
        )
        assert [(row["revision"], row["status"]) for row in rows] == [
            (1, "superseded"),
            (2, "approved"),
        ]
        assert rows[0]["superseded_by_revision_id"] == second["id"]
        assert second["supersedes_revision_id"] == first["id"]
        assert PerformanceAssignmentRepository.assignment_at(
            user_id, "2026-07-15 12:00:00", db=db
        )["department_id"] == department_b
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(
                "UPDATE performance_assignment_department_revisions "
                "SET department_name_snapshot='不允许修改' WHERE id=?",
                (second["id"],),
            )


def test_department_revision_requires_distinct_approver(client):
    with client.application.app_context():
        db = get_db()
        _, assignment_id, department_id, _ = _assignment(db)
        actor = _actor(db, "同人", "*")
        draft = PerformanceAssignmentDepartmentService.create_revision(
            {
                "assignment_id": assignment_id,
                "department_id": department_id,
                "reason": "测试双人批准",
                "source_key": "department-revision:same-actor",
            },
            actor,
        )
        with pytest.raises(ValueError, match="must differ"):
            PerformanceAssignmentDepartmentService.approve_revision(
                draft["id"], actor, draft["row_version"]
            )
