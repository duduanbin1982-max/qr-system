import pytest

from modules import config
from modules.services.position_service import PositionService


def test_position_flags_default_closed_and_parse_truthy_values():
    assert config.get_position_versioning_flags({}) == {
        "POSITION_VERSIONED_QUERY_ENABLED": False,
        "POSITION_COMPAT_AUDIT_ENABLED": False,
        "POSITION_VERSIONED_WRITE_ENABLED": False,
        "POSITION_LEGACY_WRITE_BLOCKED": False,
    }
    assert config.get_position_versioning_flags(
        {
            "POSITION_VERSIONED_QUERY_ENABLED": "yes",
            "POSITION_COMPAT_AUDIT_ENABLED": "1",
            "POSITION_VERSIONED_WRITE_ENABLED": "true",
            "POSITION_LEGACY_WRITE_BLOCKED": "on",
        }
    ) == {
        "POSITION_VERSIONED_QUERY_ENABLED": True,
        "POSITION_COMPAT_AUDIT_ENABLED": True,
        "POSITION_VERSIONED_WRITE_ENABLED": True,
        "POSITION_LEGACY_WRITE_BLOCKED": True,
    }


@pytest.mark.parametrize(
    "flags",
    [
        {
            "POSITION_VERSIONED_QUERY_ENABLED": False,
            "POSITION_COMPAT_AUDIT_ENABLED": True,
            "POSITION_VERSIONED_WRITE_ENABLED": False,
            "POSITION_LEGACY_WRITE_BLOCKED": False,
        },
        {
            "POSITION_VERSIONED_QUERY_ENABLED": False,
            "POSITION_COMPAT_AUDIT_ENABLED": False,
            "POSITION_VERSIONED_WRITE_ENABLED": True,
            "POSITION_LEGACY_WRITE_BLOCKED": False,
        },
        {
            "POSITION_VERSIONED_QUERY_ENABLED": True,
            "POSITION_COMPAT_AUDIT_ENABLED": False,
            "POSITION_VERSIONED_WRITE_ENABLED": False,
            "POSITION_LEGACY_WRITE_BLOCKED": True,
        },
    ],
)
def test_position_flag_order_is_fail_closed(flags):
    with pytest.raises(RuntimeError, match="岗位版本化功能开关组合无效"):
        config.validate_position_versioning_flags(flags)


def test_position_flag_order_accepts_each_controlled_cutover_stage():
    for flags in (
        {
            "POSITION_VERSIONED_QUERY_ENABLED": False,
            "POSITION_COMPAT_AUDIT_ENABLED": False,
            "POSITION_VERSIONED_WRITE_ENABLED": False,
            "POSITION_LEGACY_WRITE_BLOCKED": False,
        },
        {
            "POSITION_VERSIONED_QUERY_ENABLED": True,
            "POSITION_COMPAT_AUDIT_ENABLED": True,
            "POSITION_VERSIONED_WRITE_ENABLED": False,
            "POSITION_LEGACY_WRITE_BLOCKED": False,
        },
        {
            "POSITION_VERSIONED_QUERY_ENABLED": True,
            "POSITION_COMPAT_AUDIT_ENABLED": True,
            "POSITION_VERSIONED_WRITE_ENABLED": True,
            "POSITION_LEGACY_WRITE_BLOCKED": False,
        },
        {
            "POSITION_VERSIONED_QUERY_ENABLED": True,
            "POSITION_COMPAT_AUDIT_ENABLED": True,
            "POSITION_VERSIONED_WRITE_ENABLED": True,
            "POSITION_LEGACY_WRITE_BLOCKED": True,
        },
    ):
        assert config.validate_position_versioning_flags(flags) == flags


def test_versioned_create_returns_stable_409_while_write_is_disabled(
    client, auth_headers, monkeypatch
):
    monkeypatch.setattr(config, "POSITION_VERSIONED_WRITE_ENABLED", False)
    response = client.post(
        "/api/positions",
        headers=auth_headers,
        json={
            "name": "尚未开启的版本岗位",
            "revision_reason": "测试写开关",
            "idempotency_key": "position-write-disabled",
        },
    )

    assert response.status_code == 409
    assert response.get_json()["code"] == "POSITION_VERSIONED_WRITE_DISABLED"
    assert response.get_json()["action"] == "enable_position_versioned_write"


def test_legacy_put_and_delete_return_stable_409_when_blocked(
    client, auth_headers, monkeypatch
):
    with client.application.app_context():
        position_id = PositionService.create_position(
            {"name": "Legacy 阻断岗位", "description": "原说明"}
        )
    monkeypatch.setattr(config, "POSITION_LEGACY_WRITE_BLOCKED", True)

    update = client.put(
        f"/api/positions/{position_id}",
        headers=auth_headers,
        json={"description": "不应写入"},
    )
    delete = client.delete(
        f"/api/positions/{position_id}", headers=auth_headers
    )

    for response in (update, delete):
        assert response.status_code == 409
        assert response.get_json()["code"] == "POSITION_LEGACY_WRITE_BLOCKED"
        assert response.get_json()["action"] == "use_position_version_api"


def test_legacy_create_remains_available_before_versioned_write_cutover(
    client, auth_headers, monkeypatch
):
    monkeypatch.setattr(config, "POSITION_VERSIONED_WRITE_ENABLED", False)
    response = client.post(
        "/api/positions",
        headers=auth_headers,
        json={"name": "切换前 Legacy 岗位", "description": "兼容创建"},
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["id"] > 0
