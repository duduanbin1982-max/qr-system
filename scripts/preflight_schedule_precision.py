#!/usr/bin/env python3
"""Read-only source preflight via the stable operations application boundary."""
import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.application.operations_facade import OperationsFacade


def classify_work_time_operation(order, operation):
    return OperationsFacade.classify_work_time_operation(order, operation)


def summarize_work_time_coverage(rows):
    return OperationsFacade.summarize_work_time_coverage(rows)


def run_preflight(source_path, limit=1000):
    return OperationsFacade.precision_preflight(source_path, limit)


def main(argv=None):
    parser = argparse.ArgumentParser(description="在数据库副本上执行排程精度试排")
    parser.add_argument("--db", required=True, help="源数据库路径（只读）")
    parser.add_argument("--limit", type=int, default=1000, help="最多试排订单数，1-1000")
    args = parser.parse_args(argv)
    if args.limit < 1 or args.limit > 1000:
        parser.error("--limit 必须在 1 到 1000 之间")
    print(json.dumps(run_preflight(args.db, args.limit), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
