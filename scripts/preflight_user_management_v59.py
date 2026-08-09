#!/usr/bin/env python3
"""Read-only production preflight for the employee-management v059 migration."""

import argparse
import json
import sqlite3
from pathlib import Path


REQUIRED_VERSION = 59
REQUIRED_COLUMNS = {"purged_at", "purged_by", "purge_reason"}
REQUIRED_INDEX = "idx_users_employee_no_normalized"


def _table_exists(db, table):
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone() is not None


def inspect_database(db_path):
    path = Path(db_path).expanduser().resolve()
    if not path.is_file():
        return {
            "status": "blocked",
            "database": str(path),
            "blockers": ["database file does not exist"],
        }

    db = sqlite3.connect("file:" + str(path) + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        current_version = db.execute("PRAGMA user_version").fetchone()[0]
        if not _table_exists(db, "users"):
            return {
                "status": "blocked",
                "database": str(path),
                "current_version": current_version,
                "blockers": ["users table does not exist"],
            }

        columns = {
            row["name"] for row in db.execute("PRAGMA table_info(users)").fetchall()
        }
        indexes = {
            row["name"]
            for row in db.execute("PRAGMA index_list(users)").fetchall()
        }
        duplicates = [
            {
                "employee_no": row["employee_no"],
                "count": row["count"],
                "users": row["users"],
            }
            for row in db.execute(
                "SELECT lower(trim(employee_no)) AS employee_no, COUNT(*) AS count, "
                "GROUP_CONCAT(id || ':' || username, ', ') AS users "
                "FROM users WHERE trim(COALESCE(employee_no, '')) <> '' "
                "GROUP BY lower(trim(employee_no)) HAVING COUNT(*) > 1 "
                "ORDER BY employee_no LIMIT 20"
            ).fetchall()
        ]
        counts = dict(db.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active, "
            "SUM(CASE WHEN status = 'inactive' THEN 1 ELSE 0 END) AS inactive, "
            "SUM(CASE WHEN status = 'deleted' THEN 1 ELSE 0 END) AS deleted, "
            "SUM(CASE WHEN trim(COALESCE(employee_no, '')) <> '' THEN 1 ELSE 0 END) "
            "AS with_employee_no FROM users"
        ).fetchone())

        blockers = []
        if duplicates:
            blockers.append(
                "duplicate normalized employee numbers require manual resolution"
            )
        if current_version >= REQUIRED_VERSION:
            missing_columns = sorted(REQUIRED_COLUMNS - columns)
            if missing_columns:
                blockers.append(
                    "v059 columns missing: " + ", ".join(missing_columns)
                )
            if REQUIRED_INDEX not in indexes:
                blockers.append("v059 normalized employee number index is missing")

        return {
            "status": "blocked" if blockers else "ready",
            "database": str(path),
            "database_size_bytes": path.stat().st_size,
            "current_version": current_version,
            "required_version": REQUIRED_VERSION,
            "migration_needed": current_version < REQUIRED_VERSION,
            "users": counts,
            "normalized_employee_no_duplicates": duplicates,
            "v059_columns_present": sorted(REQUIRED_COLUMNS & columns),
            "v059_index_present": REQUIRED_INDEX in indexes,
            "integrity_check": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violation_count": len(
                db.execute("PRAGMA foreign_key_check").fetchall()
            ),
            "blockers": blockers,
        }
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db",
        default="/home/dubin/qr-system/data/production.db",
        help="SQLite database path",
    )
    args = parser.parse_args()
    result = inspect_database(args.db)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
