#!/usr/bin/env python3
"""Generate the read-only role-group permission v068 migration manifest."""

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.role_group_permissions_v68 import (
    inspect_role_group_permissions,
    open_read_only,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description="角色组权限 v068 只读预检")
    parser.add_argument("--db", required=True, help="SQLite database path")
    parser.add_argument("--output", help="Optional JSON evidence output path")
    args = parser.parse_args(argv)

    db = open_read_only(args.db)
    try:
        report = inspect_role_group_permissions(db)
    finally:
        db.close()
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).expanduser().resolve().write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if report["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
