import pytest

from factories import ensure_process
from modules.db import get_db
from modules.domain.position_versioning import PositionVersionStaleError
from modules.repositories.position_version_repository import PositionVersionRepository
from modules.services import BaseService


def _root_payload(name="仓储测试岗位"):
    return {
        "name": name,
        "description": "仓储测试",
        "status": "inactive",
        "created_by": None,
    }


def _revision_payload(root, key, *, status="draft"):
    return {
        "position_code_snapshot": root["position_code"],
        "name": root["name"],
        "description": root["description"],
        "status": status,
        "revision_reason": "仓储修订测试",
        "content_digest": "digest-" + key,
        "impact_digest": "",
        "created_by": None,
        "created_by_name": "测试制单人",
        "idempotency_key": key,
    }


def test_repository_creates_idempotent_revision_and_reads_processes_in_order(client):
    with client.application.app_context():
        db = get_db()
        first_process = ensure_process(db, "岗位仓储工序一", 8101)
        second_process = ensure_process(db, "岗位仓储工序二", 8102)

        with BaseService.transaction() as txn:
            root = PositionVersionRepository.create_root(_root_payload(), txn)
            first = PositionVersionRepository.create_revision(
                root["id"], _revision_payload(root, "position-repo-same"), txn
            )
            replay = PositionVersionRepository.create_revision(
                root["id"], _revision_payload(root, "position-repo-same"), txn
            )
            PositionVersionRepository.replace_version_processes(
                first["id"], [second_process, first_process], txn
            )

        assert first["id"] == replay["id"]
        loaded = PositionVersionRepository.version(first["id"])
        assert loaded["process_ids"] == [second_process, first_process]
        assert loaded["processes"] == [
            {"process_id": second_process, "seq_order": 1},
            {"process_id": first_process, "seq_order": 2},
        ]

        listed = PositionVersionRepository.roots([root["id"]])
        assert listed[0]["id"] == root["id"]
        assert listed[0]["current_version"] is None
        assert PositionVersionRepository.open_version(root["id"])["id"] == first["id"]


def test_repository_allocates_next_revision_after_terminal_draft(client):
    with client.application.app_context():
        with BaseService.transaction() as txn:
            root = PositionVersionRepository.create_root(_root_payload("仓储版本号岗位"), txn)
            first = PositionVersionRepository.create_revision(
                root["id"], _revision_payload(root, "position-repo-v1"), txn
            )
            PositionVersionRepository.transition_version(
                first["id"], "draft", 0, "cancelled", {}, txn
            )
            second = PositionVersionRepository.create_revision(
                root["id"], _revision_payload(root, "position-repo-v2"), txn
            )

        assert first["version"] == 1
        assert second["version"] == 2
        assert [row["version"] for row in PositionVersionRepository.list_versions(root["id"])] == [1, 2]


def test_repository_never_commits_the_callers_transaction(client):
    with client.application.app_context():
        db = get_db()
        with pytest.raises(RuntimeError, match="rollback marker"):
            with BaseService.transaction() as txn:
                root = PositionVersionRepository.create_root(
                    _root_payload("仓储回滚岗位"), txn
                )
                PositionVersionRepository.create_revision(
                    root["id"], _revision_payload(root, "position-repo-rollback"), txn
                )
                raise RuntimeError("rollback marker")

        assert db.execute(
            "SELECT COUNT(*) FROM positions WHERE name='仓储回滚岗位'"
        ).fetchone()[0] == 0
        assert db.execute(
            "SELECT COUNT(*) FROM position_versions "
            "WHERE idempotency_key='position-repo-rollback'"
        ).fetchone()[0] == 0


def test_repository_conditional_updates_raise_stale_conflict(client):
    with client.application.app_context():
        with BaseService.transaction() as txn:
            root = PositionVersionRepository.create_root(_root_payload("仓储锁岗位"), txn)
            version = PositionVersionRepository.create_revision(
                root["id"], _revision_payload(root, "position-repo-lock"), txn
            )

        with pytest.raises(PositionVersionStaleError):
            with BaseService.transaction() as txn:
                PositionVersionRepository.update_version_content(
                    version["id"], "draft", 99, {"description": "过期更新"}, txn
                )
        with pytest.raises(PositionVersionStaleError):
            with BaseService.transaction() as txn:
                PositionVersionRepository.transition_version(
                    version["id"], "pending_approval", 0, "published", {}, txn
                )


def test_repository_projects_published_version_and_records_event(client):
    with client.application.app_context():
        db = get_db()
        process_id = ensure_process(db, "岗位投影工序", 8201)
        with BaseService.transaction() as txn:
            root = PositionVersionRepository.create_root(_root_payload("岗位投影旧名"), txn)
            version = PositionVersionRepository.create_revision(
                root["id"],
                {
                    **_revision_payload(root, "position-repo-publish"),
                    "name": "岗位投影新名",
                    "description": "新描述",
                },
                txn,
            )
            PositionVersionRepository.replace_version_processes(
                version["id"], [process_id], txn
            )
            published = PositionVersionRepository.transition_version(
                version["id"], "draft", 0, "published", {"published_at": "2026-08-20 08:00:00"}, txn
            )
            projected = PositionVersionRepository.update_compatibility_projection(
                root["id"], published["id"], root["row_version"], txn
            )
            event = PositionVersionRepository.create_event(
                {
                    "position_id": root["id"],
                    "position_version_id": published["id"],
                    "event_type": "published",
                    "actor_name": "测试批准人",
                    "idempotency_key": "position-repo-event",
                    "payload": {"process_ids": [process_id]},
                },
                txn,
            )

        assert projected["name"] == "岗位投影新名"
        assert projected["description"] == "新描述"
        assert projected["status"] == "active"
        assert projected["current_effective_version_id"] == published["id"]
        assert db.execute(
            "SELECT process_id FROM position_processes WHERE position_id=?",
            (root["id"],),
        ).fetchone()[0] == process_id
        assert event["id"] == PositionVersionRepository.event_by_idempotency_key(
            "position-repo-event"
        )["id"]
        assert PositionVersionRepository.list_events(root["id"])[0]["payload"] == {
            "process_ids": [process_id]
        }


def test_lifecycle_request_is_idempotent_and_conditionally_resolved(client):
    with client.application.app_context():
        with BaseService.transaction() as txn:
            root = PositionVersionRepository.create_root(_root_payload("生命周期仓储岗位"), txn)
            request = PositionVersionRepository.create_lifecycle_request(
                {
                    "position_id": root["id"],
                    "action": "retire",
                    "reason": "停止使用",
                    "impact_digest": "impact",
                    "requested_by": None,
                    "requested_by_name": "制单人",
                    "idempotency_key": "position-repo-retire",
                },
                txn,
            )
            replay = PositionVersionRepository.create_lifecycle_request(
                {
                    "position_id": root["id"],
                    "action": "retire",
                    "reason": "停止使用",
                    "impact_digest": "impact",
                    "requested_by": None,
                    "requested_by_name": "制单人",
                    "idempotency_key": "position-repo-retire",
                },
                txn,
            )
        assert request["id"] == replay["id"]
        assert PositionVersionRepository.pending_lifecycle_request(root["id"])["id"] == request["id"]

        with pytest.raises(PositionVersionStaleError):
            with BaseService.transaction() as txn:
                PositionVersionRepository.transition_lifecycle_request(
                    request["id"], "pending", 9, "approved", {}, txn
                )

        with BaseService.transaction() as txn:
            resolved = PositionVersionRepository.transition_lifecycle_request(
                request["id"],
                "pending",
                0,
                "rejected",
                {"resolved_at": "2026-08-20 09:00:00"},
                txn,
            )
        assert resolved["status"] == "rejected"
        assert PositionVersionRepository.pending_lifecycle_request(root["id"]) is None
