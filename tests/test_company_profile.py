import json
import sqlite3
import uuid

import pytest

from factories import TEST_HASH, TEST_PASS
from modules.db import get_db
from modules.domain.company_profile import COMPANY_PROFILE_FIELDS
from modules.migration_company_profile import m065_version_company_profile
from modules.repositories.company_profile_repository import CompanyProfileRepository
from modules.services.company_profile_service import CompanyProfileService


def _permission_headers(client, permissions, role_code=None):
    suffix = uuid.uuid4().hex[:8]
    username = f"company_profile_{suffix}"
    role_code = role_code or f"company_profile_{suffix}"
    with client.application.app_context():
        db = get_db()
        role_id = db.execute(
            "INSERT INTO roles (name, code, description, permissions, status, level) "
            "VALUES (?, ?, 'pytest company profile role', ?, 'active', 1)",
            (
                f"Company Profile {suffix}",
                role_code,
                json.dumps(permissions, ensure_ascii=False),
            ),
        ).lastrowid
        user_id = db.execute(
            "INSERT INTO users "
            "(username, password, name, role, status, password_version, employee_no) "
            "VALUES (?, ?, ?, ?, 'active', 2, ?)",
            (
                username,
                TEST_HASH,
                f"Company Profile {suffix}",
                role_code,
                f"TEST-COMPANY-{suffix.upper()}",
            ),
        ).lastrowid
        db.execute(
            "INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)",
            (user_id, role_id),
        )
        db.commit()
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": TEST_PASS},
    )
    assert response.status_code == 200, response.get_json()
    return {
        "Authorization": f"Bearer {response.get_json()['user']['token']}"
    }


def _profile(client, headers):
    response = client.get("/api/settings/company-info", headers=headers)
    assert response.status_code == 200, response.get_json()
    return response.get_json()["profile"]


def test_v065_backfills_exact_legacy_values_and_is_idempotent():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE system_settings (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);
        CREATE TABLE roles (
            id INTEGER PRIMARY KEY, code TEXT, permissions TEXT
        );
        """
    )
    expected = {
        "company_name": "精密制造有限公司",
        "contact": "杨冰",
        "phone": "+86 138-0000-0000",
        "address": "生产路 8 号",
        "description": "历史简介原文",
    }
    db.executemany(
        "INSERT INTO system_settings(key,value) VALUES (?,?)", expected.items()
    )
    db.execute(
        "INSERT INTO roles(id,code,permissions) VALUES (1,'legacy',?)",
        (json.dumps(["page:settings.company-info", "settings:edit"]),),
    )
    db.execute(
        "INSERT INTO roles(id,code,permissions) VALUES (2,'manager',?)",
        (json.dumps(["settings:manage"]),),
    )
    db.execute(
        "INSERT INTO roles(id,code,permissions) VALUES (3,'production_manager','[]')"
    )

    m065_version_company_profile(db)
    m065_version_company_profile(db)

    profile = dict(db.execute("SELECT * FROM company_profiles").fetchone())
    assert {field: profile[field] for field in COMPANY_PROFILE_FIELDS} == expected
    assert profile["version"] == 1
    assert db.execute(
        "SELECT COUNT(*) FROM company_profile_revisions"
    ).fetchone()[0] == 1
    legacy = json.loads(
        db.execute("SELECT permissions FROM roles WHERE id=1").fetchone()[0]
    )
    manager = json.loads(
        db.execute("SELECT permissions FROM roles WHERE id=2").fetchone()[0]
    )
    production_manager = json.loads(
        db.execute("SELECT permissions FROM roles WHERE id=3").fetchone()[0]
    )
    assert "company_info:view" in legacy
    assert "company_info:edit" not in legacy
    assert {"company_info:view", "company_info:edit"}.issubset(manager)
    assert "company_info:view" in production_manager
    assert "company_info:edit" not in production_manager


def test_scoped_api_permission_matrix_and_generic_settings_block(client, auth_headers):
    viewer = _permission_headers(
        client,
        ["page:settings", "page:settings.company-info", "company_info:view"],
    )
    worker = _permission_headers(client, ["page:scan", "scan:view"])

    viewer_response = client.get("/api/settings/company-info", headers=viewer)
    assert viewer_response.status_code == 200
    assert set(viewer_response.get_json()["profile"]).issuperset(COMPANY_PROFILE_FIELDS)
    assert client.put(
        "/api/settings/company-info",
        headers=viewer,
        json={"version": 1, "company_name": "禁止编辑"},
    ).status_code == 403
    assert client.get("/api/settings/company-info", headers=worker).status_code == 403

    generic = client.post(
        "/api/settings",
        headers=auth_headers,
        json={"company_name": "不能走通用设置"},
    )
    assert generic.status_code == 400
    settings = client.get("/api/settings", headers=auth_headers).get_json()["settings"]
    assert not set(COMPANY_PROFILE_FIELDS).intersection(settings)


def test_versioned_update_writes_revision_mirror_and_redacted_audit(
    client, auth_headers
):
    current = _profile(client, auth_headers)
    response = client.put(
        "/api/settings/company-info",
        headers=auth_headers,
        json={
            "version": current["version"],
            "contact": "审计联系人",
            "phone": "138-1234-5678",
            "address": "审计地址 99 号",
        },
    )
    assert response.status_code == 200, response.get_json()
    saved = response.get_json()["profile"]
    assert saved["version"] == current["version"] + 1

    with client.application.app_context():
        db = get_db()
        revision = db.execute(
            "SELECT * FROM company_profile_revisions WHERE version=?",
            (saved["version"],),
        ).fetchone()
        assert json.loads(revision["changed_fields"]) == ["contact", "phone", "address"]
        mirrors = dict(db.execute(
            "SELECT key,value FROM system_settings WHERE key IN (?,?,?,?,?)",
            COMPANY_PROFILE_FIELDS,
        ).fetchall())
        assert mirrors["contact"] == "审计联系人"
        audit = db.execute(
            "SELECT detail FROM audit_logs WHERE action='company_profile_update' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()["detail"]
        assert "审计联系人" not in audit
        assert "138-1234-5678" not in audit
        assert "审计地址" not in audit
        assert json.loads(audit)["changed_fields"] == ["contact", "phone", "address"]


def test_history_is_redacted_without_audit_permission(client, auth_headers):
    current = _profile(client, auth_headers)
    client.put(
        "/api/settings/company-info",
        headers=auth_headers,
        json={
            "version": current["version"],
            "contact": "完整联系人",
            "phone": "13800000000",
            "address": "完整地址",
        },
    )
    viewer = _permission_headers(client, ["company_info:view"])
    redacted_response = client.get(
        "/api/settings/company-info/history", headers=viewer
    )
    full_response = client.get(
        "/api/settings/company-info/history", headers=auth_headers
    )
    assert redacted_response.status_code == 200, redacted_response.get_json()
    assert full_response.status_code == 200, full_response.get_json()
    redacted = redacted_response.get_json()
    full = full_response.get_json()

    assert redacted["sensitive_history_visible"] is False
    assert redacted["revisions"][0]["contact"] == "***"
    assert redacted["revisions"][0]["phone"] == "***"
    assert redacted["revisions"][0]["address"] == "***"
    assert full["sensitive_history_visible"] is True
    assert full["revisions"][0]["contact"] == "完整联系人"
    assert full["revisions"][0]["address"] == "完整地址"


def test_stale_noop_validation_and_immutable_history(client, auth_headers):
    current = _profile(client, auth_headers)
    no_op = client.put(
        "/api/settings/company-info",
        headers=auth_headers,
        json={"version": current["version"], "company_name": current["company_name"]},
    )
    assert no_op.status_code == 200
    assert no_op.get_json()["changed"] is False

    updated = client.put(
        "/api/settings/company-info",
        headers=auth_headers,
        json={"version": current["version"], "company_name": "并发版本测试"},
    )
    assert updated.status_code == 200
    stale = client.put(
        "/api/settings/company-info",
        headers=auth_headers,
        json={"version": current["version"], "description": "旧页面覆盖"},
    )
    assert stale.status_code == 409
    assert stale.get_json()["code"] == "COMPANY_PROFILE_STALE"

    invalid_cases = [
        {"version": updated.get_json()["profile"]["version"], "unknown": "x"},
        {"version": updated.get_json()["profile"]["version"], "phone": "call-me"},
        {"version": updated.get_json()["profile"]["version"], "contact": 123},
        {"version": updated.get_json()["profile"]["version"], "address": "x" * 501},
    ]
    for payload in invalid_cases:
        response = client.put(
            "/api/settings/company-info", headers=auth_headers, json=payload
        )
        assert response.status_code == 400, response.get_json()

    with client.application.app_context():
        db = get_db()
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(
                "UPDATE company_profile_revisions SET actor_name='篡改' WHERE version=1"
            )


def test_update_rolls_back_atomically_when_revision_insert_fails(
    client, monkeypatch
):
    with client.application.app_context():
        before = CompanyProfileService.get_profile()
        mirror_before = get_db().execute(
            "SELECT value FROM system_settings WHERE key='company_name'"
        ).fetchone()["value"]

        def fail_revision(*args, **kwargs):
            raise RuntimeError("revision insert failed")

        monkeypatch.setattr(
            CompanyProfileRepository, "insert_revision_txn", fail_revision
        )
        with pytest.raises(RuntimeError, match="revision insert failed"):
            CompanyProfileService.update_profile(
                {"company_name": "不应保存"},
                before["version"],
                {"id": 1, "name": "事务测试"},
            )
        after = CompanyProfileService.get_profile()
        mirror_after = get_db().execute(
            "SELECT value FROM system_settings WHERE key='company_name'"
        ).fetchone()["value"]
        assert after == before
        assert mirror_after == mirror_before


def test_update_prunes_revisions_older_than_three_years(client):
    with client.application.app_context():
        db = get_db()
        current = CompanyProfileService.get_profile()
        db.execute(
            "UPDATE company_profiles SET version=2 WHERE id=1"
        )
        db.execute(
            "INSERT INTO company_profile_revisions "
            "(profile_id,company_name,contact,phone,address,description,version,"
            "changed_fields,actor_name,created_at) VALUES (1,?,?,?,?,?,2,'[]','旧记录',"
            "datetime('now','localtime','-3 years','-1 day'))",
            tuple(current[field] for field in COMPANY_PROFILE_FIELDS),
        )
        db.commit()

        result = CompanyProfileService.update_profile(
            {"description": "触发三年清理"},
            2,
            {"id": 1, "name": "清理测试"},
        )
        assert result["profile"]["version"] == 3
        assert not db.execute(
            "SELECT 1 FROM company_profile_revisions WHERE version=2"
        ).fetchone()
        assert db.execute(
            "SELECT 1 FROM company_profile_revisions WHERE version=3"
        ).fetchone()
