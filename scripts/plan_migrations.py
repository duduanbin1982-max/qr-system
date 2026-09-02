#!/usr/bin/env python3
"""Preview the validated database migration plan using a read-only connection."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.bootstrap import load_environment  # noqa: E402

load_environment(PROJECT_ROOT)

from modules.config import DB_PATH  # noqa: E402
from modules.migrations import LATEST_VERSION, pending_migrations  # noqa: E402


def inspect_plan(database_path):
    database = Path(database_path).resolve()
    if not database.is_file():
        raise RuntimeError(f"database does not exist: {database}")
    connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        current = int(connection.execute("PRAGMA user_version").fetchone()[0])
        integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"database quick_check failed: {integrity}")
        pending = pending_migrations(current)
        return {
            "database": str(database),
            "connection_mode": "read-only",
            "current_version": current,
            "target_version": LATEST_VERSION,
            "pending_count": len(pending),
            "pending": [
                {"version": version, "description": description}
                for version, description, _ in pending
            ],
            "quick_check": integrity,
        }
    finally:
        connection.close()


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
