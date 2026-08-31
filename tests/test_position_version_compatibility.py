import json
import logging
import uuid

from modules import config
from modules.db import get_db
from modules.services.position_service import PositionService
from tests.test_position_version_workflow import (
    _actors,
    _create_position,
    _publish_position,
)


def _published_position(client, name):
    preparer, approver = _actors(client)
    created = _create_position(client, preparer, [], name)
    published = _publish_position(
        client, created["version"]["id"], preparer, approver
    )
    return created, published


def _set_flags(monkeypatch, *, query=False, audit=False):
    monkeypatch.setattr(config, "POSITION_VERSIONED_QUERY_ENABLED", query)
    monkeypatch.setattr(config, "POSITION_COMPAT_AUDIT_ENABLED", audit)


def test_position_query_disabled_preserves_legacy_contract(client, monkeypatch):
    created, _ = _published_position(
        client, f"岗位 Legacy 查询-{uuid.uuid4().hex[:8]}"
    )
    _set_flags(monkeypatch)

    with client.application.app_context():
        payload = PositionService.list_positions()

    position = next(
        item for item in payload["positions"] if item["id"] == created["root"]["id"]
    )
    assert position["name"] == created["version"]["name"]
    assert position["process_ids"] == []
    for version_field in (
        "position_code",
        "lifecycle_status",
        "current_effective_version_id",
        "current_version",
        "open_version",
        "pending_lifecycle_request",
        "employee_count",
    ):
        assert version_field not in position


def test_position_query_enabled_projects_current_version(client, monkeypatch):
    created, published = _published_position(
        client, f"岗位 V2 查询-{uuid.uuid4().hex[:8]}"
    )
    _set_flags(monkeypatch, query=True)

    with client.application.app_context():
        db = get_db()
        db.execute(
            "UPDATE positions SET name='故意偏离当前版本' WHERE id=?",
            (created["root"]["id"],),
        )
        db.commit()
        payload = PositionService.list_positions()

    position = next(
        item for item in payload["positions"] if item["id"] == created["root"]["id"]
    )
    assert position["name"] == published["name"]
    assert position["position_code"] == created["root"]["position_code"]
    assert position["current_effective_version_id"] == published["id"]
    assert position["current_version"]["id"] == published["id"]
    assert position["employee_count"] == 0


def test_position_compat_audit_is_silent_when_disabled(client, monkeypatch, caplog):
    created, _ = _published_position(
        client, f"岗位审计关闭-{uuid.uuid4().hex[:8]}"
    )
    _set_flags(monkeypatch, query=True, audit=False)

    with client.application.app_context():
        db = get_db()
        db.execute(
            "UPDATE positions SET description='审计关闭时的差异' WHERE id=?",
            (created["root"]["id"],),
        )
        db.commit()
        with caplog.at_level(logging.WARNING, logger="qr-system.compatibility"):
            PositionService.list_positions()

    assert "master_data_compat_diff" not in caplog.text


def test_position_compat_audit_logs_redacted_structured_diff(
    client, monkeypatch, caplog
):
    created, _ = _published_position(
        client, f"岗位双读审计-{uuid.uuid4().hex[:8]}"
    )
    sensitive_value = "不得进入兼容日志的岗位说明"
    _set_flags(monkeypatch, query=True, audit=True)

    with client.application.app_context():
        db = get_db()
        db.execute(
            "UPDATE positions SET description=? WHERE id=?",
            (sensitive_value, created["root"]["id"]),
        )
        db.commit()
        with caplog.at_level(logging.WARNING, logger="qr-system.compatibility"):
            PositionService.list_positions()

    records = [
        record
        for record in caplog.records
        if record.getMessage().startswith("master_data_compat_diff ")
    ]
    assert len(records) == 1
    details = json.loads(records[0].getMessage().split(" ", 1)[1])
    assert details["event"] == "master_data_compat_diff"
    assert details["entity"] == "positions"
    assert {
        "id": created["root"]["id"],
        "field": "description",
    } in details["field_differences"]
    assert sensitive_value not in caplog.text


def test_position_compat_audit_does_not_log_matching_projection(
    client, monkeypatch, caplog
):
    _published_position(client, f"岗位无差异-{uuid.uuid4().hex[:8]}")
    _set_flags(monkeypatch, query=True, audit=True)

    with client.application.app_context():
        with caplog.at_level(logging.WARNING, logger="qr-system.compatibility"):
            PositionService.list_positions()

    assert "master_data_compat_diff" not in caplog.text
