#!/usr/bin/env python3
"""Copy a database, run v64, and verify the migrated copy."""

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.product_integrity_v64 import rehearse_copy  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Product v64 copy rehearsal")
    parser.add_argument("--source-db", required=True)
    parser.add_argument("--output-db", required=True)
    parser.add_argument("--evidence")
    args = parser.parse_args(argv)
    try:
        report = rehearse_copy(args.source_db, args.output_db)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.evidence:
        Path(args.evidence).resolve().write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
