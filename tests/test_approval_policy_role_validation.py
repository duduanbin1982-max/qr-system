"""Resolved role identity is the invariant, rather than caller-supplied codes."""
import uuid

import pytest

from modules.db import get_db
from modules.domain.errors import ValidationError
from modules.services.approval_policy_service import ApprovalPolicyService
from tests.factories import ensure_process


@pytest.fixture
def policy_context(client, monkeypatch):
    monkeypatch.setattr("modules.config.APPROVAL_POLICY_VERSIONED_WRITE_ENABLED", True)
    with client.application.app_context():
        db = get_db()
        pid = ensure_process(db, name=f"Role validation {uuid.uuid4().hex[:8]}", seq_order=998)
        roles = [dict(row) for row in db.execute(
            "SELECT id,code FROM roles WHERE status='active' ORDER BY id LIMIT 3"
        )]
        db.commit()
        yield db, pid, roles


def _payload(pid, steps):
    return {"process_id": pid, "idempotency_key": f"roles-{uuid.uuid4().hex}",
            "require_approval": 1, "approval_level": len(steps), "steps": steps}


def _counts(db):
    return tuple(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                 for table in ("approval_policies", "approval_policy_revisions",
                               "approval_policy_revision_steps", "approval_policy_events"))


@pytest.mark.parametrize("scenario", ["conflicting_code", "duplicate_id", "missing_id", "inactive_id"])
def test_invalid_role_identity_is_rejected_atomically(policy_context, scenario):
    db, pid, roles = policy_context
    first, second = roles[:2]
    if scenario == "conflicting_code":
        steps = [{"role_id": first["id"], "code": second["code"]}]
    elif scenario == "duplicate_id":
        steps = [{"role_id": first["id"], "code": first["code"]},
                 {"role_id": first["id"], "code": second["code"]}]
    elif scenario == "missing_id":
        steps = [{"role_id": 99999999, "code": first["code"]}]
    else:
        db.execute("UPDATE roles SET status='inactive' WHERE id=?", (second["id"],))
        db.commit()
        steps = [{"role_id": second["id"], "code": first["code"]}]
    before = _counts(db)
    with pytest.raises(ValidationError):
        ApprovalPolicyService.create_revision(_payload(pid, steps), {"id": 1, "name": "Maker"})
    assert _counts(db) == before, "Rejected policy must not leave partial persistence"


@pytest.mark.parametrize("level", [1, 2, 3])
@pytest.mark.parametrize("with_ids", [False, True])
def test_valid_distinct_roles_preserve_code_only_clients(policy_context, level, with_ids):
    db, pid, roles = policy_context
    steps = [{"code": row["code"], **({"role_id": row["id"]} if with_ids else {})}
             for row in roles[:level]]
    revision = ApprovalPolicyService.create_revision(_payload(pid, steps), {"id": 1, "name": "Maker"})
    actual = db.execute("SELECT role_id,role_code_snapshot FROM approval_policy_revision_steps "
                        "WHERE revision_id=? ORDER BY step_level", (revision["id"],)).fetchall()
    assert [(row[0], row[1]) for row in actual] == [(row["id"], row["code"]) for row in roles[:level]]


def test_duplicate_code_only_roles_are_rejected(policy_context):
    db, pid, roles = policy_context
    before = _counts(db)
    with pytest.raises(ValidationError, match="各级审批角色不能重复"):
        ApprovalPolicyService.create_revision(_payload(pid, [{"code": roles[0]["code"]}] * 2),
                                              {"id": 1, "name": "Maker"})
    assert _counts(db) == before


@pytest.mark.parametrize("duplicate", [False, True])
def test_historical_alias_uses_stable_identity(policy_context, duplicate):
    db, pid, roles = policy_context
    role = roles[0]
    alias = "old_" + uuid.uuid4().hex
    db.execute("INSERT INTO role_code_aliases(role_id,role_code) VALUES (?,?)", (role["id"], alias))
    db.commit()
    steps = [{"code": alias, "role_id": role["id"]}]
    if duplicate:
        steps.append({"code": role["code"]})
        before = _counts(db)
        with pytest.raises(ValidationError, match="各级审批角色不能重复"):
            ApprovalPolicyService.create_revision(_payload(pid, steps), {"id": 1, "name": "Maker"})
        assert _counts(db) == before
    else:
        revision = ApprovalPolicyService.create_revision(_payload(pid, steps), {"id": 1, "name": "Maker"})
        step = db.execute("SELECT role_id,role_code_snapshot FROM approval_policy_revision_steps WHERE revision_id=?",
                          (revision["id"],)).fetchone()
        assert (step[0], step[1]) == (role["id"], role["code"])


def test_role_identity_error_preserves_api_contract(policy_context, client, auth_headers):
    db, pid, roles = policy_context
    before = _counts(db)
    response = client.post("/api/approval-policies/revisions", headers=auth_headers,
                           json=_payload(pid, [{"role_id": roles[0]["id"], "code": roles[1]["code"]}]))
    assert response.status_code == 400
    assert response.get_json() == {"error": "审批角色 ID 与编码不一致", "code": "validation_error"}
    assert _counts(db) == before
