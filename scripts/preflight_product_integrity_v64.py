#!/usr/bin/env python3
"""Run a read-only product-management v64 preflight."""

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.product_integrity_v64 import inspect_product_integrity, open_read_only  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only product v64 preflight")
    parser.add_argument("--db", required=True)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    db = open_read_only(args.db)
    try:
        report = inspect_product_integrity(db)
    finally:
        db.close()
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).resolve().write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
