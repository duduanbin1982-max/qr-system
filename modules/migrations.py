"""Database migration registry and runner."""

import sqlite3

from modules.config import DB_PATH
from modules.migration_auth import MIGRATIONS as AUTH_MIGRATIONS
from modules.migration_baseline import MIGRATIONS as BASELINE_MIGRATIONS
from modules.migration_core import MIGRATIONS as CORE_MIGRATIONS
from modules.migration_performance import MIGRATIONS as PERFORMANCE_MIGRATIONS
from modules.migration_work_time import MIGRATIONS as WORK_TIME_MIGRATIONS
from modules.migration_order_completion import MIGRATIONS as ORDER_COMPLETION_MIGRATIONS
from modules.migration_process_quality import MIGRATIONS as PROCESS_QUALITY_MIGRATIONS
from modules.migration_quality_management import MIGRATIONS as QUALITY_MANAGEMENT_MIGRATIONS
from modules.migration_materials import MIGRATIONS as MATERIAL_MIGRATIONS
from modules.migration_approval_workflow import MIGRATIONS as APPROVAL_WORKFLOW_MIGRATIONS
from modules.migration_order_qr_print import MIGRATIONS as ORDER_QR_PRINT_MIGRATIONS
from modules.migration_serial_backfill import MIGRATIONS as SERIAL_BACKFILL_MIGRATIONS
from modules.migration_process_management import MIGRATIONS as PROCESS_MANAGEMENT_MIGRATIONS
from modules.migration_product_identity import MIGRATIONS as PRODUCT_IDENTITY_MIGRATIONS
from modules.migration_inventory_ledger import MIGRATIONS as INVENTORY_LEDGER_MIGRATIONS
from modules.migration_shipment_lifecycle import MIGRATIONS as SHIPMENT_LIFECYCLE_MIGRATIONS
from modules.migration_reporting import MIGRATIONS as REPORTING_MIGRATIONS


MIGRATIONS = sorted([
    *BASELINE_MIGRATIONS,
    *CORE_MIGRATIONS,
    *PERFORMANCE_MIGRATIONS,
    *WORK_TIME_MIGRATIONS,
    *AUTH_MIGRATIONS,
    *ORDER_COMPLETION_MIGRATIONS,
    *PROCESS_QUALITY_MIGRATIONS,
    *QUALITY_MANAGEMENT_MIGRATIONS,
    *MATERIAL_MIGRATIONS,
    *APPROVAL_WORKFLOW_MIGRATIONS,
    *ORDER_QR_PRINT_MIGRATIONS,
    *SERIAL_BACKFILL_MIGRATIONS,
    *PROCESS_MANAGEMENT_MIGRATIONS,
    *PRODUCT_IDENTITY_MIGRATIONS,
    *INVENTORY_LEDGER_MIGRATIONS,
    *SHIPMENT_LIFECYCLE_MIGRATIONS,
    *REPORTING_MIGRATIONS,
], key=lambda migration: migration[0])

_versions = [version for version, _, _ in MIGRATIONS]
if len(_versions) != len(set(_versions)):
    raise RuntimeError("duplicate database migration versions registered")
LATEST_VERSION = max(_versions, default=0)

def run_migrations(db=None):

    """Run all pending migrations in order."""
    own_db = db is None
    if own_db:
        db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    try:
        current = db.execute("PRAGMA user_version").fetchone()[0]
        sorted_migs = sorted(MIGRATIONS, key=lambda m: m[0])
        executed = 0
        for ver, desc, fn in sorted_migs:
            if ver <= current:
                continue
            try:
                fn(db)
                db.execute(f"PRAGMA user_version = {ver}")
                db.commit()
                executed += 1
            except Exception as e:
                print(f"[Migration v{ver}] {desc} - FAILED: {e}")
                db.rollback()
                raise
        if executed:
            print(f"[Migration] Ran {executed} migration(s)")
        return executed
    finally:
        if own_db:
            db.close()


def init_db():
    """Thin wrapper - runs pending migrations."""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        run_migrations(db)
    finally:
        db.close()
