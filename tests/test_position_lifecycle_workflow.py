import uuid

import pytest

from factories import TEST_HASH
from modules.db import get_db
from modules.domain.position_versioning import (
    PositionActiveEmployeesError,
    PositionActiveSessionsError,
    PositionApprovalSeparationError,
    PositionImpactChangedError,
    PositionNotFoundError,
    PositionReferenceConflictError,
    PositionVersionAlreadyOpenError,
)
from modules.repositories.position_version_repository import PositionVersionRepository
from modules.services.position_audit_service import PositionAuditService
from modules.services.position_lifecycle_service import PositionLifecycleService
from modules.services.position_version_service import PositionVersionService
from tests.test_position_version_workflow import (
    _actors,
    _create_position,
    _publish_position,
    _published_process,
    _revision,
)


def _published_position(client, preparer, approver, name="生命周期岗位"):
    _, process = _published_process(
        client, preparer, approver, f"{name}工序"
    )
    created = _create_position(
        client, preparer, [process["process_id"]], name
    )
    published = _publish_position(
        client, created["version"]["id"], preparer, approver
    )
    return created, published


def _request_retirement(client, position_id, preparer, key=None):
    with client.application.app_context():
        root = PositionVersionRepository.root(position_id)
        return PositionLifecycleService.request_retirement(
            position_id,
            {
                "row_version": root["row_version"],
                "lifecycle_reason": "岗位停止使用",
                "idempotency_key": key or f"retire-position-{uuid.uuid4().hex}",
            },
            preparer,
        )


def _approve_lifecycle(client, lifecycle, approver, key=None):
    with client.application.app_context():
        return PositionLifecycleService.approve_request(
            lifecycle["id"],
            {
                "row_version": lifecycle["row_version"],
                "idempotency_key": key or f"approve-lifecycle-{uuid.uuid4().hex}",
            },
            approver,
        )


def _employee(db, position_id, status="active"):
    suffix = uuid.uuid4().hex[:8]
    return db.execute(
        "INSERT INTO users(username,password,name,role,employee_no,status,position_id) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            f"lifecycle-worker-{suffix}",
            TEST_HASH,
            "生命周期员工",
            "worker",
            f"LIFECYCLE-{suffix}",
            status,
            position_id,
        ),
    ).lastrowid


def test_retirement_approval_blocks_active_employee_without_partial_changes(client):
    preparer, approver = _actors(client)
    created, published = _published_position(client, preparer, approver)
    with client.application.app_context():
        db = get_db()
        _employee(db, created["root"]["id"], "active")
        db.commit()
    lifecycle = _request_retirement(client, created["root"]["id"], preparer)

    with client.application.app_context():
        with pytest.raises(PositionActiveEmployeesError):
            PositionLifecycleService.approve_request(
                lifecycle["id"],
                {
                    "row_version": lifecycle["row_version"],
                    "idempotency_key": "retirement-active-employee",
                },
                approver,
            )
        root = PositionVersionRepository.root(created["root"]["id"])
        version = PositionVersionRepository.version(published["id"])
        request = PositionVersionRepository.lifecycle_request(lifecycle["id"])

    assert root["lifecycle_status"] == "active"
    assert root["status"] == "active"
    assert version["status"] == "published"
    assert request["status"] == "pending"


def test_retirement_approval_blocks_active_session(client):
    preparer, approver = _actors(client)
    created, published = _published_position(
        client, preparer, approver, "会话阻断岗位"
    )
    with client.application.app_context():
        db = get_db()
        user_id = _employee(db, None, "inactive")
        db.execute(
            "INSERT INTO user_sessions(user_id,token,is_active,active_position_id) "
            "VALUES (?,?,1,?)",
            (
                user_id,
                f"position-session-{uuid.uuid4().hex}",
                created["root"]["id"],
            ),
        )
        db.commit()
    lifecycle = _request_retirement(client, created["root"]["id"], preparer)

    with client.application.app_context():
        with pytest.raises(PositionActiveSessionsError):
            PositionLifecycleService.approve_request(
                lifecycle["id"],
                {
                    "row_version": lifecycle["row_version"],
                    "idempotency_key": "retirement-active-session",
                },
                approver,
            )
        assert PositionVersionRepository.version(published["id"])["status"] == "published"


def test_retirement_rechecks_impact_digest(client):
    preparer, approver = _actors(client)
    created, _ = _published_position(client, preparer, approver, "影响漂移岗位")
    lifecycle = _request_retirement(client, created["root"]["id"], preparer)

    with client.application.app_context():
        db = get_db()
        _employee(db, created["root"]["id"], "inactive")
        db.commit()
        with pytest.raises(PositionImpactChangedError):
            PositionLifecycleService.approve_request(
                lifecycle["id"],
                {
                    "row_version": lifecycle["row_version"],
                    "idempotency_key": "retirement-impact-drift",
                },
                approver,
            )


def test_retirement_requires_two_people_and_is_idempotent_audited(client):
    preparer, approver = _actors(client)
    created, published = _published_position(client, preparer, approver)
    lifecycle = _request_retirement(client, created["root"]["id"], preparer)

    with client.application.app_context():
        with pytest.raises(PositionApprovalSeparationError):
            PositionLifecycleService.approve_request(
                lifecycle["id"],
                {
                    "row_version": lifecycle["row_version"],
                    "idempotency_key": "retirement-self-approval",
                },
                preparer,
            )
        command = {
            "row_version": lifecycle["row_version"],
            "idempotency_key": "retirement-approved-once",
        }
        approved = PositionLifecycleService.approve_request(
            lifecycle["id"], command, approver, "retirement-request-id"
        )
        replay = PositionLifecycleService.approve_request(
            lifecycle["id"], command, approver, "retirement-request-id"
        )
        db = get_db()
        root = PositionVersionRepository.root(created["root"]["id"])
        version = PositionVersionRepository.version(published["id"])
        event_count = db.execute(
            "SELECT COUNT(*) FROM position_version_events WHERE idempotency_key=?",
            (command["idempotency_key"],),
        ).fetchone()[0]
        audit_count = db.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE action='position_retired' "
            "AND target_id=?",
            (root["id"],),
        ).fetchone()[0]

    assert approved["status"] == replay["status"] == "approved"
    assert root["lifecycle_status"] == "retired"
    assert root["status"] == "inactive"
    assert root["retired_at"]
    assert version["status"] == "retired"
    assert version["effective_to"] == root["retired_at"]
    assert event_count == 1
    assert audit_count == 1


def test_only_one_pending_lifecycle_request_and_request_replay(client):
    preparer, approver = _actors(client)
    created, _ = _published_position(client, preparer, approver, "单一申请岗位")
    key = f"retirement-request-replay-{uuid.uuid4().hex}"
    first = _request_retirement(client, created["root"]["id"], preparer, key)
    replay = _request_retirement(client, created["root"]["id"], preparer, key)

    with client.application.app_context():
        root = PositionVersionRepository.root(created["root"]["id"])
        with pytest.raises(PositionVersionAlreadyOpenError):
            PositionLifecycleService.request_retirement(
                root["id"],
                {
                    "row_version": root["row_version"],
                    "reason": "重复申请",
                    "idempotency_key": f"retirement-duplicate-{uuid.uuid4().hex}",
                },
                preparer,
            )

    assert replay["id"] == first["id"]


def test_reactivation_requires_new_published_revision_after_retirement(client):
    preparer, approver = _actors(client)
    created, first = _published_position(client, preparer, approver, "重新启用岗位")
    retirement = _request_retirement(client, created["root"]["id"], preparer)
    _approve_lifecycle(client, retirement, approver)

    with client.application.app_context():
        root = PositionVersionRepository.root(created["root"]["id"])
        with pytest.raises(PositionReferenceConflictError, match="新岗位修订版"):
            PositionLifecycleService.request_reactivation(
                root["id"],
                {
                    "row_version": root["row_version"],
                    "reason": "恢复生产",
                    "idempotency_key": "reactivation-without-revision",
                },
                preparer,
            )

    revision = _revision(
        client,
        created["root"]["id"],
        preparer,
        description="重新启用前完成岗位复核",
    )
    second = _publish_position(client, revision["id"], preparer, approver)
    with client.application.app_context():
        retired_root = PositionVersionRepository.root(created["root"]["id"])
        assert retired_root["lifecycle_status"] == "retired"
        assert retired_root["status"] == "inactive"
        request = PositionLifecycleService.request_reactivation(
            retired_root["id"],
            {
                "row_version": retired_root["row_version"],
                "reason": "新修订版复核通过",
                "idempotency_key": "reactivation-request",
            },
            preparer,
        )
        approved = PositionLifecycleService.approve_request(
            request["id"],
            {
                "row_version": request["row_version"],
                "idempotency_key": "reactivation-approve",
            },
            approver,
        )
        root = PositionVersionRepository.root(created["root"]["id"])
        first_after = PositionVersionRepository.version(first["id"])
        second_after = PositionVersionRepository.version(second["id"])
        event = PositionVersionRepository.event_by_idempotency_key(
            "reactivation-approve"
        )

    assert approved["status"] == "approved"
    assert root["lifecycle_status"] == "active"
    assert root["status"] == "active"
    assert root["retired_at"] == ""
    assert root["current_effective_version_id"] == second["id"]
    assert first_after["status"] == "retired"
    assert second_after["status"] == "published"
    assert event["event_type"] == "reactivated"


def test_lifecycle_rejection_is_terminal_and_audited(client):
    preparer, approver = _actors(client)
    created, _ = _published_position(client, preparer, approver, "驳回退休岗位")
    lifecycle = _request_retirement(client, created["root"]["id"], preparer)

    with client.application.app_context():
        rejected = PositionLifecycleService.reject_request(
            lifecycle["id"],
            {
                "row_version": lifecycle["row_version"],
                "reason": "退休依据不足",
                "idempotency_key": "retirement-rejected",
            },
            approver,
        )
        with pytest.raises(PositionReferenceConflictError, match="已处理"):
            PositionLifecycleService.approve_request(
                lifecycle["id"],
                {
                    "row_version": rejected["row_version"],
                    "idempotency_key": "rejected-request-approve",
                },
                approver,
            )
        db = get_db()
        audit = db.execute(
            "SELECT mandatory FROM audit_logs "
            "WHERE action='position_lifecycle_rejected' AND target_id=?",
            (created["root"]["id"],),
        ).fetchone()

    assert rejected["status"] == "rejected"
    assert audit["mandatory"] == 1


def test_retirement_audit_failure_rolls_back_entire_approval(client, monkeypatch):
    preparer, approver = _actors(client)
    created, published = _published_position(client, preparer, approver, "审计回滚岗位")
    lifecycle = _request_retirement(client, created["root"]["id"], preparer)

    def fail(*args, **kwargs):
        raise RuntimeError("lifecycle audit failed")

    with client.application.app_context():
        monkeypatch.setattr(PositionAuditService, "_insert", fail)
        with pytest.raises(RuntimeError, match="lifecycle audit failed"):
            PositionLifecycleService.approve_request(
                lifecycle["id"],
                {
                    "row_version": lifecycle["row_version"],
                    "idempotency_key": "retirement-audit-failure",
                },
                approver,
            )
        db = get_db()
        root = PositionVersionRepository.root(created["root"]["id"])
        version = PositionVersionRepository.version(published["id"])
        request = PositionVersionRepository.lifecycle_request(lifecycle["id"])
        event_count = db.execute(
            "SELECT COUNT(*) FROM position_version_events WHERE idempotency_key=?",
            ("retirement-audit-failure",),
        ).fetchone()[0]

    assert root["lifecycle_status"] == "active"
    assert root["status"] == "active"
    assert root["retired_at"] == ""
    assert version["status"] == "published"
    assert version["effective_to"] == ""
    assert request["status"] == "pending"
    assert event_count == 0


def test_list_requests_validates_position_and_returns_history(client):
    preparer, approver = _actors(client)
    created, _ = _published_position(client, preparer, approver, "申请历史岗位")
    lifecycle = _request_retirement(client, created["root"]["id"], preparer)

    with client.application.app_context():
        listed = PositionLifecycleService.list_requests(created["root"]["id"])
        with pytest.raises(PositionNotFoundError, match="岗位不存在"):
            PositionLifecycleService.list_requests(99999999)

    assert [item["id"] for item in listed] == [lifecycle["id"]]
