"""Database migration registry and runner."""

import sqlite3

from modules.config import DB_PATH
from modules.migration_baseline import MIGRATIONS as BASELINE_MIGRATIONS
from modules.migration_core import MIGRATIONS as CORE_MIGRATIONS
from modules.migration_performance import MIGRATIONS as PERFORMANCE_MIGRATIONS
from modules.migration_work_time import MIGRATIONS as WORK_TIME_MIGRATIONS


MIGRATIONS = [
    *BASELINE_MIGRATIONS,
    *CORE_MIGRATIONS,
    *PERFORMANCE_MIGRATIONS,
    *WORK_TIME_MIGRATIONS,
]

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
