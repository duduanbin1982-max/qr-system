#!/usr/bin/env python3
"""Apply or verify one authorized role-group permission v068 cutover."""

import argparse
import json
from pathlib import Path
import sqlite3
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.role_group_permissions_v68 import apply_cutover, verify_cutover


def _open_database(path, *, read_only):
    db_path = Path(path).expanduser().resolve()
    if read_only:
        db = sqlite3.connect("file:" + db_path.as_posix() + "?mode=ro", uri=True)
        db.execute("PRAGMA query_only=ON")
    else:
        db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    return db


def main(argv=None):
    parser = argparse.ArgumentParser(description="角色组权限 v068 受控切换")
    parser.add_argument("mode", choices=("apply", "verify"))
    parser.add_argument("--db", required=True)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--expected-manifest-sha256")
    parser.add_argument("--actor-user-id", type=int)
    parser.add_argument("--actor-name")
    parser.add_argument("--approved-by-user-id", type=int)
    parser.add_argument("--approved-by-name")
    args = parser.parse_args(argv)

    if args.mode == "apply":
        required = {
            "expected_manifest_sha256": args.expected_manifest_sha256,
            "actor_user_id": args.actor_user_id,
            "actor_name": args.actor_name,
            "approved_by_user_id": args.approved_by_user_id,
            "approved_by_name": args.approved_by_name,
        }
        missing = [name for name, value in required.items() if value in (None, "")]
        if missing:
            parser.error("apply 缺少参数: " + ", ".join(missing))

    db = _open_database(args.db, read_only=args.mode == "verify")
    try:
        if args.mode == "apply":
            result = apply_cutover(
                db,
                idempotency_key=args.idempotency_key,
                expected_manifest_sha256=args.expected_manifest_sha256,
                actor_user_id=args.actor_user_id,
                actor_name=args.actor_name,
                approved_by_user_id=args.approved_by_user_id,
                approved_by_name=args.approved_by_name,
            )
        else:
            result = verify_cutover(db, args.idempotency_key)
    finally:
        db.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
