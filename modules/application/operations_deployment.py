"""Read-only release checks and isolated replica operations."""
from contextlib import closing
from pathlib import Path
import hashlib
import json
import sqlite3
import tempfile

from .operations_migrations import MigrationOperations
from .operations_schedule import ScheduleOperations


def _file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _database_evidence(database):
    path = Path(database).resolve(strict=True)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        version = int(db.execute("PRAGMA user_version").fetchone()[0])
        integrity = db.execute("PRAGMA quick_check").fetchone()[0]
        violations = [tuple(row) for row in db.execute("PRAGMA foreign_key_check")]
        table_names = [row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        tables = {}
        for name in table_names:
            quoted = name.replace('"', '""')
            rows = [tuple(row) for row in db.execute(f'SELECT * FROM "{quoted}"')]
            # A logical fingerprint must not depend on physical SQLite row order.
            encoded = sorted(json.dumps(row, ensure_ascii=False, default=lambda value: value.hex()) for row in rows)
            tables[name] = {"count": len(rows), "sha256": hashlib.sha256("\n".join(encoded).encode()).hexdigest()}
        db.rollback()
    return {
        "connection_mode": "read-only", "database": str(path),
        "user_version": version, "quick_check": integrity,
        "foreign_key_violations": violations, "tables": tables,
        "facts_digest": hashlib.sha256(json.dumps(tables, sort_keys=True).encode()).hexdigest(),
    }


class DeploymentOperations:
    @staticmethod
    def database_evidence(database):
        return _database_evidence(database)

    @staticmethod
    def deployment_acceptance(database, *, expected_version, expected_commit, health):
        evidence = _database_evidence(database)
        actual_commit = health.get("commit", "")
        return {
            "ok": evidence["quick_check"] == "ok"
                and not evidence["foreign_key_violations"]
                and evidence["user_version"] == expected_version
                and health.get("status") == "ok"
                and health.get("db") == "connected"
                and actual_commit == expected_commit,
            "expected_commit": expected_commit, "actual_commit": actual_commit,
            "database": evidence,
        }

    @staticmethod
    def rollback_check(database, baseline, *, attachments=()):
        """Check logical facts and explicitly captured attachment hashes."""
        evidence = _database_evidence(database)
        attachment_checks = [
            {"path": str(path), "unchanged": Path(path).is_file() and _file_digest(path) == digest}
            for path, digest in attachments
        ]
        facts_unchanged = evidence["facts_digest"] == baseline["facts_digest"]
        return {
            "ok": facts_unchanged and all(item["unchanged"] for item in attachment_checks)
                and evidence["quick_check"] == "ok" and not evidence["foreign_key_violations"],
            "facts_unchanged": facts_unchanged, "attachments": attachment_checks,
            "database": evidence,
        }

    @staticmethod
    def copy_database_replica(source, target):
        """Online copy from a read-only connection; never overwrite any file."""
        source = Path(source).resolve(strict=True)
        target_input = Path(target)
        if target_input.is_symlink():
            raise ValueError("replica path cannot be a symlink")
        target = target_input.resolve()
        if source == target:
            raise ValueError("source and replica paths must differ")
        target.parent.mkdir(parents=True, exist_ok=True)
        # Reserve only our new destination. Existing files, including hard links
        # to the source, fail before a writable SQLite connection is opened.
        with target.open("xb"):
            pass
        try:
            with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
                original.execute("PRAGMA query_only=ON")
                with closing(sqlite3.connect(target)) as replica:
                    original.backup(replica)
                    replica.commit()
                    if replica.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise RuntimeError("replica quick_check failed")
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return {"source": str(source), "replica": str(target), "connection_mode": "read-only-source"}

    @staticmethod
    def replica_replay(database, *, order_id, run_key, actor_id, start_date=None, planning_now=None):
        """Run an immutable candidate plan in a disposable, automatically cleaned copy."""
        with tempfile.TemporaryDirectory(prefix="qr-operations-replay-") as directory:
            replica = Path(directory) / "replica.db"
            DeploymentOperations.copy_database_replica(database, replica)
            with closing(sqlite3.connect(replica)) as db:
                db.row_factory = sqlite3.Row
                db.execute("PRAGMA foreign_keys=ON")
                MigrationOperations.migrate_database(db)
                return ScheduleOperations.generate_order_schedule(
                    order_id, start_date=start_date, schedule_run_key=run_key,
                    actor_id=actor_id, db=db, use_node_engine_override=True,
                    planning_now=planning_now,
                )

    @staticmethod
    def shadow_trial(database, *, order_id, run_key, actor_id, start_date=None):
        """The caller's source remains read-only even when shadow writes are enabled."""
        with tempfile.TemporaryDirectory(prefix="qr-operations-shadow-") as directory:
            replica = Path(directory) / "replica.db"
            DeploymentOperations.copy_database_replica(database, replica)
            with closing(sqlite3.connect(replica)) as db:
                db.row_factory = sqlite3.Row
                db.execute("PRAGMA foreign_keys=ON")
                MigrationOperations.migrate_database(db)
                with ScheduleOperations.schedule_flags(PRODUCTION_NODE_WRITE_ENABLED=True):
                    return ScheduleOperations.generate_shadow_order_schedule(
                        order_id, run_key, actor_id=actor_id, start_date=start_date, db=db,
                    )
