#!/usr/bin/env python3
"""Preflight or apply controlled Legacy-to-V2 performance history migration."""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_DB_PATH = os.environ.get("DB_PATH") or str(
    PROJECT_ROOT / "data" / "production.db"
)
BASELINE_FIELDS = (
    "overwritten_score_count",
    "missing_position_count",
    "cross_month_work_count",
    "cross_month_quality_count",
)


def _parser():
    parser = argparse.ArgumentParser(
        description=(
            "Preflight historical performance data or generate reviewable V2 batches. "
            "The default mode is read-only preflight."
        )
    )
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="SQLite database path")
    parser.add_argument("--from-month", dest="start_month", default="")
    parser.add_argument("--to-month", dest="end_month", default="")
    parser.add_argument("--preparer-id", type=int)
    parser.add_argument("--expect-overwritten", type=int)
    parser.add_argument("--expect-missing-position", type=int)
    parser.add_argument("--expect-cross-month-work", type=int)
    parser.add_argument("--expect-cross-month-quality", type=int)
    parser.add_argument("--apply", action="store_true")
    return parser


def _expected_counts(args):
    values = {
        "overwritten_score_count": args.expect_overwritten,
        "missing_position_count": args.expect_missing_position,
        "cross_month_work_count": args.expect_cross_month_work,
        "cross_month_quality_count": args.expect_cross_month_quality,
    }
    provided = [values[field] is not None for field in BASELINE_FIELDS]
    if any(provided) and not all(provided):
        raise ValueError("四个历史绩效期望计数必须同时提供")
    return values if all(provided) else None


def _require_apply_arguments(parser, args, expected_counts):
    if not args.apply:
        return
    missing = []
    if not args.start_month:
        missing.append("--from-month")
    if not args.end_month:
        missing.append("--to-month")
    if args.preparer_id is None:
        missing.append("--preparer-id")
    if expected_counts is None:
        missing.extend(
            (
                "--expect-overwritten",
                "--expect-missing-position",
                "--expect-cross-month-work",
                "--expect-cross-month-quality",
            )
        )
    if missing:
        parser.error("--apply requires " + ", ".join(dict.fromkeys(missing)))


def main(argv=None):
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        expected_counts = _expected_counts(args)
    except ValueError as exc:
        parser.error(str(exc))
    _require_apply_arguments(parser, args, expected_counts)

    from modules.services.performance_history_migration_service import (
        PerformanceHistoryMigrationService,
    )

    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=5000")
    if not args.apply:
        db.execute("PRAGMA query_only=ON")
    try:
        plan = PerformanceHistoryMigrationService.analyze(
            db, args.start_month, args.end_month
        )
        if expected_counts is not None:
            PerformanceHistoryMigrationService.validate_counts(
                plan, expected_counts
            )
        if not args.apply:
            result = {"mode": "preflight", "plan": plan}
        else:
            applied = PerformanceHistoryMigrationService.apply(
                db,
                args.start_month,
                args.end_month,
                args.preparer_id,
                expected_counts,
            )
            result = {
                "mode": "applied",
                "plan": applied["plan"],
                "months": applied["months"],
            }
    except Exception as exc:
        print(
            json.dumps(
                {"mode": "error", "error": str(exc)},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1
    finally:
        db.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
