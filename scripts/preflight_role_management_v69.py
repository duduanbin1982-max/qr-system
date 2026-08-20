#!/usr/bin/env python3
"""Read-only v069 role identity and approval-reference preflight."""

import argparse
import json
import sqlite3
from pathlib import Path


def inspect(db):
    db.row_factory = sqlite3.Row
    blockers = []
    warnings = []
    version = int(db.execute("PRAGMA user_version").fetchone()[0])
    required_tables = {
        "roles", "role_code_aliases", "approval_config",
        "role_permission_migration_evidence",
    }
    tables = {
        row["name"] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    for table in sorted(required_tables - tables):
        blockers.append("missing table: " + table)

    old_permission_count = 0
    mismatch_count = 0
    invalid_code_count = 0
    invalid_level_count = 0
    alias_count = 0
    evidence_count = 0
    if not blockers:
        old_permission_count = db.execute(
            "SELECT COUNT(*) FROM roles WHERE permissions LIKE '%page:production.quality%'"
        ).fetchone()[0]
        mismatch_count = db.execute(
            """SELECT COUNT(*) FROM approval_config ac
               WHERE (ac.approver_role_id IS NOT NULL AND NOT EXISTS (
                   SELECT 1 FROM roles r WHERE r.id=ac.approver_role_id
               ))
                  OR (ac.approver_role_2_id IS NOT NULL AND NOT EXISTS (
                   SELECT 1 FROM roles r WHERE r.id=ac.approver_role_2_id
               ))
                  OR (ac.approver_role_3_id IS NOT NULL AND NOT EXISTS (
                   SELECT 1 FROM roles r WHERE r.id=ac.approver_role_3_id
               ))"""
        ).fetchone()[0]
        invalid_code_count = db.execute(
            """SELECT COUNT(*) FROM roles
               WHERE length(code) < 2 OR length(code) > 64
                  OR code != lower(code) OR code GLOB '*[^a-z0-9_]*'"""
        ).fetchone()[0]
        invalid_level_count = db.execute(
            "SELECT COUNT(*) FROM roles WHERE level IS NULL OR level < 1 "
            "OR level != CAST(level AS INTEGER)"
        ).fetchone()[0]
        alias_count = db.execute("SELECT COUNT(*) FROM role_code_aliases").fetchone()[0]
        evidence_count = db.execute(
            "SELECT COUNT(*) FROM role_permission_migration_evidence"
        ).fetchone()[0]

        if old_permission_count:
            blockers.append("legacy page:production.quality remains on roles")
        if mismatch_count:
            blockers.append(f"approval role-id references missing roles: {mismatch_count}")
        if invalid_code_count:
            blockers.append(f"invalid role codes: {invalid_code_count}")
        if invalid_level_count:
            blockers.append(f"invalid role levels: {invalid_level_count}")
        if alias_count == 0:
            warnings.append("no role-code aliases found")
        if evidence_count == 0:
            warnings.append("no permission migration evidence rows found")

    return {
        "status": "ready" if not blockers else "blocked",
        "user_version": version,
        "summary": {
            "role_code_alias_count": alias_count,
            "permission_migration_evidence_count": evidence_count,
            "legacy_permission_count": old_permission_count,
            "approval_role_id_mismatch_count": mismatch_count,
            "invalid_role_code_count": invalid_code_count,
            "invalid_role_level_count": invalid_level_count,
        },
        "blockers": blockers,
        "warnings": warnings,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="角色管理 v069 只读预检")
    parser.add_argument("--db", required=True)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    db_path = Path(args.db).expanduser().resolve()
    db = sqlite3.connect("file:" + db_path.as_posix() + "?mode=ro", uri=True)
    try:
        report = inspect(db)
    finally:
        db.close()
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).expanduser().resolve().write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if report["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
