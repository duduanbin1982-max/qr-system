#!/usr/bin/env python3
"""Generate production performance V2 draft batches with backup and evidence."""

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


EXPECTED_PAYROLL = {
    "payroll_batches": 4,
    "payroll_employee_lines": 119,
    "payroll_adjustments": 0,
    "payroll_detail_lines": 2975,
    "payroll_work_price_resolutions": 2638,
    "payroll_events": 4,
    "payroll_migration_manifests": 1,
}
EXPECTED_COUNTS = {
    "overwritten_score_count": 64,
    "missing_position_count": 30,
    "cross_month_work_count": 5,
    "cross_month_quality_count": 11,
}


def _parser():
    parser = argparse.ArgumentParser(
        description="Controlled production V2 draft generation"
    )
    parser.add_argument("--system-root", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--from-month", default="2026-06")
    parser.add_argument("--to-month", default="2026-07")
    parser.add_argument("--preparer-id", type=int, required=True)
    parser.add_argument("--confirm-production-apply", action="store_true")
    return parser


def _canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


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


def _db_checks(db):
    return {
        "user_version": int(_scalar(db, "PRAGMA user_version")),
        "integrity_check": _scalar(db, "PRAGMA integrity_check"),
        "foreign_key_violations": len(_rows(db, "PRAGMA foreign_key_check")),
        "query_only": int(_scalar(db, "PRAGMA query_only")),
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
        "v2_scores": int(
            _scalar(
                db,
                "SELECT COUNT(*) FROM performance_score_revisions score "
                "JOIN performance_batches batch ON batch.id=score.batch_id "
                "WHERE batch.version>=2",
            )
        ),
        "draft_v2_batches": int(
            _scalar(
                db,
                "SELECT COUNT(*) FROM performance_batches "
                "WHERE version>=2 AND status IN ('draft','supervisor_review')",
            )
        ),
    }


def _payroll_fingerprint(db):
    tables = (
        "payroll_batches",
        "payroll_employee_lines",
        "payroll_adjustments",
        "payroll_detail_lines",
        "payroll_work_price_resolutions",
        "payroll_events",
        "payroll_migration_manifests",
    )
    return {
        table: int(_scalar(db, "SELECT COUNT(*) FROM " + table))
        for table in tables
    }


def _quality_fingerprint(db):
    tables = (
        "performance_quality_events",
        "performance_quality_event_sources",
        "performance_data_exceptions",
        "performance_batches",
        "performance_score_revisions",
        "performance_batch_events",
    )
    values = {}
    for table in tables:
        rows = _rows(db, f"SELECT * FROM {table} ORDER BY id")
        values[table] = {"count": len(rows), "sha256": _digest(rows)}
    return values


def _query_flag(system_root):
    value = ""
    env_path = Path(system_root) / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, candidate = stripped.split("=", 1)
            if key.strip() == "PERFORMANCE_LEDGER_V2_QUERY_ENABLED":
                value = candidate.strip().strip("\"'")
    return {"raw": value or "false(default)", "enabled": value.lower() in {"1", "true", "yes", "on"}}


def _commit(system_root):
    return subprocess.check_output(
        ["git", "-C", str(system_root), "rev-parse", "HEAD"], text=True
    ).strip()


def _backup(source_path, target_path):
    source = _open_ro(source_path)
    target = sqlite3.connect(str(target_path))
    try:
        source.backup(target)
        target.commit()
    finally:
        target.close()
        source.close()


def _validate_pre_apply(db, migration_service):
    checks = _db_checks(db)
    if checks != {
        "user_version": 57,
        "integrity_check": "ok",
        "foreign_key_violations": 0,
        "query_only": 0,
    }:
        raise RuntimeError(f"写入前数据库门禁失败: {checks}")
    batches = _batch_fingerprint(db)
    if batches["legacy_batches"] != 2 or batches["v2_batches"] != 0 or batches["legacy_scores"] != 64:
        raise RuntimeError(f"写入前绩效批次门禁失败: {batches}")
    payroll = _payroll_fingerprint(db)
    if payroll != EXPECTED_PAYROLL:
        raise RuntimeError(f"写入前工资台账指纹不一致: {payroll}")
    plan = migration_service.analyze(db, "2026-06", "2026-07")
    migration_service.validate_counts(plan, EXPECTED_COUNTS)
    totals = plan["totals"]
    if totals.get("quality_ambiguity_count") or totals.get("missing_target_count"):
        raise RuntimeError("写入前仍存在质量歧义或缺少岗位目标")
    return checks, batches, payroll, plan


def _post_summary(db):
    checks = _db_checks(db)
    batches = _batch_fingerprint(db)
    payroll = _payroll_fingerprint(db)
    rows = _rows(
        db,
        "SELECT id,production_month,version,status,idempotency_key,input_digest "
        "FROM performance_batches WHERE version>=2 ORDER BY production_month,id",
    )
    events = _rows(
        db,
        "SELECT id,batch_id,event_type,from_status,to_status,operator_id,operator_name,"
        "idempotency_key FROM performance_batch_events "
        "WHERE event_type='historical_revision_generated' ORDER BY id",
    )
    return {
        "checks": checks,
        "batches": batches,
        "payroll": payroll,
        "v2_batches": rows,
        "migration_events": events,
        "quality": _quality_fingerprint(db),
    }


def run(args):
    if not args.confirm_production_apply:
        raise RuntimeError("必须提供 --confirm-production-apply")
    system_root = Path(args.system_root).resolve()
    db_path = Path(args.db).resolve()
    output_base = Path(args.output_dir).resolve()
    if not system_root.is_dir() or not db_path.is_file():
        raise RuntimeError("生产系统目录或数据库不存在")
    query_flag = _query_flag(system_root)
    if query_flag["enabled"]:
        raise RuntimeError("V2 查询开关必须保持关闭")
    os.environ.setdefault("SECRET_KEY", "offline-production-v2-apply")
    sys.path.insert(0, str(system_root))
    from modules.repositories.performance_history_migration_repository import (
        PerformanceHistoryMigrationRepository,
    )
    from modules.services.performance_history_migration_service import (
        PerformanceHistoryMigrationService,
    )

    started_at = datetime.now().astimezone()
    stamp = started_at.strftime("%Y%m%d-%H%M%S")
    run_dir = output_base / stamp
    run_dir.mkdir(parents=True, exist_ok=False)
    backup_path = run_dir / f"production-pre-v2-apply-{stamp}.db"
    evidence_path = run_dir / f"performance-v2-apply-evidence-{stamp}.json"
    if backup_path.exists() or evidence_path.exists():
        raise RuntimeError("证据路径已存在")

    source_ro = _open_ro(db_path)
    try:
        pre_checks = _db_checks(source_ro)
        pre_batches = _batch_fingerprint(source_ro)
        pre_payroll = _payroll_fingerprint(source_ro)
        pre_quality = _quality_fingerprint(source_ro)
        pre_plan = PerformanceHistoryMigrationService.analyze(
            source_ro, args.from_month, args.to_month
        )
        PerformanceHistoryMigrationService.validate_counts(pre_plan, EXPECTED_COUNTS)
        if pre_plan["totals"].get("quality_ambiguity_count") or pre_plan["totals"].get("missing_target_count"):
            raise RuntimeError("生产写入前存在未清除质量歧义或岗位目标缺口")
        _backup(db_path, backup_path)
    finally:
        source_ro.close()

    backup_ro = _open_ro(backup_path)
    try:
        backup_checks = _db_checks(backup_ro)
        backup_batches = _batch_fingerprint(backup_ro)
        backup_payroll = _payroll_fingerprint(backup_ro)
    finally:
        backup_ro.close()
    if backup_checks != {"user_version": 57, "integrity_check": "ok", "foreign_key_violations": 0, "query_only": 1}:
        raise RuntimeError(f"生产备份完整性验证失败: {backup_checks}")
    if backup_batches != pre_batches or backup_payroll != pre_payroll:
        raise RuntimeError("生产备份与写入前指纹不一致")

    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=10000")
    try:
        applied = PerformanceHistoryMigrationService.apply(
            db,
            args.from_month,
            args.to_month,
            args.preparer_id,
            EXPECTED_COUNTS,
        )
    finally:
        db.close()

    post_db = _open_ro(db_path)
    try:
        post = _post_summary(post_db)
        post_plan = PerformanceHistoryMigrationService.analyze(
            post_db, args.from_month, args.to_month
        )
        PerformanceHistoryMigrationService.validate_counts(post_plan, EXPECTED_COUNTS)
    finally:
        post_db.close()
    if post["checks"] != {"user_version": 57, "integrity_check": "ok", "foreign_key_violations": 0, "query_only": 1}:
        raise RuntimeError(f"生成后数据库完整性失败: {post['checks']}")
    if post["batches"]["legacy_batches"] != 2 or post["batches"]["v2_batches"] != 2 or post["batches"]["legacy_scores"] != 64:
        raise RuntimeError(f"生成后绩效批次门禁失败: {post['batches']}")
    if post["payroll"] != pre_payroll:
        raise RuntimeError("历史 V2 生成修改了工资台账")
    if len(post["v2_batches"]) != 2 or any(row["version"] != 2 for row in post["v2_batches"]):
        raise RuntimeError("生成后的 V2 批次数量或版本不正确")

    applied_summary = []
    for item in applied["months"]:
        batch = item["batch"]
        comparison = item.get("comparison") or {}
        applied_summary.append(
            {
                "production_month": item["production_month"],
                "batch_id": int(batch["id"]),
                "version": int(batch["version"]),
                "status": batch["status"],
                "event_id": int(item["event_id"]),
                "idempotent_replay": bool(item.get("idempotent_replay")),
                "input_digest": batch.get("input_digest") or "",
                "comparison_row_count": len(comparison.get("rows") or []),
                "comparison_reason_counts": comparison.get("reason_counts") or {},
                "quality_backfill": item.get("quality_backfill") or {},
            }
        )

    evidence = {
        "status": "passed",
        "mode": "production_apply_v2_drafts",
        "executed_at": started_at.isoformat(),
        "hostname": socket.gethostname(),
        "system_root": str(system_root),
        "database": str(db_path),
        "deployed_commit": _commit(system_root),
        "preparer": {"id": args.preparer_id, "name": "杨冰"},
        "read_only_preflight_manifest_sha256": pre_plan["manifest_sha256"],
        "v2_query_flag": query_flag,
        "preflight_totals": pre_plan["totals"],
        "database_checks_before": pre_checks,
        "database_checks_after": post["checks"],
        "backup": {
            "path": str(backup_path),
            "sha256": _sha256(backup_path),
            "bytes": backup_path.stat().st_size,
            "checks": backup_checks,
        },
        "batches_before": pre_batches,
        "batches_after": post["batches"],
        "payroll_before": pre_payroll,
        "payroll_after": post["payroll"],
        "quality_before": pre_quality,
        "quality_after": post["quality"],
        "applied_months": applied_summary,
        "post_preflight_manifest_sha256": post_plan["manifest_sha256"],
    }
    evidence["evidence_sha256"] = _digest(evidence)
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "status": "passed",
        "run_directory": str(run_dir),
        "backup": evidence["backup"],
        "evidence": {
            "path": str(evidence_path),
            "sha256": _sha256(evidence_path),
        },
        "read_only_preflight_manifest_sha256": pre_plan["manifest_sha256"],
        "preflight_totals": pre_plan["totals"],
        "batches_after": post["batches"],
        "payroll_unchanged": post["payroll"] == pre_payroll,
        "applied_months": applied_summary,
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
