#!/usr/bin/env python3
"""Run the confirmed uniform supervisor review on production V2 draft batches."""

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys


EXPECTED_PAYROLL = {
    "payroll_batches": 4,
    "payroll_employee_lines": 119,
    "payroll_adjustments": 0,
    "payroll_detail_lines": 2975,
    "payroll_work_price_resolutions": 2638,
    "payroll_events": 4,
    "payroll_migration_manifests": 1,
}


def _parser():
    parser = argparse.ArgumentParser(description="Production V2 uniform supervisor review")
    parser.add_argument("--system-root", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--from-month", default="2026-06")
    parser.add_argument("--to-month", default="2026-07")
    parser.add_argument("--preparer-id", type=int, default=10304)
    parser.add_argument("--reviewer-username", default="1000_perf")
    parser.add_argument("--confirm-production-review", action="store_true")
    return parser


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rows(db, sql, params=()):
    return [dict(row) for row in db.execute(sql, params).fetchall()]


def _scalar(db, sql, params=()):
    return db.execute(sql, params).fetchone()[0]


def _open_ro(path):
    uri = "file:" + Path(path).resolve().as_posix() + "?mode=ro"
    db = sqlite3.connect(uri, uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=10000")
    db.execute("PRAGMA query_only=ON")
    db.execute("BEGIN")
    return db


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
    return {table: int(_scalar(db, "SELECT COUNT(*) FROM " + table)) for table in tables}


def _batch_counts(db):
    return {
        "legacy_batches": int(_scalar(db, "SELECT COUNT(*) FROM performance_batches WHERE version=1")),
        "v2_batches": int(_scalar(db, "SELECT COUNT(*) FROM performance_batches WHERE version>=2")),
        "legacy_scores": int(_scalar(db, "SELECT COUNT(*) FROM performance_score_revisions score JOIN performance_batches batch ON batch.id=score.batch_id WHERE batch.version=1")),
        "v2_scores": int(_scalar(db, "SELECT COUNT(*) FROM performance_score_revisions score JOIN performance_batches batch ON batch.id=score.batch_id WHERE batch.version>=2")),
        "supervisor_review_batches": int(_scalar(db, "SELECT COUNT(*) FROM performance_batches WHERE version>=2 AND status='supervisor_review'")),
    }


def _query_flag(root):
    value = ""
    path = Path(root) / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, candidate = stripped.split("=", 1)
            if key.strip() == "PERFORMANCE_LEDGER_V2_QUERY_ENABLED":
                value = candidate.strip().strip("\"'")
    return {"raw": value or "false(default)", "enabled": value.lower() in {"1", "true", "yes", "on"}}


def _commit(root):
    return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()


def _backup(source_path, target_path):
    source = _open_ro(source_path)
    target = sqlite3.connect(str(target_path))
    try:
        source.backup(target)
        target.commit()
    finally:
        target.close()
        source.close()


def _actor(db, username, access_policy_repository, collect_permission_codes):
    row = db.execute("SELECT id,username,name,status,role FROM users WHERE username=?", (username,)).fetchone()
    if not row:
        raise RuntimeError(f"复核账号不存在: {username}")
    actor = dict(row)
    if actor["status"] != "active" or actor["role"] != "worker":
        raise RuntimeError("复核账号必须是 active/worker")
    actor["_permissions"] = collect_permission_codes(
        access_policy_repository.get_permission_rows(actor["id"], db=db),
        user_id=actor["id"],
    )
    if "performance:review_department" not in actor["_permissions"]:
        raise RuntimeError("复核账号缺少 performance:review_department")
    return actor


def run(args):
    if not args.confirm_production_review:
        raise RuntimeError("必须提供 --confirm-production-review")
    root = Path(args.system_root).resolve()
    db_path = Path(args.db).resolve()
    out_base = Path(args.output_dir).resolve()
    if not root.is_dir() or not db_path.is_file():
        raise RuntimeError("生产目录或数据库不存在")
    query_flag = _query_flag(root)
    if query_flag["enabled"]:
        raise RuntimeError("V2 查询开关必须保持关闭")
    os.environ.setdefault("SECRET_KEY", "offline-production-v2-supervisor-review")
    sys.path.insert(0, str(root))
    from modules.access_policy import collect_permission_codes
    from modules.repositories.access_policy_repository import AccessPolicyRepository
    from modules.repositories.performance_ledger_repository import PerformanceLedgerRepository
    from modules.services.performance_ledger_service import PerformanceLedgerService

    started_at = datetime.now().astimezone()
    stamp = started_at.strftime("%Y%m%d-%H%M%S")
    run_dir = out_base / stamp
    run_dir.mkdir(parents=True, exist_ok=False)
    backup_path = run_dir / f"production-pre-supervisor-review-{stamp}.db"
    evidence_path = run_dir / f"performance-v2-supervisor-review-evidence-{stamp}.json"

    before_ro = _open_ro(db_path)
    try:
        before_checks = _checks(before_ro)
        before_batches = _batch_counts(before_ro)
        before_payroll = _payroll(before_ro)
        before_review_count = int(_scalar(before_ro, "SELECT COUNT(*) FROM performance_reviews_v2"))
        if before_checks != {"user_version": 57, "integrity_check": "ok", "foreign_key_violations": 0, "query_only": 1}:
            raise RuntimeError(f"主管复核前数据库门禁失败: {before_checks}")
        if before_batches["v2_batches"] != 2 or before_batches["supervisor_review_batches"] != 0:
            raise RuntimeError(f"主管复核前 V2 批次状态不正确: {before_batches}")
        if before_payroll != EXPECTED_PAYROLL:
            raise RuntimeError("主管复核前工资台账指纹不一致")
        _backup(db_path, backup_path)
    finally:
        before_ro.close()
    backup_ro = _open_ro(backup_path)
    try:
        backup_checks = _checks(backup_ro)
    finally:
        backup_ro.close()
    if backup_checks != {"user_version": 57, "integrity_check": "ok", "foreign_key_violations": 0, "query_only": 1}:
        raise RuntimeError(f"主管复核备份验证失败: {backup_checks}")

    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=10000")
    reviewed = []
    reviewer = None
    try:
        db.execute("BEGIN IMMEDIATE")
        reviewer = _actor(db, args.reviewer_username, AccessPolicyRepository, collect_permission_codes)
        preparer = {"id": args.preparer_id, "name": "杨冰", "_permissions": ["performance:prepare"]}
        batches = _rows(
            db,
            "SELECT * FROM performance_batches WHERE version=2 AND production_month>=? "
            "AND production_month<=? ORDER BY production_month,id",
            (args.from_month, args.to_month),
        )
        for batch in batches:
            batch_id = int(batch["id"])
            current = PerformanceLedgerRepository.batch(batch_id, db=db)
            if current["status"] == "draft":
                submitted = PerformanceLedgerService.submit_supervisor_review(
                    batch_id,
                    {"expected_row_version": current["row_version"], "idempotency_key": f"production-v2-submit-review:{batch_id}"},
                    preparer,
                    db=db,
                )
                current = PerformanceLedgerRepository.batch(batch_id, db=db)
            if current["status"] != "supervisor_review":
                raise RuntimeError(f"V2 批次 {batch_id} 未进入主管复核状态")
            scores = PerformanceLedgerRepository.latest_score_revisions(batch_id, db=db)
            if not scores:
                raise RuntimeError(f"V2 批次 {batch_id} 没有评分")
            reviews = 0
            for score in scores:
                result = PerformanceLedgerService.save_supervisor_review(
                    {
                        "batch_id": batch_id,
                        "user_id": int(score["user_id"]),
                        "expected_row_version": current["row_version"],
                        "idempotency_key": f"production-v2-review:{batch_id}:user:{score['user_id']}",
                        "request_id": f"production-v2-review-request:{batch_id}:user:{score['user_id']}",
                        "reason": "生产 V2 首轮统一主管复核，未调整业务输入",
                        "review": {},
                    },
                    reviewer,
                    db=db,
                )
                current = PerformanceLedgerRepository.batch(batch_id, db=db)
                reviews += 1
            latest = PerformanceLedgerRepository.latest_score_revisions(batch_id, db=db)
            if len(latest) != len(scores):
                raise RuntimeError(f"V2 批次 {batch_id} 复核后评分数量变化")
            eligible_by_position = Counter(
                int(row["position_id_snapshot"])
                for row in latest
                if row.get("eligibility_status") == "eligible"
                and row.get("position_id_snapshot") is not None
            )
            for row in latest:
                eligible = row.get("eligibility_status") == "eligible"
                position_id = row.get("position_id_snapshot")
                group_size = (
                    eligible_by_position.get(int(position_id), 0)
                    if eligible and position_id is not None
                    else 0
                )
                expected_total = group_size if group_size >= 3 else None
                if row.get("rank_total") != expected_total:
                    raise RuntimeError(f"V2 批次 {batch_id} 岗位排名总人数不正确")
                if expected_total is None and row.get("rank_no") is not None:
                    raise RuntimeError(f"V2 批次 {batch_id} 非公开排名员工出现名次")
                if expected_total is not None and row.get("rank_no") is None:
                    raise RuntimeError(f"V2 批次 {batch_id} 具备排名资格员工缺少名次")
            reviewed.append(
                {
                    "production_month": current["production_month"],
                    "batch_id": batch_id,
                    "status": current["status"],
                    "row_version": current["row_version"],
                    "score_count": len(latest),
                    "review_count": reviews,
                    "ranked_count": len(latest),
                }
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    after_ro = _open_ro(db_path)
    try:
        after_checks = _checks(after_ro)
        after_batches = _batch_counts(after_ro)
        after_payroll = _payroll(after_ro)
        after_review_count = int(_scalar(after_ro, "SELECT COUNT(*) FROM performance_reviews_v2"))
        review_events = int(_scalar(after_ro, "SELECT COUNT(*) FROM performance_batch_events WHERE event_type='supervisor_review_saved'"))
    finally:
        after_ro.close()
    if after_checks != {"user_version": 57, "integrity_check": "ok", "foreign_key_violations": 0, "query_only": 1}:
        raise RuntimeError(f"主管复核后数据库门禁失败: {after_checks}")
    if after_payroll != before_payroll:
        raise RuntimeError("主管复核修改了工资台账")
    if after_batches["legacy_batches"] != 2 or after_batches["v2_batches"] != 2 or after_batches["supervisor_review_batches"] != 2:
        raise RuntimeError(f"主管复核后 V2 批次状态不正确: {after_batches}")
    if after_review_count - before_review_count != 64 or review_events < 64:
        raise RuntimeError(f"主管复核记录数量不正确: before={before_review_count}, after={after_review_count}, events={review_events}")

    evidence = {
        "status": "passed",
        "mode": "production_uniform_supervisor_review",
        "executed_at": started_at.isoformat(),
        "hostname": socket.gethostname(),
        "system_root": str(root),
        "database": str(db_path),
        "deployed_commit": _commit(root),
        "reviewer": {
            "id": reviewer["id"],
            "username": reviewer["username"],
            "name": reviewer["name"],
            "permissions": reviewer["_permissions"],
        },
        "review_policy": "uniform_no_input_adjustment",
        "v2_query_flag": query_flag,
        "database_checks_before": before_checks,
        "database_checks_after": after_checks,
        "batches_before": before_batches,
        "batches_after": after_batches,
        "payroll_before": before_payroll,
        "payroll_after": after_payroll,
        "reviews_before": before_review_count,
        "reviews_after": after_review_count,
        "supervisor_review_saved_events": review_events,
        "backup": {
            "path": str(backup_path),
            "bytes": backup_path.stat().st_size,
            "sha256": _sha256(backup_path),
            "checks": backup_checks,
        },
        "batches": reviewed,
    }
    evidence["content_digest"] = _digest(evidence)
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "passed",
        "run_directory": str(run_dir),
        "reviewer": evidence["reviewer"],
        "batches": reviewed,
        "reviews_after": after_review_count,
        "payroll_unchanged": True,
        "backup": evidence["backup"],
        "evidence": {"path": str(evidence_path), "sha256": _sha256(evidence_path)},
    }


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        result = run(args)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
