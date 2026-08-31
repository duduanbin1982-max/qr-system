#!/usr/bin/env python3
"""Shared mechanical safety primitives for controlled production commands."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from typing import Any, Callable, Iterable, Mapping, Sequence, TextIO

from scripts import deployment_manifest


class ProductionOperationError(RuntimeError):
    """An operational failure with a stable category for evidence and callers."""

    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = str(category)


def _reserve_output(path: Path, category: str, label: str) -> tuple[int, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ProductionOperationError(
            category, f"{label} already exists: {path}"
        ) from exc
    except OSError as exc:
        raise ProductionOperationError(category, str(exc)) from exc
    try:
        reserved = os.fstat(descriptor)
        return reserved.st_dev, reserved.st_ino
    finally:
        os.close(descriptor)


def _remove_reservation(path: Path, identity: tuple[int, int]) -> None:
    try:
        observed = path.stat()
    except FileNotFoundError:
        return
    if (observed.st_dev, observed.st_ino) == identity:
        path.unlink(missing_ok=True)


def open_read_only_sqlite(path: str | Path) -> sqlite3.Connection:
    """Open a transactionally stable, fail-closed SQLite read connection."""

    database = Path(path).expanduser().resolve()
    uri = "file:" + database.as_posix() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA query_only=ON")
        if int(connection.execute("PRAGMA query_only").fetchone()[0]) != 1:
            raise ProductionOperationError(
                "integrity", "SQLite query_only was not enabled"
            )
        connection.execute("BEGIN")
        return connection
    except Exception:
        connection.close()
        raise


def file_fingerprint(path: str | Path) -> dict[str, Any]:
    artifact = Path(path).expanduser().resolve()
    if not artifact.is_file():
        raise ProductionOperationError(
            "argument", f"evidence file does not exist: {artifact}"
        )
    return {
        "path": str(artifact),
        "sha256": deployment_manifest.sha256_file(artifact),
        "size_bytes": artifact.stat().st_size,
    }


def database_fingerprint(path: str | Path) -> dict[str, Any]:
    artifact = Path(path).expanduser().resolve()
    return {
        **file_fingerprint(artifact),
        **deployment_manifest.sqlite_evidence(artifact),
    }


def table_count_fingerprint(
    connection: sqlite3.Connection, tables: Iterable[str]
) -> dict[str, int]:
    result = {}
    for table in tables:
        if not isinstance(table, str) or not table.isidentifier():
            raise ProductionOperationError(
                "argument", f"unsupported table identifier: {table!r}"
            )
        result[table] = int(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        )
    return result


def write_evidence_json(
    path: str | Path, payload: Any, *, overwrite: bool = False
) -> Path:
    target = Path(path).expanduser().resolve()
    reservation = None
    if not overwrite:
        reservation = _reserve_output(target, "argument", "evidence destination")
    try:
        deployment_manifest.atomic_write_json(target, payload)
    except Exception:
        if reservation is not None:
            _remove_reservation(target, reservation)
        raise
    return target


def online_database_backup(source: str | Path, target: str | Path) -> dict[str, Any]:
    """Create an online SQLite backup and verify it with the deployment authority."""

    source_path = Path(source).expanduser().resolve()
    target_path = Path(target).expanduser().resolve()
    source_connection = open_read_only_sqlite(source_path)
    try:
        reservation = _reserve_output(
            target_path, "backup", "database backup"
        )
    except Exception:
        source_connection.close()
        raise
    target_connection = None
    try:
        target_connection = sqlite3.connect(str(target_path))
        source_connection.backup(target_connection)
        target_connection.close()
        target_connection = None
        return database_fingerprint(target_path)
    except Exception:
        _remove_reservation(target_path, reservation)
        raise
    finally:
        if target_connection is not None:
            target_connection.close()
        source_connection.close()


def run_authoritative_backup(
    *,
    project_root: str | Path,
    database: str | Path,
    backup_dir: str | Path,
    metadata_file: str | Path,
) -> dict[str, Any]:
    """Invoke backup-db.sh and verify its metadata with deployment_manifest.py."""

    root = Path(project_root).expanduser().resolve()
    script = root / "scripts" / "backup-db.sh"
    if not script.is_file():
        raise ProductionOperationError(
            "argument", f"authoritative backup script does not exist: {script}"
        )
    metadata = Path(metadata_file).expanduser().resolve()
    reservation = _reserve_output(metadata, "argument", "backup metadata")
    environment = os.environ.copy()
    environment.update(
        {
            "QR_PROJECT_ROOT": str(root),
            "DB_PATH": str(Path(database).expanduser().resolve()),
            "BACKUP_DIR": str(Path(backup_dir).expanduser().resolve()),
            "BACKUP_METADATA_FILE": str(metadata),
        }
    )
    try:
        completed = subprocess.run(
            ["bash", str(script)],
            cwd=str(root),
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        _remove_reservation(metadata, reservation)
        raise ProductionOperationError("backup", str(exc)) from exc
    if completed.returncode != 0:
        _remove_reservation(metadata, reservation)
        detail = (completed.stderr or completed.stdout or "backup command failed").strip()
        raise ProductionOperationError("backup", detail)
    try:
        return deployment_manifest.verify_backup_metadata(metadata)
    except Exception as exc:
        raise ProductionOperationError("integrity", str(exc)) from exc


def run_json_cli(
    parser_factory: Callable[[], Any],
    operation: Callable[[Any], Mapping[str, Any]],
    argv: Sequence[str] | None = None,
    *,
    failure_indent: int | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run an existing argparse command with its frozen JSON stream contract."""

    args = parser_factory().parse_args(argv)
    output = stdout if stdout is not None else sys.stdout
    errors = stderr if stderr is not None else sys.stderr
    try:
        result = operation(args)
    except Exception as exc:
        print(
            json.dumps(
                {"status": "failed", "error": str(exc)},
                ensure_ascii=False,
                indent=failure_indent,
            ),
            file=errors,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2), file=output)
    return 0
