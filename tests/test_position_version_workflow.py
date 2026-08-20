import json
import uuid

import pytest

from factories import TEST_HASH
from modules.db import get_db
from modules.domain.errors import ValidationError
from modules.domain.position_versioning import (
    PositionApprovalSeparationError,
    PositionImpactChangedError,
    PositionProcessInvalidError,
    PositionReferenceConflictError,
    PositionVersionAlreadyOpenError,
    PositionVersionImmutableError,
    PositionVersionStaleError,
)
from modules.repositories.performance_assignment_repository import (
    PerformanceAssignmentRepository,
)
from modules.repositories.position_version_repository import PositionVersionRepository
from modules.services.position_audit_service import PositionAuditService
from modules.services.position_snapshot_service import PositionSnapshotService
from modules.services.position_version_service import PositionVersionService
from tests.test_process_version_workflow import _actors, _create_process, _publish


def _published_process(client, preparer, approver, name="岗位关联工序"):
    created = _create_process(client, preparer, name)
    published = _publish(
        client, created["version"]["id"], preparer, approver
    )
    return created, published


def _create_position(client, preparer, process_ids, name="版本化岗位"):
    with client.application.app_context():
        return PositionVersionService.create_position(
            {
                "name": f"{name}-{uuid.uuid4().hex[:8]}",
                "description": "V1 草稿",
                "process_ids": list(process_ids),
                "idempotency_key": f"create-position-{uuid.uuid4().hex}",
            },
            preparer,
            "position-create-request",
        )


def _publish_position(client, version_id, preparer, approver):
    with client.application.app_context():
        current = PositionVersionService.get_version(version_id)
        submitted = PositionVersionService.submit(
            version_id,
            {
                "row_version": current["row_version"],
                "idempotency_key": f"submit-position-{uuid.uuid4().hex}",
            },
            preparer,
        )
        return PositionVersionService.approve(
            version_id,
            {
                "row_version": submitted["row_version"],
                "idempotency_key": f"approve-position-{uuid.uuid4().hex}",
            },
            approver,
        )


def _create_assignment(db, position, version):
    suffix = uuid.uuid4().hex[:8]
    user_id = db.execute(
        "INSERT INTO users(username,password,name,role,employee_no,status,position_id) "
        "VALUES (?,?,?,?,?,'active',?)",
        (
            f"position-worker-{suffix}",
            TEST_HASH,
            "岗位快照员工",
            "worker",
            f"POSITION-{suffix}",
            position["id"],
        ),
    ).lastrowid
    PerformanceAssignmentRepository.create_assignment(
        {
            "user_id": user_id,
            "employee_name_snapshot": "岗位快照员工",
            "employee_no_snapshot": f"POSITION-{suffix}",
            "position_id": position["id"],
            "position_version_id": version["id"],
            "position_name_snapshot": version["name"],
            "department_id": None,
            "department_name_snapshot": "",
            "valid_from": "2026-08-01 07:00:00",
            "valid_to": "",
            "source_type": "test",
            "source_key": f"position-assignment-{suffix}",
        },
        db=db,
    )
    db.commit()
    return user_id


def _revision(client, position_id, preparer, **changes):
    with client.application.app_context():
        return PositionVersionService.create_revision(
            position_id,
            {
                "revision_reason": "岗位修订测试",
                "idempotency_key": f"position-revision-{uuid.uuid4().hex}",
                **changes,
            },
            preparer,
        )


def test_new_position_is_v1_draft_then_publish_projects_and_records_evidence(client):
    preparer, approver = _actors(client)
    _, process = _published_process(client, preparer, approver)
    created = _create_position(client, preparer, [process["process_id"]])

    assert created["version"]["version"] == 1
    assert created["version"]["status"] == "draft"
    assert created["root"]["status"] == "inactive"
    assert created["root"]["current_effective_version_id"] is None

    with client.application.app_context():
        with pytest.raises(PositionReferenceConflictError, match="尚无已发布版本"):
            PositionVersionService.resolve_current_for_business(created["root"]["id"])

    published = _publish_position(
        client, created["version"]["id"], preparer, approver
    )
    with client.application.app_context():
        db = get_db()
        root = PositionVersionRepository.root(created["root"]["id"])
        projected_processes = [
            row["process_id"]
            for row in db.execute(
                "SELECT process_id FROM position_processes WHERE position_id=? "
                "ORDER BY id",
                (root["id"],),
            ).fetchall()
        ]
        events = PositionVersionRepository.list_events(root["id"])
        audit = db.execute(
            "SELECT * FROM audit_logs WHERE action='position_version_approve' "
            "AND target_id=?",
            (root["id"],),
        ).fetchone()
        resolved = PositionVersionService.resolve_current_for_business(root["id"])

    assert published["status"] == "published"
    assert root["status"] == "active"
    assert root["current_effective_version_id"] == published["id"]
    assert root["name"] == published["name"]
    assert projected_processes == [process["process_id"]]
    assert {event["event_type"] for event in events} >= {
        "created",
        "submitted",
        "approved",
        "published",
    }
    assert audit["mandatory"] == 1
    assert json.loads(audit["detail"])["position_version_id"] == published["id"]
    assert resolved["id"] == published["id"]


def test_position_creation_and_command_replays_are_idempotent(client):
    preparer, approver = _actors(client)
    _, process = _published_process(client, preparer, approver)
    command = {
        "name": f"幂等岗位-{uuid.uuid4().hex[:8]}",
        "description": "初始描述",
        "process_ids": [process["process_id"]],
        "idempotency_key": f"position-create-replay-{uuid.uuid4().hex}",
    }
    with client.application.app_context():
        first = PositionVersionService.create_position(command, preparer)
        replay = PositionVersionService.create_position(command, preparer)
        updated = PositionVersionService.update_draft(
            first["version"]["id"],
            {
                "description": "幂等更新",
                "row_version": first["version"]["row_version"],
                "idempotency_key": "position-update-replay",
            },
            preparer,
        )
        update_replay = PositionVersionService.update_draft(
            first["version"]["id"],
            {
                "description": "不会覆盖第一次结果",
                "row_version": first["version"]["row_version"],
                "idempotency_key": "position-update-replay",
            },
            preparer,
        )
        submitted = PositionVersionService.submit(
            first["version"]["id"],
            {
                "row_version": updated["row_version"],
                "idempotency_key": "position-submit-replay",
            },
            preparer,
        )
        submit_replay = PositionVersionService.submit(
            first["version"]["id"],
            {
                "row_version": updated["row_version"],
                "idempotency_key": "position-submit-replay",
            },
            preparer,
        )
        db = get_db()
        root_count = db.execute(
            "SELECT COUNT(*) FROM positions WHERE name=?", (command["name"],)
        ).fetchone()[0]

    assert replay["root"]["id"] == first["root"]["id"]
    assert replay["version"]["id"] == first["version"]["id"]
    assert update_replay["id"] == updated["id"]
    assert update_replay["description"] == "幂等更新"
    assert submit_replay["id"] == submitted["id"]
    assert submit_replay["status"] == "pending_approval"
    assert root_count == 1


def test_revision_requires_reason_copies_current_and_allows_only_one_open(client):
    preparer, approver = _actors(client)
    _, process = _published_process(client, preparer, approver)
    created = _create_position(client, preparer, [process["process_id"]])
    published = _publish_position(
        client, created["version"]["id"], preparer, approver
    )

    with client.application.app_context():
        with pytest.raises(ValidationError, match="修订原因不能为空"):
            PositionVersionService.create_revision(
                created["root"]["id"],
                {"revision_reason": "", "idempotency_key": "blank-position-reason"},
                preparer,
            )
        revision = PositionVersionService.create_revision(
            created["root"]["id"],
            {
                "description": "V2 描述",
                "revision_reason": "补充岗位描述",
                "idempotency_key": f"position-v2-{uuid.uuid4().hex}",
            },
            preparer,
        )
        with pytest.raises(PositionVersionAlreadyOpenError):
            PositionVersionService.create_revision(
                created["root"]["id"],
                {
                    "revision_reason": "重复开放版本",
                    "idempotency_key": f"position-v3-{uuid.uuid4().hex}",
                },
                preparer,
            )

    assert revision["version"] == 2
    assert revision["name"] == published["name"]
    assert revision["process_ids"] == [process["process_id"]]
    assert revision["supersedes_version_id"] == published["id"]
    assert revision["description"] == "V2 描述"


def test_position_rejects_unpublished_retired_processes_and_root_meaning_change(client):
    preparer, approver = _actors(client)
    draft_process = _create_process(client, preparer, "岗位未发布工序")
    with client.application.app_context():
        with pytest.raises(PositionProcessInvalidError):
            PositionVersionService.create_position(
                {
                    "name": f"非法岗位-{uuid.uuid4().hex[:8]}",
                    "process_ids": [draft_process["root"]["id"]],
                    "idempotency_key": f"invalid-position-{uuid.uuid4().hex}",
                },
                preparer,
            )

    _, process = _published_process(client, preparer, approver, "岗位退休工序")
    with client.application.app_context():
        db = get_db()
        db.execute(
            "UPDATE processes SET status='inactive',lifecycle_status='retired' "
            "WHERE id=?",
            (process["process_id"],),
        )
        db.commit()
        with pytest.raises(PositionProcessInvalidError):
            PositionVersionService.create_position(
                {
                    "name": f"退休工序岗位-{uuid.uuid4().hex[:8]}",
                    "process_ids": [process["process_id"]],
                    "idempotency_key": f"retired-position-{uuid.uuid4().hex}",
                },
                preparer,
            )

    _, active_process = _published_process(client, preparer, approver, "岗位有效工序")
    created = _create_position(client, preparer, [active_process["process_id"]])
    with client.application.app_context():
        with pytest.raises(PositionReferenceConflictError, match="必须创建新的岗位根实体"):
            PositionVersionService.update_draft(
                created["version"]["id"],
                {
                    "name": "职责已经根本改变",
                    "responsibility_changed": True,
                    "row_version": created["version"]["row_version"],
                    "idempotency_key": "position-identity-change",
                },
                preparer,
            )


def test_draft_update_uses_optimistic_row_version(client):
    preparer, approver = _actors(client)
    _, process = _published_process(client, preparer, approver)
    created = _create_position(client, preparer, [process["process_id"]])

    with client.application.app_context():
        updated = PositionVersionService.update_draft(
            created["version"]["id"],
            {
                "description": "并发后的描述",
                "row_version": created["version"]["row_version"],
                "idempotency_key": "position-optimistic-update-1",
            },
            preparer,
        )
        with pytest.raises(PositionVersionStaleError):
            PositionVersionService.update_draft(
                created["version"]["id"],
                {
                    "description": "过期写入",
                    "row_version": created["version"]["row_version"],
                    "idempotency_key": "position-optimistic-update-2",
                },
                preparer,
            )

    assert updated["row_version"] == created["version"]["row_version"] + 1


def test_approval_requires_different_user_and_unchanged_impact(client):
    preparer, approver = _actors(client)
    _, process = _published_process(client, preparer, approver)
    created = _create_position(client, preparer, [process["process_id"]])

    with client.application.app_context():
        submitted = PositionVersionService.submit(
            created["version"]["id"],
            {
                "row_version": created["version"]["row_version"],
                "idempotency_key": "position-approval-submit",
            },
            preparer,
        )
        with pytest.raises(PositionApprovalSeparationError):
            PositionVersionService.approve(
                submitted["id"],
                {
                    "row_version": submitted["row_version"],
                    "idempotency_key": "position-self-approval",
                },
                preparer,
            )
        db = get_db()
        suffix = uuid.uuid4().hex[:8]
        db.execute(
            "INSERT INTO users(username,password,name,role,employee_no,status,position_id) "
            "VALUES (?,?,?,?,?,'active',?)",
            (
                f"impact-worker-{suffix}",
                TEST_HASH,
                "影响范围员工",
                "worker",
                f"IMPACT-{suffix}",
                created["root"]["id"],
            ),
        )
        db.commit()
        with pytest.raises(PositionImpactChangedError):
            PositionVersionService.approve(
                submitted["id"],
                {
                    "row_version": submitted["row_version"],
                    "idempotency_key": "position-impact-drift",
                },
                approver,
            )
        status_after_drift = PositionVersionService.get_version(submitted["id"])[
            "status"
        ]

    assert status_after_drift == "pending_approval"


def test_new_publication_supersedes_prior_and_splits_snapshot_only_for_name(client):
    preparer, approver = _actors(client)
    _, process = _published_process(client, preparer, approver)
    created = _create_position(client, preparer, [process["process_id"]])
    first = _publish_position(
        client, created["version"]["id"], preparer, approver
    )
    with client.application.app_context():
        db = get_db()
        user_id = _create_assignment(db, created["root"], first)

    renamed = _revision(
        client,
        created["root"]["id"],
        preparer,
        name=f"修订岗位-{uuid.uuid4().hex[:8]}",
    )
    second = _publish_position(client, renamed["id"], preparer, approver)

    with client.application.app_context():
        first_after = PositionVersionRepository.version(first["id"])
        rows_after_name = PerformanceAssignmentRepository.list_for_user(user_id)
    assert first_after["status"] == "superseded"
    assert first_after["effective_to"] == second["effective_from"]
    assert [row["position_version_id"] for row in rows_after_name] == [
        first["id"],
        second["id"],
    ]
    assert rows_after_name[0]["valid_to"] == rows_after_name[1]["valid_from"]

    description_revision = _revision(
        client,
        created["root"]["id"],
        preparer,
        description="仅修改岗位说明",
    )
    third = _publish_position(
        client, description_revision["id"], preparer, approver
    )
    with client.application.app_context():
        rows_after_description = PerformanceAssignmentRepository.list_for_user(user_id)
        root = PositionVersionRepository.root(created["root"]["id"])
        second_after = PositionVersionRepository.version(second["id"])

    assert second["status"] == "published"
    assert second_after["status"] == "superseded"
    assert len(rows_after_description) == 2
    assert rows_after_description[-1]["position_version_id"] == second["id"]
    assert root["current_effective_version_id"] == third["id"]


def test_approve_replay_writes_one_published_event_and_one_audit(client):
    preparer, approver = _actors(client)
    _, process = _published_process(client, preparer, approver)
    created = _create_position(client, preparer, [process["process_id"]])

    with client.application.app_context():
        submitted = PositionVersionService.submit(
            created["version"]["id"],
            {
                "row_version": created["version"]["row_version"],
                "idempotency_key": "position-idempotent-submit",
            },
            preparer,
        )
        command = {
            "row_version": submitted["row_version"],
            "idempotency_key": "position-idempotent-approve",
        }
        first = PositionVersionService.approve(submitted["id"], command, approver)
        replay = PositionVersionService.approve(submitted["id"], command, approver)
        db = get_db()
        event_count = db.execute(
            "SELECT COUNT(*) FROM position_version_events WHERE idempotency_key=?",
            (command["idempotency_key"],),
        ).fetchone()[0]
        audit_count = db.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE action='position_version_approve' "
            "AND target_id=?",
            (created["root"]["id"],),
        ).fetchone()[0]

    assert replay["id"] == first["id"]
    assert event_count == 1
    assert audit_count == 1


@pytest.mark.parametrize("failure_point", ["projection", "snapshot", "audit"])
def test_publish_failure_rolls_back_supersede_projection_snapshot_and_events(
    client, monkeypatch, failure_point
):
    preparer, approver = _actors(client)
    _, process = _published_process(client, preparer, approver)
    created = _create_position(client, preparer, [process["process_id"]])
    first = _publish_position(
        client, created["version"]["id"], preparer, approver
    )
    with client.application.app_context():
        db = get_db()
        user_id = _create_assignment(db, created["root"], first)

    revision = _revision(
        client,
        created["root"]["id"],
        preparer,
        name=f"回滚岗位-{uuid.uuid4().hex[:8]}",
    )
    with client.application.app_context():
        submitted = PositionVersionService.submit(
            revision["id"],
            {
                "row_version": revision["row_version"],
                "idempotency_key": f"rollback-submit-{failure_point}",
            },
            preparer,
        )

        def fail(*args, **kwargs):
            raise RuntimeError(f"{failure_point} failed")

        if failure_point == "projection":
            monkeypatch.setattr(
                PositionVersionRepository, "update_compatibility_projection", fail
            )
        elif failure_point == "snapshot":
            monkeypatch.setattr(PositionSnapshotService, "apply_published_name", fail)
        else:
            monkeypatch.setattr(PositionAuditService, "_insert", fail)

        approval_key = f"rollback-approve-{failure_point}"
        with pytest.raises(RuntimeError, match=f"{failure_point} failed"):
            PositionVersionService.approve(
                submitted["id"],
                {
                    "row_version": submitted["row_version"],
                    "idempotency_key": approval_key,
                },
                approver,
            )

        root = PositionVersionRepository.root(created["root"]["id"])
        first_after = PositionVersionRepository.version(first["id"])
        revision_after = PositionVersionRepository.version(revision["id"])
        assignments = PerformanceAssignmentRepository.list_for_user(user_id)
        event_count = get_db().execute(
            "SELECT COUNT(*) FROM position_version_events "
            "WHERE idempotency_key LIKE ?",
            (approval_key + "%",),
        ).fetchone()[0]

    assert root["current_effective_version_id"] == first["id"]
    assert root["name"] == first["name"]
    assert first_after["status"] == "published"
    assert first_after["effective_to"] == ""
    assert revision_after["status"] == "pending_approval"
    assert len(assignments) == 1
    assert assignments[0]["position_version_id"] == first["id"]
    assert event_count == 0


def test_reject_and_cancel_are_terminal_and_audited(client):
    preparer, approver = _actors(client)
    _, process = _published_process(client, preparer, approver)
    cancelled_position = _create_position(
        client, preparer, [process["process_id"]], "待取消岗位"
    )
    rejected_position = _create_position(
        client, preparer, [process["process_id"]], "待驳回岗位"
    )

    with client.application.app_context():
        cancelled = PositionVersionService.cancel(
            cancelled_position["version"]["id"],
            {
                "row_version": cancelled_position["version"]["row_version"],
                "reason": "不再创建",
                "idempotency_key": "position-cancel-terminal",
            },
            preparer,
        )
        submitted = PositionVersionService.submit(
            rejected_position["version"]["id"],
            {
                "row_version": rejected_position["version"]["row_version"],
                "idempotency_key": "position-reject-submit",
            },
            preparer,
        )
        rejected = PositionVersionService.reject(
            submitted["id"],
            {
                "row_version": submitted["row_version"],
                "reason": "资料不完整",
                "idempotency_key": "position-reject-terminal",
            },
            approver,
        )
        with pytest.raises(PositionVersionImmutableError):
            PositionVersionService.submit(
                cancelled["id"],
                {
                    "row_version": cancelled["row_version"],
                    "idempotency_key": "position-cancelled-resubmit",
                },
                preparer,
            )
        db = get_db()
        audit_actions = {
            row["action"]
            for row in db.execute(
                "SELECT action FROM audit_logs WHERE target_id IN (?,?)",
                (
                    cancelled_position["root"]["id"],
                    rejected_position["root"]["id"],
                ),
            ).fetchall()
        }

    assert cancelled["status"] == "cancelled"
    assert rejected["status"] == "rejected"
    assert "position_version_cancelled" in audit_actions
    assert "position_version_rejected" in audit_actions
