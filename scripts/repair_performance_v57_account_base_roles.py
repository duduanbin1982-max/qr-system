#!/usr/bin/env python3
"""Repair V57 dedicated accounts whose permission role leaked into users.role."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys


PROJECT_ROOT = Path(os.environ.get("QR_SYSTEM_ROOT") or Path(__file__).resolve().parents[1])
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("SECRET_KEY", "offline-production-repair-only")

from modules.migrations import LATEST_VERSION
from modules.repositories.performance_history_migration_repository import (
    PerformanceHistoryMigrationRepository,
)
from scripts.validate_performance_v57_replica import (
    DEDICATED_ACCOUNT_BASE_ROLE,
    DEDICATED_ACCOUNTS,
    _batch_fingerprint,
    _canonical,
    _database_checks,
)


EXPECTED_USER_IDS = {
    "reviewer": 10336,
    "plan_manager": 10337,
    "reassessor": 10338,
}


def _parser():
    parser = argparse.ArgumentParser(
        description="Repair the base role of the three V57 dedicated accounts."
    )
    parser.add_argument("--db", required=True)
    parser.add_argument("--backup", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument(
        "--confirm-performance-account-role-repair", action="store_true"
    )
    return parser


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rows(db, sql, params=()):
    return [dict(row) for row in db.execute(sql, params).fetchall()]


def _account_snapshot(db, *, allowed_base_roles):
    machine_rows = _rows(
        db, "SELECT id,status FROM departments WHERE name='机加工班组'"
    )
    if len(machine_rows) != 1 or machine_rows[0]["status"] != "active":
        raise RuntimeError("机加工班组不存在、重复或未启用")
    expected_scope_ids = list(range(1, 9)) + [int(machine_rows[0]["id"])]
    accounts = {}
    for key, definition in DEDICATED_ACCOUNTS.items():
        users = _rows(
            db,
            "SELECT id,username,name,employee_no,role,status FROM users WHERE username=?",
            (definition["username"],),
        )
        if len(users) != 1:
            raise RuntimeError(f"专用账号数量异常: {definition['username']}")
        user = users[0]
        if int(user["id"]) != EXPECTED_USER_IDS[key]:
            raise RuntimeError(f"专用账号 ID 异常: {definition['username']}")
        if user["name"] != definition["name"] or user["employee_no"] != definition["employee_no"]:
            raise RuntimeError(f"专用账号身份异常: {definition['username']}")
        if user["status"] not in ("active", "inactive"):
            raise RuntimeError(f"专用账号状态异常: {definition['username']}")
        if user["role"] not in allowed_base_roles:
            raise RuntimeError(f"专用账号基础角色异常: {definition['username']}")

        roles = _rows(
            db,
            "SELECT r.id,r.code,r.permissions,r.status FROM user_roles ur "
            "JOIN roles r ON r.id=ur.role_id WHERE ur.user_id=? ORDER BY r.id",
            (user["id"],),
        )
        if len(roles) != 1 or roles[0]["code"] != definition["role_code"]:
            raise RuntimeError(f"专用账号权限角色异常: {definition['username']}")
        if roles[0]["status"] != "active":
            raise RuntimeError(f"专用账号权限角色未启用: {definition['username']}")
        if roles[0]["permissions"] != _canonical(definition["permissions"]):
            raise RuntimeError(f"专用账号权限集合异常: {definition['username']}")

        scope_ids = [
            int(row["department_id"])
            for row in _rows(
                db,
                "SELECT department_id FROM performance_department_scopes "
                "WHERE user_id=? ORDER BY department_id",
                (user["id"],),
            )
        ]
        if scope_ids != expected_scope_ids:
            raise RuntimeError(f"专用账号部门范围异常: {definition['username']}")
        accounts[key] = {
            **user,
            "role_id": int(roles[0]["id"]),
            "role_code": roles[0]["code"],
            "permissions": json.loads(roles[0]["permissions"]),
            "department_ids": scope_ids,
        }
    return accounts


def _business_fingerprint(db):
    return {
        "database": _database_checks(db),
        "performance_batches": _batch_fingerprint(db),
        "payroll": PerformanceHistoryMigrationRepository.payroll_fingerprint(db),
        "approved_department_revisions": int(
            db.execute(
                "SELECT COUNT(*) FROM performance_assignment_department_revisions "
                "WHERE status='approved' AND source_key LIKE "
                "'performance-v57:department-supplement:%'"
            ).fetchone()[0]
        ),
    }


def _backup_database(source, backup_path):
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    if backup_path.exists():
        raise RuntimeError(f"备份文件已存在: {backup_path}")
    target = sqlite3.connect(backup_path)
    try:
        source.backup(target)
        target.row_factory = sqlite3.Row
        checks = _database_checks(target)
        if checks["integrity_check"] != "ok" or checks["foreign_key_violations"] != 0:
            raise RuntimeError("备份数据库完整性校验失败")
    finally:
        target.close()
    return checks


def _repair_account_base_roles(db):
    locked_accounts = _account_snapshot(
        db,
        allowed_base_roles={
            DEDICATED_ACCOUNT_BASE_ROLE,
            *(definition["role_code"] for definition in DEDICATED_ACCOUNTS.values()),
        },
    )
    changed = 0
    for key, account in locked_accounts.items():
        if account["role"] == DEDICATED_ACCOUNT_BASE_ROLE:
            continue
        definition = DEDICATED_ACCOUNTS[key]
        cursor = db.execute(
            "UPDATE users SET role=? WHERE id=? AND role=?",
            (
                DEDICATED_ACCOUNT_BASE_ROLE,
                account["id"],
                definition["role_code"],
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"专用账号并发更新失败: {account['username']}")
        db.execute(
            "INSERT INTO audit_logs "
            "(user_id,action,target_type,target_id,detail) VALUES (NULL,?,?,?,?)",
            (
                "performance_v57_account_base_role_repair",
                "user",
                account["id"],
                f"users.role: {definition['role_code']} -> {DEDICATED_ACCOUNT_BASE_ROLE}; "
                f"user_roles retained: {definition['role_code']}",
            ),
        )
        changed += 1
    return changed


def main():
    args = _parser().parse_args()
    if not args.confirm_performance_account_role_repair:
        raise SystemExit("缺少生产修复确认参数")

    database_path = Path(args.db).resolve()
    backup_path = Path(args.backup).resolve()
    evidence_path = Path(args.evidence).resolve()
    if not database_path.is_file():
        raise SystemExit(f"数据库不存在: {database_path}")
    if evidence_path.exists():
        raise SystemExit(f"证据文件已存在: {evidence_path}")

    started_at = datetime.now(timezone.utc)
    db = sqlite3.connect(database_path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        before_fingerprint = _business_fingerprint(db)
        if before_fingerprint["database"]["user_version"] != LATEST_VERSION:
            raise RuntimeError("数据库版本不是当前 V57")
        if before_fingerprint["database"]["integrity_check"] != "ok":
            raise RuntimeError("生产数据库完整性校验失败")
        if before_fingerprint["database"]["foreign_key_violations"] != 0:
            raise RuntimeError("生产数据库存在外键违规")
        before_accounts = _account_snapshot(
            db,
            allowed_base_roles={
                DEDICATED_ACCOUNT_BASE_ROLE,
                *(definition["role_code"] for definition in DEDICATED_ACCOUNTS.values()),
            },
        )
        backup_checks = _backup_database(db, backup_path)

        db.execute("BEGIN IMMEDIATE")
        try:
            changed = _repair_account_base_roles(db)
            db.commit()
        except Exception:
            db.rollback()
            raise

        after_accounts = _account_snapshot(
            db, allowed_base_roles={DEDICATED_ACCOUNT_BASE_ROLE}
        )
        after_fingerprint = _business_fingerprint(db)
        if before_fingerprint["performance_batches"] != after_fingerprint["performance_batches"]:
            raise RuntimeError("绩效批次指纹发生变化")
        if before_fingerprint["payroll"] != after_fingerprint["payroll"]:
            raise RuntimeError("工资台账指纹发生变化")
        if (
            before_fingerprint["approved_department_revisions"]
            != after_fingerprint["approved_department_revisions"]
        ):
            raise RuntimeError("部门修订数量发生变化")

        evidence = {
            "operation": "performance_v57_account_base_role_repair",
            "started_at_utc": started_at.isoformat(),
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "database": str(database_path),
            "backup": {
                "path": str(backup_path),
                "sha256": _sha256(backup_path),
                "size": backup_path.stat().st_size,
                "checks": backup_checks,
            },
            "changed_account_count": changed,
            "before_accounts": before_accounts,
            "after_accounts": after_accounts,
            "before_fingerprint": before_fingerprint,
            "after_fingerprint": after_fingerprint,
        }
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    finally:
        db.close()


if __name__ == "__main__":
    main()
