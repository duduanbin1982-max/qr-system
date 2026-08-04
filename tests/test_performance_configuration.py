import json
import sqlite3

import pytest

from modules.db import get_db
from modules.domain.errors import NotFoundError
from modules.domain.performance_policy import PerformanceConflictError
from modules.services.performance_authorization_service import (
    PerformanceAuthorizationService,
)
from modules.services.performance_configuration_service import (
    PerformanceConfigurationService,
)
from modules.services.user_service import UserService


def _actor(user_id, permissions, name="绩效配置操作人"):
    return {"id": user_id, "name": name, "_permissions": list(permissions)}


def _position(db, name="配置岗位"):
    position_id = db.execute(
        "INSERT INTO positions (name,status) VALUES (?, 'active')", (name,)
    ).lastrowid
    db.commit()
    return position_id


def _prepare_actor(db, suffix="prepare"):
    user_id = db.execute(
        "INSERT INTO users (username,password,name,role,employee_no,status) "
        "VALUES (?,?,?,?,?,'active')",
        (
            "configuration-prepare-" + suffix,
            "hash",
            "配置制单人" + suffix,
            "worker",
            "CONFIG-" + suffix,
        ),
    ).lastrowid
    db.commit()
    return _actor(user_id, ["performance:prepare"], "配置制单人" + suffix)


def _approve_actor(db, suffix="approve"):
    user_id = db.execute(
        "INSERT INTO users (username,password,name,role,employee_no,status) "
        "VALUES (?,?,?,?,?,'active')",
        (
            "configuration-approve-" + suffix,
            "hash",
            "配置批准人" + suffix,
            "worker",
            "CONFIG-APPROVE-" + suffix,
        ),
    ).lastrowid
    db.commit()
    return _actor(user_id, ["performance:approve"], "配置批准人" + suffix)


def test_rule_draft_is_editable_then_publish_locks_content_and_delete(client):
    with client.application.app_context():
        db = get_db()
        preparer = _prepare_actor(db, "rule")
        approver = _approve_actor(db, "rule")
        created = PerformanceConfigurationService.create_rule_version(
            {
                "version_code": "rule-v2-2026",
                "name": "2026绩效规则",
                "effective_from_month": "2026-01",
                "effective_to_month": "2027-01",
            },
            preparer,
            db=db,
        )
        assert created["status"] == "draft"
        assert json.loads(created["weights_json"])["output"] == 35
        assert PerformanceConfigurationService.update_rule_version(
            created["id"],
            {"name": "2026绩效规则修订"},
            preparer,
            expected_row_version=1,
            db=db,
        )["row_version"] == 2

        published = PerformanceConfigurationService.publish_rule_version(
            created["id"], approver, expected_row_version=2, db=db
        )
        assert published["status"] == "published"
        assert published["published_by"] == approver["id"]

        with pytest.raises(PerformanceConflictError, match="immutable"):
            PerformanceConfigurationService.update_rule_version(
                created["id"],
                {"name": "不应修改"},
                preparer,
                expected_row_version=3,
                db=db,
            )
        with pytest.raises(sqlite3.IntegrityError, match="published performance rules"):
            db.execute(
                "DELETE FROM performance_rule_versions WHERE id=?", (created["id"],)
            )


def test_rule_weights_thresholds_and_month_range_are_validated(client):
    with client.application.app_context():
        db = get_db()
        preparer = _prepare_actor(db, "validation")
        with pytest.raises(ValueError, match="合计 100"):
            PerformanceConfigurationService.create_rule_version(
                {
                    "version_code": "rule-invalid-weight",
                    "weights": {
                        "output": 40,
                        "quality": 30,
                        "delivery": 15,
                        "discipline": 10,
                        "improvement": 10,
                    },
                },
                preparer,
                db=db,
            )
        with pytest.raises(ValueError, match="YYYY-MM"):
            PerformanceConfigurationService.create_rule_version(
                {
                    "version_code": "rule-invalid-month",
                    "effective_from_month": "2026-13",
                },
                preparer,
                db=db,
            )
        with pytest.raises(ValueError, match="阈值"):
            PerformanceConfigurationService.create_rule_version(
                {
                    "version_code": "rule-invalid-warning",
                    "warning_levels": [],
                },
                preparer,
                db=db,
            )


def test_first_rule_keeps_current_scoring_baseline(client):
    with client.application.app_context():
        db = get_db()
        preparer = _prepare_actor(db, "baseline")
        created = PerformanceConfigurationService.create_rule_version(
            {"version_code": "rule-baseline"}, preparer, db=db
        )
        weights = json.loads(created["weights_json"])
        parameters = json.loads(created["scoring_parameters_json"])
        assert weights == {
            "output": 35,
            "quality": 30,
            "delivery": 15,
            "discipline": 10,
            "improvement": 10,
        }
        assert parameters["work_days_target"] == 22
        assert parameters["handoff"]["low_penalty_cap"] == 8
        assert parameters["improvement"]["completed_plan_bonus_cap"] == 2


def test_published_rule_ranges_are_half_open_and_cannot_overlap(client):
    with client.application.app_context():
        db = get_db()
        preparer = _prepare_actor(db, "rule-range")
        approver = _approve_actor(db, "rule-range")

        def create_and_publish(version_code, effective_from, effective_to):
            rule = PerformanceConfigurationService.create_rule_version(
                {
                    "version_code": version_code,
                    "effective_from_month": effective_from,
                    "effective_to_month": effective_to,
                },
                preparer,
                db=db,
            )
            return PerformanceConfigurationService.publish_rule_version(
                rule["id"], approver, expected_row_version=1, db=db
            )

        create_and_publish("rule-range-first", "2026-01", "2026-06")
        adjacent = create_and_publish("rule-range-adjacent", "2026-06", "2026-12")
        assert adjacent["status"] == "published"

        enveloping = PerformanceConfigurationService.create_rule_version(
            {
                "version_code": "rule-range-enveloping",
                "effective_from_month": "2025-01",
                "effective_to_month": "2027-01",
            },
            preparer,
            db=db,
        )
        with pytest.raises(PerformanceConflictError, match="重叠"):
            PerformanceConfigurationService.publish_rule_version(
                enveloping["id"], approver, expected_row_version=1, db=db
            )


def test_position_target_requires_positive_values_and_approved_ranges_do_not_overlap(
    client
):
    with client.application.app_context():
        db = get_db()
        preparer = _prepare_actor(db, "target")
        approver = _approve_actor(db, "target")
        position_id = _position(db, "目标岗位")
        with pytest.raises(ValueError, match="大于 0"):
            PerformanceConfigurationService.create_position_target_version(
                {
                    "position_id": position_id,
                    "target_output_qty": 0,
                    "minimum_effective_work_days": 1,
                    "effective_from_month": "2026-01",
                    "effective_to_month": "2026-06",
                },
                preparer,
                db=db,
            )
        first = PerformanceConfigurationService.create_position_target_version(
            {
                "position_id": position_id,
                "target_output_qty": 100,
                "minimum_effective_work_days": 20,
                "effective_from_month": "2026-01",
                "effective_to_month": "2026-06",
            },
            preparer,
            db=db,
        )
        PerformanceConfigurationService.approve_position_target_version(
            first["id"], approver, expected_row_version=1, db=db
        )
        second = PerformanceConfigurationService.create_position_target_version(
            {
                "position_id": position_id,
                "target_output_qty": 120,
                "minimum_effective_work_days": 21,
                "effective_from_month": "2026-05",
                "effective_to_month": "2026-12",
            },
            preparer,
            db=db,
        )
        with pytest.raises(PerformanceConflictError, match="重叠"):
            PerformanceConfigurationService.approve_position_target_version(
                second["id"], approver, expected_row_version=1, db=db
            )


def test_target_is_time_effective_and_missing_target_never_falls_back(client):
    with client.application.app_context():
        db = get_db()
        preparer = _prepare_actor(db, "lookup")
        approver = _approve_actor(db, "lookup")
        position_id = _position(db, "查询岗位")
        target = PerformanceConfigurationService.create_position_target_version(
            {
                "position_id": position_id,
                "target_output_qty": 80,
                "minimum_effective_work_days": 18,
                "effective_from_month": "2026-03",
                "effective_to_month": "2026-06",
            },
            preparer,
            db=db,
        )
        PerformanceConfigurationService.approve_position_target_version(
            target["id"], approver, expected_row_version=1, db=db
        )
        assert PerformanceConfigurationService.get_position_target(
            position_id, "2026-05", db=db
        )["id"] == target["id"]
        with pytest.raises(NotFoundError, match="目标"):
            PerformanceConfigurationService.get_position_target(
                position_id, "2026-06", db=db
            )
        with pytest.raises(NotFoundError, match="岗位|目标"):
            PerformanceConfigurationService.get_position_target(
                999999, "2026-05", db=db
            )


def test_target_referenced_by_score_cannot_be_updated_or_deleted(client):
    with client.application.app_context():
        db = get_db()
        preparer = _prepare_actor(db, "reference")
        approver = _approve_actor(db, "reference")
        position_id = _position(db, "引用岗位")
        target = PerformanceConfigurationService.create_position_target_version(
            {
                "position_id": position_id,
                "target_output_qty": 90,
                "minimum_effective_work_days": 19,
                "effective_from_month": "2026-01",
                "effective_to_month": "2026-12",
            },
            preparer,
            db=db,
        )
        approved = PerformanceConfigurationService.approve_position_target_version(
            target["id"], approver, expected_row_version=1, db=db
        )
        user_id = db.execute(
            "INSERT INTO users (username,password,name,role,employee_no,status) "
            "VALUES ('target-reference-user','hash','目标引用员工','worker','TARGET-REF','active')"
        ).lastrowid
        batch_id = db.execute(
            "INSERT INTO performance_batches ("
            "production_month,version,period_start,period_end,idempotency_key,status"
            ") VALUES ('2026-02',1,'2026-02-01 07:00:00','2026-03-01 07:00:00',"
            "'test:configuration:reference','draft')"
        ).lastrowid
        db.execute(
            "INSERT INTO performance_score_revisions ("
            "batch_id,user_id,revision,position_target_version_id"
            ") VALUES (?,?,1,?)",
            (batch_id, user_id, approved["id"]),
        )
        db.commit()
        with pytest.raises(PerformanceConflictError, match="引用"):
            PerformanceConfigurationService.update_position_target_version(
                approved["id"],
                {"target_output_qty": 95},
                preparer,
                expected_row_version=2,
                db=db,
            )
        with pytest.raises(PerformanceConflictError, match="引用"):
            PerformanceConfigurationService.delete_position_target_version(
                approved["id"], preparer, db=db
            )


def test_stale_row_version_is_rejected_and_routes_split_prepare_approve_permissions(
    client, auth_headers, worker_auth_headers
):
    with client.application.app_context():
        db = get_db()
        position_id = _position(db, "路由岗位")
        preparer = _prepare_actor(db, "route")
        created = PerformanceConfigurationService.create_position_target_version(
            {
                "position_id": position_id,
                "target_output_qty": 100,
                "minimum_effective_work_days": 20,
                "effective_from_month": "2026-01",
                "effective_to_month": "2026-12",
            },
            preparer,
            db=db,
        )
        with pytest.raises(PerformanceConflictError, match="版本"):
            PerformanceConfigurationService.update_position_target_version(
                created["id"],
                {"target_output_qty": 101},
                preparer,
                expected_row_version=99,
                db=db,
            )

    denied = client.post(
        "/api/performance/position-target-versions",
        json={
            "position_id": position_id,
            "target_output_qty": 100,
            "minimum_effective_work_days": 20,
            "effective_from_month": "2026-01",
            "effective_to_month": "2026-12",
        },
        headers=worker_auth_headers,
    )
    assert denied.status_code == 403

    allowed = client.post(
        "/api/performance/position-target-versions",
        json={
            "position_id": position_id,
            "target_output_qty": 100,
            "minimum_effective_work_days": 20,
            "effective_from_month": "2027-01",
            "effective_to_month": "2027-12",
        },
        headers=auth_headers,
    )
    assert allowed.status_code == 201, allowed.get_json()
    target_id = allowed.get_json()["id"]
    approved_without_version = client.post(
        f"/api/performance/position-target-versions/{target_id}/approve",
        json={"row_version": 1},
        headers=worker_auth_headers,
    )
    assert approved_without_version.status_code == 403
