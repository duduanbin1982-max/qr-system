#!/usr/bin/env python3
"""Run the production process V2 preflight without modifying the source DB."""

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.process_v2_operations import file_sha256, run_preflight  # noqa: E402


def _parser():
    parser = argparse.ArgumentParser(
        description="Read-only process V2 production preflight and migration simulation"
    )
    parser.add_argument("--db", required=True, help="SQLite database to inspect read-only")
    parser.add_argument("--output-dir", required=True, help="Evidence output directory")
    return parser


def run(args):
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = run_preflight(args.db)
    evidence = output / "process-v2-preflight-evidence.json"
    evidence.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    result = {
        "status": report["status"],
        "summary_sha256": report["summary_sha256"],
        "database_sha256": report["database"]["sha256"],
        "blocking_issue_count": len(report["blocking_issues"]),
        "manual_review_count": len(report["manual_review"]),
        "evidence": {"path": str(evidence), "sha256": file_sha256(evidence)},
    }
    if report["status"] != "passed":
        raise RuntimeError(
            "process V2 preflight is blocked; evidence=" + str(evidence)
        )
    return result


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
