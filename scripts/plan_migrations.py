#!/usr/bin/env python3
"""Preview the validated database migration plan using a read-only connection."""

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.application.operations_facade import OperationsFacade  # noqa: E402


DB_PATH = OperationsFacade.default_database_path(PROJECT_ROOT)


def inspect_plan(database_path):
    return OperationsFacade.migration_plan(database_path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=DB_PATH)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = inspect_plan(args.database)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            f"schema v{report['current_version']} -> v{report['target_version']}; "
            f"pending={report['pending_count']}; quick_check={report['quick_check']}"
        )
        for item in report["pending"]:
            print(f"v{item['version']}: {item['description']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
