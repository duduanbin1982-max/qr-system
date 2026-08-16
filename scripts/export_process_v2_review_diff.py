#!/usr/bin/env python3
"""Export human- and machine-readable process V2 differences without repairs."""

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.process_v2_operations import export_review_diff  # noqa: E402


def _parser():
    parser = argparse.ArgumentParser(
        description="Export process V2 replica differences; never applies automatic repairs"
    )
    parser.add_argument("--source-db", required=True)
    parser.add_argument("--candidate-db", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        result = export_review_diff(args.source_db, args.candidate_db, args.output_dir)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
