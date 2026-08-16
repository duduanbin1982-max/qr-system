#!/usr/bin/env python3
"""Create, migrate and validate a disposable process V2 database replica."""

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.process_v2_operations import file_sha256, validate_replica  # noqa: E402


def _parser():
    parser = argparse.ArgumentParser(
        description="Run v060-v063 on a new SQLite replica and compare protected totals"
    )
    parser.add_argument("--source-db", required=True)
    parser.add_argument("--replica-db", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--apply", action="store_true", help="Create and migrate the replica")
    parser.add_argument("--confirm-replica-validation", action="store_true")
    return parser


def run(args):
    if not args.apply or not args.confirm_replica_validation:
        raise RuntimeError("replica creation requires --apply and --confirm-replica-validation")
    report = validate_replica(args.source_db, args.replica_db)
    evidence = Path(args.evidence).resolve()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "status": report["status"],
        "replica": str(Path(args.replica_db).resolve()),
        "evidence": {"path": str(evidence), "sha256": file_sha256(evidence)},
        "migration": report["migration"],
        "blocking_difference_count": len(report["blocking_differences"]),
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
