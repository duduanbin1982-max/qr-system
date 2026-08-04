import json

import pytest

from modules.db import get_db
from modules.domain.errors import NotFoundError
from modules.services.performance_authorization_service import (
    PerformanceAuthorizationService,
)
from modules.services.user_service import UserService


def _department(db, name):
    department_id = db.execute(
        "INSERT INTO departments (name, status) VALUES (?, 'active')", (name,)
    ).lastrowid
    db.commit()
    return department_id


def _user(db, username, name, department_id=None, status="active"):
    user_id = db.execute(
        "INSERT INTO users (username,password,name,role,employee_no,status,department_id) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            username,
            "hash",
            name,
            "worker",
            "PERM-" + username,
            status,
            department_id,
        ),
    ).lastrowid
    db.commit()
    return user_id


def _actor(user_id, permissions, name="授权测试员"):
    return {"id": user_id, "name": name, "_permissions": list(permissions)}


def _seed_scores(db, rows, month="2026-05"):
    batch_id = db.execute(
        "INSERT INTO performance_batches ("
        "production_month,version,period_start,period_end,idempotency_key"
        ") VALUES (?,?,?,?,?)",
        (
            month,
            1,
            month + "-01 07:00:00",
            "2026-06-01 07:00:00",
            "test:performance:permissions:" + month,
        ),
    ).lastrowid
    for user_id, department_id, department_name in rows:
        db.execute(
            "INSERT INTO performance_score_revisions ("
            "batch_id,user_id,revision,employee_name_snapshot,"
            "department_id_snapshot,department_name_snapshot"
            ") SELECT ?,?,1,name,?,? FROM users WHERE id=?",
            (batch_id, user_id, department_id, department_name, user_id),
        )
    db.commit()
    return batch_id


def test_view_scope_unions_self_and_explicit_departments_without_filter_widening(client):
    with client.application.app_context():
        db = get_db()
        department_a = _department(db, "绩效权限部门甲")
        department_b = _department(db, "绩效权限部门乙")
        department_self = _department(db, "绩效权限本人部门")
        actor_id = _user(db, "scope-actor", "范围员工", department_self)
        department_user = _user(db, "scope-dept", "部门员工", department_a)
        outside_user = _user(db, "scope-outside", "范围外员工", department_b)
        batch_id = _seed_scores(
            db,
            [
                (actor_id, department_self, "绩效权限本人部门"),
                (department_user, department_a, "绩效权限部门甲"),
                (outside_user, department_b, "绩效权限部门乙"),
            ],
        )
        PerformanceAuthorizationService.replace_department_scopes(
            actor_id,
            [department_a],
            _actor(1, ["users:admin"], "管理员"),
            db=db,
        )
        actor = _actor(
            actor_id,
            ["performance:view_self", "performance:view_department"],
        )

        scope = PerformanceAuthorizationService.resolve_view_scope(actor, db=db)
        assert scope == {
            "all": False,
            "self_user_id": actor_id,
            "department_ids": [department_a],
        }
        visible = PerformanceAuthorizationService.list_visible_scores(
            actor, batch_id=batch_id, page=1, limit=20, db=db
        )
        assert {row["user_id"] for row in visible["items"]} == {
            actor_id,
            department_user,
        }
        assert PerformanceAuthorizationService.list_visible_scores(
            actor, batch_id=batch_id, user_id=outside_user, db=db
        )["total"] == 0
        assert PerformanceAuthorizationService.list_visible_scores(
            actor, batch_id=batch_id, department_id=department_b, db=db
        )["total"] == 0


def test_historical_department_snapshot_controls_visibility_not_current_user_department(client):
    with client.application.app_context():
        db = get_db()
        historical_department = _department(db, "历史归属部门")
        current_department = _department(db, "当前归属部门")
        actor_id = _user(db, "history-manager", "历史部门主管")
        employee_id = _user(db, "history-worker", "历史部门员工", current_department)
        batch_id = _seed_scores(
            db, [(employee_id, historical_department, "历史归属部门")]
        )
        PerformanceAuthorizationService.replace_department_scopes(
            actor_id,
            [historical_department],
            _actor(1, ["users:admin"], "管理员"),
            db=db,
        )

        visible = PerformanceAuthorizationService.list_visible_scores(
            _actor(actor_id, ["performance:view_department"]),
            batch_id=batch_id,
            db=db,
        )
        assert [row["user_id"] for row in visible["items"]] == [employee_id]
        assert visible["items"][0]["department_id_snapshot"] == historical_department


def test_empty_department_scope_fails_closed_and_legacy_view_cannot_read_others(client):
    with client.application.app_context():
        db = get_db()
        department_id = _department(db, "空范围部门")
        employee_id = _user(db, "empty-scope-worker", "空范围员工", department_id)
        batch_id = _seed_scores(db, [(employee_id, department_id, "空范围部门")])
        scoped_actor = _actor(
            _user(db, "empty-scope-manager", "空范围主管"),
            ["performance:view_department"],
        )
        legacy_actor = _actor(
            _user(db, "legacy-viewer", "旧查看者"), ["performance:view"]
        )

        assert PerformanceAuthorizationService.resolve_view_scope(
            scoped_actor, db=db
        )["department_ids"] == []
        assert PerformanceAuthorizationService.list_visible_scores(
            scoped_actor, batch_id=batch_id, db=db
        )["total"] == 0
        assert PerformanceAuthorizationService.list_visible_scores(
            legacy_actor, batch_id=batch_id, db=db
        )["total"] == 0


def test_migrated_worker_role_can_open_performance_and_only_view_self(client):
    with client.application.app_context():
        db = get_db()
        worker_role = db.execute(
            "SELECT id,permissions FROM roles WHERE code='worker' ORDER BY id LIMIT 1"
        ).fetchone()
        permissions = json.loads(worker_role["permissions"])
        assert "page:performance" in permissions
        assert "performance:view_self" in permissions
        assert "performance:view_department" not in permissions
        assert "performance:view_all" not in permissions

        department_id = _department(db, "普通员工绩效部门")
        worker_id = _user(db, "self-only-worker", "仅本人员工", department_id)
        other_id = _user(db, "self-only-other", "其他员工", department_id)
        db.execute(
            "INSERT INTO user_roles (user_id,role_id) VALUES (?,?)",
            (worker_id, worker_role["id"]),
        )
        batch_id = _seed_scores(
            db,
            [
                (worker_id, department_id, "普通员工绩效部门"),
                (other_id, department_id, "普通员工绩效部门"),
            ],
        )

        visible = PerformanceAuthorizationService.list_visible_scores(
            _actor(worker_id, permissions), batch_id=batch_id, db=db
        )
        assert [row["user_id"] for row in visible["items"]] == [worker_id]


def test_view_all_is_global_but_does_not_grant_review_or_other_write_actions(client):
    with client.application.app_context():
        db = get_db()
        department_a = _department(db, "复核部门甲")
        department_b = _department(db, "复核部门乙")
        reviewer_id = _user(db, "department-reviewer", "部门复核人")
        member_a = _user(db, "review-member-a", "复核员工甲", department_b)
        member_b = _user(db, "review-member-b", "复核员工乙", department_a)
        batch_id = _seed_scores(
            db,
            [
                (member_a, department_a, "复核部门甲"),
                (member_b, department_b, "复核部门乙"),
            ],
        )
        PerformanceAuthorizationService.replace_department_scopes(
            reviewer_id,
            [department_a],
            _actor(1, ["users:admin"], "管理员"),
            db=db,
        )
        reviewer = _actor(reviewer_id, ["performance:review_department"])

        assert PerformanceAuthorizationService.can_review_member(
            reviewer, batch_id, member_a, db=db
        )
        assert not PerformanceAuthorizationService.can_review_member(
            reviewer, batch_id, member_b, db=db
        )
        global_viewer = _actor(reviewer_id, ["performance:view_all"])
        assert PerformanceAuthorizationService.resolve_view_scope(
            global_viewer, db=db
        )["all"]
        assert not PerformanceAuthorizationService.can_review_member(
            global_viewer, batch_id, member_a, db=db
        )
        assert not PerformanceAuthorizationService.can_perform(
            global_viewer, "prepare"
        )
        assert not PerformanceAuthorizationService.can_perform(
            global_viewer, "approve"
        )


def test_wildcard_admin_can_invoke_actions_without_bypassing_later_duty_checks(client):
    with client.application.app_context():
        db = get_db()
        admin = _actor(1, ["*"], "通配管理员")
        assert PerformanceAuthorizationService.resolve_view_scope(admin, db=db)["all"]
        for action in ("review_department", "prepare", "approve", "plan_manage"):
            assert PerformanceAuthorizationService.can_perform(admin, action)
        with pytest.raises(ValueError, match="must differ"):
            PerformanceAuthorizationService.require_distinct_actors(1, 1)


def test_admin_scope_endpoint_replaces_atomically_and_writes_security_audit(
    client, auth_headers, worker_auth_headers
):
    with client.application.app_context():
        db = get_db()
        department_a = _department(db, "接口范围部门甲")
        department_b = _department(db, "接口范围部门乙")
        target_user_id, _ = UserService.create_user(
            {
                "username": "scope-target",
                "name": "范围配置员工",
                "password": "Worker123",
            }
        )
        permissions_before = db.execute(
            "SELECT r.permissions FROM roles r JOIN user_roles ur ON ur.role_id=r.id "
            "WHERE ur.user_id=? ORDER BY r.id LIMIT 1",
            (target_user_id,),
        ).fetchone()["permissions"]

    denied = client.put(
        f"/api/performance/department-scopes/{target_user_id}",
        json={"department_ids": [department_a]},
        headers=worker_auth_headers,
    )
    assert denied.status_code == 403

    replaced = client.put(
        f"/api/performance/department-scopes/{target_user_id}",
        json={"department_ids": [department_b, department_a, department_a]},
        headers=auth_headers,
    )
    assert replaced.status_code == 200, replaced.get_json()
    assert replaced.get_json()["department_ids"] == [department_a, department_b]
    fetched = client.get(
        f"/api/performance/department-scopes/{target_user_id}",
        headers=auth_headers,
    )
    assert fetched.status_code == 200
    assert [row["id"] for row in fetched.get_json()["departments"]] == [
        department_a,
        department_b,
    ]

    invalid = client.put(
        f"/api/performance/department-scopes/{target_user_id}",
        json={"department_ids": [999999]},
        headers=auth_headers,
    )
    assert invalid.status_code == 404

    with client.application.app_context():
        db = get_db()
        persisted = db.execute(
            "SELECT department_id FROM performance_department_scopes "
            "WHERE user_id=? ORDER BY department_id",
            (target_user_id,),
        ).fetchall()
        assert [row["department_id"] for row in persisted] == [
            department_a,
            department_b,
        ]
        permissions_after = db.execute(
            "SELECT r.permissions FROM roles r JOIN user_roles ur ON ur.role_id=r.id "
            "WHERE ur.user_id=? ORDER BY r.id LIMIT 1",
            (target_user_id,),
        ).fetchone()["permissions"]
        assert json.loads(permissions_after) == json.loads(permissions_before)
        audit = db.execute(
            "SELECT action, target_type, target_id, detail FROM audit_logs "
            "WHERE action='replace_performance_department_scopes' "
            "AND target_id=? ORDER BY id DESC LIMIT 1",
            (target_user_id,),
        ).fetchone()
        assert audit is not None
        assert audit["target_type"] == "user"
        assert str(department_a) in audit["detail"]


def test_scope_service_rejects_non_admin_and_missing_target(client):
    with client.application.app_context():
        db = get_db()
        department_id = _department(db, "服务校验部门")
        target_id = _user(db, "scope-service-target", "服务范围员工")
        with pytest.raises(PermissionError):
            PerformanceAuthorizationService.replace_department_scopes(
                target_id,
                [department_id],
                _actor(2, ["performance:view_all"]),
                db=db,
            )
        with pytest.raises(NotFoundError, match="user"):
            PerformanceAuthorizationService.replace_department_scopes(
                999999,
                [department_id],
                _actor(1, ["users:admin"]),
                db=db,
            )
