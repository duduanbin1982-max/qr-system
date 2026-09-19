#!/usr/bin/env python3
"""Safe, evidence-first operations for the production-node scheduling rollout.

The commands in this module deliberately separate read-only validation from
state changes.  A preflight or shadow run never opens SQLite for writing; the
only mutable artifact owned here is the explicitly supplied feature-flag file,
and every flag change is guarded by a monotonic stage transition and an
immutable evidence record.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
from typing import Any, Mapping, Sequence

from modules import migrations
from scripts import production_operations


SCHEMA = "qr-system-production-node-operations/v1"
FLAG_NAMES = (
    "PRODUCTION_NODE_QUERY_ENABLED",
    "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED",
    "PRODUCTION_NODE_WRITE_ENABLED",
    "PRODUCTION_NODE_ENGINE_ENABLED",
    "LEGACY_PROCESS_LINE_WRITE_BLOCKED",
)

# Values are intentionally ordered.  A rollout may advance only one state at
# a time; a backward move requires a rollback-readiness evidence artifact.
_STATES = {
    "off": (False, False, False, False, False),
    "query_audit": (True, True, False, False, False),
    "write_shadow": (True, True, True, False, False),
    "engine": (True, True, True, True, False),
    "legacy_blocked": (True, True, True, True, True),
}


class OperationError(RuntimeError):
    """A deterministic operational error suitable for JSON output."""


def _table_exists(db: sqlite3.Connection, table: str) -> bool:
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(db, table):
        return set()
    return {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}


def _scalar(db: sqlite3.Connection, sql: str, params=(), default=0):
    row = db.execute(sql, params).fetchone()
    return default if row is None or row[0] is None else row[0]


def _open_read_only(path: str | Path) -> sqlite3.Connection:
    return production_operations.open_read_only_sqlite(path)


def _commit_value(expected_commit: str, actual_commit: str | None) -> tuple[str, str]:
    expected = str(expected_commit or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise OperationError("expected_commit must be a 40-character SHA")
    actual = str(actual_commit or "").strip().lower()
    if actual and not re.fullmatch(r"[0-9a-f]{40}", actual):
        raise OperationError("actual_commit must be a 40-character SHA")
    return expected, actual


def resolve_checkout_commit(project_root: str | Path) -> str:
    root = Path(project_root).expanduser().resolve()
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip().lower()


def flags_for_state(state: str) -> dict[str, bool]:
    try:
        values = _STATES[state]
    except KeyError as exc:
        raise ValueError(f"unknown production-node flag state: {state}") from exc
    return dict(zip(FLAG_NAMES, values))


def _state_for_flags(flags: Mapping[str, Any]) -> str:
    values = tuple(bool(flags.get(name, False)) for name in FLAG_NAMES)
    for state, expected in _STATES.items():
        if values == expected:
            return state
    raise ValueError("flag values do not describe an approved production-node state")


def validate_flag_transition(
    current_flags: Mapping[str, Any],
    target_flags: Mapping[str, Any],
    rollback_evidence: str | Path | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    current_state = _state_for_flags(current_flags)
    target_state = _state_for_flags(target_flags)
    current_index = list(_STATES).index(current_state)
    target_index = list(_STATES).index(target_state)
    if current_index == target_index:
        return {
            "changed": False,
            "current_state": current_state,
            "target_state": target_state,
        }
    if target_index == current_index + 1:
        return {
            "changed": True,
            "current_state": current_state,
            "target_state": target_state,
        }
    if target_index < current_index:
        if rollback_evidence is None:
            raise ValueError("rollback evidence is required for a backward flag transition")
        evidence = _load_json_artifact(rollback_evidence)
        if evidence.get("command") != "rollback-readiness" or evidence.get("ok") is not True:
            raise ValueError("rollback evidence is not a valid rollback-readiness artifact")
        if evidence.get("current_state") not in _STATES:
            raise ValueError("rollback evidence has an invalid current state")
        return {
            "changed": True,
            "current_state": current_state,
            "target_state": target_state,
            "rollback": True,
        }
    raise ValueError("cannot skip production-node flag stages")


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _canonical_digest(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_json_artifact(value: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    path = Path(value).expanduser().resolve()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid evidence artifact: {path}") from exc


def _write_artifact(evidence_dir: str | Path, name: str, payload: Mapping[str, Any]) -> Path:
    target = Path(evidence_dir).expanduser().resolve() / name
    production_operations.write_evidence_json(target, dict(payload))
    return target


def _base_report(command: str, mode: str, expected: str, actual: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "ok": True,
        "mode": mode,
        "command": command,
        "checks": {},
        "counts": {},
        "digests": {},
        "artifacts": {},
        "expected_commit": expected,
        "actual_commit": actual,
    }


def _database_checks(db: sqlite3.Connection) -> dict[str, Any]:
    integrity = str(_scalar(db, "PRAGMA integrity_check", default=""))
    foreign_keys = list(db.execute("PRAGMA foreign_key_check").fetchall())
    return {
        "database_integrity": integrity == "ok",
        "foreign_key_errors_zero": len(foreign_keys) == 0,
        "integrity_check": integrity,
        "foreign_key_error_count": len(foreign_keys),
        "query_only": int(_scalar(db, "PRAGMA query_only", default=0)),
        "user_version": int(_scalar(db, "PRAGMA user_version", default=0)),
    }


def _mapping_metrics(db: sqlite3.Connection) -> tuple[Any, int, int]:
    if not _table_exists(db, "production_nodes") or not _table_exists(
        db, "process_production_lines"
    ):
        return None, 0, 0
    node_count = int(_scalar(db, "SELECT COUNT(*) FROM production_nodes"))
    missing = int(
        _scalar(
            db,
            "SELECT COUNT(*) FROM process_production_lines pl "
            "LEFT JOIN production_nodes n ON n.legacy_process_line_id=pl.id "
            "WHERE n.id IS NULL",
        )
    )
    return node_count, missing, int(
        _scalar(
            db,
            "SELECT COUNT(*) FROM process_production_lines",
        )
    )


def _historical_missing_count(db: sqlite3.Connection) -> int | None:
    if not _table_exists(db, "production_node_migration_differences"):
        return None
    return int(
        _scalar(
            db,
            "SELECT COUNT(*) FROM production_node_migration_differences "
            "WHERE difference_code IN ('missing_mapping','missing_legacy_reference')",
        )
    )


def _intentionally_unassigned_blocked_count(db: sqlite3.Connection) -> int | None:
    if not _table_exists(db, "production_node_migration_differences"):
        return None
    return int(
        _scalar(
            db,
            "SELECT COUNT(*) FROM production_node_migration_differences "
            "WHERE difference_code='intentionally_unassigned_blocked'",
        )
    )


def _latest_compat_metrics(db: sqlite3.Connection) -> tuple[int | None, int]:
    table = "production_node_compatibility_observations"
    if not _table_exists(db, table):
        return None, 0
    rows = db.execute(
        "SELECT scope,source_id,mismatch FROM ("
        "SELECT scope,source_id,mismatch,"
        "ROW_NUMBER() OVER (PARTITION BY scope,source_id "
        "ORDER BY observed_at DESC,id DESC) AS rn "
        f"FROM {table}) WHERE rn=1"
    ).fetchall()
    return len(rows), sum(1 for row in rows if int(row[2]) == 1)


def _shadow_metrics(db: sqlite3.Connection) -> dict[str, Any]:
    table = "order_process_schedule_segments"
    schedules = "order_process_schedules"
    if not _table_exists(db, table) or not _table_exists(db, schedules):
        return {
            "shadow_conflict_count": 0,
            "quantity_difference": 0,
            "serial_split_violation_count": 0,
        }
    segment_columns = _columns(db, table)
    schedule_columns = _columns(db, schedules)
    if not {"schedule_id", "quantity"} <= segment_columns or not {
        "id",
        "quantity",
    } <= schedule_columns:
        return {
            "shadow_conflict_count": 0,
            "quantity_difference": 0,
            "serial_split_violation_count": 0,
        }

    # V078-V085 segment facts predate production_node_id.  Stage-one
    # preflight must be able to inspect that approved source schema before
    # V087 adds the node reference; there cannot be a node conflict until the
    # column exists.  Quantity conservation remains valid on both schemas.
    if "production_node_id" not in segment_columns:
        conflict_count = 0
    elif _table_exists(db, "production_nodes"):
        conflict_sql = (
            "SELECT COUNT(*) FROM {table} a JOIN {table} b "
            "ON a.id < b.id AND a.production_node_id=b.production_node_id "
            "AND a.segment_start_at < b.segment_end_at "
            "AND b.segment_start_at < a.segment_end_at "
            "LEFT JOIN production_nodes n ON n.id=a.production_node_id "
            "WHERE COALESCE(n.capacity_mode,'exclusive')='exclusive'"
        ).format(table=table)
        conflict_count = int(_scalar(db, conflict_sql))
    else:
        conflict_sql = (
            "SELECT COUNT(*) FROM {table} a JOIN {table} b "
            "ON a.id < b.id AND a.production_node_id=b.production_node_id "
            "AND a.segment_start_at < b.segment_end_at "
            "AND b.segment_start_at < a.segment_end_at"
        ).format(table=table)
        conflict_count = int(_scalar(db, conflict_sql))
    quantity_difference = 0
    for row in db.execute(
        "SELECT s.id,s.quantity,COALESCE(SUM(g.quantity),0) AS segment_quantity "
        f"FROM {schedules} s LEFT JOIN {table} g ON g.schedule_id=s.id "
        "GROUP BY s.id,s.quantity"
    ):
        quantity_difference += abs(int(row[1] or 0) - int(row[2] or 0))

    serial_split = 0
    allocation_table = "production_node_schedule_allocations"
    if _table_exists(db, allocation_table):
        columns = _columns(db, allocation_table)
        if {"schedule_id", "serial_id", "production_node_id"} <= columns:
            serial_split = int(
                _scalar(
                    db,
                    f"SELECT COUNT(*) FROM (SELECT schedule_id,serial_id "
                    f"FROM {allocation_table} WHERE serial_id IS NOT NULL "
                    "AND TRIM(serial_id)<>'' GROUP BY schedule_id,serial_id "
                    "HAVING COUNT(DISTINCT production_node_id)>1)",
                )
            )
    return {
        "shadow_conflict_count": conflict_count,
        "quantity_difference": quantity_difference,
        "serial_split_violation_count": serial_split,
    }


def run_preflight(
    db: str | Path,
    expected_commit: str,
    actual_commit: str | None = None,
) -> dict[str, Any]:
    expected, actual = _commit_value(expected_commit, actual_commit)
    report = _base_report("preflight", "read_only_preflight", expected, actual)
    report["checks"]["expected_commit_matches"] = bool(actual) and actual == expected
    with _open_read_only(db) as connection:
        database = _database_checks(connection)
        report["counts"]["database_user_version"] = database["user_version"]
        report["checks"].update(
            {
                "database_integrity": database["database_integrity"],
                "foreign_key_errors_zero": database["foreign_key_errors_zero"],
                "query_only": database["query_only"] == 1,
            }
        )
        version = database["user_version"]
        report["checks"]["expected_database_version"] = version in range(85, 90)
        node_count, mapping_missing, legacy_count = _mapping_metrics(connection)
        if node_count is None:
            report["checks"]["core_node_count_21"] = None
            report["checks"]["legacy_mapping_complete"] = None
        else:
            report["counts"]["core_node_count"] = node_count
            report["counts"]["legacy_process_line_count"] = legacy_count
            report["counts"]["legacy_mapping_missing"] = mapping_missing
            report["checks"]["core_node_count_21"] = node_count == 21
            report["checks"]["legacy_mapping_complete"] = mapping_missing == 0
        historical_missing = _historical_missing_count(connection)
        if historical_missing is None:
            report["checks"]["unmapped_historical_facts"] = None
        else:
            report["counts"]["unmapped_historical_facts"] = historical_missing
            report["checks"]["unmapped_historical_facts"] = historical_missing == 0
        intentionally_unassigned = _intentionally_unassigned_blocked_count(connection)
        if intentionally_unassigned is not None:
            report["counts"][
                "intentionally_unassigned_blocked_facts"
            ] = intentionally_unassigned
        latest_observations, latest_mismatch = _latest_compat_metrics(connection)
        if latest_observations is None:
            report["checks"]["latest_compat_mismatch_zero"] = None
        else:
            report["counts"]["latest_compat_observation_count"] = latest_observations
            report["counts"]["latest_compat_mismatch_count"] = latest_mismatch
            report["checks"]["latest_compat_mismatch_zero"] = latest_mismatch == 0
        shadow = _shadow_metrics(connection)
        report["counts"].update(shadow)
        report["checks"].update(
            {
                "shadow_conflicts_zero": shadow["shadow_conflict_count"] == 0,
                "quantity_conservation_100_percent": shadow["quantity_difference"] == 0,
                "serial_split_violations_zero": shadow["serial_split_violation_count"] == 0,
            }
        )
        report["digests"]["database"] = production_operations.database_fingerprint(db)
    report["ok"] = all(value is not False for value in report["checks"].values())
    return report


def run_shadow_run(
    db: str | Path,
    expected_commit: str,
    actual_commit: str | None = None,
) -> dict[str, Any]:
    expected, actual = _commit_value(expected_commit, actual_commit)
    report = _base_report("shadow-run", "read_only_shadow_run", expected, actual)
    report["checks"]["expected_commit_matches"] = bool(actual) and actual == expected
    with _open_read_only(db) as connection:
        shadow = _shadow_metrics(connection)
        report["counts"].update(shadow)
        report["checks"].update(
            {
                "shadow_conflicts_zero": shadow["shadow_conflict_count"] == 0,
                "quantity_conservation_100_percent": shadow["quantity_difference"] == 0,
                "serial_split_violations_zero": shadow["serial_split_violation_count"] == 0,
            }
        )
        report["digests"]["database"] = production_operations.database_fingerprint(db)
    report["ok"] = all(value is not False for value in report["checks"].values())
    return report


def _read_env(path: str | Path) -> tuple[list[str], dict[str, bool]]:
    target = Path(path).expanduser().resolve()
    if not target.exists():
        return [], flags_for_state("off")
    lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
    values = flags_for_state("off")
    for line in lines:
        match = re.match(r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*(?:#.*)?$", line.rstrip("\r\n"))
        if match and match.group(1) in FLAG_NAMES:
            values[match.group(1)] = match.group(2).lower() in {"1", "true", "yes", "on"}
    return lines, values


def _write_env_atomic(path: Path, lines: list[str], flags: Mapping[str, bool]) -> None:
    seen: set[str] = set()
    output: list[str] = []
    for line in lines:
        match = re.match(
            r"^(\s*)([A-Z][A-Z0-9_]*)(\s*=\s*)([^#]*?)(\s+#.*)?(\r?\n)?$",
            line,
        )
        if match and match.group(2) in FLAG_NAMES:
            key = match.group(2)
            output.append(
                f"{match.group(1)}{key}{match.group(3)}"
                f"{'true' if flags[key] else 'false'}"
                f"{match.group(5) or ''}{match.group(6) or chr(10)}"
            )
            seen.add(key)
        else:
            output.append(line)
    if output and not output[-1].endswith(("\n", "\r")):
        output[-1] += "\n"
    for key in FLAG_NAMES:
        if key not in seen:
            output.append(f"{key}={'true' if flags[key] else 'false'}\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        os.chmod(temporary, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.writelines(output)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _find_idempotent_artifact(evidence_dir: str | Path, command: str, key: str) -> Path | None:
    directory = Path(evidence_dir).expanduser().resolve()
    if not directory.exists():
        return None
    for path in directory.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("command") == command and payload.get("idempotency_key") == key:
            return path
    return None


def _check_replay(path: Path, expected: str, actual: str, request: Mapping[str, Any]) -> dict[str, Any]:
    payload = _load_json_artifact(path)
    for key, value in request.items():
        if payload.get(key) != value:
            raise OperationError(f"idempotency key already used with different {key}")
    if payload.get("expected_commit") != expected or payload.get("actual_commit") != actual:
        raise OperationError("idempotency key already used with different commit")
    payload["idempotent_replay"] = True
    payload["artifacts"] = {**payload.get("artifacts", {}), "evidence": str(path)}
    return payload


def set_flags(
    *,
    db: str | Path,
    env_file: str | Path,
    state: str,
    evidence_dir: str | Path,
    expected_commit: str,
    actual_commit: str | None = None,
    idempotency_key: str = "",
    rollback_evidence: str | Path | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not idempotency_key.strip():
        raise OperationError("idempotency_key is required")
    expected, actual = _commit_value(expected_commit, actual_commit)
    existing = _find_idempotent_artifact(evidence_dir, "set-flags", idempotency_key)
    request = {"state": state, "idempotency_key": idempotency_key}
    if existing:
        return _check_replay(existing, expected, actual, request)
    target_flags = flags_for_state(state)
    lines, current_flags = _read_env(env_file)
    if rollback_evidence is not None:
        evidence = _load_json_artifact(rollback_evidence)
        if (
            evidence.get("expected_commit") != expected
            or evidence.get("actual_commit") != actual
        ):
            raise OperationError(
                "rollback evidence commit does not match the deployed commit"
            )
    transition = validate_flag_transition(current_flags, target_flags, rollback_evidence)
    # The SQLite file is intentionally opened read-only.  It provides a
    # consistent input digest without allowing this command to mutate facts.
    with _open_read_only(db) as connection:
        database = _database_checks(connection)
        database_digest = production_operations.database_fingerprint(db)
    _write_env_atomic(Path(env_file).expanduser().resolve(), lines, target_flags)
    payload = {
        "schema": SCHEMA,
        "ok": True,
        "mode": "controlled_flag_change",
        "command": "set-flags",
        "idempotency_key": idempotency_key,
        "expected_commit": expected,
        "actual_commit": actual,
        "state": state,
        "previous_state": transition["current_state"],
        "flags": target_flags,
        "previous_flags": current_flags,
        "database_user_version": database["user_version"],
        "digests": {"database": database_digest},
        "artifacts": {"env_file": str(Path(env_file).expanduser().resolve())},
    }
    artifact = _write_artifact(evidence_dir, f"set-flags-{idempotency_key}.json", payload)
    payload["artifacts"]["evidence"] = str(artifact)
    return payload


def rollback_readiness(
    *,
    db: str | Path,
    evidence_dir: str | Path,
    expected_commit: str,
    actual_commit: str | None = None,
    rollback_commit: str = "",
    idempotency_key: str = "",
) -> dict[str, Any]:
    if not idempotency_key.strip():
        raise OperationError("idempotency_key is required")
    expected, actual = _commit_value(expected_commit, actual_commit)
    rollback = rollback_commit.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", rollback):
        raise OperationError("rollback_commit must be a 40-character SHA")
    existing = _find_idempotent_artifact(evidence_dir, "rollback-readiness", idempotency_key)
    request = {"idempotency_key": idempotency_key, "rollback_commit": rollback}
    if existing:
        return _check_replay(existing, expected, actual, request)
    with _open_read_only(db) as connection:
        database = _database_checks(connection)
        current_flags = flags_for_state("off")
    payload = {
        "schema": SCHEMA,
        "ok": True,
        "mode": "rollback_readiness",
        "command": "rollback-readiness",
        "idempotency_key": idempotency_key,
        "expected_commit": expected,
        "actual_commit": actual,
        "rollback_commit": rollback,
        "current_state": _state_for_flags(current_flags),
        "database_user_version": database["user_version"],
        "digests": {"database": production_operations.database_fingerprint(db)},
        "artifacts": {},
    }
    artifact = _write_artifact(evidence_dir, f"rollback-readiness-{idempotency_key}.json", payload)
    payload["artifacts"]["evidence"] = str(artifact)
    return payload


def migrate_replica(
    *,
    source_db: str | Path,
    replica_db: str | Path,
    evidence_dir: str | Path,
    expected_commit: str,
    actual_commit: str | None = None,
    idempotency_key: str = "",
) -> dict[str, Any]:
    if not idempotency_key.strip():
        raise OperationError("idempotency_key is required")
    expected, actual = _commit_value(expected_commit, actual_commit)
    existing = _find_idempotent_artifact(evidence_dir, "migrate-replica", idempotency_key)
    request = {"idempotency_key": idempotency_key}
    if existing:
        return _check_replay(existing, expected, actual, request)
    replica = Path(replica_db).expanduser().resolve()
    if replica.exists():
        raise OperationError(f"replica destination already exists: {replica}")
    backup = production_operations.online_database_backup(source_db, replica)
    connection = sqlite3.connect(str(replica))
    try:
        executed = migrations.run_migrations(connection)
        connection.commit()
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    finally:
        connection.close()
    payload = {
        "schema": SCHEMA,
        "ok": True,
        "mode": "replica_migration",
        "command": "migrate-replica",
        "idempotency_key": idempotency_key,
        "expected_commit": expected,
        "actual_commit": actual,
        "migrations_executed": executed,
        "database_user_version": version,
        "backup": backup,
        "digests": {"replica": production_operations.database_fingerprint(replica)},
        "artifacts": {"replica": str(replica)},
    }
    artifact = _write_artifact(evidence_dir, f"migrate-replica-{idempotency_key}.json", payload)
    payload["artifacts"]["evidence"] = str(artifact)
    return payload


def _operation_report(command: str, db: str | Path, expected: str, actual: str) -> dict[str, Any]:
    if command == "preflight":
        return run_preflight(db, expected, actual)
    if command == "shadow-run":
        return run_shadow_run(db, expected, actual)
    if command == "compat-audit":
        report = run_preflight(db, expected, actual)
        report["command"] = "compat-audit"
        report["mode"] = "read_only_compat_audit"
        return report
    if command == "acceptance":
        preflight = run_preflight(db, expected, actual)
        shadow = run_shadow_run(db, expected, actual)
        return {
            "schema": SCHEMA,
            "ok": preflight["ok"] and shadow["ok"],
            "mode": "production_node_acceptance",
            "command": "acceptance",
            "checks": {"preflight_ok": preflight["ok"], "shadow_run_ok": shadow["ok"]},
            "counts": {**preflight["counts"], **shadow["counts"]},
            "digests": {"preflight": preflight["digests"], "shadow": shadow["digests"]},
            "artifacts": {},
            "expected_commit": expected,
            "actual_commit": actual,
        }
    raise OperationError(f"unsupported read-only command: {command}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(command_parser: argparse.ArgumentParser, *, required_evidence=False):
        command_parser.add_argument("--db", required=True)
        command_parser.add_argument("--expected-commit", required=True)
        command_parser.add_argument("--actual-commit")
        command_parser.add_argument("--evidence-dir", required=required_evidence)

    for command in ("preflight", "compat-audit", "shadow-run", "acceptance"):
        child = sub.add_parser(command)
        common(child)
        child.add_argument("--project-root", default=".")
    replica = sub.add_parser("migrate-replica")
    replica.add_argument("--source-db", required=True)
    replica.add_argument("--replica-db", required=True)
    replica.add_argument("--evidence-dir", required=True)
    replica.add_argument("--expected-commit", required=True)
    replica.add_argument("--actual-commit")
    replica.add_argument("--idempotency-key", required=True)

    flags = sub.add_parser("set-flags")
    flags.add_argument("--db", required=True)
    flags.add_argument("--env-file", required=True)
    flags.add_argument("--state", choices=tuple(_STATES), required=True)
    flags.add_argument("--evidence-dir", required=True)
    flags.add_argument("--expected-commit", required=True)
    flags.add_argument("--actual-commit")
    flags.add_argument("--idempotency-key", required=True)
    flags.add_argument("--rollback-evidence")

    readiness = sub.add_parser("rollback-readiness")
    readiness.add_argument("--db", required=True)
    readiness.add_argument("--evidence-dir", required=True)
    readiness.add_argument("--expected-commit", required=True)
    readiness.add_argument("--actual-commit")
    readiness.add_argument("--rollback-commit", required=True)
    readiness.add_argument("--idempotency-key", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command in {"preflight", "compat-audit", "shadow-run", "acceptance"}:
            actual = args.actual_commit or resolve_checkout_commit(args.project_root)
            expected, actual = _commit_value(args.expected_commit, actual)
            result = _operation_report(args.command, args.db, expected, actual)
        elif args.command == "set-flags":
            result = set_flags(
                db=args.db,
                env_file=args.env_file,
                state=args.state,
                evidence_dir=args.evidence_dir,
                expected_commit=args.expected_commit,
                actual_commit=args.actual_commit or resolve_checkout_commit("."),
                idempotency_key=args.idempotency_key,
                rollback_evidence=args.rollback_evidence,
            )
        elif args.command == "rollback-readiness":
            result = rollback_readiness(
                db=args.db,
                evidence_dir=args.evidence_dir,
                expected_commit=args.expected_commit,
                actual_commit=args.actual_commit or resolve_checkout_commit("."),
                rollback_commit=args.rollback_commit,
                idempotency_key=args.idempotency_key,
            )
        else:
            result = migrate_replica(
                source_db=args.source_db,
                replica_db=args.replica_db,
                evidence_dir=args.evidence_dir,
                expected_commit=args.expected_commit,
                actual_commit=args.actual_commit or resolve_checkout_commit("."),
                idempotency_key=args.idempotency_key,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))
        return 0 if result.get("ok", False) else 2
    except Exception as exc:
        print(json.dumps({"schema": SCHEMA, "ok": False, "command": args.command, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
