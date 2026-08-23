import uuid

import pytest

from modules.db import get_db
from modules.domain.errors import ConflictError
from modules.services.approval_policy_service import ApprovalPolicyService
from tests.factories import ensure_process


def _payload(process_id, key, role="admin"):
    return {
        "process_id": process_id,
        "idempotency_key": key,
        "require_approval": 1,
        "approval_level": 1,
        "steps": [{"code": role}],
    }


def test_versioned_policy_revision_is_idempotent_and_requires_separation(client, monkeypatch):
    monkeypatch.setattr("modules.services.approval_policy_service.config.APPROVAL_POLICY_VERSIONED_WRITE_ENABLED", True)
    with client.application.app_context():
        db = get_db()
        process_id = ensure_process(db, name=f"Policy {uuid.uuid4().hex[:8]}", seq_order=998)
        actor = {"id": 1, "name": "Maker"}
        payload = _payload(process_id, f"policy-{uuid.uuid4().hex}")
        first = ApprovalPolicyService.create_revision(payload, actor)
        second = ApprovalPolicyService.create_revision(payload, actor)
        assert first["id"] == second["id"]
        submitted = ApprovalPolicyService.transition(first["id"], "pending_approval", actor)
        assert submitted["status"] == "pending_approval"
        with pytest.raises(ConflictError, match="制单人不能批准"):
            ApprovalPolicyService.transition(first["id"], "published", actor)


def test_approval_policy_api_exposes_versioned_catalog(client, auth_headers):
    response = client.get("/api/approval-policies", headers=auth_headers)
    assert response.status_code == 200
    assert "policies" in response.get_json()


def test_compat_audit_ignores_display_only_differences(client, monkeypatch):
    monkeypatch.setattr(
        "modules.services.approval_policy_service.config.APPROVAL_POLICY_VERSIONED_QUERY_ENABLED",
        True,
    )
    monkeypatch.setattr(
        "modules.services.approval_policy_service.config.APPROVAL_POLICY_COMPAT_AUDIT_ENABLED",
        True,
    )
    with client.application.app_context():
        db = get_db()
        process_id = ensure_process(db, name=f"Compat {uuid.uuid4().hex[:8]}", seq_order=997)
        db.execute(
            "INSERT INTO approval_config(process_id,require_approval,approval_level,approver_role,approver_role_id) "
            "VALUES (?,?,?,?,?)",
            (process_id, 1, 1, "admin", 1),
        )
        db.execute(
            "INSERT INTO approval_policies(policy_key,process_id,name) VALUES (?,?,?)",
            (f"process:{process_id}", process_id, "Compat"),
        )
        policy_id = db.execute(
            "SELECT id FROM approval_policies WHERE process_id=?", (process_id,)
        ).fetchone()[0]
        db.execute(
            "INSERT INTO approval_policy_revisions "
            "(policy_id,version,status,require_approval,approval_level,idempotency_key) "
            "VALUES (?,?,?,?,?,?)",
            (policy_id, 1, "published", 1, 1, f"compat-{uuid.uuid4().hex}"),
        )
        revision_id = db.execute(
            "SELECT id FROM approval_policy_revisions WHERE policy_id=?", (policy_id,)
        ).fetchone()[0]
        db.execute(
            "UPDATE approval_policies SET current_revision_id=? WHERE id=?",
            (revision_id, policy_id),
        )
        db.execute(
            "INSERT INTO approval_policy_revision_steps "
            "(revision_id,step_level,role_id,role_code_snapshot,role_name_snapshot) "
            "VALUES (?,?,?,?,?)",
            (revision_id, 1, 1, "admin", "系统管理员"),
        )
        db.commit()

        snapshot, _ = ApprovalPolicyService.effective_snapshot(process_id, db=db)

        assert snapshot["source"] == "versioned"
        assert db.execute(
            "SELECT mismatch FROM approval_policy_compat_audit WHERE process_id=?",
            (process_id,),
        ).fetchone()[0] == 0


def test_compat_audit_detects_business_role_difference(client, monkeypatch):
    monkeypatch.setattr(
        "modules.services.approval_policy_service.config.APPROVAL_POLICY_VERSIONED_QUERY_ENABLED",
        True,
    )
    monkeypatch.setattr(
        "modules.services.approval_policy_service.config.APPROVAL_POLICY_COMPAT_AUDIT_ENABLED",
        True,
    )
    with client.application.app_context():
        db = get_db()
        process_id = ensure_process(db, name=f"Mismatch {uuid.uuid4().hex[:8]}", seq_order=996)
        db.execute(
            "INSERT INTO approval_config(process_id,require_approval,approval_level,approver_role,approver_role_id) "
            "VALUES (?,?,?,?,?)",
            (process_id, 1, 1, "admin", 1),
        )
        db.execute(
            "INSERT INTO approval_policies(policy_key,process_id,name) VALUES (?,?,?)",
            (f"process:{process_id}", process_id, "Mismatch"),
        )
        policy_id = db.execute(
            "SELECT id FROM approval_policies WHERE process_id=?", (process_id,)
        ).fetchone()[0]
        worker_role = db.execute(
            "SELECT id,name FROM roles WHERE code='worker'"
        ).fetchone()
        db.execute(
            "INSERT INTO approval_policy_revisions "
            "(policy_id,version,status,require_approval,approval_level,idempotency_key) "
            "VALUES (?,?,?,?,?,?)",
            (policy_id, 1, "published", 1, 1, f"mismatch-{uuid.uuid4().hex}"),
        )
        revision_id = db.execute(
            "SELECT id FROM approval_policy_revisions WHERE policy_id=?", (policy_id,)
        ).fetchone()[0]
        db.execute(
            "UPDATE approval_policies SET current_revision_id=? WHERE id=?",
            (revision_id, policy_id),
        )
        db.execute(
            "INSERT INTO approval_policy_revision_steps "
            "(revision_id,step_level,role_id,role_code_snapshot,role_name_snapshot) "
            "VALUES (?,?,?,?,?)",
            (revision_id, 1, worker_role["id"], "worker", worker_role["name"]),
        )
        db.commit()

        ApprovalPolicyService.effective_snapshot(process_id, db=db)

        assert db.execute(
            "SELECT mismatch FROM approval_policy_compat_audit WHERE process_id=?",
            (process_id,),
        ).fetchone()[0] == 1
