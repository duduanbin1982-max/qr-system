#!/usr/bin/env python3
"""Read-only production-copy preflight for inventory dual views."""

import argparse
import json
import sqlite3
from pathlib import Path


REQUIRED_TABLES = {
    "inventory", "inventory_logs", "products", "product_code_aliases",
    "product_inventory_thresholds", "inventory_allocation_runs",
    "inventory_allocation_items", "audit_event_outbox",
}
REQUIRED_TRIGGERS = {
    "prevent_inventory_allocation_runs_update",
    "prevent_inventory_allocation_runs_delete",
    "prevent_inventory_allocation_items_update",
    "prevent_inventory_allocation_items_delete",
}


def run(path, limit=1000):
    database = Path(path).resolve()
    uri = f"file:{database.as_posix()}?mode=ro"
    db = sqlite3.connect(uri, uri=True)
    db.row_factory = sqlite3.Row
    try:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        triggers = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        foreign_keys = db.execute("PRAGMA foreign_key_check").fetchall()
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        identity_exceptions = db.execute(
            "SELECT COUNT(*) FROM inventory i "
            "LEFT JOIN orders o ON o.id=i.order_id "
            "LEFT JOIN product_code_aliases a ON a.product_code=COALESCE(NULLIF(i.product_code_snapshot,''),i.product_model) "
            "WHERE i.deleted_at IS NULL AND COALESCE(i.product_id,o.product_id,a.product_id) IS NULL"
        ).fetchone()[0]
        active_inventory = db.execute(
            "SELECT COUNT(*) FROM inventory WHERE deleted_at IS NULL"
        ).fetchone()[0]
        allocation_runs = db.execute("SELECT COUNT(*) FROM inventory_allocation_runs").fetchone()[0]
        report = {
            "database": str(database),
            "connection_mode": "read-only",
            "user_version": db.execute("PRAGMA user_version").fetchone()[0],
            "required_version": 96,
            "required_tables_missing": sorted(REQUIRED_TABLES - tables),
            "required_triggers_missing": sorted(REQUIRED_TRIGGERS - triggers),
            "foreign_key_violations": len(foreign_keys),
            "integrity_check": integrity,
            "active_inventory_count": active_inventory,
            "identity_exceptions": min(int(identity_exceptions), int(limit)),
            "allocation_run_count": allocation_runs,
            "feature_flags_default_off": True,
        }
        report["ok"] = (
            report["user_version"] >= report["required_version"]
            and not report["required_tables_missing"]
            and not report["required_triggers_missing"]
            and not report["foreign_key_violations"]
            and report["integrity_check"] == "ok"
        )
        return report
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()
    print(json.dumps(run(args.db, args.limit), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
