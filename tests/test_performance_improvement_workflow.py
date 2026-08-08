import json
import sqlite3

import pytest

from modules.db import get_db
from modules.domain.errors import ConflictError
from modules.repositories.performance_improvement_repository import (
    PerformanceImprovementRepository,
)
from modules.services.performance_fact_collector import PerformanceFactCollector
from modules.services.performance_improvement_service import (
    PerformanceImprovementService,
)


PERIOD_START = "2026-08-01 07:00:00"
PERIOD_END = "2026-09-01 07:00:00"


def _user(db, suffix, permissions=None):
    permissions = list(permissions or [])
    if any(
        permission in permissions
        for permission in ("performance:plan_manage", "performance:plan_reassess")
    ) and "performance:view_department" not in permissions:
        permissions.append("performance:view_department")
    department_id = db.execute(
        "INSERT INTO departments (name,status) VALUES (?,'active')",
        ("绩效改进部门-" + suffix,),
    ).lastrowid
    position_id = db.execute(
        "INSERT INTO positions (name,status) VALUES (?,'active')",
        ("绩效改进岗位-" + suffix,),
    ).lastrowid
    user_id = db.execute(
        "INSERT INTO users (username,password,name,role,employee_no,status,"
        "department_id,position_id) VALUES (?,?,?,?,?,'active',?,?)",
        (
            "performance-plan-" + suffix,
            "hash",
            "绩效改进人员-" + suffix,
            "worker",
            "PERF-PLAN-" + suffix.upper(),
            department_id,
            position_id,
        ),
    ).lastrowid
    db.execute(
        "INSERT INTO performance_assignment_history ("
        "user_id,employee_name_snapshot,employee_no_snapshot,position_id,"
        "position_name_snapshot,department_id,department_name_snapshot,"
        "valid_from,valid_to,source_type,source_key) "
        "VALUES (?,?,?,?,?,?,?,'2026-01-01 07:00:00','','test',?)",
        (
            user_id,
            "绩效改进人员-" + suffix,
            "PERF-PLAN-" + suffix.upper(),
            position_id,
            "绩效改进岗位-" + suffix,
            department_id,
            "绩效改进部门-" + suffix,
            "test:performance-plan:" + suffix,
        ),
    )
    if any(
        permission in permissions
        for permission in ("performance:plan_manage", "performance:plan_reassess")
    ):
        for row in db.execute("SELECT id FROM departments ORDER BY id").fetchall():
            db.execute(
                "INSERT OR IGNORE INTO performance_department_scopes "
                "(user_id,department_id,granted_by,granted_by_name) "
                "VALUES (?,?,1,'测试管理员')",
                (user_id, row["id"]),
            )
    db.commit()
    return {
        "id": user_id,
        "name": "绩效改进人员-" + suffix,
        "department_id": department_id,
        "_permissions": permissions,
    }


def _plan_data(user, owner, suffix, *, complete=True):
    data = {
        "user_id": user["id"],
        "production_month": "2026-08",
        "idempotency_key": "performance-plan:create:" + suffix,
    }
    if complete:
        data.update(
            {
                "warning_level": "orange",
                "reason": "连续两周交付指标未达到岗位要求",
                "goal": "2026-08-31 前将准时完成率提升到 95%",
                "actions": "每周复盘两次并完成三项工序纠偏",
                "owner_id": owner["id"],
                "due_date": "2026-08-31",
            }
        )
    return data


def _command(row_version, key, **values):
    return {
        "row_version": row_version,
        "idempotency_key": key,
        **values,
    }


def _create(db, suffix, *, complete=True):
    employee = _user(db, suffix + "-employee")
    owner = _user(db, suffix + "-owner")
    manager = _user(
        db, suffix + "-manager", ["performance:plan_manage"]
    )
    plan = PerformanceImprovementService.create_plan(
        _plan_data(employee, owner, suffix, complete=complete), manager
    )
    return employee, owner, manager, plan


def _activate(plan, manager, suffix, **values):
    return PerformanceImprovementService.transition(
        plan["plan_id"],
        _command(
            plan["row_version"],
            "performance-plan:activate:" + suffix,
            target_status="active",
            **values,
        ),
        manager,
    )


def _pending(db, suffix):
    employee, owner, manager, plan = _create(db, suffix)
    active = _activate(plan, manager, suffix)
    evidence = PerformanceImprovementService.add_evidence(
        plan["plan_id"],
        _command(
            active["row_version"],
            "performance-plan:evidence:" + suffix,
            evidence_type="metric",
            description="准时完成率已提升至 96%",
            source_url="https://evidence.local/metrics/" + suffix,
        ),
        manager,
    )
    pending = PerformanceImprovementService.transition(
        plan["plan_id"],
        _command(
            evidence["row_version"],
            "performance-plan:request:" + suffix,
            target_status="reassessment_pending",
        ),
        manager,
    )
    return employee, owner, manager, pending, evidence


def _replace_scopes(db, actor_id, department_ids):
    db.execute(
        "DELETE FROM performance_department_scopes WHERE user_id=?", (actor_id,)
    )
    for department_id in department_ids:
        db.execute(
            "INSERT INTO performance_department_scopes "
            "(user_id,department_id,granted_by,granted_by_name) "
            "VALUES (?,?,1,'测试管理员')",
            (actor_id, department_id),
        )
    db.commit()


def test_plan_manager_and_reassessor_writes_fail_closed_outside_department_scope(
    client,
):
    with client.application.app_context():
        db = get_db()
        employee = _user(db, "scope-employee")
        owner = _user(db, "scope-owner")
        manager = _user(db, "scope-manager", ["performance:plan_manage"])
        outside_department = db.execute(
            "INSERT INTO departments (name,status) VALUES "
            "('绩效改进范围外部门','active')"
        ).lastrowid
        db.commit()
        _replace_scopes(db, manager["id"], [outside_department])

        with pytest.raises(PermissionError, match="数据范围"):
            PerformanceImprovementService.create_plan(
                _plan_data(employee, owner, "scope-denied"), manager
            )

        _replace_scopes(db, manager["id"], [employee["department_id"]])
        plan = PerformanceImprovementService.create_plan(
            _plan_data(employee, owner, "scope-allowed"), manager
        )
        active = _activate(plan, manager, "scope-allowed")
        evidence = PerformanceImprovementService.add_evidence(
            plan["plan_id"],
            _command(
                active["row_version"],
                "performance-plan:evidence:scope-allowed",
                evidence_type="metric",
                description="范围测试证据",
            ),
            manager,
        )
        pending = PerformanceImprovementService.transition(
            plan["plan_id"],
            _command(
                evidence["row_version"],
                "performance-plan:request:scope-allowed",
                target_status="reassessment_pending",
            ),
            manager,
        )
        assessor = _user(db, "scope-assessor", ["performance:plan_reassess"])
        _replace_scopes(db, assessor["id"], [outside_department])
        with pytest.raises(PermissionError, match="数据范围"):
            PerformanceImprovementService.reassess(
                plan["plan_id"],
                _command(
                    pending["row_version"],
                    "performance-plan:reassess:scope-denied",
                    result="passed",
                    notes="范围外复评不应成功",
                    evidence_ids=[evidence["evidence_id"]],
                ),
                assessor,
            )


def test_activation_validates_fields_and_illegal_transitions(client):
    with client.application.app_context():
        db = get_db()
        employee, owner, manager, incomplete = _create(
            db, "activation-invalid", complete=False
        )

        with pytest.raises(ValueError, match="依据|目标|措施|负责人|截止"):
            _activate(incomplete, manager, "activation-invalid")
        with pytest.raises(ConflictError, match="不允许"):
            PerformanceImprovementService.transition(
                incomplete["plan_id"],
                _command(
                    incomplete["row_version"],
                    "performance-plan:close-draft",
                    target_status="closed",
                ),
                manager,
            )
        with pytest.raises(ConflictError, match="状态"):
            PerformanceImprovementService.transition(
                incomplete["plan_id"],
                _command(
                    incomplete["row_version"],
                    "performance-plan:unknown-state",
                    target_status="paused",
                ),
                manager,
            )

        activated = _activate(
            incomplete,
            manager,
            "activation-complete",
            reason="一次交检合格率持续低于目标",
            goal="2026-08-31 前一次交检合格率达到 98%",
            actions="完成质量复盘、首件确认和每日抽检",
            owner_id=owner["id"],
            due_date="2026-08-31",
        )
        assert activated["status"] == "active"
        assert activated["plan"]["owner_id"] == owner["id"]
        assert activated["row_version"] == incomplete["row_version"] + 1


def test_cancel_requires_reason_from_draft_or_active(client):
    with client.application.app_context():
        db = get_db()
        _, _, manager, plan = _create(db, "cancel")

        with pytest.raises(ValueError, match="原因"):
            PerformanceImprovementService.transition(
                plan["plan_id"],
                _command(
                    plan["row_version"],
                    "performance-plan:cancel:missing",
                    target_status="cancelled",
                ),
                manager,
            )
        cancelled = PerformanceImprovementService.transition(
            plan["plan_id"],
            _command(
                plan["row_version"],
                "performance-plan:cancel:valid",
                target_status="cancelled",
                reason="岗位职责调整，原计划终止",
            ),
            manager,
        )
        assert cancelled["status"] == "cancelled"
        assert cancelled["plan"]["cancellation_reason"] == "岗位职责调整，原计划终止"


def test_create_and_transition_retries_precede_row_version_validation(client):
    with client.application.app_context():
        db = get_db()
        employee, owner, manager, plan = _create(db, "idempotency")

        create_replay = PerformanceImprovementService.create_plan(
            _plan_data(employee, owner, "idempotency"), manager
        )
        assert create_replay["idempotent_replay"] is True
        assert create_replay["plan_id"] == plan["plan_id"]

        active = _activate(plan, manager, "idempotency")
        transition_replay = _activate(plan, manager, "idempotency")
        assert transition_replay["idempotent_replay"] is True
        assert transition_replay["event_id"] == active["event_id"]

        with pytest.raises(ConflictError, match="版本"):
            PerformanceImprovementService.transition(
                plan["plan_id"],
                _command(
                    plan["row_version"],
                    "performance-plan:cancel:stale",
                    target_status="cancelled",
                    reason="并发测试取消",
                ),
                manager,
            )

        other_employee = _user(db, "idempotency-other")
        with pytest.raises(ConflictError, match="员工|月份"):
            PerformanceImprovementService.create_plan(
                _plan_data(other_employee, owner, "idempotency"), manager
            )


def test_reassessment_request_requires_immutable_evidence(client):
    with client.application.app_context():
        db = get_db()
        _, _, manager, plan = _create(db, "evidence")
        active = _activate(plan, manager, "evidence")

        with pytest.raises(ConflictError, match="证据"):
            PerformanceImprovementService.transition(
                plan["plan_id"],
                _command(
                    active["row_version"],
                    "performance-plan:request:no-evidence",
                    target_status="reassessment_pending",
                ),
                manager,
            )
        evidence = PerformanceImprovementService.add_evidence(
            plan["plan_id"],
            _command(
                active["row_version"],
                "performance-plan:evidence:immutable",
                evidence_type="file",
                description="改进执行记录",
                file_name="improvement-record.pdf",
                file_path="performance/evidence/improvement-record.pdf",
            ),
            manager,
        )
        replay = PerformanceImprovementService.add_evidence(
            plan["plan_id"],
            _command(
                active["row_version"],
                "performance-plan:evidence:immutable",
                evidence_type="file",
                description="改进执行记录",
                file_name="improvement-record.pdf",
                file_path="performance/evidence/improvement-record.pdf",
            ),
            manager,
        )
        assert replay["idempotent_replay"] is True
        assert replay["evidence_id"] == evidence["evidence_id"]

        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(
                "UPDATE performance_plan_evidence SET description='tampered' "
                "WHERE id=?",
                (evidence["evidence_id"],),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(
                "DELETE FROM performance_plan_evidence WHERE id=?",
                (evidence["evidence_id"],),
            )

        pending = PerformanceImprovementService.transition(
            plan["plan_id"],
            _command(
                evidence["row_version"],
                "performance-plan:request:with-evidence",
                target_status="reassessment_pending",
            ),
            manager,
        )
        assert pending["status"] == "reassessment_pending"


def test_plan_owner_cannot_reassess_even_with_wildcard_permission(client):
    with client.application.app_context():
        db = get_db()
        _, owner, _, pending, evidence = _pending(db, "owner-separation")
        owner["_permissions"] = ["*"]

        with pytest.raises(PermissionError, match="负责人"):
            PerformanceImprovementService.reassess(
                pending["plan_id"],
                _command(
                    pending["row_version"],
                    "performance-plan:reassess:owner",
                    result="passed",
                    notes="负责人自行确认通过",
                    evidence_ids=[evidence["evidence_id"]],
                ),
                owner,
            )


def test_passed_reassessment_closes_once_and_is_idempotent(client):
    with client.application.app_context():
        db = get_db()
        _, _, _, pending, evidence = _pending(db, "reassess-pass")
        assessor = _user(
            db, "reassess-pass-assessor", ["performance:plan_reassess"]
        )
        data = _command(
            pending["row_version"],
            "performance-plan:reassess:pass",
            result="passed",
            notes="复评指标和执行证据均符合关闭条件",
            evidence_ids=[evidence["evidence_id"]],
        )

        closed = PerformanceImprovementService.reassess(
            pending["plan_id"], data, assessor
        )
        replay = PerformanceImprovementService.reassess(
            pending["plan_id"], data, assessor
        )
        assert closed["status"] == "closed"
        assert closed["reassessment"]["result"] == "passed"
        assert replay["idempotent_replay"] is True
        assert db.execute(
            "SELECT COUNT(*) FROM performance_plan_reassessments WHERE plan_id=?",
            (pending["plan_id"],),
        ).fetchone()[0] == 1

        with pytest.raises(ConflictError):
            PerformanceImprovementService.reassess(
                pending["plan_id"],
                {**data, "idempotency_key": "performance-plan:reassess:duplicate"},
                assessor,
            )


def test_failed_reassessment_starts_new_round_with_new_actions(client):
    with client.application.app_context():
        db = get_db()
        _, _, manager, pending, evidence = _pending(db, "reassess-fail")
        assessor = _user(
            db, "reassess-fail-assessor", ["performance:plan_reassess"]
        )

        with pytest.raises(ValueError, match="措施|截止"):
            PerformanceImprovementService.reassess(
                pending["plan_id"],
                _command(
                    pending["row_version"],
                    "performance-plan:reassess:fail-invalid",
                    result="failed",
                    notes="当前改进结果未达到目标",
                    evidence_ids=[evidence["evidence_id"]],
                ),
                assessor,
            )
        failed = PerformanceImprovementService.reassess(
            pending["plan_id"],
            _command(
                pending["row_version"],
                "performance-plan:reassess:fail",
                result="failed",
                notes="连续三天指标仍低于目标",
                evidence_ids=[evidence["evidence_id"]],
                new_actions="增加每日首件确认并由主管现场复核",
                new_due_date="2026-09-15",
            ),
            assessor,
        )
        assert failed["status"] == "active"
        assert failed["plan"]["reassessment_round"] == 1
        assert failed["plan"]["actions"] == "增加每日首件确认并由主管现场复核"
        assert failed["plan"]["due_date"] == "2026-09-15"
        assert failed["reassessment"]["reassessment_round"] == 0

        with pytest.raises(ConflictError, match="证据"):
            PerformanceImprovementService.transition(
                pending["plan_id"],
                _command(
                    failed["row_version"],
                    "performance-plan:request:round-1-no-evidence",
                    target_status="reassessment_pending",
                ),
                manager,
            )


def test_plan_fact_uses_event_at_cutoff_after_later_close(client, monkeypatch):
    with client.application.app_context():
        db = get_db()
        employee = _user(db, "fact-employee")
        owner = _user(db, "fact-owner")
        manager = _user(db, "fact-manager", ["performance:plan_manage"])
        assessor = _user(db, "fact-assessor", ["performance:plan_reassess"])
        clock = {"now": "2026-08-05 08:00:00"}
        monkeypatch.setattr(
            PerformanceImprovementRepository,
            "database_now",
            staticmethod(lambda db=None: clock["now"]),
        )
        plan = PerformanceImprovementService.create_plan(
            _plan_data(employee, owner, "fact"), manager
        )
        clock["now"] = "2026-08-10 08:00:00"
        active = _activate(plan, manager, "fact")
        clock["now"] = "2026-08-11 08:00:00"
        evidence = PerformanceImprovementService.add_evidence(
            plan["plan_id"],
            _command(
                active["row_version"],
                "performance-plan:evidence:fact",
                evidence_type="metric",
                description="改进指标证据",
            ),
            manager,
        )
        clock["now"] = "2026-08-12 08:00:00"
        pending = PerformanceImprovementService.transition(
            plan["plan_id"],
            _command(
                evidence["row_version"],
                "performance-plan:request:fact",
                target_status="reassessment_pending",
            ),
            manager,
        )

        first_batch = _fact_batch(db, "fact-before-close", 1, "2026-08-15 08:00:00")
        first = PerformanceFactCollector.collect(first_batch, db=db)
        first_plan = _plan_fact(first, plan["plan_id"])
        assert json.loads(first_plan["payload_json"])["status"] == "reassessment_pending"

        clock["now"] = "2026-08-20 08:00:00"
        PerformanceImprovementService.reassess(
            plan["plan_id"],
            _command(
                pending["row_version"],
                "performance-plan:reassess:fact",
                result="passed",
                notes="截止后完成复评关闭",
                evidence_ids=[evidence["evidence_id"]],
            ),
            assessor,
        )
        second_batch = _fact_batch(db, "fact-after-close", 2, "2026-08-15 08:00:00")
        second = PerformanceFactCollector.collect(second_batch, db=db)
        second_plan = _plan_fact(second, plan["plan_id"])

        assert second_plan["source_digest"] == first_plan["source_digest"]
        assert json.loads(second_plan["payload_json"])["status"] == "reassessment_pending"


def _fact_batch(db, suffix, version, cutoff):
    return db.execute(
        "INSERT INTO performance_batches ("
        "production_month,version,period_start,period_end,source_cutoff_at,"
        "idempotency_key) VALUES ('2026-08',?,?,?,?,?)",
        (version, PERIOD_START, PERIOD_END, cutoff, "performance-plan-fact:" + suffix),
    ).lastrowid


def _plan_fact(collection, plan_id):
    return next(
        row
        for row in collection["facts"]
        if row["fact_type"] == "plan_status"
        and json.loads(row["payload_json"])["plan_id"] == plan_id
    )


def test_legacy_plan_put_is_read_only(client, auth_headers):
    response = client.put(
        "/api/performance/plans/1",
        json={"status": "closed", "review_notes": "覆盖旧计划"},
        headers=auth_headers,
    )
    assert response.status_code == 409
    assert response.get_json()["code"] == "LEGACY_LEDGER_READ_ONLY"


def test_plan_routes_expose_versioned_commands_and_enforce_permissions(
    client, auth_headers, worker_auth_headers
):
    with client.application.app_context():
        db = get_db()
        employee = _user(db, "route-employee")
        owner = _user(db, "route-owner")

    created_response = client.post(
        "/api/performance/plans",
        json=_plan_data(employee, owner, "route"),
        headers=auth_headers,
    )
    assert created_response.status_code == 201, created_response.get_json()
    created = created_response.get_json()
    activated_response = client.post(
        "/api/performance/plans/{}/transitions".format(created["plan_id"]),
        json=_command(
            created["row_version"],
            "performance-plan:route:activate",
            target_status="active",
        ),
        headers=auth_headers,
    )
    assert activated_response.status_code == 200, activated_response.get_json()
    assert activated_response.get_json()["status"] == "active"

    detail_response = client.get(
        "/api/performance/plans/{}".format(created["plan_id"]),
        headers=auth_headers,
    )
    assert detail_response.status_code == 200
    assert detail_response.get_json()["plan_id"] == created["plan_id"]

    denied_response = client.post(
        "/api/performance/plans",
        json=_plan_data(employee, owner, "route-denied"),
        headers=worker_auth_headers,
    )
    assert denied_response.status_code == 403
    assert denied_response.get_json()["code"] == "forbidden"
