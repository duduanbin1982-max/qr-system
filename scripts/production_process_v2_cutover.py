#!/usr/bin/env python3
"""Apply one authorized process V2 migration or feature-flag cutover stage."""

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.process_v2_operations import (  # noqa: E402
    PROCESS_FLAG_STAGES,
    advance_cutover_stage,
    database_checks,
    database_sha256,
    file_sha256,
    migrate_database,
    online_backup,
    payload_sha256,
    read_process_flags,
    validate_cutover_authorization,
)


STAGES = ("migrate",) + tuple(stage for stage, _ in PROCESS_FLAG_STAGES)


def _parser():
    parser = argparse.ArgumentParser(
        description="Authorized process V2 migration and ordered feature-flag cutover"
    )
    parser.add_argument("--system-root", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--stage", required=True, choices=STAGES)
    parser.add_argument("--preflight-evidence", required=True)
    parser.add_argument("--preflight-sha256", required=True)
    parser.add_argument("--target-commit", required=True)
    parser.add_argument("--database-sha256", required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--service", default="qr-system")
    parser.add_argument("--health-url", default="https://127.0.0.1:3000/api/health")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-production-cutover", action="store_true")
    return parser


def _load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _git_commit(root):
    return subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()


def _read_database_checks(path):
    uri = "file:" + Path(path).resolve().as_posix() + "?mode=ro"
    db = sqlite3.connect(uri, uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA query_only=ON")
    try:
        return database_checks(db)
    finally:
        db.close()


def _service_active(service):
    result = subprocess.run(
        ["systemctl", "--user", "is-active", service],
        text=True,
        capture_output=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "active"


def _restart_service(service):
    subprocess.run(["systemctl", "--user", "restart", service], check=True)


def _health(url):
    context = ssl._create_unverified_context()
    with urllib.request.urlopen(url, context=context, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _wait_for_health(url, expected_commit, timeout_seconds=45):
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        try:
            health = _health(url)
            if (
                health.get("status") == "ok"
                and health.get("db") == "connected"
                and health.get("commit") == expected_commit
            ):
                return health
            last_error = "health response does not match status/db/commit gate"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(1)
    raise RuntimeError("service health timeout: " + last_error)


def _atomic_restore(source, destination):
    destination = Path(destination)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".process-v2-rollback.", dir=str(destination.parent)
    )
    temporary_path = Path(temporary)
    try:
        with Path(source).open("rb") as source_handle, os.fdopen(descriptor, "wb") as target:
            shutil.copyfileobj(source_handle, target)
            target.flush()
            os.fsync(target.fileno())
        os.chmod(temporary_path, Path(source).stat().st_mode & 0o777)
        os.replace(temporary_path, destination)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _evidence_path(output, idempotency_key):
    suffix = payload_sha256({"idempotency_key": idempotency_key})[:20]
    return output / f"process-v2-cutover-{suffix}.json"


def _idempotent_replay(path, args, actual_commit, actual_database_sha256):
    if not path.is_file():
        return None
    evidence = _load_json(path)
    if evidence.get("status") != "passed":
        raise RuntimeError("idempotency evidence exists without passed status")
    expected = {
        "stage": args.stage,
        "target_commit": args.target_commit,
        "operator": args.operator,
        "idempotency_key": args.idempotency_key,
    }
    actual = {key: evidence.get(key) for key in expected}
    if actual != expected:
        raise RuntimeError("idempotency key was already used for another cutover command")
    if actual_commit != args.target_commit:
        raise RuntimeError("deployed commit changed since the recorded cutover")
    authorized_database = evidence.get("authorization", {}).get("database_sha256", "")
    if authorized_database != args.database_sha256.lower():
        raise RuntimeError("idempotent replay database authorization does not match")
    recorded_preflight = evidence.get("preflight", {}).get("file_sha256", "")
    if recorded_preflight != args.preflight_sha256.lower():
        raise RuntimeError("idempotent replay preflight evidence does not match")
    recorded_after = evidence.get("database_after", {}).get("sha256", "")
    if recorded_after and actual_database_sha256 != recorded_after:
        raise RuntimeError("database changed since the recorded cutover")
    return {
        "status": "passed",
        "idempotent_replay": True,
        "stage": args.stage,
        "evidence": {"path": str(path), "sha256": file_sha256(path)},
    }


def _validate_preflight(path, expected_sha256):
    evidence = Path(path).resolve()
    if not evidence.is_file():
        raise RuntimeError("preflight evidence does not exist")
    actual_sha256 = file_sha256(evidence)
    if actual_sha256.lower() != expected_sha256.lower():
        raise RuntimeError("preflight evidence SHA-256 does not match")
    report = _load_json(evidence)
    if report.get("status") != "passed" or not report.get("summary_sha256"):
        raise RuntimeError("preflight evidence is not a passed full report")
    return report, actual_sha256


def run(args):
    root = Path(args.system_root).resolve()
    db_path = Path(args.db).resolve()
    env_path = root / ".env"
    output = Path(args.output_dir).resolve()
    if not root.is_dir() or not db_path.is_file() or not env_path.is_file():
        raise RuntimeError("system root, database or .env does not exist")
    output.mkdir(parents=True, exist_ok=True)

    preflight, preflight_file_sha256 = _validate_preflight(
        args.preflight_evidence, args.preflight_sha256
    )
    actual_commit = _git_commit(root)
    actual_database_sha256 = database_sha256(db_path)
    evidence_path = _evidence_path(output, args.idempotency_key)
    replay = _idempotent_replay(
        evidence_path, args, actual_commit, actual_database_sha256
    )
    if replay:
        return replay
    authorization = validate_cutover_authorization(
        expected_commit=args.target_commit,
        actual_commit=actual_commit,
        expected_database_sha256=args.database_sha256,
        actual_database_sha256=actual_database_sha256,
        operator=args.operator,
        idempotency_key=args.idempotency_key,
    )
    before_checks = _read_database_checks(db_path)
    flags_before = read_process_flags(env_path)
    if args.stage == "migrate" and any(flags_before.values()):
        raise RuntimeError("migration stage requires all process versioning flags to be disabled")
    if args.stage != "migrate" and before_checks["user_version"] < 63:
        raise RuntimeError("feature flags require database migration v063 or later")

    if not args.apply:
        stage_plan = (
            {"stage": "migrate", "changed": False, "dry_run": True}
            if args.stage == "migrate"
            else advance_cutover_stage(env_path, args.stage, apply=False)
        )
        return {
            "status": "dry_run",
            "authorization": authorization,
            "stage_plan": stage_plan,
            "database": before_checks,
            "flags": flags_before,
            "preflight_summary_sha256": preflight["summary_sha256"],
        }
    if not args.confirm_production_cutover:
        raise RuntimeError("--apply requires --confirm-production-cutover")

    started_at = datetime.now().astimezone()
    backup = None
    env_backup = None
    health = None
    stage_result = None
    try:
        if args.stage == "migrate":
            if _service_active(args.service):
                raise RuntimeError("migration requires the production service to be stopped")
            backup = output / (
                "process-v2-pre-migration-" + payload_sha256(args.idempotency_key)[:12] + ".db"
            )
            online_backup(db_path, backup)
            backup_checks = _read_database_checks(backup)
            if (
                backup_checks["integrity_check"] != "ok"
                or backup_checks["foreign_key_violations"]
            ):
                raise RuntimeError("pre-migration backup verification failed")
            stage_result = migrate_database(
                db_path,
                expected_preflight_sha256=preflight["summary_sha256"],
            )
        else:
            env_backup = output / (
                "process-v2-env-before-"
                + args.stage
                + "-"
                + payload_sha256(args.idempotency_key)[:12]
                + ".backup"
            )
            if env_backup.exists():
                raise RuntimeError("environment backup destination already exists")
            shutil.copy2(env_path, env_backup)
            os.chmod(env_backup, 0o600)
            stage_result = advance_cutover_stage(env_path, args.stage, apply=True)
            _restart_service(args.service)
            health = _wait_for_health(args.health_url, actual_commit)
            if database_sha256(db_path) != actual_database_sha256:
                raise RuntimeError("feature-flag cutover unexpectedly changed the database")
    except Exception as exc:
        rollback = {
            "environment": {"attempted": False, "succeeded": False, "error": ""},
            "database": {"attempted": False, "succeeded": False, "error": ""},
        }
        if env_backup and env_backup.is_file():
            rollback["environment"]["attempted"] = True
            try:
                _atomic_restore(env_backup, env_path)
                _restart_service(args.service)
                _wait_for_health(args.health_url, actual_commit)
                rollback["environment"]["succeeded"] = True
            except Exception as rollback_exc:
                rollback["environment"]["error"] = str(rollback_exc)
        if backup and backup.is_file():
            rollback["database"]["attempted"] = True
            try:
                if _service_active(args.service):
                    raise RuntimeError("service became active during database rollback")
                _atomic_restore(backup, db_path)
                restored_checks = _read_database_checks(db_path)
                if (
                    restored_checks["integrity_check"] != "ok"
                    or restored_checks["foreign_key_violations"]
                ):
                    raise RuntimeError(
                        "restored database failed integrity or foreign-key checks"
                    )
                rollback["database"]["succeeded"] = True
                rollback["database"]["checks"] = restored_checks
                rollback["database"]["sha256"] = database_sha256(db_path)
            except Exception as rollback_exc:
                rollback["database"]["error"] = str(rollback_exc)
        failure = {
            "status": "failed",
            "stage": args.stage,
            "error": str(exc),
            "operator": args.operator,
            "idempotency_key": args.idempotency_key,
            "rollback": rollback,
        }
        failure_path = evidence_path.with_name(evidence_path.stem + "-failed.json")
        failure_path.write_text(
            json.dumps(failure, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        raise RuntimeError(str(exc) + "; failure_evidence=" + str(failure_path)) from exc

    after_checks = _read_database_checks(db_path)
    database_after_sha256 = database_sha256(db_path)
    evidence = {
        "status": "passed",
        "mode": "production_process_v2_cutover",
        "stage": args.stage,
        "executed_at": started_at.isoformat(),
        "hostname": socket.gethostname(),
        "target_commit": args.target_commit,
        "operator": args.operator,
        "idempotency_key": args.idempotency_key,
        "authorization": authorization,
        "preflight": {
            "path": str(Path(args.preflight_evidence).resolve()),
            "file_sha256": preflight_file_sha256,
            "summary_sha256": preflight["summary_sha256"],
        },
        "database_before": {**before_checks, "sha256": actual_database_sha256},
        "database_after": {**after_checks, "sha256": database_after_sha256},
        "flags_before": flags_before,
        "flags_after": read_process_flags(env_path),
        "stage_result": stage_result,
        "service_health": health,
        "backup": (
            {"path": str(backup), "sha256": file_sha256(backup)} if backup else None
        ),
        "environment_backup": (
            {"path": str(env_backup), "sha256": file_sha256(env_backup)}
            if env_backup
            else None
        ),
    }
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "status": "passed",
        "idempotent_replay": False,
        "stage": args.stage,
        "database": evidence["database_after"],
        "flags": evidence["flags_after"],
        "service_health": health,
        "evidence": {"path": str(evidence_path), "sha256": file_sha256(evidence_path)},
    }


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        result = run(args)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
