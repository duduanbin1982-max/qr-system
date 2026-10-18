"""Migration metadata and execution adapter for controlled operations."""
from pathlib import Path
from contextlib import closing
import sqlite3
import subprocess
import sys
import os
from threading import RLock

from .operations_dto import MigrationStep


_CATALOG_LOCK = RLock()


class MigrationOperations:
    @staticmethod
    def latest_schema_version():
        from modules.migrations import LATEST_VERSION

        return int(LATEST_VERSION)

    @staticmethod
    def pending_migration_steps(current_version):
        from modules.migrations import pending_migrations

        return tuple(MigrationStep(version, description) for version, description, _ in pending_migrations(current_version))

    @staticmethod
    def migration_plan(database_path):
        database = Path(database_path).resolve(strict=True)
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
            connection.execute("PRAGMA query_only=ON")
            current = int(connection.execute("PRAGMA user_version").fetchone()[0])
            integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(f"database quick_check failed: {integrity}")
            pending = MigrationOperations.pending_migration_steps(current)
            return {
                "database": str(database),
                "connection_mode": "read-only",
                "current_version": current,
                "target_version": MigrationOperations.latest_schema_version(),
                "pending_count": len(pending),
                "pending": [{"version": item.version, "description": item.description} for item in pending],
                "quick_check": integrity,
            }

    @staticmethod
    def migrate_database(db):
        from modules.migrations import run_migrations

        return int(run_migrations(db))

    @staticmethod
    def migrate_default_database():
        from modules.migrations import run_migrations

        return int(run_migrations())

    @staticmethod
    def target_schema_version(target_root):
        """Read target metadata in a separate process, including older releases."""
        result = subprocess.run(
            [sys.executable, "-c", "from modules.migrations import LATEST_VERSION; print(LATEST_VERSION)"],
            cwd=target_root,
            env={**os.environ, "PYTHONPATH": str(target_root)},
            check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        if result.returncode:
            raise RuntimeError("cannot read target schema version without running migrations: " + result.stderr.strip())
        try:
            return int(result.stdout.strip())
        except ValueError as error:
            raise RuntimeError("target schema version is not an integer") from error

    @staticmethod
    def replay_migration_step(db, version):
        """Replay one registered step on the caller's disposable connection.

        Preserve historical validators' direct-step semantics: no commit or
        user_version change is introduced by this adapter.
        """
        from modules.migrations import MIGRATIONS

        matches = [callback for number, _, callback in MIGRATIONS if number == version]
        if len(matches) != 1:
            raise ValueError(f"unknown migration version: {version}")
        return matches[0](db)

    @staticmethod
    def prepare_e2e_schema(db):
        from modules import migrations

        with _CATALOG_LOCK:
            catalog = migrations.MIGRATIONS
            migrations.MIGRATIONS = [entry for entry in catalog if entry[0] < 60]
            try:
                return int(migrations.run_migrations(db))
            finally:
                migrations.MIGRATIONS = catalog
