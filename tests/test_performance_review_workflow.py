import pytest

from modules.db import get_db
from modules.domain.errors import ConflictError
from modules.services.performance_ledger_service import PerformanceLedgerService

from tests.test_performance_ledger import _actor, _create, _setup


def _review_actor(db, suffix, department_id, *, wildcard=False):
    actor_id = db.execute(
        "INSERT INTO users (username,password,name,role,employee_no,status) "
        "VALUES (?,?,?,?,?,'active')",
        (
            "performance-review-actor-" + suffix,
            "hash",
            "绩效主管-" + suffix,
            "worker",
            "PERF-REVIEW-ACTOR-" + suffix.upper(),
        ),
    ).lastrowid
    db.execute(
        "INSERT INTO performance_department_scopes "
        "(user_id,department_id,granted_by,granted_by_name) VALUES (?,?,?,?)",
        (actor_id, department_id, actor_id, "绩效主管-" + suffix),
    )
    db.commit()
    return {
        "id": actor_id,
        "name": "绩效主管-" + suffix,
        "_permissions": ["*"] if wildcard else ["performance:review_department"],
    }


def _review_data(batch_id, user_id, row_version, key, **overrides):
    data = {
        "batch_id": batch_id,
        "user_id": user_id,
        "row_version": row_version,
        "idempotency_key": key,
        "manual_score": 5,
        "manual_comment": "现场复核确认存在执行偏差",
        "request_id": key + ":request",
    }
    data.update(overrides)
    return data


def _to_supervisor_review(db, batch_id):
    db.execute(
        "UPDATE performance_batches SET status='supervisor_review' WHERE id=?",
        (batch_id,),
    )
    db.commit()


def test_review_requires_supervisor_state_and_authorized_department(client):
    with client.application.app_context():
        db = get_db()
        preparer, _, _, department_id, users = _setup(db, "review-state", workers=1)
        batch = _create(preparer, "performance-review:state")

        reviewer = _review_actor(db, "state", department_id)
        with pytest.raises(ConflictError, match="主管复核状态"):
            PerformanceLedgerService.save_supervisor_review(
                _review_data(batch["batch_id"], users[0], batch["row_version"], "review:state"),
                reviewer,
            )

        _to_supervisor_review(db, batch["batch_id"])
        outside_reviewer = _actor(db, "outside")
        outside_reviewer["_permissions"] = ["performance:review_department"]
        db.commit()
        with pytest.raises(PermissionError, match="无权"):
            PerformanceLedgerService.save_supervisor_review(
                _review_data(
                    batch["batch_id"], users[0], batch["row_version"], "review:outside"
                ),
                outside_reviewer,
            )


def test_review_reason_requirements_are_checked_before_append(client):
    with client.application.app_context():
        db = get_db()
        preparer, _, _, department_id, users = _setup(db, "review-reasons", workers=1)
        batch = _create(preparer, "performance-review:reasons")
        _to_supervisor_review(db, batch["batch_id"])
        reviewer = _review_actor(db, "reasons", department_id)

        for key, values in (
            ("discipline", {"discipline_deduction": 1}),
            ("improvement", {"improvement_adjustment": 1}),
            ("manual", {"manual_score": 9, "manual_comment": ""}),
        ):
            with pytest.raises(ValueError, match="原因|说明"):
                PerformanceLedgerService.save_supervisor_review(
                    _review_data(
                        batch["batch_id"],
                        users[0],
                        batch["row_version"],
                        "review:reason:" + key,
                        **values,
                    ),
                    reviewer,
                )
        assert db.execute(
            "SELECT COUNT(*) FROM performance_reviews_v2 WHERE batch_id=?",
            (batch["batch_id"],),
        ).fetchone()[0] == 0


def test_review_appends_revision_and_recalculates_entire_position_group(client):
    with client.application.app_context():
        db = get_db()
        preparer, _, position_id, department_id, users = _setup(
            db, "review-ranking", workers=3
        )
        batch = _create(preparer, "performance-review:ranking")
        _to_supervisor_review(db, batch["batch_id"])
        reviewer = _review_actor(db, "ranking", department_id)

        result = PerformanceLedgerService.save_supervisor_review(
            _review_data(
                batch["batch_id"],
                users[0],
                batch["row_version"],
                "review:ranking:v1",
            ),
            reviewer,
        )
        assert result["idempotent_replay"] is False
        assert set(result["changed_user_ids"]) == set(users[:2])
        reviews = db.execute(
            "SELECT * FROM performance_reviews_v2 WHERE batch_id=?",
            (batch["batch_id"],),
        ).fetchall()
        assert len(reviews) == 1
        rows = db.execute(
            "SELECT * FROM performance_score_revisions WHERE batch_id=? "
            "ORDER BY user_id,revision",
            (batch["batch_id"],),
        ).fetchall()
        assert len(rows) == 5
        assert {row["revision"] for row in rows} == {1, 2}
        latest = [row for row in rows if row["revision"] == 2]
        assert {row["user_id"] for row in latest} == set(users[:2])
        assert {row["position_id_snapshot"] for row in latest} == {position_id}
        assert len({row["calculated_at"] for row in latest}) == 1
        assert len({row["ranking_digest"] for row in latest}) == 1
        assert len({row["calculation_group_id"] for row in latest}) == 1
        assert latest[0]["manual_score"] == 5
        assert latest[0]["review_revision_id"] == reviews[0]["id"]
        assert db.execute(
            "SELECT row_version FROM performance_batches WHERE id=?",
            (batch["batch_id"],),
        ).fetchone()[0] == batch["row_version"] + 1

        replay = PerformanceLedgerService.save_supervisor_review(
            _review_data(
                batch["batch_id"],
                users[0],
                batch["row_version"],
                "review:ranking:v1",
            ),
            reviewer,
        )
        assert replay["idempotent_replay"] is True
        assert db.execute(
            "SELECT COUNT(*) FROM performance_reviews_v2 WHERE batch_id=?",
            (batch["batch_id"],),
        ).fetchone()[0] == 1
        assert db.execute(
            "SELECT COUNT(*) FROM performance_score_revisions WHERE batch_id=?",
            (batch["batch_id"],),
        ).fetchone()[0] == 5

        with pytest.raises(ConflictError, match="版本号"):
            PerformanceLedgerService.save_supervisor_review(
                _review_data(
                    batch["batch_id"],
                    users[1],
                    batch["row_version"],
                    "review:ranking:stale",
                ),
                reviewer,
            )


def test_review_failure_rolls_back_review_scores_and_batch_version(client, monkeypatch):
    with client.application.app_context():
        db = get_db()
        preparer, _, _, department_id, users = _setup(db, "review-rollback", workers=3)
        batch = _create(preparer, "performance-review:rollback")
        _to_supervisor_review(db, batch["batch_id"])
        reviewer = _review_actor(db, "rollback", department_id)
        repository = __import__(
            "modules.repositories.performance_ledger_repository",
            fromlist=["PerformanceLedgerRepository"],
        ).PerformanceLedgerRepository
        original = repository.insert_score_revision

        def fail_insert(payload, db):
            raise RuntimeError("forced score failure")

        monkeypatch.setattr(repository, "insert_score_revision", fail_insert)
        with pytest.raises(RuntimeError, match="forced score failure"):
            PerformanceLedgerService.save_supervisor_review(
                _review_data(
                    batch["batch_id"],
                    users[0],
                    batch["row_version"],
                    "review:rollback:v1",
                ),
                reviewer,
            )
        monkeypatch.setattr(repository, "insert_score_revision", original)
        assert db.execute(
            "SELECT COUNT(*) FROM performance_reviews_v2 WHERE batch_id=?",
            (batch["batch_id"],),
        ).fetchone()[0] == 0
        assert db.execute(
            "SELECT COUNT(*) FROM performance_score_revisions WHERE batch_id=? AND revision>1",
            (batch["batch_id"],),
        ).fetchone()[0] == 0
        assert db.execute(
            "SELECT row_version FROM performance_batches WHERE id=?",
            (batch["batch_id"],),
        ).fetchone()[0] == batch["row_version"]
        assert db.execute(
            "SELECT COUNT(*) FROM performance_batch_events WHERE batch_id=? AND event_type='supervisor_review_saved'",
            (batch["batch_id"],),
        ).fetchone()[0] == 0
