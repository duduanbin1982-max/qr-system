#!/usr/bin/env python3
"""Preflight or apply the confirmed 2026-07 historical payroll cutover."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from modules.config import DB_PATH
from modules.services.payroll_history_migration_service import (
    PayrollHistoryMigrationService,
)


def _summary(plan):
    return {
        "payroll_month": plan["payroll_month"],
        "period_start": plan["period_start"],
        "period_end": plan["period_end"],
        "total": plan["total"],
        "resolved": plan["resolved"],
        "unresolved": plan["unresolved"],
        "reason_counts": plan["reason_counts"],
        "unresolved_work_record_ids": [
            row["work_record_id"] for row in plan["unresolved_rows"]
        ],
        "manifest_sha256": plan["manifest_sha256"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=DB_PATH)
    parser.add_argument("--month", default="2026-07")
    parser.add_argument("--expect-resolved", type=int, default=2592)
    parser.add_argument("--expect-unresolved", type=int, default=61)
    parser.add_argument("--preparer-id", type=int)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--no-revision", action="store_true")
    args = parser.parse_args()

    if args.apply and args.preparer_id is None:
        parser.error("--apply requires --preparer-id")

    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=5000")
    try:
        plan = PayrollHistoryMigrationService.analyze(db, args.month)
        PayrollHistoryMigrationService.validate_counts(
            plan, args.expect_resolved, args.expect_unresolved
        )
        if not args.apply:
            result = {"mode": "preflight", **_summary(plan)}
        else:
            applied = PayrollHistoryMigrationService.apply(
                db,
                args.month,
                args.preparer_id,
                args.expect_resolved,
                args.expect_unresolved,
                create_revision=not args.no_revision,
            )
            result = {
                "mode": "applied",
                **_summary(applied["plan"]),
                "inserted_resolutions": applied["inserted_resolutions"],
                "batch_id": (applied["batch"] or {}).get("id"),
                "batch_version": (applied["batch"] or {}).get("version"),
                "batch_status": (applied["calculation"] or {}).get("status"),
                "manifest_id": applied["manifest"]["id"],
                "manifest_sha256": applied["manifest"]["manifest_sha256"],
            }
    finally:
        db.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
