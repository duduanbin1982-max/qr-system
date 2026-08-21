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
