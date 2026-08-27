#!/usr/bin/env python3
"""Export V1/V2 per-user differences for supervisor review, read-only."""

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.domain import evidence_protocol  # noqa: E402


def _parser():
    parser = argparse.ArgumentParser(description="Export production V1/V2 review differences")
    parser.add_argument("--system-root", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--from-month", default="2026-06")
    parser.add_argument("--to-month", default="2026-07")
    parser.add_argument("--confirm-read-only-export", action="store_true")
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
    if int(_scalar(db, "PRAGMA query_only")) != 1:
        db.close()
        raise RuntimeError("SQLite query_only 未生效")
    db.execute("BEGIN")
    return db


def _query_flag(system_root):
    value = ""
    path = Path(system_root) / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, candidate = stripped.split("=", 1)
            if key.strip() == "PERFORMANCE_LEDGER_V2_QUERY_ENABLED":
                value = candidate.strip().strip("\"'")
    return {"raw": value or "false(default)", "enabled": value.lower() in {"1", "true", "yes", "on"}}


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_csv(path, rows):
    fields = (
        "production_month",
        "batch_id",
        "batch_status",
        "user_id",
        "employee_name",
        "employee_no",
        "legacy_score",
        "v2_score",
        "legacy_eligibility",
        "v2_eligibility",
        "changed_fields",
        "reasons",
    )
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        handle.write(",".join(fields) + "\n")
        import csv

        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writerows(
            {
                **row,
                "changed_fields": "+".join(row["changed_fields"]),
                "reasons": "+".join(row["reasons"]),
            }
            for row in rows
        )


def run(args):
    if not args.confirm_read_only_export:
        raise RuntimeError("必须提供 --confirm-read-only-export")
    system_root = Path(args.system_root).resolve()
    db_path = Path(args.db).resolve()
    if not system_root.is_dir() or not db_path.is_file():
        raise RuntimeError("生产目录或数据库不存在")
    query_flag = _query_flag(system_root)
    if query_flag["enabled"]:
        raise RuntimeError("V2 查询开关必须保持关闭")
    db = _open_ro(db_path)
    try:
        checks = {
            "user_version": int(_scalar(db, "PRAGMA user_version")),
            "integrity_check": _scalar(db, "PRAGMA integrity_check"),
            "foreign_key_violations": len(_rows(db, "PRAGMA foreign_key_check")),
            "query_only": int(_scalar(db, "PRAGMA query_only")),
        }
        if checks != {"user_version": 57, "integrity_check": "ok", "foreign_key_violations": 0, "query_only": 1}:
            raise RuntimeError(f"只读导出数据库门禁失败: {checks}")
        events = _rows(
            db,
            "SELECT event.id AS event_id,event.payload_json,event.operator_id,event.operator_name,"
            "batch.id AS batch_id,batch.production_month,batch.status AS batch_status,batch.version "
            "FROM performance_batch_events event JOIN performance_batches batch "
            "ON batch.id=event.batch_id WHERE event.event_type='historical_revision_generated' "
            "AND batch.version=2 AND batch.production_month>=? AND batch.production_month<=? "
            "ORDER BY batch.production_month,batch.id,event.id",
            (args.from_month, args.to_month),
        )
        if len(events) != 2:
            raise RuntimeError(f"V2 历史迁移事件数量不是 2: {len(events)}")
        rows = []
        source_manifests = {}
        for event in events:
            if event["batch_status"] != "draft":
                raise RuntimeError(f"批次 {event['batch_id']} 已离开 draft，停止导出")
            payload = json.loads(event["payload_json"] or "{}")
            source_manifests[event["production_month"]] = payload.get("migration_manifest_sha256") or ""
            comparison = payload.get("comparison") or {}
            for item in comparison.get("rows") or []:
                rows.append(
                    {
                        "production_month": event["production_month"],
                        "batch_id": int(event["batch_id"]),
                        "batch_status": event["batch_status"],
                        "user_id": item.get("user_id"),
                        "employee_name": item.get("employee_name") or "",
                        "employee_no": item.get("employee_no") or "",
                        "legacy_score": item.get("legacy_score"),
                        "v2_score": item.get("v2_score"),
                        "legacy_eligibility": item.get("legacy_eligibility") or "",
                        "v2_eligibility": item.get("v2_eligibility") or "",
                        "changed_fields": item.get("changed_fields") or [],
                        "reasons": item.get("reasons") or [],
                    }
                )
        rows.sort(key=lambda row: (row["production_month"], int(row["user_id"]), row["batch_id"]))
        if len(rows) != 64:
            raise RuntimeError(f"V1/V2 逐人差异数量不是 64: {len(rows)}")
        reason_counts = Counter(reason for row in rows for reason in row["reasons"])
        changed_field_counts = Counter(field for row in rows for field in row["changed_fields"])
        changed_row_count = sum(bool(row["changed_fields"]) for row in rows)
        document = {
            "status": "passed",
            "mode": "production_read_only_review_export",
            "executed_at": datetime.now().astimezone().isoformat(),
            "system_root": str(system_root),
            "database": str(db_path),
            "read_only": True,
            "v2_query_flag": query_flag,
            "database_checks": checks,
            "from_month": args.from_month,
            "to_month": args.to_month,
            "source_manifest_sha256": dict(sorted(source_manifests.items())),
            "batch_count": len(events),
            "row_count": len(rows),
            "changed_row_count": changed_row_count,
            "unchanged_row_count": len(rows) - changed_row_count,
            "reason_counts": dict(sorted(reason_counts.items())),
            "changed_field_counts": dict(sorted(changed_field_counts.items())),
            "rows": rows,
        }
    finally:
        db.close()

    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    run_dir = Path(args.output_dir).resolve() / stamp
    run_dir.mkdir(parents=True, exist_ok=False)
    json_path = run_dir / f"performance-v2-review-differences-{stamp}.json"
    csv_path = run_dir / f"performance-v2-review-differences-{stamp}.csv"
    evidence_path = run_dir / f"performance-v2-review-export-evidence-{stamp}.json"
    _write_json(json_path, document)
    _write_csv(csv_path, document["rows"])
    evidence = {
        "status": "passed",
        "mode": document["mode"],
        "executed_at": document["executed_at"],
        "run_directory": str(run_dir),
        "row_count": document["row_count"],
        "changed_row_count": document["changed_row_count"],
        "unchanged_row_count": document["unchanged_row_count"],
        "reason_counts": document["reason_counts"],
        "changed_field_counts": document["changed_field_counts"],
        "source_manifest_sha256": document["source_manifest_sha256"],
        "artifacts": {
            json_path.name: {"path": str(json_path), "sha256": _sha256(json_path)},
            csv_path.name: {"path": str(csv_path), "sha256": _sha256(csv_path)},
        },
    }
    _write_json(evidence_path, evidence)
    evidence["artifacts"][evidence_path.name] = {"path": str(evidence_path), "sha256": _sha256(evidence_path)}
    return {"status": "passed", "run_directory": str(run_dir), "row_count": document["row_count"], "changed_row_count": document["changed_row_count"], "reason_counts": document["reason_counts"], "artifacts": evidence["artifacts"]}


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
