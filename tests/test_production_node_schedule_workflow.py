import json
import sqlite3
import uuid

import pytest

from factories import (
    TEST_HASH,
    bind_order_process_versions,
    create_order,
    create_process_route,
    ensure_user,
)
from modules import config
from modules.db import get_db
from modules.domain.production_node_scheduling import NodeSchedulingError
from modules.migration_production_nodes import m089_schedule_revision_workflow
from modules.repositories.schedule_capacity_repository import (
    ScheduleCapacityRepository,
)
from modules.services.schedule_capacity_service import ScheduleCapacityService


def _enable_node_engine(monkeypatch):
    monkeypatch.setattr(config, "PRODUCTION_NODE_QUERY_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_WRITE_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_ENGINE_ENABLED", True)


def _actors(db):
    creator_id = db.execute(
        "SELECT id FROM users WHERE username='testrunner'"
    ).fetchone()[0]
    reviewer_id = ensure_user(
        db,
        "schedule-workflow-reviewer",
        TEST_HASH,
        "Schedule Workflow Reviewer",
        "worker",
        "SCHEDULE-WORKFLOW-REVIEWER",
    )
    return creator_id, reviewer_id


def _seed_schedule(
    db,
    *,
    actor_id,
    route_name="Workflow route",
    plan_start="2026-09-21",
    unit_minutes=60,
    with_standard=True,
    run_key=None,
):
    process = db.execute(
        "SELECT id FROM processes WHERE name='\u4e0b\u6599'"
    ).fetchone()
    assert process
    route_id = create_process_route(db, [process["id"]], name=route_name)
    order_id = create_order(
        db,
        [process["id"]],
        quantity=1,
        product_code=f"WORKFLOW-{uuid.uuid4().hex[:8].upper()}",
    )
    db.execute(
        "UPDATE orders SET route_id=?,plan_start=? WHERE id=?",
        (route_id, plan_start, order_id),
    )
    bind_order_process_versions(db, order_id)
    route_version_id = db.execute(
        "SELECT route_version_id FROM orders WHERE id=?", (order_id,)
    ).fetchone()[0]
    process_version_id = db.execute(
        "SELECT process_version_id FROM order_processes WHERE order_id=?",
        (order_id,),
    ).fetchone()[0]
    if with_standard:
        db.execute(
            "INSERT INTO work_time_standards "
            "(route_id,route_version_id,process_id,process_version_id,"
            "standard_minutes_per_unit,setup_minutes,difficulty_factor,status,version) "
            "VALUES (?,?,?,?,?,0,1,'active',1)",
            (
                route_id,
                route_version_id,
                process["id"],
                process_version_id,
                unit_minutes,
            ),
        )
    db.commit()
    result = ScheduleCapacityService.generate_order_schedule(
        order_id,
        start_date=plan_start,
        schedule_run_key=run_key or f"workflow-{uuid.uuid4().hex}",
        actor_id=actor_id,
    )
    item = db.execute(
        "SELECT * FROM schedule_revision_items WHERE revision_id=? ORDER BY id LIMIT 1",
        (result["schedule_revision_id"],),
    ).fetchone()
    assert item
    return result, dict(item)


def _approve(revision_id, creator_id, reviewer_id, prefix):
    ScheduleCapacityService.submit_revision(
        revision_id, "submit for independent review", f"{prefix}-submit", creator_id
    )
    return ScheduleCapacityService.approve_revision(
        revision_id, "independent approval", f"{prefix}-approve", reviewer_id
    )


def _login_with_permissions(client, permissions):
    suffix = uuid.uuid4().hex[:8]
    username = f"schedule-workflow-{suffix}"
    with client.application.app_context():
        db = get_db()
        role_id = db.execute(
            "INSERT INTO roles (name,code,description,permissions,status,level) "
            "VALUES (?,?,'',?,'active',1)",
            (
                f"Schedule Workflow Role {suffix}",
                f"schedule_workflow_{suffix}",
                json.dumps(permissions),
            ),
        ).lastrowid
        user_id = db.execute(
            "INSERT INTO users (username,password,name,role,employee_no,status,"
            "password_version,must_change_password) VALUES (?,?,?,'worker',?,'active',2,0)",
            (username, TEST_HASH, f"Schedule Workflow {suffix}", f"SW-{suffix}"),
        ).lastrowid
        db.execute(
            "INSERT INTO user_roles (user_id,role_id) VALUES (?,?)",
            (user_id, role_id),
        )
        db.commit()
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": "Test@1234"},
    )
    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    token = payload.get("token") or payload["user"]["token"]
    return {"Authorization": f"Bearer {token}"}, user_id


def test_v089_adds_workflow_schema_and_backfills_published_revisions(
    client, monkeypatch
):
    _enable_node_engine(monkeypatch)
    with client.application.app_context():
        db = get_db()
        creator_id, reviewer_id = _actors(db)
        result, _ = _seed_schedule(db, actor_id=creator_id)
        revision_id = result["schedule_revision_id"]
        _approve(revision_id, creator_id, reviewer_id, "workflow-schema")
        ScheduleCapacityService.publish_revision(
            revision_id, published_by=creator_id
        )
        db.execute(
            "UPDATE schedule_revisions SET approval_status='draft' WHERE id=?",
            (revision_id,),
        )
        db.commit()

        m089_schedule_revision_workflow(db)
        db.commit()

        revision_columns = {
            row["name"] for row in db.execute("PRAGMA table_info(schedule_revisions)")
        }
        item_columns = {
            row["name"]
            for row in db.execute("PRAGMA table_info(schedule_revision_items)")
        }
        assert {
            "approval_status",
            "submitted_by",
            "approved_by",
            "rejected_by",
        }.issubset(revision_columns)
        assert "row_version" in item_columns
        assert db.execute("PRAGMA user_version").fetchone()[0] == 89
        assert db.execute(
            "SELECT approval_status FROM schedule_revisions WHERE id=?",
            (revision_id,),
        ).fetchone()[0] == "approved"
        assert db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='schedule_node_task_locks'"
        ).fetchone()
        assert db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='schedule_node_workflow_events'"
        ).fetchone()
        assert db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='uq_schedule_node_task_active_lock'"
        ).fetchone()
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(
                "UPDATE schedule_revision_items SET row_version=2 "
                "WHERE revision_id=?",
                (revision_id,),
            )


def test_lock_replay_unlock_and_dynamic_replan_preserves_lock(client, monkeypatch):
    _enable_node_engine(monkeypatch)
    with client.application.app_context():
        db = get_db()
        creator_id, _ = _actors(db)
        result, item = _seed_schedule(db, actor_id=creator_id)

        locked = ScheduleCapacityService.lock_schedule_item(
            item["id"], "freeze execution task", "workflow-lock-001", creator_id
        )
        assert locked["idempotent_replay"] is False
        replay = ScheduleCapacityService.lock_schedule_item(
            item["id"], "freeze execution task", "workflow-lock-001", creator_id
        )
        assert replay["idempotent_replay"] is True
        with pytest.raises(NodeSchedulingError) as reused:
            ScheduleCapacityService.lock_schedule_item(
                item["id"], "different reason", "workflow-lock-001", creator_id
            )
        assert reused.value.code == "IDEMPOTENCY_CONFLICT"
        with pytest.raises(NodeSchedulingError) as duplicate:
            ScheduleCapacityService.lock_schedule_item(
                item["id"], "second active lock", "workflow-lock-002", creator_id
            )
        assert duplicate.value.code == "LOCKED_TASK_CONFLICT"
        replanned = ScheduleCapacityService.dynamic_replan_order(
            result["order_id"],
            start_at="2026-09-21 08:00",
            schedule_run_key="workflow-replan-locked-001",
            reason="new production facts",
            actor_id=creator_id,
        )
        assert replanned["conflicts"] == []
        operation = replanned["operations"][0]
        assert operation["production_node_id"] == item["production_node_id"]
        assert operation["planned_start_at"] == item["planned_start_at"]
        assert operation["planned_end_at"] == item["planned_end_at"]
        assert operation["locked"] is True
        copied_item_id = operation["revision_item_id"]
        assert copied_item_id != item["id"]
        assert db.execute(
            "SELECT COUNT(*) FROM schedule_node_task_locks "
            "WHERE revision_item_id=? AND status='active'",
            (copied_item_id,),
        ).fetchone()[0] == 1

        unlocked = ScheduleCapacityService.unlock_schedule_item(
            copied_item_id, "release execution task", "workflow-unlock-001", creator_id
        )
        assert unlocked["result"]["status"] == "released"
        unlock_replay = ScheduleCapacityService.unlock_schedule_item(
            copied_item_id, "release execution task", "workflow-unlock-001", creator_id
        )
        assert unlock_replay["idempotent_replay"] is True
        with pytest.raises(ValueError, match="\u539f\u56e0\u5fc5\u987b\u586b\u5199"):
            ScheduleCapacityService.lock_schedule_item(
                copied_item_id, "", "workflow-lock-empty", creator_id
            )


def test_schedule_list_exposes_node_workflow_and_split_detail_fields(client, monkeypatch):
    _enable_node_engine(monkeypatch)
    with client.application.app_context():
        db = get_db()
        creator_id, _ = _actors(db)
        result, item = _seed_schedule(db, actor_id=creator_id)
        ScheduleCapacityService.lock_schedule_item(
            item["id"], "lock for read contract", "workflow-list-lock-001", creator_id
        )

        payload = ScheduleCapacityService.list_schedules(limit=500)
        row = next(
            operation
            for operation in payload["operations"]
            if operation["order_id"] == result["order_id"]
        )
        assert row["revision_item_id"] == item["id"]
        assert row["revision_item_row_version"] == item["row_version"]
        assert row["revision_status"] == "draft"
        assert row["locked"] is True
        assert row["task_lock_id"]
        assert row["node_code"]
        assert row["node_name"]
        assert isinstance(row["allocations"], list)
        assert row["allocations"]
        assert row["allocations"][0]["production_node_id"] == row["production_node_id"]


def test_blocked_schedule_item_cannot_be_locked(client, monkeypatch):
    _enable_node_engine(monkeypatch)
    with client.application.app_context():
        db = get_db()
        creator_id, _ = _actors(db)
        _, item = _seed_schedule(
            db,
            actor_id=creator_id,
            route_name="Workflow blocked route",
            with_standard=False,
        )
        assert item["status"] == "blocked"
        with pytest.raises(NodeSchedulingError) as blocked:
            ScheduleCapacityService.lock_schedule_item(
                item["id"], "invalid blocked lock", "workflow-blocked-lock", creator_id
            )
        assert blocked.value.code == "NO_COMPATIBLE_NODE"


def test_manual_adjustment_clones_revision_and_preserves_source(client, monkeypatch):
    _enable_node_engine(monkeypatch)
    with client.application.app_context():
        db = get_db()
        creator_id, _ = _actors(db)
        result, item = _seed_schedule(db, actor_id=creator_id)
        source_before = dict(
            db.execute(
                "SELECT * FROM schedule_revision_items WHERE id=?", (item["id"],)
            ).fetchone()
        )
        adjusted = ScheduleCapacityService.adjust_schedule_item(
            item["id"],
            item["production_node_id"],
            "2026-09-22 08:00",
            "move to next working day",
            item["row_version"],
            "workflow-adjust-001",
            creator_id,
        )
        new_revision_id = adjusted["result"]["revision_id"]
        new_item_id = adjusted["result"]["revision_item_id"]
        assert new_revision_id != result["schedule_revision_id"]
        assert new_item_id != item["id"]
        assert adjusted["result"]["approval_status"] == "draft"
        assert dict(
            db.execute(
                "SELECT * FROM schedule_revision_items WHERE id=?", (item["id"],)
            ).fetchone()
        ) == source_before
        new_item = db.execute(
            "SELECT * FROM schedule_revision_items WHERE id=?", (new_item_id,)
        ).fetchone()
        assert new_item["planned_start_at"] == "2026-09-22 08:00"
        assert new_item["row_version"] == 1
        new_revision = db.execute(
            "SELECT * FROM schedule_revisions WHERE id=?", (new_revision_id,)
        ).fetchone()
        assert new_revision["status"] == "draft"
        assert new_revision["approval_status"] == "draft"
        assert new_revision["created_by"] == creator_id

        replay = ScheduleCapacityService.adjust_schedule_item(
            item["id"],
            item["production_node_id"],
            "2026-09-22 08:00",
            "move to next working day",
            item["row_version"],
            "workflow-adjust-001",
            creator_id,
        )
        assert replay["idempotent_replay"] is True
        assert replay["result"]["revision_id"] == new_revision_id


def test_manual_adjustment_validates_version_calendar_downtime_and_lock(
    client, monkeypatch
):
    _enable_node_engine(monkeypatch)
    with client.application.app_context():
        db = get_db()
        creator_id, _ = _actors(db)
        _, item = _seed_schedule(db, actor_id=creator_id)

        with pytest.raises(NodeSchedulingError) as stale:
            ScheduleCapacityService.adjust_schedule_item(
                item["id"],
                item["production_node_id"],
                "2026-09-22 08:00",
                "stale edit",
                item["row_version"] + 1,
                "workflow-adjust-stale",
                creator_id,
            )
        assert stale.value.code == "ROW_VERSION_CONFLICT"

        other_node = db.execute(
            "SELECT id FROM production_nodes WHERE process_id<>? AND status='active' "
            "ORDER BY id LIMIT 1",
            (item["process_id"],),
        ).fetchone()[0]
        with pytest.raises(NodeSchedulingError) as incompatible:
            ScheduleCapacityService.adjust_schedule_item(
                item["id"],
                other_node,
                "2026-09-22 08:00",
                "wrong process node",
                item["row_version"],
                "workflow-adjust-wrong-node",
                creator_id,
            )
        assert incompatible.value.code == "NO_COMPATIBLE_NODE"

        with pytest.raises(NodeSchedulingError) as calendar_gap:
            ScheduleCapacityService.adjust_schedule_item(
                item["id"],
                item["production_node_id"],
                "2026-09-22 12:30",
                "invalid calendar gap",
                item["row_version"],
                "workflow-adjust-calendar-gap",
                creator_id,
            )
        assert calendar_gap.value.code == "NODE_CALENDAR_UNAVAILABLE"

        db.execute(
            "INSERT INTO schedule_downtime_events "
            "(process_line_id,production_node_id,start_at,end_at,reason,status) "
            "VALUES (?,?,?,?,?,'active')",
            (
                item["process_line_id"],
                item["production_node_id"],
                "2026-09-22 08:00",
                "2026-09-22 09:00",
                "planned maintenance",
            ),
        )
        db.commit()
        with pytest.raises(NodeSchedulingError) as downtime:
            ScheduleCapacityService.adjust_schedule_item(
                item["id"],
                item["production_node_id"],
                "2026-09-22 08:00",
                "overlap maintenance",
                item["row_version"],
                "workflow-adjust-downtime",
                creator_id,
            )
        assert downtime.value.code == "NODE_CALENDAR_UNAVAILABLE"

        ScheduleCapacityService.lock_schedule_item(
            item["id"], "freeze source", "workflow-adjust-source-lock", creator_id
        )
        with pytest.raises(NodeSchedulingError) as locked:
            ScheduleCapacityService.adjust_schedule_item(
                item["id"],
                item["production_node_id"],
                "2026-09-23 08:00",
                "move locked source",
                item["row_version"],
                "workflow-adjust-locked",
                creator_id,
            )
        assert locked.value.code == "LOCKED_TASK_CONFLICT"


def test_submit_reject_resubmit_approve_publish_and_immutable_events(
    client, monkeypatch
):
    _enable_node_engine(monkeypatch)
    with client.application.app_context():
        db = get_db()
        creator_id, reviewer_id = _actors(db)
        result, _ = _seed_schedule(db, actor_id=creator_id)
        revision_id = result["schedule_revision_id"]

        with pytest.raises(NodeSchedulingError) as unapproved:
            ScheduleCapacityService.publish_revision(
                revision_id, published_by=creator_id
            )
        assert unapproved.value.code == "REVISION_STATE_CONFLICT"
        submitted = ScheduleCapacityService.submit_revision(
            revision_id,
            "ready for review",
            "workflow-submit-001",
            creator_id,
        )
        assert submitted["result"]["approval_status"] == "submitted"
        assert ScheduleCapacityService.submit_revision(
            revision_id,
            "ready for review",
            "workflow-submit-001",
            creator_id,
        )["idempotent_replay"] is True
        with pytest.raises(NodeSchedulingError) as self_approval:
            ScheduleCapacityService.approve_revision(
                revision_id,
                "self approval is invalid",
                "workflow-self-approve",
                creator_id,
            )
        assert self_approval.value.code == "INDEPENDENT_APPROVER_REQUIRED"

        rejected = ScheduleCapacityService.reject_revision(
            revision_id,
            "capacity conflict found",
            "workflow-reject-001",
            reviewer_id,
        )
        assert rejected["result"]["approval_status"] == "rejected"
        ScheduleCapacityService.submit_revision(
            revision_id,
            "conflict resolved",
            "workflow-resubmit-001",
            creator_id,
        )
        approved = ScheduleCapacityService.approve_revision(
            revision_id,
            "approve corrected schedule",
            "workflow-approve-001",
            reviewer_id,
        )
        assert approved["result"]["approval_status"] == "approved"
        published = ScheduleCapacityService.publish_revision(
            revision_id, published_by=creator_id
        )
        assert published["revision"]["status"] == "published"

        event_id = approved["event"]["id"]
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(
                "UPDATE schedule_node_workflow_events SET reason='tampered' WHERE id=?",
                (event_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(
                "DELETE FROM schedule_node_workflow_events WHERE id=?", (event_id,)
            )


def test_workflow_api_returns_400_403_404_and_409(client, monkeypatch):
    _enable_node_engine(monkeypatch)
    allowed_headers, actor_id = _login_with_permissions(
        client,
        [
            "schedule:edit",
            "schedules:lock",
            "schedules:unlock",
            "schedules:approve",
        ],
    )
    denied_headers, _ = _login_with_permissions(client, ["schedule:view"])
    with client.application.app_context():
        db = get_db()
        result, item = _seed_schedule(db, actor_id=actor_id)

    unapproved = client.post(
        f"/api/schedule/revisions/{result['schedule_revision_id']}/publish",
        headers=allowed_headers,
        json={},
    )
    assert unapproved.status_code == 409
    assert unapproved.get_json()["code"] == "REVISION_STATE_CONFLICT"

    invalid = client.post(
        f"/api/schedule/revision-items/{item['id']}/lock",
        headers=allowed_headers,
        json={"idempotency_key": "workflow-api-invalid"},
    )
    assert invalid.status_code == 400

    forbidden = client.post(
        f"/api/schedule/revision-items/{item['id']}/lock",
        headers=denied_headers,
        json={"reason": "not authorized", "idempotency_key": "workflow-api-denied"},
    )
    assert forbidden.status_code == 403

    missing = client.post(
        "/api/schedule/revision-items/999999/lock",
        headers=allowed_headers,
        json={"reason": "missing item", "idempotency_key": "workflow-api-missing"},
    )
    assert missing.status_code == 404

    locked = client.post(
        f"/api/schedule/revision-items/{item['id']}/lock",
        headers=allowed_headers,
        json={"reason": "api lock", "idempotency_key": "workflow-api-lock-001"},
    )
    assert locked.status_code == 200, locked.get_json()
    conflict = client.post(
        f"/api/schedule/revision-items/{item['id']}/lock",
        headers=allowed_headers,
        json={"reason": "second lock", "idempotency_key": "workflow-api-lock-002"},
    )
    assert conflict.status_code == 409
    assert conflict.get_json()["code"] == "LOCKED_TASK_CONFLICT"
