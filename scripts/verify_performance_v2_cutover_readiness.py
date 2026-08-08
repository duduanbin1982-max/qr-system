#!/usr/bin/env python3
"""Verify Legacy fallback and V2 candidate selection without changing the query flag."""

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys


def _parser():
    parser = argparse.ArgumentParser(description="Read-only V2 cutover readiness check")
    parser.add_argument("--system-root", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--confirm-read-only-verification", action="store_true")
    return parser


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


def run(args):
    if not args.confirm_read_only_verification:
        raise RuntimeError("必须提供 --confirm-read-only-verification")
    root = Path(args.system_root).resolve()
    db_path = Path(args.db).resolve()
    evidence_path = Path(args.evidence).resolve()
    if not root.is_dir() or not db_path.is_file() or evidence_path.exists():
        raise RuntimeError("生产路径无效或证据文件已存在")
    query_flag = _query_flag(root)
    if query_flag["enabled"]:
        raise RuntimeError("验证阶段 V2 查询开关必须保持关闭")
    os.environ.setdefault("SECRET_KEY", "offline-v2-cutover-readiness")
    sys.path.insert(0, str(root))
    from modules.repositories.performance_repository import PerformanceRepository

    uri = "file:" + db_path.as_posix() + "?mode=ro"
    db = sqlite3.connect(uri, uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA query_only=ON")
    db.execute("BEGIN")
    try:
        checks = {
            "user_version": int(_scalar(db, "PRAGMA user_version")),
            "integrity_check": _scalar(db, "PRAGMA integrity_check"),
            "foreign_key_violations": len(_rows(db, "PRAGMA foreign_key_check")),
            "query_only": int(_scalar(db, "PRAGMA query_only")),
        }
        if checks != {"user_version": 57, "integrity_check": "ok", "foreign_key_violations": 0, "query_only": 1}:
            raise RuntimeError(f"切换就绪数据库门禁失败: {checks}")
        months = []
        for month, expected_legacy, expected_v2, expected_scores in (
            ("2026-06", 1, 3, 27),
            ("2026-07", 2, 4, 37),
        ):
            legacy = PerformanceRepository.formal_result_batch(month, False, db=db)
            v2 = PerformanceRepository.formal_result_batch(month, True, db=db)
            if not legacy or int(legacy["id"]) != expected_legacy or legacy["status"] != "superseded" or not int(legacy["legacy_imported"]):
                raise RuntimeError(f"{month} Legacy 回退选择不正确")
            if not v2 or int(v2["id"]) != expected_v2 or v2["status"] != "approved" or int(v2["legacy_imported"]):
                raise RuntimeError(f"{month} V2 候选选择不正确")
            legacy_scores = int(_scalar(db, "SELECT COUNT(*) FROM performance_score_revisions score WHERE score.batch_id=? AND NOT EXISTS (SELECT 1 FROM performance_score_revisions newer WHERE newer.batch_id=score.batch_id AND newer.user_id=score.user_id AND newer.revision>score.revision)", (legacy["id"],)))
            v2_scores = int(_scalar(db, "SELECT COUNT(*) FROM performance_score_revisions score WHERE score.batch_id=? AND NOT EXISTS (SELECT 1 FROM performance_score_revisions newer WHERE newer.batch_id=score.batch_id AND newer.user_id=score.user_id AND newer.revision>score.revision)", (v2["id"],)))
            if legacy_scores != expected_scores or v2_scores != expected_scores:
                raise RuntimeError(f"{month} Legacy/V2 最新评分数量不一致")
            months.append(
                {
                    "production_month": month,
                    "query_flag_false": {"batch_id": legacy["id"], "version": legacy["version"], "status": legacy["status"], "result_source": "legacy_v1", "score_count": legacy_scores},
                    "simulated_query_flag_true": {"batch_id": v2["id"], "version": v2["version"], "status": v2["status"], "result_source": "ledger_v2", "score_count": v2_scores},
                }
            )
    finally:
        db.close()

    result = {
        "status": "passed",
        "mode": "read_only_v2_cutover_readiness",
        "executed_at": datetime.now().astimezone().isoformat(),
        "database": str(db_path),
        "database_checks": checks,
        "actual_query_flag": query_flag,
        "legacy_fallback_valid": True,
        "v2_candidate_valid": True,
        "months": months,
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**result, "evidence": {"path": str(evidence_path), "sha256": _sha256(evidence_path)}}


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
