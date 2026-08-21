import json
import uuid

import pytest

from modules.db import get_db
from modules.services import BaseService
from modules.services.position_audit_service import PositionAuditService


def _position(db):
    position_id = db.execute(
        "INSERT INTO positions(name,description,status) VALUES (?, '', 'active')",
        (f"Audit Position {uuid.uuid4().hex[:8]}",),
    ).lastrowid
    db.commit()
    return position_id


def test_position_audit_is_mandatory_structured_and_idempotent(client):
    with client.application.app_context():
        db = get_db()
        position_id = _position(db)
        with BaseService.transaction() as txn:
            first_id = PositionAuditService.record(
                txn,
                action="position_version_approve",
                actor={"id": 1000, "name": "Reviewer", "role": "admin"},
                request_id="position-request-1",
                idempotency_key="position-audit-idempotent-1",
                position_id=position_id,
                position_version_id=17,
                before={
                    "name": "Old Position",
                    "description": "Old",
                    "process_ids": [1, 2],
                },
                after={
                    "name": "New Position",
                    "description": "New",
                    "process_ids": [2, 3],
                },
                reason="Approved revision",
                impact_digest="impact-1",
            )
            replay_id = PositionAuditService.record(
                txn,
                action="position_version_approve",
                actor={"id": 1000, "name": "Reviewer", "role": "admin"},
                request_id="position-request-1",
                idempotency_key="position-audit-idempotent-1",
                position_id=position_id,
                position_version_id=17,
                before={"name": "ignored", "process_ids": []},
                after={"name": "ignored too", "process_ids": []},
            )

        row = db.execute(
            "SELECT * FROM audit_logs WHERE id=?", (first_id,)
        ).fetchone()
        detail = json.loads(row["detail"])

    assert replay_id == first_id
    assert row["category"] == "master_data"
    assert row["mandatory"] == 1
    assert row["request_id"] == "position-request-1"
    assert detail["changed_fields"] == ["name", "description", "process_ids"]
    assert detail["added_process_ids"] == [3]
    assert detail["removed_process_ids"] == [1]
    assert detail["position_version_id"] == 17


def test_position_audit_failure_rolls_back_business_transaction(client, monkeypatch):
    with client.application.app_context():
        db = get_db()
        position_id = _position(db)
        original_name = db.execute(
            "SELECT name FROM positions WHERE id=?", (position_id,)
        ).fetchone()["name"]

        def fail_insert(*args, **kwargs):
            raise RuntimeError("audit failed")

        monkeypatch.setattr(PositionAuditService, "_insert", fail_insert)
        with pytest.raises(RuntimeError, match="audit failed"):
            with BaseService.transaction() as txn:
                txn.execute(
                    "UPDATE positions SET description='must rollback' WHERE id=?",
                    (position_id,),
                )
                PositionAuditService.record(
                    txn,
                    action="position_version_update",
                    actor={"id": 1000, "name": "Reviewer"},
                    idempotency_key="position-audit-failure-1",
                    position_id=position_id,
                    before={"name": original_name, "description": "", "process_ids": []},
                    after={
                        "name": original_name,
                        "description": "must rollback",
                        "process_ids": [],
                    },
                )

        row = db.execute(
            "SELECT description FROM positions WHERE id=?", (position_id,)
        ).fetchone()
        assert row["description"] == ""
        assert db.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE action='position_version_update'"
        ).fetchone()[0] == 0
