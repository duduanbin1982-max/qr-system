#!/usr/bin/env python3
"""Read-only post-cutover acceptance checks for process V2."""

import argparse
import json
from pathlib import Path
import ssl
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.process_v2_operations import (  # noqa: E402
    database_checks,
    evaluate_post_cutover,
    file_sha256,
    missing_version_bindings,
    read_process_flags,
)


def _parser():
    parser = argparse.ArgumentParser(
        description="Post-cutover health, permission, Legacy and V2 process smoke checks"
    )
    parser.add_argument("--system-root", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--base-url", default="https://127.0.0.1:3000")
    parser.add_argument("--auth-token", required=True, help="Short-lived admin acceptance token")
    return parser


def _request(base_url, path, token="", method="GET", payload=None):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=data,
        headers=headers,
        method=method,
    )
    context = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(request, context=context, timeout=10) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            payload = {"body": body[:500]}
        return exc.code, payload


def _historical_snapshot_status(db):
    from modules.migration_process_versioning import PROCESS_FACT_BINDINGS

    checks = (
        ("order_processes", "process_id", "process_version_id", "process_name_snapshot"),
        ("work_records", "process_id", "process_version_id", "process_name_snapshot"),
    )
    missing = 0
    for table, root, version, snapshot in checks:
        columns = {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}
        if not {root, version, snapshot} <= columns:
            return "failed"
        missing += db.execute(
            f'SELECT COUNT(*) FROM "{table}" WHERE "{root}" IS NOT NULL '
            f'AND ("{version}" IS NULL OR TRIM(COALESCE("{snapshot}",\'\'))=\'\')'
        ).fetchone()[0]
    for spec in PROCESS_FACT_BINDINGS:
        table = spec["table"]
        columns = {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}
        for role in spec["roles"]:
            required = {
                role + "_id",
                role + "_version_id",
                role + "_code_snapshot",
                role + "_name_snapshot",
            }
            if not required <= columns:
                return "failed"
            missing += db.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE "{role}_id" IS NOT NULL '
                f'AND ("{role}_version_id" IS NULL '
                f'OR TRIM(COALESCE("{role}_code_snapshot",\'\'))=\'\' '
                f'OR TRIM(COALESCE("{role}_name_snapshot",\'\'))=\'\')'
            ).fetchone()[0]
        if {"route_id", "route_version_id", "route_name_snapshot"} <= columns:
            missing += db.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE route_id IS NOT NULL '
                "AND (route_version_id IS NULL "
                "OR TRIM(COALESCE(route_name_snapshot,''))='')"
            ).fetchone()[0]
    return "passed" if missing == 0 else "failed"


def run(args):
    root = Path(args.system_root).resolve()
    db_path = Path(args.db).resolve()
    uri = "file:" + db_path.as_posix() + "?mode=ro"
    db = sqlite3.connect(uri, uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    try:
        checks = database_checks(db)
        missing = missing_version_bindings(db)
        process_id_row = db.execute("SELECT MIN(id) FROM processes").fetchone()
        process_id = process_id_row[0] if process_id_row else None
        snapshot_status = _historical_snapshot_status(db)
    finally:
        db.close()
    if process_id is None:
        raise RuntimeError("no process exists for the V2 query acceptance check")

    health_status, health = _request(args.base_url, "/api/health")
    expected_commit = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    if health.get("commit") != expected_commit:
        health = {**health, "status": "failed", "expected_commit": expected_commit}
    auth_status, auth = _request(args.base_url, "/api/auth/info", args.auth_token)
    legacy_get, _ = _request(args.base_url, "/api/processes?limit=1", args.auth_token)
    legacy_write, _ = _request(
        args.base_url,
        "/api/processes",
        args.auth_token,
        method="POST",
        payload={},
    )
    v2_query, _ = _request(
        args.base_url, f"/api/processes/{process_id}/versions", args.auth_token
    )
    permissions = auth.get("user", auth).get("permissions", []) if auth_status == 200 else []
    permission_ok = auth_status == 200 and (
        "*" in permissions
        or all(
            permission in permissions
            for permission in ("process_versions:view", "route_versions:view")
        )
    )
    api_results = {
        "permissions": "passed" if permission_ok else "failed",
        "legacy_get": legacy_get,
        "legacy_write": legacy_write,
        "v2_query": v2_query,
        "historical_snapshot": snapshot_status,
    }
    if health_status != 200:
        health = {**health, "status": "failed"}
    report = evaluate_post_cutover(
        database=checks,
        flags=read_process_flags(root / ".env"),
        health=health,
        api_results=api_results,
        missing_bindings=missing,
    )
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    evidence = output / "process-v2-post-cutover-smoke.json"
    evidence.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if report["status"] != "passed":
        raise RuntimeError("post-cutover smoke failed; evidence=" + str(evidence))
    return {
        "status": "passed",
        "evidence": {"path": str(evidence), "sha256": file_sha256(evidence)},
        "health": health,
        "api_results": api_results,
        "missing_bindings": missing,
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
