import sqlite3

import pytest

from modules.db import get_db
from modules.domain.errors import ConflictError
from modules.repositories.performance_ledger_repository import (
    PerformanceLedgerRepository,
)
from modules.services.performance_ledger_service import PerformanceLedgerService

from tests.test_performance_ledger import _create, _setup, _work
from tests.test_performance_review_workflow import _review_actor, _review_data


def _actor(db, suffix, permissions):
    actor_id = db.execute(
        "INSERT INTO users (username,password,name,role,employee_no,status) "
        "VALUES (?,?,?,?,?,'active')",
        (
            "performance-workflow-actor-" + suffix,
            "hash",
            "绩效流程人员-" + suffix,
            "worker",
            "PERF-WORKFLOW-" + suffix.upper(),
        ),
    ).lastrowid
    db.commit()
    return {
        "id": actor_id,
        "name": "绩效流程人员-" + suffix,
        "_permissions": permissions,
    }


def _command(row_version, key, reason=""):
    return {
        "row_version": row_version,
        "idempotency_key": key,
        "request_id": key + ":request",
        "reason": reason,
    }


def _fully_reviewed(db, batch, preparer, department_id, users, suffix):
    result = PerformanceLedgerService.submit_supervisor_review(
        batch["batch_id"],
        _command(batch["row_version"], "workflow:review:" + suffix),
        preparer,
    )
    reviewer = _review_actor(db, suffix, department_id)
    for index, user_id in enumerate(users):
        result = PerformanceLedgerService.save_supervisor_review(
            _review_data(
                batch["batch_id"],
                user_id,
                result["row_version"],
                f"workflow:member-review:{suffix}:{index}",
            ),
            reviewer,
        )
    return result


def _pending_approval(db, batch, preparer, department_id, users, suffix):
    reviewed = _fully_reviewed(
        db, batch, preparer, department_id, users, suffix
    )
    return PerformanceLedgerService.submit_approval(
        batch["batch_id"],
        _command(reviewed["row_version"], "workflow:approval:" + suffix),
        preparer,
    )


def _approve(db, batch, preparer, department_id, users, suffix):
    pending = _pending_approval(
        db, batch, preparer, department_id, users, suffix
    )
    approver = _actor(
        db,
        "approver-" + suffix,
        ["performance:view_all", "performance:approve"],
    )
    approved = PerformanceLedgerService.approve_batch(
        batch["batch_id"],
        _command(pending["row_version"], "workflow:approve:" + suffix),
        approver,
    )
    return approved, approver


def _issue_codes(error):
    return {
        item["code"]
        for item in (error.value.details or {}).get("issues", [])
    }


def test_submit_review_and_independent_approval_are_idempotent(client):
    with client.application.app_context():
        db = get_db()
        preparer, _, _, department_id, users = _setup(
            db, "batch-happy", workers=2
        )
        batch = _create(preparer, "performance-batch:happy")

        pending = _pending_approval(
            db, batch, preparer, department_id, users, "batch-happy"
        )
        approver = _actor(
            db,
            "batch-happy-approver",
            ["performance:view_all", "performance:approve"],
        )
        approved = PerformanceLedgerService.approve_batch(
            batch["batch_id"],
            _command(pending["row_version"], "workflow:approve:batch-happy"),
            approver,
        )
        replay = PerformanceLedgerService.approve_batch(
            batch["batch_id"],
            _command(pending["row_version"], "workflow:approve:batch-happy"),
            approver,
        )

        assert approved["status"] == "approved"
        assert approved["batch"]["approved_by"] == approver["id"]
        assert approved["batch"]["prepared_by"] == preparer["id"]
        assert replay["idempotent_replay"] is True
        assert replay["event_id"] == approved["event_id"]
        assert db.execute(
            "SELECT COUNT(*) FROM performance_batch_events WHERE batch_id=? "
            "AND event_type='batch_approved'",
            (batch["batch_id"],),
        ).fetchone()[0] == 1


def test_submit_approval_reports_all_integrity_blockers(client):
    with client.application.app_context():
        db = get_db()
        preparer, _, _, _, _ = _setup(
            db, "batch-blockers", workers=1, target=False
        )
        batch = _create(preparer, "performance-batch:blockers")
        started = PerformanceLedgerService.submit_supervisor_review(
            batch["batch_id"],
            _command(batch["row_version"], "workflow:review:blockers"),
            preparer,
        )

        with pytest.raises(ConflictError) as error:
            PerformanceLedgerService.submit_approval(
                batch["batch_id"],
                _command(started["row_version"], "workflow:approval:blockers"),
                preparer,
            )

        assert "unresolved_exceptions" in _issue_codes(error)
        assert db.execute(
            "SELECT status FROM performance_batches WHERE id=?",
            (batch["batch_id"],),
        ).fetchone()[0] == "supervisor_review"


def test_submit_approval_requires_every_eligible_member_review(client):
    with client.application.app_context():
        db = get_db()
        preparer, _, _, _, _ = _setup(db, "batch-review-gap", workers=2)
        batch = _create(preparer, "performance-batch:review-gap")
        started = PerformanceLedgerService.submit_supervisor_review(
            batch["batch_id"],
            _command(batch["row_version"], "workflow:review:review-gap"),
            preparer,
        )

        with pytest.raises(ConflictError) as error:
            PerformanceLedgerService.submit_approval(
                batch["batch_id"],
                _command(
                    started["row_version"], "workflow:approval:review-gap"
                ),
                preparer,
            )

        assert "incomplete_reviews" in _issue_codes(error)


def test_input_drift_cancels_old_batch_and_creates_fresh_version(client):
    with client.application.app_context():
        db = get_db()
        preparer, _, _, department_id, users = _setup(
            db, "batch-drift", workers=1
        )
        batch = _create(preparer, "performance-batch:drift")
        reviewed = _fully_reviewed(
            db, batch, preparer, department_id, users, "batch-drift"
        )
        frozen_fact_count = db.execute(
            "SELECT COUNT(*) FROM performance_source_facts WHERE batch_id=?",
            (batch["batch_id"],),
        ).fetchone()[0]
        late_work_id = _work(
            db, users[0], "batch-drift-late", quantity=15, day=25
        )
        db.execute(
            "UPDATE work_records SET created_at=datetime('now','localtime') "
            "WHERE id=?",
            (late_work_id,),
        )
        db.commit()

        replaced = PerformanceLedgerService.submit_approval(
            batch["batch_id"],
            _command(reviewed["row_version"], "workflow:approval:drift"),
            preparer,
        )
        replay = PerformanceLedgerService.submit_approval(
            batch["batch_id"],
            _command(reviewed["row_version"], "workflow:approval:drift"),
            preparer,
        )

        replacement_id = replaced["replacement_batch_id"]
        assert replaced["input_drift_detected"] is True
        assert replaced["status"] == "cancelled"
        assert replaced["replacement"]["status"] == "draft"
        assert replaced["replacement"]["version"] == batch["version"] + 1
        assert replay["replacement_batch_id"] == replacement_id
        assert replay["idempotent_replay"] is True
        assert db.execute(
            "SELECT COUNT(*) FROM performance_source_facts WHERE batch_id=?",
            (batch["batch_id"],),
        ).fetchone()[0] == frozen_fact_count
        assert db.execute(
            "SELECT COUNT(*) FROM performance_source_facts WHERE batch_id=?",
            (replacement_id,),
        ).fetchone()[0] > frozen_fact_count


def test_return_and_cancel_require_reason_and_respect_row_version(client):
    with client.application.app_context():
        db = get_db()
        preparer, _, _, _, _ = _setup(db, "batch-return", workers=1)
        batch = _create(preparer, "performance-batch:return")
        started = PerformanceLedgerService.submit_supervisor_review(
            batch["batch_id"],
            _command(batch["row_version"], "workflow:review:return"),
            preparer,
        )

        with pytest.raises(ValueError, match="原因"):
            PerformanceLedgerService.return_batch(
                batch["batch_id"],
                _command(started["row_version"], "workflow:return:missing"),
                preparer,
            )
        returned = PerformanceLedgerService.return_batch(
            batch["batch_id"],
            _command(
                started["row_version"],
                "workflow:return:valid",
                "主管复核资料需要补充",
            ),
            preparer,
        )
        assert returned["status"] == "draft"

        with pytest.raises(ConflictError, match="版本"):
            PerformanceLedgerService.cancel_batch(
                batch["batch_id"],
                _command(
                    started["row_version"],
                    "workflow:cancel:stale",
                    "旧请求取消",
                ),
                preparer,
            )
        cancelled = PerformanceLedgerService.cancel_batch(
            batch["batch_id"],
            _command(
                returned["row_version"],
                "workflow:cancel:valid",
                "本批次不再使用",
            ),
            preparer,
        )
        assert cancelled["status"] == "cancelled"


def test_approval_return_requires_independent_approver(client):
    with client.application.app_context():
        db = get_db()
        preparer, _, _, department_id, users = _setup(
            db, "batch-approval-return", workers=1
        )
        batch = _create(preparer, "performance-batch:approval-return")
        pending = _pending_approval(
            db,
            batch,
            preparer,
            department_id,
            users,
            "batch-approval-return",
        )
        preparer["_permissions"] = ["*"]

        with pytest.raises(PermissionError, match="不同用户"):
            PerformanceLedgerService.approve_batch(
                batch["batch_id"],
                _command(
                    pending["row_version"], "workflow:approve:same-actor"
                ),
                preparer,
            )
        approver = _actor(
            db,
            "batch-return-approver",
            ["performance:view_all", "performance:approve"],
        )
        with pytest.raises(ValueError, match="原因"):
            PerformanceLedgerService.return_batch(
                batch["batch_id"],
                _command(
                    pending["row_version"], "workflow:return-approval:missing"
                ),
                approver,
            )
        returned = PerformanceLedgerService.return_batch(
            batch["batch_id"],
            _command(
                pending["row_version"],
                "workflow:return-approval:valid",
                "批准证据不充分",
            ),
            approver,
        )
        assert returned["status"] == "supervisor_review"


def test_new_revision_atomically_supersedes_current_approved_batch(client):
    with client.application.app_context():
        db = get_db()
        preparer, _, _, department_id, users = _setup(
            db, "batch-supersede", workers=2
        )
        first = _create(preparer, "performance-batch:supersede:v1")
        first_approved, _ = _approve(
            db,
            first,
            preparer,
            department_id,
            users,
            "batch-supersede-v1",
        )
        revision = PerformanceLedgerService.create_revision(
            first["batch_id"],
            {
                "row_version": first_approved["row_version"],
                "idempotency_key": "workflow:revision:supersede:v2",
                "request_id": "workflow:revision:supersede:v2:request",
                "reason": "修正本月绩效来源",
            },
            preparer,
        )
        second_approved, _ = _approve(
            db,
            revision,
            preparer,
            department_id,
            users,
            "batch-supersede-v2",
        )

        old = PerformanceLedgerRepository.batch(first["batch_id"], db=db)
        current = PerformanceLedgerRepository.current_approved_batch(
            first["production_month"], db=db
        )
        comparison = PerformanceLedgerService.compare_batches(
            first["batch_id"], revision["batch_id"], actor=preparer, db=db
        )
        assert first_approved["status"] == "approved"
        assert second_approved["status"] == "approved"
        assert old["status"] == "superseded"
        assert old["superseded_by_batch_id"] == revision["batch_id"]
        assert current["id"] == revision["batch_id"]
        assert comparison["base_batch_id"] == first["batch_id"]
        assert comparison["compare_batch_id"] == revision["batch_id"]
        assert {item["user_id"] for item in comparison["items"]} == set(users)


def test_supersession_failure_rolls_back_old_and_new_batches(client, monkeypatch):
    with client.application.app_context():
        db = get_db()
        preparer, _, _, department_id, users = _setup(
            db, "batch-supersede-rollback", workers=1
        )
        first = _create(preparer, "performance-batch:rollback:v1")
        first_approved, _ = _approve(
            db,
            first,
            preparer,
            department_id,
            users,
            "batch-supersede-rollback-v1",
        )
        revision = PerformanceLedgerService.create_revision(
            first["batch_id"],
            {
                "row_version": first_approved["row_version"],
                "idempotency_key": "workflow:revision:rollback:v2",
                "reason": "验证取代事务回滚",
            },
            preparer,
        )
        pending = _pending_approval(
            db,
            revision,
            preparer,
            department_id,
            users,
            "batch-supersede-rollback-v2",
        )
        approver = _actor(
            db,
            "batch-supersede-rollback-approver",
            ["performance:view_all", "performance:approve"],
        )

        def fail_approval(*args, **kwargs):
            raise RuntimeError("forced approval failure")

        monkeypatch.setattr(
            PerformanceLedgerRepository,
            "approve_batch",
            staticmethod(fail_approval),
        )
        with pytest.raises(RuntimeError, match="forced approval failure"):
            PerformanceLedgerService.approve_batch(
                revision["batch_id"],
                _command(
                    pending["row_version"],
                    "workflow:approve:supersede-rollback",
                ),
                approver,
            )

        assert PerformanceLedgerRepository.batch(
            first["batch_id"], db=db
        )["status"] == "approved"
        assert PerformanceLedgerRepository.batch(
            revision["batch_id"], db=db
        )["status"] == "approval_pending"
        assert db.execute(
            "SELECT COUNT(*) FROM performance_batch_events WHERE batch_id=? "
            "AND event_type='batch_approved'",
            (revision["batch_id"],),
        ).fetchone()[0] == 0


def test_approved_batch_cannot_accept_new_reviews_or_mutate_facts(client):
    with client.application.app_context():
        db = get_db()
        preparer, _, _, department_id, users = _setup(
            db, "batch-immutable", workers=1
        )
        batch = _create(preparer, "performance-batch:immutable")
        approved, _ = _approve(
            db,
            batch,
            preparer,
            department_id,
            users,
            "batch-immutable",
        )
        reviewer = _review_actor(db, "batch-immutable-late", department_id)

        with pytest.raises(ConflictError, match="主管复核状态"):
            PerformanceLedgerService.save_supervisor_review(
                _review_data(
                    batch["batch_id"],
                    users[0],
                    approved["row_version"],
                    "workflow:member-review:immutable-late",
                ),
                reviewer,
            )
        fact_id = db.execute(
            "SELECT id FROM performance_source_facts WHERE batch_id=? LIMIT 1",
            (batch["batch_id"],),
        ).fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(
                "UPDATE performance_source_facts SET source_digest='changed' "
                "WHERE id=?",
                (fact_id,),
            )
