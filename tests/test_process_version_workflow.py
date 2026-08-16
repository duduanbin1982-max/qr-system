import uuid

import pytest

from factories import TEST_HASH
from modules.db import get_db
from modules.domain.errors import ConflictError, ValidationError
from modules.domain.process_versioning import ApprovalSeparationError
from modules.repositories.process_version_repository import ProcessVersionRepository
from modules.services.master_data_lifecycle_service import MasterDataLifecycleService
from modules.services.process_version_service import ProcessVersionService


def _actors(client):
    with client.application.app_context():
        db = get_db()
        suffix = uuid.uuid4().hex[:8]
        actors = []
        for index, name in enumerate(("工序制单人", "工序批准人"), start=1):
            user_id = db.execute(
                "INSERT INTO users (username,password,name,role,employee_no,status,"
                "password_version,must_change_password) "
                "VALUES (?,?,?,'worker',?,'active',2,0)",
                (f"process-v-{suffix}-{index}", TEST_HASH, name, f"PV-{suffix}-{index}"),
            ).lastrowid
            actors.append({"id": user_id, "name": name, "role": "process_version_user"})
        db.commit()
        return actors


def _create_process(client, actor, name="版本化车削"):
    with client.application.app_context():
        return ProcessVersionService.create_process(
            {
                "name": f"{name}-{uuid.uuid4().hex[:6]}",
                "category": "机加工",
                "description": "V1 草稿",
                "seq_order": 10,
                "idempotency_key": f"create-process-{uuid.uuid4().hex}",
            },
            actor,
        )


def _publish(client, version_id, preparer, approver):
    with client.application.app_context():
        current = ProcessVersionService.get_version(version_id)
        submitted = ProcessVersionService.submit(
            version_id,
            {
                "row_version": current["row_version"],
                "idempotency_key": f"submit-process-{uuid.uuid4().hex}",
            },
            preparer,
        )
        return ProcessVersionService.approve(
            version_id,
            {
                "row_version": submitted["row_version"],
                "idempotency_key": f"approve-process-{uuid.uuid4().hex}",
            },
            approver,
        )


def test_new_process_is_v1_draft_and_unavailable_until_published(client):
    preparer, approver = _actors(client)
    created = _create_process(client, preparer)

    assert created["version"]["version"] == 1
    assert created["version"]["status"] == "draft"
    assert created["root"]["current_effective_version_id"] is None
    assert created["root"]["status"] == "inactive"

    with client.application.app_context():
        with pytest.raises(ConflictError, match="尚无已发布版本"):
            ProcessVersionService.resolve_current_for_business(created["root"]["id"])

    published = _publish(client, created["version"]["id"], preparer, approver)
    assert published["status"] == "published"
    with client.application.app_context():
        resolved = ProcessVersionService.resolve_current_for_business(
            created["root"]["id"]
        )
        root = ProcessVersionRepository.root(created["root"]["id"])
    assert resolved["id"] == published["id"]
    assert root["name"] == published["name"]
    assert root["current_effective_version_id"] == published["id"]


def test_revision_copies_current_content_requires_reason_and_blocks_second_open_revision(client):
    preparer, approver = _actors(client)
    created = _create_process(client, preparer)
    _publish(client, created["version"]["id"], preparer, approver)

    with client.application.app_context():
        with pytest.raises(ValidationError, match="修订原因不能为空"):
            ProcessVersionService.create_revision(
                created["root"]["id"],
                {"revision_reason": "", "idempotency_key": "blank-process-reason"},
                preparer,
            )
        revision = ProcessVersionService.create_revision(
            created["root"]["id"],
            {
                "name": "精密车削",
                "revision_reason": "提高加工精度",
                "idempotency_key": f"process-revision-{uuid.uuid4().hex}",
            },
            preparer,
        )
        with pytest.raises(ConflictError, match="已有草稿或待审批修订版"):
            ProcessVersionService.create_revision(
                created["root"]["id"],
                {
                    "revision_reason": "重复草稿",
                    "idempotency_key": f"process-revision-{uuid.uuid4().hex}",
                },
                preparer,
            )

    assert revision["version"] == 2
    assert revision["name"] == "精密车削"
    assert revision["category"] == "机加工"
    assert revision["supersedes_version_id"] == created["version"]["id"]
    assert revision["effective_from"] == ""
    assert revision["approved_by"] is None
    assert revision["approved_by_name"] == ""


def test_process_approval_rejects_impact_drift_and_same_user(client):
    preparer, approver = _actors(client)
    created = _create_process(client, preparer)
    with client.application.app_context():
        submitted = ProcessVersionService.submit(
            created["version"]["id"],
            {
                "row_version": 0,
                "idempotency_key": f"submit-process-{uuid.uuid4().hex}",
            },
            preparer,
        )
        with pytest.raises(ApprovalSeparationError):
            ProcessVersionService.approve(
                submitted["id"],
                {
                    "row_version": submitted["row_version"],
                    "idempotency_key": f"approve-process-{uuid.uuid4().hex}",
                },
                preparer,
            )

        db = get_db()
        db.execute(
            "INSERT INTO approval_config "
            "(process_id,require_approval,approver_role,approval_level) "
            "VALUES (?,1,'admin',1)",
            (created["root"]["id"],),
        )
        db.commit()
        with pytest.raises(ConflictError, match="影响范围已变化") as error:
            ProcessVersionService.approve(
                submitted["id"],
                {
                    "row_version": submitted["row_version"],
                    "idempotency_key": f"approve-process-{uuid.uuid4().hex}",
                },
                approver,
            )
        assert error.value.details["submitted_impact_digest"] != error.value.details[
            "current_impact_digest"
        ]


def test_process_publish_supersedes_old_version_and_idempotent_retry_writes_one_event(client):
    preparer, approver = _actors(client)
    created = _create_process(client, preparer)
    _publish(client, created["version"]["id"], preparer, approver)
    with client.application.app_context():
        revision = ProcessVersionService.create_revision(
            created["root"]["id"],
            {
                "name": "车削 V2",
                "revision_reason": "更新工艺参数",
                "idempotency_key": f"process-revision-{uuid.uuid4().hex}",
            },
            preparer,
        )
        submitted = ProcessVersionService.submit(
            revision["id"],
            {
                "row_version": revision["row_version"],
                "idempotency_key": f"submit-process-{uuid.uuid4().hex}",
            },
            preparer,
        )
        command = {
            "row_version": submitted["row_version"],
            "idempotency_key": f"approve-process-{uuid.uuid4().hex}",
        }
        published = ProcessVersionService.approve(submitted["id"], command, approver)
        replay = ProcessVersionService.approve(submitted["id"], command, approver)
        versions = ProcessVersionRepository.list_versions(created["root"]["id"])
        events = ProcessVersionRepository.list_events(created["root"]["id"])

    assert replay == published
    assert [item["status"] for item in versions] == ["superseded", "published"]
    assert sum(
        event["event_type"] == "published" and event["version_id"] == published["id"]
        for event in events
    ) == 1
    assert sum(
        event["event_type"] == "approved" and event["version_id"] == published["id"]
        for event in events
    ) == 1


def test_process_lifecycle_retire_and_reactivate_require_two_people_and_new_revision(client):
    preparer, approver = _actors(client)
    created = _create_process(client, preparer)
    first = _publish(client, created["version"]["id"], preparer, approver)

    with client.application.app_context():
        request = MasterDataLifecycleService.request_process(
            created["root"]["id"],
            "retire",
            {
                "reason": "旧工艺停用",
                "idempotency_key": f"retire-process-{uuid.uuid4().hex}",
            },
            preparer,
        )
        with pytest.raises(ApprovalSeparationError):
            MasterDataLifecycleService.approve_process(
                request["id"], {"row_version": 0}, preparer
            )
        retired = MasterDataLifecycleService.approve_process(
            request["id"], {"row_version": 0}, approver
        )
        root = ProcessVersionRepository.root(created["root"]["id"])
        old_version = ProcessVersionRepository.version(first["id"])
        lifecycle_events = ProcessVersionRepository.list_events(created["root"]["id"])
        assert retired["status"] == "approved"
        assert root["lifecycle_status"] == "retired"
        assert old_version["status"] == "retired"
        assert lifecycle_events[-1]["event_type"] == "retired"
        with pytest.raises(ConflictError, match="新修订版"):
            MasterDataLifecycleService.request_process(
                root["id"],
                "reactivate",
                {
                    "reason": "恢复生产",
                    "idempotency_key": f"reactivate-process-{uuid.uuid4().hex}",
                },
                preparer,
            )

        revision = ProcessVersionService.create_revision(
            root["id"],
            {
                "revision_reason": "重新启用前复核",
                "idempotency_key": f"process-reactivation-revision-{uuid.uuid4().hex}",
            },
            preparer,
        )
        submitted = ProcessVersionService.submit(
            revision["id"],
            {"row_version": 0, "idempotency_key": f"submit-{uuid.uuid4().hex}"},
            preparer,
        )
        ProcessVersionService.approve(
            submitted["id"],
            {
                "row_version": submitted["row_version"],
                "idempotency_key": f"approve-{uuid.uuid4().hex}",
            },
            approver,
        )
        reactivate = MasterDataLifecycleService.request_process(
            root["id"],
            "reactivate",
            {
                "reason": "新修订版已发布",
                "idempotency_key": f"reactivate-process-{uuid.uuid4().hex}",
            },
            preparer,
        )
        MasterDataLifecycleService.approve_process(
            reactivate["id"], {"row_version": 0}, approver
        )
        active_root = ProcessVersionRepository.root(root["id"])

    assert active_root["lifecycle_status"] == "active"
    assert active_root["status"] == "active"


def test_process_rejection_is_a_terminal_audited_transition(client):
    preparer, approver = _actors(client)
    created = _create_process(client, preparer, "待驳回工序")
    with client.application.app_context():
        submitted = ProcessVersionService.submit(
            created["version"]["id"],
            {"row_version": 0, "idempotency_key": f"submit-{uuid.uuid4().hex}"},
            preparer,
        )
        rejected = ProcessVersionService.reject(
            submitted["id"],
            {
                "row_version": submitted["row_version"],
                "reason": "工艺参数证据不足",
                "idempotency_key": f"reject-{uuid.uuid4().hex}",
            },
            approver,
        )
        events = ProcessVersionRepository.list_events(created["root"]["id"])

    assert rejected["status"] == "rejected"
    assert events[-1]["event_type"] == "rejected"
