"""Database migration runner backed by a validated dependency catalog."""

import sqlite3

from modules.config import DB_PATH
from modules.migration_catalog import MIGRATION_DEPENDENCIES, MIGRATIONS
from modules.migration_planning import linear_dependencies, plan_migrations, validate_registry


validate_registry(MIGRATIONS, MIGRATION_DEPENDENCIES)
LATEST_VERSION = max((version for version, _, _ in MIGRATIONS), default=0)


def _active_dependencies():
    """Preserve test/plugin compatibility when MIGRATIONS is replaced at runtime."""
    registered = {version for version, _, _ in MIGRATIONS}
    if registered == set(MIGRATION_DEPENDENCIES):
        return MIGRATION_DEPENDENCIES
    return linear_dependencies(MIGRATIONS)


def pending_migrations(current_version):
    """Return the validated migration plan without changing a database."""
    return plan_migrations(current_version, MIGRATIONS, _active_dependencies())


def run_migrations(db=None):
    """Run all pending migrations in dependency order."""
    own_db = db is None
    if own_db:
        db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    try:
        current = int(db.execute("PRAGMA user_version").fetchone()[0])
        executed = 0
        for version, description, migration_fn in pending_migrations(current):
            try:
                migration_fn(db)
                db.execute(f"PRAGMA user_version = {version}")
                db.commit()
                executed += 1
            except Exception as exc:
                print(f"[Migration v{version}] {description} - FAILED: {exc}")
                db.rollback()
                raise
        if executed:
            print(f"[Migration] Ran {executed} migration(s)")
        return executed
    finally:
        if own_db:
            db.close()


def init_db():
    """Thin compatibility wrapper that runs pending migrations."""
    run_migrations()
