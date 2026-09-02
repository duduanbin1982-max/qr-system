#!/usr/bin/env python3
"""Read-only post-cutover business smoke test for production performance V2."""

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import urllib.request


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.domain import evidence_protocol  # noqa: E402
from scripts import production_operations  # noqa: E402


EXPECTED_PAYROLL = {
    "payroll_batches": 4,
    "payroll_employee_lines": 119,
    "payroll_adjustments": 0,
    "payroll_detail_lines": 2975,
    "payroll_work_price_resolutions": 2638,
    "payroll_events": 4,
    "payroll_migration_manifests": 1,
}
QUERY_KEY = "PERFORMANCE_LEDGER_V2_QUERY_ENABLED"
ACCOUNT_EXPECTATIONS = {
    "1000_perf": {
        "name": "杜斌",
        "role": "performance_reviewer_v57",
        "required": {"page:performance", "performance:view_department", "performance:review_department"},
        "forbidden": {"performance:prepare", "performance:approve", "performance:plan_manage", "performance:plan_reassess"},
    },
    "1004_plan": {
        "name": "Dooley",
        "role": "performance_plan_manager_v57",
        "required": {"page:performance", "performance:view_department", "performance:plan_manage"},
        "forbidden": {"performance:prepare", "performance:approve", "performance:review_department", "performance:plan_reassess"},
    },
    "1005_reassess": {
        "name": "王晓璐",
        "role": "performance_reassessor_v57",
        "required": {"page:performance", "performance:view_department", "performance:plan_reassess"},
        "forbidden": {"performance:prepare", "performance:approve", "performance:review_department", "performance:plan_manage"},
    },
}


def _parser():
    parser = argparse.ArgumentParser(description="Post-cutover production V2 smoke test")
    parser.add_argument("--system-root", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--confirm-read-only-smoke", action="store_true")
    return parser


def _canonical(value):
    return evidence_protocol.canonical_json_v1(value)


def _sha256(path):
    return production_operations.file_fingerprint(path)["sha256"]


def _rows(db, sql, params=()):
    return [dict(row) for row in db.execute(sql, params).fetchall()]


def _scalar(db, sql, params=()):
    return db.execute(sql, params).fetchone()[0]


def _open_ro(path):
    return production_operations.open_read_only_sqlite(path)


def _checks(db):
    return {
        "user_version": int(_scalar(db, "PRAGMA user_version")),
        "integrity_check": _scalar(db, "PRAGMA integrity_check"),
        "foreign_key_violations": len(_rows(db, "PRAGMA foreign_key_check")),
        "query_only": int(_scalar(db, "PRAGMA query_only")),
    }


def _payroll(db):
    tables = (
        "payroll_batches",
        "payroll_employee_lines",
        "payroll_adjustments",
        "payroll_detail_lines",
        "payroll_work_price_resolutions",
        "payroll_events",
        "payroll_migration_manifests",
    )
    return production_operations.table_count_fingerprint(db, tables)


def _batch_fingerprint(db):
    rows = _rows(
        db,
        "SELECT id,production_month,version,status,row_version,supersedes_batch_id,"
        "superseded_by_batch_id,prepared_by,approved_by FROM performance_batches "
        "WHERE production_month BETWEEN '2026-06' AND '2026-07' ORDER BY production_month,version,id",
    )
    return {
        "rows": rows,
        "latest_v2_scores": {
            str(batch_id): int(
                _scalar(
                    db,
                    "SELECT COUNT(*) FROM performance_score_revisions score WHERE score.batch_id=? "
                    "AND NOT EXISTS (SELECT 1 FROM performance_score_revisions newer "
                    "WHERE newer.batch_id=score.batch_id AND newer.user_id=score.user_id "
                    "AND newer.revision>score.revision)",
                    (batch_id,),
                )
            )
            for batch_id in (3, 4)
        },
    }


def _flag(root):
    value = ""
    for line in (Path(root) / ".env").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, candidate = stripped.split("=", 1)
            if key.strip() == QUERY_KEY:
                value = candidate.strip().strip("\"'")
    return {"raw": value or "false(default)", "enabled": value.lower() in {"1", "true", "yes", "on"}}


def _health(expected_commit):
    context = ssl._create_unverified_context()
    with urllib.request.urlopen("https://127.0.0.1:3000/api/health", context=context, timeout=5) as response:
        value = json.loads(response.read().decode("utf-8"))
    if value.get("status") != "ok" or value.get("db") != "connected" or value.get("commit") != expected_commit:
        raise RuntimeError("生产健康接口不符合预期")
    return value


def _actor(db, username, access_repository, collect_permissions):
    row = db.execute("SELECT id,username,name,status,role FROM users WHERE username=?", (username,)).fetchone()
    if not row:
        raise RuntimeError(f"专用账号不存在: {username}")
    actor = dict(row)
    if actor["status"] != "active" or actor["role"] != "worker":
        raise RuntimeError(f"专用账号状态或基础角色不正确: {username}")
    actor["_permissions"] = collect_permissions(access_repository.get_permission_rows(actor["id"], db=db), user_id=actor["id"])
    return actor


def _admin_actor(db, access_repository, collect_permissions):
    row = db.execute("SELECT id,username,name,status,role FROM users WHERE username='1000'").fetchone()
    if not row:
        raise RuntimeError("Legacy 回退管理员账号不存在")
    actor = dict(row)
    if actor["status"] != "active" or actor["role"] != "admin":
        raise RuntimeError("Legacy 回退管理员账号状态或基础角色不正确")
    actor["_permissions"] = collect_permissions(access_repository.get_permission_rows(actor["id"], db=db), user_id=actor["id"])
    if "*" not in actor["_permissions"] and "performance:view_all" not in actor["_permissions"]:
        raise RuntimeError("Legacy 回退管理员缺少全局查询权限")
    return actor


def run(args):
    if not args.confirm_read_only_smoke:
        raise RuntimeError("必须提供 --confirm-read-only-smoke")
    root = Path(args.system_root).resolve()
    db_path = Path(args.db).resolve()
    evidence_path = Path(args.evidence).resolve()
    if not root.is_dir() or not db_path.is_file() or evidence_path.exists():
        raise RuntimeError("生产路径无效或证据文件已存在")
    query_flag = _flag(root)
    if not query_flag["enabled"]:
        raise RuntimeError("切换后 .env 查询开关不是 true")
    expected_commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    health = _health(expected_commit)
    os.environ[QUERY_KEY] = "true"
    os.environ.setdefault("SECRET_KEY", "offline-production-v2-post-cutover-smoke")
    sys.path.insert(0, str(root))
    from flask import Flask
    from modules.access_policy import collect_permission_codes
    from modules.repositories.access_policy_repository import AccessPolicyRepository
    from modules.services.performance_ledger_service import PerformanceLedgerService
    from modules.services.performance_service import PerformanceService

    db = _open_ro(db_path)
    try:
        checks_before = _checks(db)
        payroll_before = _payroll(db)
        batches_before = _batch_fingerprint(db)
        if checks_before != {"user_version": 57, "integrity_check": "ok", "foreign_key_violations": 0, "query_only": 1}:
            raise RuntimeError(f"冒烟前数据库门禁失败: {checks_before}")
        if payroll_before != EXPECTED_PAYROLL:
            raise RuntimeError("冒烟前工资台账指纹不一致")
        actors = {
            username: _actor(db, username, AccessPolicyRepository, collect_permission_codes)
            for username in ACCOUNT_EXPECTATIONS
        }
        legacy_admin = _admin_actor(db, AccessPolicyRepository, collect_permission_codes)
        machine_id = int(_scalar(db, "SELECT id FROM departments WHERE name='机加工班组' AND status='active'"))
        expected_scopes = list(range(1, 9)) + [machine_id]
        account_results = {}
        for username, expected in ACCOUNT_EXPECTATIONS.items():
            actor = actors[username]
            permissions = set(actor["_permissions"])
            roles = _rows(
                db,
                "SELECT role.code,role.permissions FROM user_roles relation JOIN roles role ON role.id=relation.role_id WHERE relation.user_id=?",
                (actor["id"],),
            )
            role_codes = [row["code"] for row in roles]
            if expected["role"] not in role_codes:
                raise RuntimeError(f"{username} 绩效角色不正确")
            if not expected["required"].issubset(permissions) or expected["forbidden"] & permissions:
                raise RuntimeError(f"{username} 权限矩阵不符合确认方案")
            scopes = [
                int(row["department_id"])
                for row in db.execute("SELECT department_id FROM performance_department_scopes WHERE user_id=? ORDER BY department_id", (actor["id"],)).fetchall()
            ]
            if scopes != expected_scopes:
                raise RuntimeError(f"{username} 数据范围不正确: {scopes}")
            account_results[username] = {
                "id": actor["id"],
                "name": actor["name"],
                "role_codes": role_codes,
                "permissions": sorted(permissions),
                "department_scope_ids": scopes,
            }

        app = Flask("performance-v2-post-cutover-smoke")
        v2_results = {}
        legacy_fallback_results = {}
        integrity_results = {}
        outside_scope = {}
        with app.app_context():
            app.config[QUERY_KEY] = True
            for month, batch_id, count in (("2026-06", 3, 27), ("2026-07", 4, 37)):
                result = PerformanceService.list_scores(month, page=1, per_page=200, actor=actors["1000_perf"], db=db)
                if result["result_source"] != "ledger_v2" or int(result["batch_id"]) != batch_id or int(result["total"]) != count or result["batch_status"] != "approved":
                    raise RuntimeError(f"{month} V2 正式查询不正确")
                v2_results[month] = {"batch_id": result["batch_id"], "score_count": result["total"], "result_source": result["result_source"], "status": result["batch_status"]}
                integrity = PerformanceLedgerService.check_batch_integrity(batch_id, db=db, include_current=True)
                if not integrity.get("complete"):
                    raise RuntimeError(f"{month} V2 批次完整性不通过")
                integrity_results[month] = {"complete": integrity["complete"], "issue_count": len(integrity.get("issues") or [])}
            for username, actor in actors.items():
                try:
                    PerformanceService.list_scores("2026-07", department_id=9, page=1, per_page=200, actor=actor, db=db)
                except PermissionError:
                    outside_scope[username] = True
                else:
                    raise RuntimeError(f"{username} 意外通过范围外部门查询")
            app.config[QUERY_KEY] = False
            for month, batch_id, count in (("2026-06", 1, 27), ("2026-07", 2, 37)):
                result = PerformanceService.list_scores(month, page=1, per_page=200, actor=legacy_admin, db=db)
                if result["result_source"] != "legacy_v1" or int(result["batch_id"]) != batch_id or int(result["total"]) != count or result["batch_status"] != "superseded":
                    raise RuntimeError(f"{month} Legacy 回退查询不正确")
                legacy_fallback_results[month] = {"batch_id": result["batch_id"], "score_count": result["total"], "result_source": result["result_source"], "status": result["batch_status"]}
            app.config[QUERY_KEY] = True
    finally:
        db.close()

    db_after = _open_ro(db_path)
    try:
        checks_after = _checks(db_after)
        payroll_after = _payroll(db_after)
        batches_after = _batch_fingerprint(db_after)
    finally:
        db_after.close()
    if checks_after != checks_before or payroll_after != payroll_before or batches_after != batches_before:
        raise RuntimeError("只读冒烟前后生产指纹发生变化")
    result = {
        "status": "passed",
        "mode": "production_v2_post_cutover_smoke",
        "executed_at": datetime.now().astimezone().isoformat(),
        "hostname": socket.gethostname(),
        "system_root": str(root),
        "database": str(db_path),
        "deployed_commit": expected_commit,
        "query_flag": query_flag,
        "service_health": health,
        "database_checks_before": checks_before,
        "database_checks_after": checks_after,
        "payroll_before": payroll_before,
        "payroll_after": payroll_after,
        "batch_fingerprint_before": batches_before,
        "batch_fingerprint_after": batches_after,
        "accounts": account_results,
        "legacy_fallback_actor": {
            "id": legacy_admin["id"],
            "username": legacy_admin["username"],
            "name": legacy_admin["name"],
            "permissions": legacy_admin["_permissions"],
        },
        "v2_results": v2_results,
        "legacy_fallback_results": legacy_fallback_results,
        "batch_integrity": integrity_results,
        "outside_scope_denied": outside_scope,
        "read_only": True,
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    production_operations.write_evidence_json(evidence_path, result)
    return {"status": "passed", "evidence": {"path": str(evidence_path), "sha256": _sha256(evidence_path)}, "v2_results": v2_results, "legacy_fallback_results": legacy_fallback_results, "outside_scope_denied": outside_scope}


def main(argv=None):
    return production_operations.run_json_cli(
        _parser, run, argv, failure_indent=None
    )


if __name__ == "__main__":
    raise SystemExit(main())
