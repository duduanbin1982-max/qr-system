#!/usr/bin/env python3
"""Validate the V57 performance cutover against an online SQLite replica.

The source database is opened read-only and copied with SQLite's online backup
API. All migrations, authorization provisioning, historical V2 generation and
workflow acceptance tests run only against the newly created replica.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys

import bcrypt


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("SECRET_KEY", "offline-replica-validation-only")

from modules.access_policy import collect_permission_codes  # noqa: E402
from modules.domain import evidence_protocol  # noqa: E402
from modules.migrations import LATEST_VERSION, run_migrations  # noqa: E402
from modules.repositories.access_policy_repository import (  # noqa: E402
    AccessPolicyRepository,
)
from modules.repositories.performance_history_migration_repository import (  # noqa: E402
    PerformanceHistoryMigrationRepository,
)
from modules.repositories.performance_ledger_repository import (  # noqa: E402
    PerformanceLedgerRepository,
)
from modules.services.performance_assignment_department_service import (  # noqa: E402
    PerformanceAssignmentDepartmentService,
)
from modules.services.performance_authorization_service import (  # noqa: E402
    PerformanceAuthorizationService,
)
from modules.services.performance_history_migration_service import (  # noqa: E402
    PerformanceHistoryMigrationService,
)
from modules.services.performance_improvement_service import (  # noqa: E402
    PerformanceImprovementService,
)
from modules.services.performance_ledger_service import (  # noqa: E402
    PerformanceLedgerService,
)
from scripts import production_operations  # noqa: E402


EXPECTED_COUNTS = {
    "overwritten_score_count": 64,
    "missing_position_count": 30,
    "cross_month_work_count": 5,
    "cross_month_quality_count": 11,
}
DEDICATED_ACCOUNT_BASE_ROLE = "worker"
SOURCE_ACTORS = {
    "preparer": {"id": 10304, "username": "1001", "name": "杨冰"},
    "approver": {"id": 10305, "username": "1002", "name": "时文芳"},
    "reviewer": {"id": 10333, "username": "1000", "name": "杜斌"},
    "plan_manager": {"id": 10334, "username": "1004", "name": "Dooley"},
    "reassessor": {"id": 10335, "username": "1005", "name": "王晓璐"},
}
DEDICATED_ACCOUNTS = {
    "reviewer": {
        "username": "1000_perf",
        "name": "杜斌",
        "employee_no": "PERF-REVIEW",
        "role_code": "performance_reviewer_v57",
        "role_name": "绩效主管复核",
        "permissions": [
            "page:performance",
            "performance:view_department",
            "performance:review_department",
        ],
    },
    "plan_manager": {
        "username": "1004_plan",
        "name": "Dooley",
        "employee_no": "PERF-PLAN",
        "role_code": "performance_plan_manager_v57",
        "role_name": "绩效改进计划管理",
        "permissions": [
            "page:performance",
            "performance:view_department",
            "performance:plan_manage",
        ],
    },
    "reassessor": {
        "username": "1005_reassess",
        "name": "王晓璐",
        "employee_no": "PERF-REASSESS",
        "role_code": "performance_reassessor_v57",
        "role_name": "绩效改进计划复评",
        "permissions": [
            "page:performance",
            "performance:view_department",
            "performance:plan_reassess",
        ],
    },
}
POSITION_DEPARTMENTS = {
    "切割工": "下料班组",
    "铆工": "铆接班组",
    "焊工": "焊接班组",
    "抛丸工": "抛丸班组",
    "打磨工": "打磨班组",
    "镗工": "镗孔班组",
    "喷漆工": "喷漆班组",
    "车工": "机加工班组",
    "铣工": "机加工班组",
    "普工": "生产部",
}


def _parser():
    parser = argparse.ArgumentParser(
        description="Run the full V57 performance acceptance flow on a new replica."
    )
    parser.add_argument("--source-db", required=True)
    parser.add_argument("--replica-db", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--from-month", default="2026-06")
    parser.add_argument("--to-month", default="2026-07")
    parser.add_argument(
        "--confirm-replica-validation",
        action="store_true",
        help="Required acknowledgement that the destination is disposable.",
    )
    return parser


def _canonical(value):
    return evidence_protocol.canonical_json_v1(value)


def _sha256(path):
    return production_operations.file_fingerprint(path)["sha256"]


def _rows(db, sql, params=()):
    return [dict(row) for row in db.execute(sql, params).fetchall()]


def _scalar(db, sql, params=()):
    return db.execute(sql, params).fetchone()[0]


def _database_checks(db):
    return {
        "user_version": int(_scalar(db, "PRAGMA user_version")),
        "integrity_check": _scalar(db, "PRAGMA integrity_check"),
        "foreign_key_violations": len(_rows(db, "PRAGMA foreign_key_check")),
    }


def _batch_fingerprint(db):
    return {
        "legacy_batches": int(
            _scalar(db, "SELECT COUNT(*) FROM performance_batches WHERE version=1")
        ),
        "v2_batches": int(
            _scalar(db, "SELECT COUNT(*) FROM performance_batches WHERE version>=2")
        ),
        "legacy_scores": int(
            _scalar(
                db,
                "SELECT COUNT(*) FROM performance_score_revisions score "
                "JOIN performance_batches batch ON batch.id=score.batch_id "
                "WHERE batch.version=1",
            )
        ),
    }


def _assignment_rows(db):
    return _rows(
        db,
        "SELECT * FROM performance_assignment_history "
        "WHERE created_by=10304 AND source_type IN "
        "('manual_history_confirmation','legacy_score_snapshot') "
        "ORDER BY id",
    )


def _assignment_digest(rows):
    return hashlib.sha256(_canonical(rows).encode("utf-8")).hexdigest()


def _validate_source_actors(db):
    result = {}
    for key, expected in SOURCE_ACTORS.items():
        row = db.execute(
            "SELECT id,username,name,status FROM users WHERE id=?",
            (expected["id"],),
        ).fetchone()
        if not row:
            raise RuntimeError(f"{key} source user {expected['id']} does not exist")
        actual = dict(row)
        if actual["username"] != expected["username"] or actual["name"] != expected["name"]:
            raise RuntimeError(f"{key} source identity does not match confirmation")
        if actual["status"] != "active":
            raise RuntimeError(f"{key} source identity is not active")
        result[key] = actual
    return result


def _online_backup(source_path, replica_path):
    production_operations.online_database_backup(source_path, replica_path)


def _ensure_department(db, name):
    matches = _rows(db, "SELECT id,name,status FROM departments WHERE name=?", (name,))
    if len(matches) > 1:
        raise RuntimeError(f"department name is ambiguous: {name}")
    if matches:
        if matches[0]["status"] != "active":
            raise RuntimeError(f"department is not active: {name}")
        return int(matches[0]["id"]), False
    department_id = db.execute(
        "INSERT INTO departments (name,description,status) VALUES (?,?,'active')",
        (name, "绩效 V57 历史部门补充验收"),
    ).lastrowid
    return int(department_id), True


def _ensure_role(db, account):
    permissions = _canonical(account["permissions"])
    row = db.execute(
        "SELECT * FROM roles WHERE code=?", (account["role_code"],)
    ).fetchone()
    if row:
        row = dict(row)
        if row["permissions"] != permissions or row["status"] != "active":
            raise RuntimeError("replica role already exists with unexpected content")
        return int(row["id"])
    return int(
        db.execute(
            "INSERT INTO roles (name,code,description,level,permissions,status) "
            "VALUES (?,?,?,1,?,'active')",
            (
                account["role_name"],
                account["role_code"],
                "绩效 V57 副本验收专用最小权限角色",
                permissions,
            ),
        ).lastrowid
    )


def _create_dedicated_account(db, account):
    if db.execute(
        "SELECT 1 FROM users WHERE username=?", (account["username"],)
    ).fetchone():
        raise RuntimeError(f"dedicated username is already occupied: {account['username']}")
    random_password = secrets.token_urlsafe(48).encode("utf-8")
    password_hash = bcrypt.hashpw(random_password, bcrypt.gensalt()).decode("utf-8")
    user_id = int(
        db.execute(
            "INSERT INTO users (username,password,name,role,employee_no,status,password_version) "
            "VALUES (?,?,?,?,?,'inactive',2)",
            (
                account["username"],
                password_hash,
                account["name"],
                DEDICATED_ACCOUNT_BASE_ROLE,
                account["employee_no"],
            ),
        ).lastrowid
    )
    role_id = _ensure_role(db, account)
    db.execute(
        "INSERT INTO user_roles (user_id,role_id,granted_by) VALUES (?,?,?)",
        (user_id, role_id, SOURCE_ACTORS["preparer"]["id"]),
    )
    return user_id, role_id


def _actor(db, user_id):
    row = db.execute(
        "SELECT id,username,name,status FROM users WHERE id=?", (user_id,)
    ).fetchone()
    if not row:
        raise RuntimeError(f"actor {user_id} does not exist")
    actor = dict(row)
    actor["_permissions"] = collect_permission_codes(
        AccessPolicyRepository.get_permission_rows(user_id, db=db),
        user_id=user_id,
    )
    return actor


def _replace_scopes(db, user_id, department_ids):
    db.execute("DELETE FROM performance_department_scopes WHERE user_id=?", (user_id,))
    for department_id in department_ids:
        db.execute(
            "INSERT INTO performance_department_scopes "
            "(user_id,department_id,granted_by,granted_by_name) VALUES (?,?,10304,'杨冰')",
            (user_id, department_id),
        )


def _provision_replica_authorization(db):
    machine_id, created = _ensure_department(db, "机加工班组")
    production_departments = _rows(
        db,
        "SELECT id,name FROM departments WHERE id BETWEEN 1 AND 8 ORDER BY id",
    )
    if [row["id"] for row in production_departments] != list(range(1, 9)):
        raise RuntimeError("confirmed production departments 1 through 8 are incomplete")
    scope_ids = [int(row["id"]) for row in production_departments] + [machine_id]
    accounts = {}
    for key, definition in DEDICATED_ACCOUNTS.items():
        user_id, role_id = _create_dedicated_account(db, definition)
        _replace_scopes(db, user_id, scope_ids)
        accounts[key] = {
            "user_id": user_id,
            "role_id": role_id,
            "username": definition["username"],
            "name": definition["name"],
            "base_role": DEDICATED_ACCOUNT_BASE_ROLE,
            "status": "inactive",
            "permissions": list(definition["permissions"]),
            "department_ids": scope_ids,
        }
    return {
        "machine_department_id": machine_id,
        "machine_department_created": created,
        "production_department_ids": scope_ids,
        "accounts": accounts,
    }


def _apply_department_revisions(db, assignments):
    departments = {
        row["name"]: int(row["id"])
        for row in _rows(db, "SELECT id,name FROM departments WHERE status='active'")
    }
    missing_departments = sorted(set(POSITION_DEPARTMENTS.values()) - set(departments))
    if missing_departments:
        raise RuntimeError("missing mapped departments: " + ", ".join(missing_departments))
    preparer = {
        **SOURCE_ACTORS["preparer"],
        "_permissions": ["performance:prepare"],
    }
    approver = {
        **SOURCE_ACTORS["approver"],
        "_permissions": ["performance:approve"],
    }
    created = []
    mapping_counts = Counter()
    for assignment in assignments:
        position_name = assignment["position_name_snapshot"]
        department_name = POSITION_DEPARTMENTS.get(position_name)
        if not department_name:
            raise RuntimeError(f"position has no confirmed department: {position_name}")
        department_id = departments[department_name]
        source_key = (
            "performance-v57:department-supplement:assignment:"
            f"{assignment['id']}:department:{department_id}"
        )
        draft = PerformanceAssignmentDepartmentService.create_revision(
            {
                "assignment_id": assignment["id"],
                "department_id": department_id,
                "reason": "业务负责人确认历史岗位部门归属",
                "source_type": "manual_history_department_confirmation",
                "source_key": source_key,
            },
            preparer,
            db=db,
        )
        approved = PerformanceAssignmentDepartmentService.approve_revision(
            draft["id"], approver, draft["row_version"], db=db
        )
        created.append(approved)
        mapping_counts[f"{position_name}->{department_name}"] += 1
    return created, dict(sorted(mapping_counts.items()))


def _assert_revision_immutable(db, revision_id):
    db.execute("SAVEPOINT immutable_revision_probe")
    try:
        try:
            db.execute(
                "UPDATE performance_assignment_department_revisions "
                "SET department_name_snapshot='不应被写入' WHERE id=?",
                (revision_id,),
            )
        except sqlite3.IntegrityError:
            return True
        raise RuntimeError("approved department revision unexpectedly allowed mutation")
    finally:
        db.execute("ROLLBACK TO SAVEPOINT immutable_revision_probe")
        db.execute("RELEASE SAVEPOINT immutable_revision_probe")


def _historical_preflight(db, start_month, end_month):
    plan = PerformanceHistoryMigrationService.analyze(db, start_month, end_month)
    PerformanceHistoryMigrationService.validate_counts(plan, EXPECTED_COUNTS)
    if int(plan.get("quality_ambiguity_count") or 0) != 0:
        raise RuntimeError("historical quality sources are ambiguous")
    if int(plan.get("missing_target_count") or 0) != 0:
        raise RuntimeError("approved position target is missing")
    return plan


def _preflight_summary(plan):
    totals = plan.get("totals") or {}
    return {
        key: totals.get(key)
        for key in (*EXPECTED_COUNTS, "quality_ambiguity_count", "missing_target_count")
    }


def _latest_scores(db, batch_id):
    return PerformanceLedgerRepository.latest_score_revisions(batch_id, db=db)


def _review_and_approve_batches(db, applied, reviewer_actor):
    preparer = {
        **SOURCE_ACTORS["preparer"],
        "_permissions": ["performance:prepare"],
    }
    approver = {
        **SOURCE_ACTORS["approver"],
        "_permissions": ["performance:approve"],
    }
    reviewed = []
    for item in applied["months"]:
        batch_id = int(item["batch"]["id"])
        batch = PerformanceLedgerRepository.batch(batch_id, db=db)
        if batch["status"] == "draft":
            submitted = PerformanceLedgerService.submit_supervisor_review(
                batch_id,
                {
                    "expected_row_version": batch["row_version"],
                    "idempotency_key": f"v57-replica-submit-review:{batch_id}",
                },
                preparer,
                db=db,
            )
            batch = PerformanceLedgerRepository.batch(submitted["batch_id"], db=db)
        scores = _latest_scores(db, batch_id)
        if not scores:
            raise RuntimeError(f"V2 batch {batch_id} has no scores")
        for score in scores:
            if not PerformanceAuthorizationService.can_review_member(
                reviewer_actor, batch_id, int(score["user_id"]), db=db
            ):
                raise RuntimeError(
                    f"reviewer cannot review batch {batch_id} user {score['user_id']}"
                )
            summary = PerformanceLedgerService.save_supervisor_review(
                {
                    "batch_id": batch_id,
                    "user_id": int(score["user_id"]),
                    "expected_row_version": batch["row_version"],
                    "idempotency_key": (
                        f"v57-replica-review:{batch_id}:user:{score['user_id']}"
                    ),
                    "reason": "V57 副本中性复核验收",
                    "review": {},
                },
                reviewer_actor,
                db=db,
            )
            batch = PerformanceLedgerRepository.batch(summary["batch_id"], db=db)
        submitted = PerformanceLedgerService.submit_approval(
            batch_id,
            {
                "expected_row_version": batch["row_version"],
                "idempotency_key": f"v57-replica-submit-approval:{batch_id}",
            },
            preparer,
            db=db,
        )
        batch = PerformanceLedgerRepository.batch(submitted["batch_id"], db=db)
        approved = PerformanceLedgerService.approve_batch(
            batch_id,
            {
                "expected_row_version": batch["row_version"],
                "idempotency_key": f"v57-replica-approve:{batch_id}",
            },
            approver,
            db=db,
        )
        reviewed.append(
            {
                "batch_id": batch_id,
                "production_month": approved["batch"]["production_month"],
                "score_count": len(scores),
                "status": approved["batch"]["status"],
                "row_version": approved["batch"]["row_version"],
            }
        )
    return reviewed


def _exercise_improvement_plan(db, manager_actor, reassessor_actor, outside_department):
    score = db.execute(
        "SELECT score.*,batch.production_month FROM performance_score_revisions score "
        "JOIN performance_batches batch ON batch.id=score.batch_id "
        "WHERE batch.version=2 AND batch.status='approved' "
        "AND NOT EXISTS (SELECT 1 FROM performance_score_revisions newer "
        "WHERE newer.batch_id=score.batch_id AND newer.user_id=score.user_id "
        "AND newer.revision>score.revision) "
        "ORDER BY batch.production_month,score.user_id LIMIT 1"
    ).fetchone()
    if not score:
        raise RuntimeError("no approved V2 score is available for plan acceptance")
    score = dict(score)
    plan = PerformanceImprovementService.create_plan(
        {
            "score_revision_id": score["id"],
            "user_id": score["user_id"],
            "production_month": score["production_month"],
            "warning_level": score.get("warning_level") or "green",
            "reason": "V57 副本改进计划验收",
            "goal": "验证状态机、证据和部门权限",
            "actions": "提交模拟证据并由独立复评人完成复评",
            "owner_id": SOURCE_ACTORS["reviewer"]["id"],
            "due_date": "2026-09-30",
            "idempotency_key": "v57-replica-plan-create",
        },
        manager_actor,
        db=db,
    )
    active = PerformanceImprovementService.transition(
        plan["plan_id"],
        {
            "row_version": plan["row_version"],
            "target_status": "active",
            "idempotency_key": "v57-replica-plan-activate",
        },
        manager_actor,
        db=db,
    )
    evidence = PerformanceImprovementService.add_evidence(
        plan["plan_id"],
        {
            "row_version": active["row_version"],
            "evidence_type": "acceptance_test",
            "description": "V57 生产副本权限与状态机验收证据",
            "idempotency_key": "v57-replica-plan-evidence",
        },
        manager_actor,
        db=db,
    )
    pending = PerformanceImprovementService.transition(
        plan["plan_id"],
        {
            "row_version": evidence["row_version"],
            "target_status": "reassessment_pending",
            "idempotency_key": "v57-replica-plan-request-reassessment",
        },
        manager_actor,
        db=db,
    )
    closed = PerformanceImprovementService.reassess(
        plan["plan_id"],
        {
            "row_version": pending["row_version"],
            "result": "passed",
            "notes": "副本验收通过",
            "evidence_ids": [evidence["evidence_id"]],
            "idempotency_key": "v57-replica-plan-reassess",
        },
        reassessor_actor,
        db=db,
    )
    for actor, label in (
        (manager_actor, "plan manager"),
        (reassessor_actor, "reassessor"),
    ):
        try:
            PerformanceAuthorizationService.require_department_action_scope(
                actor,
                outside_department,
                "V57 replica outside-scope probe",
                db=db,
            )
        except PermissionError:
            continue
        raise RuntimeError(f"{label} unexpectedly passed outside-department scope")
    return {
        "plan_id": plan["plan_id"],
        "user_id": score["user_id"],
        "department_id": score["department_id_snapshot"],
        "status": closed["status"],
        "evidence_id": evidence["evidence_id"],
        "reassessment_id": closed["reassessment_id"],
        "outside_department_id": outside_department,
        "outside_scope_rejected": True,
    }


def _validate_frozen_departments(db):
    missing_scores = int(
        _scalar(
            db,
            "SELECT COUNT(*) FROM performance_score_revisions score "
            "JOIN performance_batches batch ON batch.id=score.batch_id "
            "WHERE batch.version=2 AND score.department_id_snapshot IS NULL",
        )
    )
    assignment_facts = _rows(
        db,
        "SELECT fact.id,fact.payload_json,fact.department_id_snapshot "
        "FROM performance_source_facts fact "
        "JOIN performance_batches batch ON batch.id=fact.batch_id "
        "WHERE batch.version=2 AND fact.fact_type='assignment'",
    )
    missing_fact_revision = 0
    for fact in assignment_facts:
        payload = json.loads(fact["payload_json"] or "{}")
        if (
            fact["department_id_snapshot"] is None
            or payload.get("department_revision_id") is None
            or payload.get("department_revision") is None
            or not payload.get("department_revision_source_key")
            or not payload.get("department_revision_approved_at")
        ):
            missing_fact_revision += 1
    if missing_scores or missing_fact_revision:
        raise RuntimeError("V2 department snapshots or revision evidence are incomplete")
    return {
        "score_rows_missing_department": missing_scores,
        "assignment_fact_count": len(assignment_facts),
        "assignment_facts_missing_revision_evidence": missing_fact_revision,
    }


def run(args):
    if not args.confirm_replica_validation:
        raise RuntimeError("--confirm-replica-validation is required")
    source_path = Path(args.source_db).expanduser().resolve()
    replica_path = Path(args.replica_db).expanduser().resolve()
    evidence_path = Path(args.evidence).expanduser().resolve()
    if source_path == replica_path:
        raise RuntimeError("source and replica database paths must differ")
    if not source_path.is_file():
        raise RuntimeError("source database does not exist")
    if replica_path.exists():
        raise RuntimeError("replica destination already exists")
    if evidence_path.exists():
        raise RuntimeError("evidence destination already exists")
    replica_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now(timezone.utc).astimezone().isoformat()
    _online_backup(source_path, replica_path)
    replica_sha_before = _sha256(replica_path)

    db = sqlite3.connect(str(replica_path))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=5000")
    try:
        source_checks = _database_checks(db)
        if source_checks["user_version"] != 56:
            raise RuntimeError("replica baseline must start at database V56")
        if source_checks["integrity_check"] != "ok" or source_checks["foreign_key_violations"]:
            raise RuntimeError("replica baseline integrity validation failed")
        source_actors = _validate_source_actors(db)
        assignments_before = _assignment_rows(db)
        if len(assignments_before) != 37:
            raise RuntimeError("confirmed assignment baseline must contain exactly 37 rows")
        assignment_digest_before = _assignment_digest(assignments_before)
        payroll_before = PerformanceHistoryMigrationRepository.payroll_fingerprint(db)
        batches_before = _batch_fingerprint(db)
        preflight_before = _historical_preflight(db, args.from_month, args.to_month)

        migrations_run = run_migrations(db)
        if int(_scalar(db, "PRAGMA user_version")) != LATEST_VERSION:
            raise RuntimeError("replica did not reach the latest database version")

        db.execute("BEGIN IMMEDIATE")
        try:
            authorization = _provision_replica_authorization(db)
            revisions, mapping_counts = _apply_department_revisions(
                db, assignments_before
            )
            if len(revisions) != 37:
                raise RuntimeError("department revision count is not 37")
            if not _assert_revision_immutable(db, revisions[0]["id"]):
                raise RuntimeError("department revision immutability probe failed")
            db.commit()
        except Exception:
            db.rollback()
            raise

        assignments_after = _assignment_rows(db)
        assignment_digest_after = _assignment_digest(assignments_after)
        if assignment_digest_after != assignment_digest_before:
            raise RuntimeError("original assignment history was modified")
        revision_summary = {
            "total": int(
                _scalar(db, "SELECT COUNT(*) FROM performance_assignment_department_revisions")
            ),
            "approved": int(
                _scalar(
                    db,
                    "SELECT COUNT(*) FROM performance_assignment_department_revisions "
                    "WHERE status='approved'",
                )
            ),
            "current_duplicates": len(
                _rows(
                    db,
                    "SELECT assignment_id,COUNT(*) AS count "
                    "FROM performance_assignment_department_revisions "
                    "WHERE status='approved' GROUP BY assignment_id HAVING COUNT(*)>1",
                )
            ),
            "mapping_counts": mapping_counts,
        }
        if revision_summary["total"] != 37 or revision_summary["approved"] != 37:
            raise RuntimeError("approved department revision baseline is incomplete")
        if revision_summary["current_duplicates"]:
            raise RuntimeError("an assignment has multiple current approved departments")

        preflight_after_departments = _historical_preflight(
            db, args.from_month, args.to_month
        )
        applied = PerformanceHistoryMigrationService.apply(
            db,
            args.from_month,
            args.to_month,
            SOURCE_ACTORS["preparer"]["id"],
            EXPECTED_COUNTS,
        )
        if len(applied["months"]) != 2:
            raise RuntimeError("historical migration did not generate two V2 months")

        reviewer_actor = _actor(
            db, authorization["accounts"]["reviewer"]["user_id"]
        )
        manager_actor = _actor(
            db, authorization["accounts"]["plan_manager"]["user_id"]
        )
        reassessor_actor = _actor(
            db, authorization["accounts"]["reassessor"]["user_id"]
        )
        if "*" in reviewer_actor["_permissions"]:
            raise RuntimeError("dedicated reviewer unexpectedly has wildcard permission")
        if "*" in manager_actor["_permissions"]:
            raise RuntimeError("dedicated plan manager unexpectedly has wildcard permission")
        if "*" in reassessor_actor["_permissions"]:
            raise RuntimeError("dedicated reassessor unexpectedly has wildcard permission")

        db.execute("BEGIN IMMEDIATE")
        try:
            reviewed_batches = _review_and_approve_batches(
                db, applied, reviewer_actor
            )
            db.commit()
        except Exception:
            db.rollback()
            raise

        quality_department = int(
            _scalar(db, "SELECT id FROM departments WHERE name='质检部'")
        )
        db.execute("BEGIN IMMEDIATE")
        try:
            plan_acceptance = _exercise_improvement_plan(
                db, manager_actor, reassessor_actor, quality_department
            )
            db.commit()
        except Exception:
            db.rollback()
            raise

        frozen_departments = _validate_frozen_departments(db)
        final_checks = _database_checks(db)
        if final_checks["integrity_check"] != "ok" or final_checks["foreign_key_violations"]:
            raise RuntimeError("final replica integrity validation failed")
        payroll_after = PerformanceHistoryMigrationRepository.payroll_fingerprint(db)
        if payroll_after != payroll_before:
            raise RuntimeError("performance validation changed the payroll ledger")
        batches_after = _batch_fingerprint(db)
        if batches_after != {
            "legacy_batches": 2,
            "v2_batches": 2,
            "legacy_scores": 64,
        }:
            raise RuntimeError("final Legacy/V2 batch fingerprint is unexpected")
        approved_v2 = int(
            _scalar(
                db,
                "SELECT COUNT(*) FROM performance_batches "
                "WHERE version=2 AND status='approved'",
            )
        )
        superseded_v1 = int(
            _scalar(
                db,
                "SELECT COUNT(*) FROM performance_batches "
                "WHERE version=1 AND legacy_imported=1 AND status='superseded'",
            )
        )
        if approved_v2 != 2 or superseded_v1 != 2:
            raise RuntimeError("V2 approval or Legacy version retention failed")
        preflight_final = _historical_preflight(db, args.from_month, args.to_month)
        result = {
            "status": "passed",
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).astimezone().isoformat(),
            "source_db": str(source_path),
            "replica_db": str(replica_path),
            "replica_sha256_before_mutation": replica_sha_before,
            "source_baseline": source_checks,
            "source_actors": source_actors,
            "migrations_run": migrations_run,
            "target_version": LATEST_VERSION,
            "authorization": authorization,
            "assignment_history": {
                "confirmed_rows": len(assignments_before),
                "digest_before": assignment_digest_before,
                "digest_after": assignment_digest_after,
                "original_rows_unchanged": True,
            },
            "department_revisions": revision_summary,
            "preflight_before": _preflight_summary(preflight_before),
            "preflight_after_departments": _preflight_summary(
                preflight_after_departments
            ),
            "preflight_final": _preflight_summary(preflight_final),
            "reviewed_batches": reviewed_batches,
            "plan_acceptance": plan_acceptance,
            "frozen_departments": frozen_departments,
            "payroll_before": payroll_before,
            "payroll_after": payroll_after,
            "batches_before": batches_before,
            "batches_after": batches_after,
            "approved_v2_batches": approved_v2,
            "superseded_legacy_v1_batches": superseded_v1,
            "final_database_checks": final_checks,
            "v2_query_environment": os.environ.get(
                "PERFORMANCE_LEDGER_V2_QUERY_ENABLED", ""
            ),
        }
    finally:
        db.close()

    result["replica_sha256_after_validation"] = _sha256(replica_path)
    production_operations.write_evidence_json(evidence_path, result)
    result["evidence_file"] = str(evidence_path)
    result["evidence_sha256"] = _sha256(evidence_path)
    return result


def main(argv=None):
    return production_operations.run_json_cli(
        _parser, run, argv, failure_indent=2
    )


if __name__ == "__main__":
    raise SystemExit(main())
