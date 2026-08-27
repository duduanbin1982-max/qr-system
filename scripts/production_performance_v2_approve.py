#!/usr/bin/env python3
"""Submit and dual-approve production V2 performance batches with evidence."""

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.domain import evidence_protocol  # noqa: E402


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
    parser = argparse.ArgumentParser(description="Production V2 dual approval")
    parser.add_argument("--system-root", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--from-month", default="2026-06")
    parser.add_argument("--to-month", default="2026-07")
    parser.add_argument("--preparer-id", type=int, default=10304)
    parser.add_argument("--approver-id", type=int, default=10305)
    parser.add_argument("--confirm-production-approval", action="store_true")
    return parser


def _canonical(value):
    return evidence_protocol.canonical_json_v1(value)


def _digest(value):
    return evidence_protocol.sha256_digest_v1(value)


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


def _batch_rows(db):
    return _rows(
        db,
        "SELECT id,production_month,version,status,row_version,prepared_by,approved_by,"
        "supersedes_batch_id,superseded_by_batch_id,submitted_at,approved_at,input_digest "
        "FROM performance_batches WHERE production_month BETWEEN '2026-06' AND '2026-07' "
        "ORDER BY production_month,version,id",
    )


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


def _identity(db, user_id, expected_name, permission):
    row = db.execute("SELECT id,username,name,status FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        raise RuntimeError(f"绩效操作人不存在: {user_id}")
    actor = dict(row)
    if actor["name"] != expected_name or actor["status"] != "active":
        raise RuntimeError(f"绩效操作人身份或状态不正确: {user_id}")
    actor["_permissions"] = [permission]
    return actor


def run(args):
    if not args.confirm_production_approval:
        raise RuntimeError("必须提供 --confirm-production-approval")
    if args.preparer_id == args.approver_id:
        raise RuntimeError("制单人与批准人必须分离")
    root = Path(args.system_root).resolve()
    db_path = Path(args.db).resolve()
    out_base = Path(args.output_dir).resolve()
    if not root.is_dir() or not db_path.is_file():
        raise RuntimeError("生产目录或数据库不存在")
    query_flag = _query_flag(root)
    if query_flag["enabled"]:
        raise RuntimeError("批准前 V2 查询开关必须关闭")
    os.environ.setdefault("SECRET_KEY", "offline-production-v2-approval")
    sys.path.insert(0, str(root))
    from modules.repositories.performance_ledger_repository import PerformanceLedgerRepository
    from modules.services.performance_ledger_service import PerformanceLedgerService

    started_at = datetime.now().astimezone()
    stamp = started_at.strftime("%Y%m%d-%H%M%S")
    run_dir = out_base / stamp
    run_dir.mkdir(parents=True, exist_ok=False)
    backup_path = run_dir / f"production-pre-v2-approval-{stamp}.db"
    evidence_path = run_dir / f"performance-v2-approval-evidence-{stamp}.json"

    before_ro = _open_ro(db_path)
    try:
        before_checks = _checks(before_ro)
        before_payroll = _payroll(before_ro)
        before_batches = _batch_rows(before_ro)
        review_count = int(_scalar(before_ro, "SELECT COUNT(*) FROM performance_reviews_v2"))
        v2_rows = [row for row in before_batches if int(row["version"]) == 2]
        legacy_rows = [row for row in before_batches if int(row["version"]) == 1]
        if before_checks != {"user_version": 57, "integrity_check": "ok", "foreign_key_violations": 0, "query_only": 1}:
            raise RuntimeError(f"批准前数据库门禁失败: {before_checks}")
        if before_payroll != EXPECTED_PAYROLL:
            raise RuntimeError("批准前工资台账指纹不一致")
        if len(v2_rows) != 2 or any(row["status"] != "supervisor_review" for row in v2_rows):
            raise RuntimeError(f"批准前 V2 批次未全部完成主管复核: {v2_rows}")
        if len(legacy_rows) != 2 or any(row["status"] != "approved" for row in legacy_rows):
            raise RuntimeError(f"批准前 Legacy 批次不是正式版本: {legacy_rows}")
        if review_count != 64:
            raise RuntimeError(f"批准前主管复核记录不是 64 条: {review_count}")
        _backup(db_path, backup_path)
    finally:
        before_ro.close()

    backup_ro = _open_ro(backup_path)
    try:
        backup_checks = _checks(backup_ro)
        backup_payroll = _payroll(backup_ro)
        backup_batches = _batch_rows(backup_ro)
    finally:
        backup_ro.close()
    if backup_checks != {"user_version": 57, "integrity_check": "ok", "foreign_key_violations": 0, "query_only": 1}:
        raise RuntimeError(f"批准前备份验证失败: {backup_checks}")
    if backup_payroll != before_payroll or backup_batches != before_batches:
        raise RuntimeError("批准前备份与生产指纹不一致")

    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=10000")
    results = []
    try:
        db.execute("BEGIN IMMEDIATE")
        preparer = _identity(db, args.preparer_id, "杨冰", "performance:prepare")
        approver = _identity(db, args.approver_id, "时文芳", "performance:approve")
        batches = _rows(
            db,
            "SELECT * FROM performance_batches WHERE version=2 AND production_month>=? "
            "AND production_month<=? ORDER BY production_month,id",
            (args.from_month, args.to_month),
        )
        if len(batches) != 2:
            raise RuntimeError("待批准 V2 批次数不是 2")
        for batch in batches:
            batch_id = int(batch["id"])
            current = PerformanceLedgerRepository.batch(batch_id, db=db)
            submitted = PerformanceLedgerService.submit_approval(
                batch_id,
                {
                    "expected_row_version": current["row_version"],
                    "idempotency_key": f"production-v2-submit-approval:{batch_id}",
                    "request_id": f"production-v2-submit-approval-request:{batch_id}",
                },
                preparer,
                db=db,
            )
            if submitted.get("input_drift_detected"):
                raise RuntimeError(f"批次 {batch_id} 检测到来源漂移并生成替代批次，停止批准")
            current = PerformanceLedgerRepository.batch(batch_id, db=db)
            if current["status"] != "approval_pending":
                raise RuntimeError(f"批次 {batch_id} 未进入待批准状态")
            approved = PerformanceLedgerService.approve_batch(
                batch_id,
                {
                    "expected_row_version": current["row_version"],
                    "idempotency_key": f"production-v2-approve:{batch_id}",
                    "request_id": f"production-v2-approve-request:{batch_id}",
                },
                approver,
                db=db,
            )
            final_batch = approved["batch"]
            if final_batch["status"] != "approved":
                raise RuntimeError(f"批次 {batch_id} 批准失败")
            predecessor_id = final_batch.get("supersedes_batch_id")
            predecessor = PerformanceLedgerRepository.batch(predecessor_id, db=db)
            if not predecessor or predecessor["status"] != "superseded" or int(predecessor.get("superseded_by_batch_id") or 0) != batch_id:
                raise RuntimeError(f"批次 {batch_id} 的 Legacy 取代关系不正确")
            results.append(
                {
                    "production_month": final_batch["production_month"],
                    "legacy_batch_id": int(predecessor_id),
                    "legacy_status": predecessor["status"],
                    "v2_batch_id": batch_id,
                    "v2_status": final_batch["status"],
                    "row_version": final_batch["row_version"],
                    "prepared_by": final_batch["prepared_by"],
                    "approved_by": final_batch["approved_by"],
                    "submitted_at": final_batch["submitted_at"],
                    "approved_at": final_batch["approved_at"],
                    "approval_event_id": approved["event_id"],
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
        after_payroll = _payroll(after_ro)
        after_batches = _batch_rows(after_ro)
        approved_v2_count = int(_scalar(after_ro, "SELECT COUNT(*) FROM performance_batches WHERE version=2 AND status='approved'"))
        superseded_legacy_count = int(_scalar(after_ro, "SELECT COUNT(*) FROM performance_batches WHERE version=1 AND status='superseded'"))
        pending_count = int(_scalar(after_ro, "SELECT COUNT(*) FROM performance_batches WHERE version=2 AND status='approval_pending'"))
    finally:
        after_ro.close()
    if after_checks != {"user_version": 57, "integrity_check": "ok", "foreign_key_violations": 0, "query_only": 1}:
        raise RuntimeError(f"批准后数据库门禁失败: {after_checks}")
    if after_payroll != before_payroll:
        raise RuntimeError("绩效批准修改了工资台账")
    if approved_v2_count != 2 or superseded_legacy_count != 2 or pending_count != 0:
        raise RuntimeError("绩效版本批准或取代数量不正确")

    evidence = {
        "status": "passed",
        "mode": "production_v2_dual_approval",
        "executed_at": started_at.isoformat(),
        "hostname": socket.gethostname(),
        "system_root": str(root),
        "database": str(db_path),
        "deployed_commit": _commit(root),
        "preparer": {"id": args.preparer_id, "name": "杨冰"},
        "approver": {"id": args.approver_id, "name": "时文芳"},
        "v2_query_flag": query_flag,
        "database_checks_before": before_checks,
        "database_checks_after": after_checks,
        "payroll_before": before_payroll,
        "payroll_after": after_payroll,
        "batches_before": before_batches,
        "batches_after": after_batches,
        "backup": {
            "path": str(backup_path),
            "bytes": backup_path.stat().st_size,
            "sha256": _sha256(backup_path),
            "checks": backup_checks,
        },
        "approval_results": results,
        "approved_v2_count": approved_v2_count,
        "superseded_legacy_count": superseded_legacy_count,
        "approval_pending_count": pending_count,
    }
    evidence["content_digest"] = _digest(evidence)
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "passed",
        "run_directory": str(run_dir),
        "approval_results": results,
        "payroll_unchanged": True,
        "v2_query_flag": query_flag,
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
