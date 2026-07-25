#!/usr/bin/env python3
import json
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")
from modules.config import DB_PATH


def cutover_status(db):
    queries = {
        "legacy_rows": "SELECT COUNT(*) FROM process_handoff_reviews",
        "imported_rows": "SELECT COUNT(*) FROM process_quality_evaluations WHERE source_type='legacy_handoff'",
        "unmapped_legacy": (
            "SELECT COUNT(*) FROM process_handoff_reviews handoff "
            "LEFT JOIN process_quality_evaluations evaluation ON evaluation.source_handoff_review_id=handoff.id "
            "WHERE evaluation.id IS NULL"
        ),
        "orphan_imports": (
            "SELECT COUNT(*) FROM process_quality_evaluations evaluation "
            "LEFT JOIN process_handoff_reviews handoff ON handoff.id=evaluation.source_handoff_review_id "
            "WHERE evaluation.source_type='legacy_handoff' AND handoff.id IS NULL"
        ),
        "status_mismatches": (
            "SELECT COUNT(*) FROM process_handoff_reviews handoff "
            "JOIN process_quality_evaluations evaluation ON evaluation.source_handoff_review_id=handoff.id "
            "WHERE handoff.status <> CASE evaluation.status "
            "WHEN 'pending_verification' THEN 'pending' ELSE evaluation.status END"
        ),
    }
    return {name: db.execute(sql).fetchone()[0] for name, sql in queries.items()}


def main():
    db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        status = cutover_status(db)
    finally:
        db.close()
    print(json.dumps(status, ensure_ascii=False, sort_keys=True))
    return 1 if any(status[key] for key in ("unmapped_legacy", "orphan_imports", "status_mismatches")) else 0


if __name__ == "__main__":
    raise SystemExit(main())
