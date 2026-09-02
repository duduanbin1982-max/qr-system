import json

from factories import TEST_HASH, TEST_PASS, ensure_user
from modules.db import get_db


def _login(client, username):
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": TEST_PASS},
    )
    assert response.status_code == 200, response.get_json()
    token = response.get_json()["user"]["token"]
    return {"Authorization": "Bearer " + token}


def test_settings_audit_is_structured_redacted_and_mandatory(client, auth_headers):
    response = client.post(
        "/api/settings",
        headers=auth_headers,
        json={"smtp_host": "smtp.local", "smtp_password": "top-secret"},
    )
    assert response.status_code == 200, response.get_json()

    with client.application.app_context():
        row = get_db().execute(
            "SELECT category,mandatory,detail FROM audit_logs "
            "WHERE action='save_settings' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row["category"] == "system"
    assert row["mandatory"] == 1
    assert "top-secret" not in row["detail"]
    assert json.loads(row["detail"])["changed_keys"] == [
        "smtp_host", "smtp_password"
    ]


def test_audit_query_rejects_invalid_bounds(client, auth_headers):
    assert client.get(
        "/api/logs?page=0", headers=auth_headers
    ).status_code == 400
    assert client.get(
        "/api/logs?date_from=2026/08/01", headers=auth_headers
    ).status_code == 400
    categories = client.get("/api/logs/categories", headers=auth_headers)
    assert categories.status_code == 200
    assert any(
        item["code"] == "permission" for item in categories.get_json()["items"]
    )


def test_cleanup_requires_second_admin_and_archives_before_delete(client, auth_headers):
    with client.application.app_context():
        db = get_db()
        ensure_user(
            db,
            "audit_approver",
            TEST_HASH,
            "Audit Approver",
            "admin",
            "AUDIT-APPROVER-001",
        )
        db.execute(
            "INSERT INTO audit_logs "
            "(event_id,user_id,action,target_type,target_id,detail,created_at,category,"
            "severity,mandatory,schema_version,redaction_version,request_id) "
            "VALUES ('old-event',NULL,'legacy_event','system',0,'old',"
            "'2020-01-01 00:00:00','legacy','info',0,1,1,'')"
        )
        db.commit()

    request_response = client.post(
        "/api/logs/clear",
        headers=auth_headers,
        json={"before_days": 1095, "reason": "公司保留期到期清理"},
    )
    assert request_response.status_code == 202, request_response.get_json()
    request_id = request_response.get_json()["request_id"]

    self_approval = client.post(
        f"/api/logs/cleanup-requests/{request_id}/approve",
        headers=auth_headers,
        json={"reason": "本人批准执行清理"},
    )
    assert self_approval.status_code == 400

    approver_headers = _login(client, "audit_approver")
    approval = client.post(
        f"/api/logs/cleanup-requests/{request_id}/approve",
        headers=approver_headers,
        json={"reason": "复核范围正确同意执行"},
    )
    assert approval.status_code == 200, approval.get_json()
    assert approval.get_json()["archived"] >= 1
    assert approval.get_json()["deleted"] >= 1

    with client.application.app_context():
        db = get_db()
        assert db.execute(
            "SELECT 1 FROM audit_logs WHERE event_id='old-event'"
        ).fetchone() is None
        archived = db.execute(
            "SELECT payload FROM audit_log_archive WHERE event_id='old-event'"
        ).fetchone()
        assert archived is not None
        request_row = db.execute(
            "SELECT status,requested_by,approved_by FROM audit_log_cleanup_requests "
            "WHERE id=?",
            (request_id,),
        ).fetchone()
        assert request_row["status"] == "executed"
        assert request_row["requested_by"] != request_row["approved_by"]
