#!/usr/bin/env python3
"""Provision the confirmed V57 department and authorization data safely."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys

import bcrypt
from dotenv import dotenv_values


PROJECT_ROOT = Path(os.environ.get("QR_SYSTEM_ROOT") or Path(__file__).resolve().parents[1])
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("SECRET_KEY", "offline-production-provisioning-only")

from modules.repositories.performance_assignment_department_repository import (  # noqa: E402
    PerformanceAssignmentDepartmentRepository,
)
from modules.repositories.performance_history_migration_repository import (  # noqa: E402
    PerformanceHistoryMigrationRepository,
)
from modules.services.performance_assignment_department_service import (  # noqa: E402
    PerformanceAssignmentDepartmentService,
)
from scripts.validate_performance_v57_replica import (  # noqa: E402
    DEDICATED_ACCOUNT_BASE_ROLE,
    DEDICATED_ACCOUNTS,
    POSITION_DEPARTMENTS,
    SOURCE_ACTORS,
    _assignment_digest,
    _assignment_rows,
    _batch_fingerprint,
    _canonical,
    _database_checks,
    _historical_preflight,
    _preflight_summary,
    _sha256,
    _validate_source_actors,
)


def _parser():
    parser = argparse.ArgumentParser(
        description="Provision approved V57 data without generating V2 batches."
    )
    parser.add_argument("--db", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--confirm-production-provisioning", action="store_true")
    return parser


def _ensure_machine_department(db):
    rows = db.execute(
        "SELECT id,name,status FROM departments WHERE name='机加工班组'"
    ).fetchall()
    if len(rows) > 1:
        raise RuntimeError("机加工班组名称存在歧义")
    if rows:
        row = dict(rows[0])
        if row["status"] != "active":
            raise RuntimeError("机加工班组未启用")
        return int(row["id"]), False
    department_id = db.execute(
        "INSERT INTO departments (name,description,status) VALUES (?,?,'active')",
        ("机加工班组", "车工、铣工绩效及生产管理范围"),
    ).lastrowid
    return int(department_id), True


def _ensure_role(db, definition):
    permissions = _canonical(definition["permissions"])
    row = db.execute(
        "SELECT id,name,code,permissions,status FROM roles WHERE code=?",
        (definition["role_code"],),
    ).fetchone()
    if row:
        row = dict(row)
        if row["permissions"] != permissions or row["status"] != "active":
            raise RuntimeError("已有专用角色与确认权限不一致")
        return int(row["id"]), False
    role_id = db.execute(
        "INSERT INTO roles (name,code,description,level,permissions,status) "
        "VALUES (?,?,?,1,?,'active')",
        (
            definition["role_name"],
            definition["role_code"],
            "绩效 V57 职责分离专用最小权限角色",
            permissions,
        ),
    ).lastrowid
    return int(role_id), True


def _ensure_account(db, definition, role_id):
    row = db.execute(
        "SELECT id,username,name,employee_no,role,status FROM users WHERE username=?",
        (definition["username"],),
    ).fetchone()
    created = False
    if row:
        account = dict(row)
        expected = {
            "username": definition["username"],
            "name": definition["name"],
            "employee_no": definition["employee_no"],
            "role": DEDICATED_ACCOUNT_BASE_ROLE,
            "status": "inactive",
        }
        if any(account[field] != value for field, value in expected.items()):
            raise RuntimeError("已有专用账号与确认身份不一致")
        user_id = int(account["id"])
    else:
        password_hash = bcrypt.hashpw(
            secrets.token_urlsafe(48).encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")
        user_id = int(
            db.execute(
                "INSERT INTO users "
                "(username,password,name,role,employee_no,status,password_version) "
                "VALUES (?,?,?,?,?,'inactive',2)",
                (
                    definition["username"],
                    password_hash,
                    definition["name"],
                    DEDICATED_ACCOUNT_BASE_ROLE,
                    definition["employee_no"],
                ),
            ).lastrowid
        )
        created = True
    assigned_roles = [
        int(item[0])
        for item in db.execute(
            "SELECT role_id FROM user_roles WHERE user_id=? ORDER BY role_id", (user_id,)
        ).fetchall()
    ]
    if assigned_roles and assigned_roles != [role_id]:
        raise RuntimeError("专用账号存在额外角色")
    if not assigned_roles:
        db.execute(
            "INSERT INTO user_roles (user_id,role_id,granted_by) VALUES (?,?,10304)",
            (user_id, role_id),
        )
    return user_id, created


def _replace_scopes(db, user_id, department_ids):
    db.execute("DELETE FROM performance_department_scopes WHERE user_id=?", (user_id,))
    for department_id in department_ids:
        db.execute(
            "INSERT INTO performance_department_scopes "
            "(user_id,department_id,granted_by,granted_by_name) "
            "VALUES (?,?,10304,'杨冰')",
            (user_id, department_id),
        )


def _provision_authorization(db):
    machine_id, machine_created = _ensure_machine_department(db)
    fixed = [
        dict(row)
        for row in db.execute(
            "SELECT id,name,status FROM departments WHERE id BETWEEN 1 AND 8 ORDER BY id"
        ).fetchall()
    ]
    if [row["id"] for row in fixed] != list(range(1, 9)):
        raise RuntimeError("生产范围 ID 1 至 8 不完整")
    if any(row["status"] != "active" for row in fixed):
        raise RuntimeError("生产范围包含未启用部门")
    scope_ids = list(range(1, 9)) + [machine_id]
    accounts = {}
    for key, definition in DEDICATED_ACCOUNTS.items():
        role_id, role_created = _ensure_role(db, definition)
        user_id, account_created = _ensure_account(db, definition, role_id)
        _replace_scopes(db, user_id, scope_ids)
        accounts[key] = {
            "user_id": user_id,
            "role_id": role_id,
            "username": definition["username"],
            "name": definition["name"],
            "base_role": DEDICATED_ACCOUNT_BASE_ROLE,
            "status": "inactive",
            "permissions": definition["permissions"],
            "department_ids": scope_ids,
            "role_created": role_created,
            "account_created": account_created,
        }
    return {
        "machine_department_id": machine_id,
        "machine_department_created": machine_created,
        "production_department_ids": scope_ids,
        "accounts": accounts,
    }


def _provision_department_revisions(db, assignments):
    departments = {
        row["name"]: int(row["id"])
        for row in db.execute(
            "SELECT id,name FROM departments WHERE status='active'"
        ).fetchall()
    }
    preparer = {**SOURCE_ACTORS["preparer"], "_permissions": ["performance:prepare"]}
    approver = {**SOURCE_ACTORS["approver"], "_permissions": ["performance:approve"]}
    created = 0
    reused = 0
    revision_ids = []
    mapping_counts = {}
    for assignment in assignments:
        position_name = assignment["position_name_snapshot"]
        department_name = POSITION_DEPARTMENTS.get(position_name)
        if not department_name or department_name not in departments:
            raise RuntimeError("任职记录缺少已确认部门映射")
        department_id = departments[department_name]
        source_key = (
            "performance-v57:department-supplement:assignment:"
            f"{assignment['id']}:department:{department_id}"
        )
        existing = PerformanceAssignmentDepartmentRepository.revision_by_source_key(
            source_key, db=db
        )
        if existing:
            if (
                existing["status"] != "approved"
                or int(existing["assignment_id"]) != int(assignment["id"])
                or int(existing["department_id"]) != department_id
                or int(existing["created_by"]) != SOURCE_ACTORS["preparer"]["id"]
                or int(existing["approved_by"] or 0) != SOURCE_ACTORS["approver"]["id"]
            ):
                raise RuntimeError("已有部门修订与确认内容不一致")
            approved = existing
            reused += 1
        else:
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
            created += 1
        revision_ids.append(int(approved["id"]))
        mapping_key = f"{position_name}->{department_name}"
        mapping_counts[mapping_key] = mapping_counts.get(mapping_key, 0) + 1
    return {
        "created": created,
        "reused": reused,
        "revision_ids": revision_ids,
        "mapping_counts": dict(sorted(mapping_counts.items())),
    }


def run(args):
    if not args.confirm_production_provisioning:
        raise RuntimeError("--confirm-production-provisioning is required")
    db_path = Path(args.db).expanduser().resolve()
    evidence_path = Path(args.evidence).expanduser().resolve()
    if not db_path.is_file():
        raise RuntimeError("生产数据库不存在")
    if evidence_path.exists():
        raise RuntimeError("证据文件已存在")
    environment = dotenv_values(PROJECT_ROOT / ".env")
    query_flag = str(environment.get("PERFORMANCE_LEDGER_V2_QUERY_ENABLED") or "")
    if query_flag.strip().lower() in {"1", "true", "yes", "on"}:
        raise RuntimeError("生产 V2 查询开关必须保持关闭")

    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=5000")
    try:
        checks_before = _database_checks(db)
        if checks_before != {
            "user_version": 57,
            "integrity_check": "ok",
            "foreign_key_violations": 0,
        }:
            raise RuntimeError("生产 V57 基线检查失败")
        _validate_source_actors(db)
        assignments_before = _assignment_rows(db)
        if len(assignments_before) != 37:
            raise RuntimeError("已确认任职记录不是 37 条")
        assignment_digest_before = _assignment_digest(assignments_before)
        payroll_before = PerformanceHistoryMigrationRepository.payroll_fingerprint(db)
        batches_before = _batch_fingerprint(db)
        if batches_before["v2_batches"] != 0:
            raise RuntimeError("生产库已存在 V2 批次，停止自动配置")
        preflight_before = _historical_preflight(db, "2026-06", "2026-07")

        db.execute("BEGIN IMMEDIATE")
        try:
            authorization = _provision_authorization(db)
            revisions = _provision_department_revisions(db, assignments_before)
            assignments_after = _assignment_rows(db)
            assignment_digest_after = _assignment_digest(assignments_after)
            if assignment_digest_after != assignment_digest_before:
                raise RuntimeError("原任职记录被修改")
            payroll_during = PerformanceHistoryMigrationRepository.payroll_fingerprint(db)
            if payroll_during != payroll_before:
                raise RuntimeError("部门和权限配置不得写工资台账")
            audit_detail = {
                "machine_department_id": authorization["machine_department_id"],
                "department_revision_count": len(revisions["revision_ids"]),
                "dedicated_user_ids": {
                    key: value["user_id"]
                    for key, value in authorization["accounts"].items()
                },
                "production_department_ids": authorization[
                    "production_department_ids"
                ],
                "v2_batches_created": 0,
            }
            db.execute(
                "INSERT INTO audit_logs "
                "(user_id,action,target_type,target_id,detail) VALUES (?,?,?,?,?)",
                (
                    SOURCE_ACTORS["preparer"]["id"],
                    "performance_v57_provisioning",
                    "performance",
                    authorization["machine_department_id"],
                    json.dumps(audit_detail, ensure_ascii=False, sort_keys=True),
                ),
            )
            db.commit()
        except Exception:
            db.rollback()
            raise

        checks_after = _database_checks(db)
        payroll_after = PerformanceHistoryMigrationRepository.payroll_fingerprint(db)
        batches_after = _batch_fingerprint(db)
        preflight_after = _historical_preflight(db, "2026-06", "2026-07")
        if checks_after["integrity_check"] != "ok" or checks_after["foreign_key_violations"]:
            raise RuntimeError("配置后数据库完整性检查失败")
        if payroll_after != payroll_before:
            raise RuntimeError("配置后工资台账指纹变化")
        if batches_after != batches_before:
            raise RuntimeError("配置过程不得生成绩效批次")
        approved_revisions = db.execute(
            "SELECT COUNT(*) FROM performance_assignment_department_revisions "
            "WHERE status='approved' AND source_key LIKE "
            "'performance-v57:department-supplement:%'"
        ).fetchone()[0]
        if int(approved_revisions) != 37:
            raise RuntimeError("生产已批准部门修订不是 37 条")
        result = {
            "status": "passed",
            "completed_at": datetime.now(timezone.utc).astimezone().isoformat(),
            "database": str(db_path),
            "database_checks_before": checks_before,
            "database_checks_after": checks_after,
            "v2_query_flag": query_flag or "false(default)",
            "authorization": authorization,
            "department_revisions": {
                **revisions,
                "approved": int(approved_revisions),
                "assignment_digest_before": assignment_digest_before,
                "assignment_digest_after": assignment_digest_after,
                "original_assignments_unchanged": True,
            },
            "preflight_before": _preflight_summary(preflight_before),
            "preflight_after": _preflight_summary(preflight_after),
            "payroll_before": payroll_before,
            "payroll_after": payroll_after,
            "batches_before": batches_before,
            "batches_after": batches_after,
        }
    finally:
        db.close()

    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    result["evidence_file"] = str(evidence_path)
    result["evidence_sha256"] = _sha256(evidence_path)
    return result


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        result = run(args)
    except Exception as exc:
        print(
            json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
