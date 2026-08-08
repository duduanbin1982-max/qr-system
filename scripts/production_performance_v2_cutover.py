#!/usr/bin/env python3
"""Enable production V2 performance queries with automatic environment rollback."""

import argparse
from datetime import datetime
import hashlib
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


EXPECTED_PAYROLL = {
    "payroll_batches": 4,
    "payroll_employee_lines": 119,
    "payroll_adjustments": 0,
    "payroll_detail_lines": 2975,
    "payroll_work_price_resolutions": 2638,
    "payroll_events": 4,
    "payroll_migration_manifests": 1,
}
QUERY_KEY = "PERFORMANCE_LEDGER_V2_QUERY_ENABLED"


def _parser():
    parser = argparse.ArgumentParser(description="Production performance V2 query cutover")
    parser.add_argument("--system-root", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--confirm-production-cutover", action="store_true")
    return parser


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rows(db, sql, params=()):
    return [dict(row) for row in db.execute(sql, params).fetchall()]


def _scalar(db, sql, params=()):
    return db.execute(sql, params).fetchone()[0]


def _open_ro(path):
    uri = "file:" + Path(path).resolve().as_posix() + "?mode=ro"
    db = sqlite3.connect(uri, uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=10000")
    db.execute("PRAGMA query_only=ON")
    db.execute("BEGIN")
    return db


def _checks(db):
    return {
        "user_version": int(_scalar(db, "PRAGMA user_version")),
        "integrity_check": _scalar(db, "PRAGMA integrity_check"),
        "foreign_key_violations": len(_rows(db, "PRAGMA foreign_key_check")),
        "query_only": int(_scalar(db, "PRAGMA query_only")),
    }


def _payroll(db):
    tables = (
        "payroll_batches",
        "payroll_employee_lines",
        "payroll_adjustments",
        "payroll_detail_lines",
        "payroll_work_price_resolutions",
        "payroll_events",
        "payroll_migration_manifests",
    )
    return {table: int(_scalar(db, "SELECT COUNT(*) FROM " + table)) for table in tables}


def _batch_state(db):
    return {
        "approved_v2": int(_scalar(db, "SELECT COUNT(*) FROM performance_batches WHERE version=2 AND status='approved'")),
        "superseded_legacy": int(_scalar(db, "SELECT COUNT(*) FROM performance_batches WHERE version=1 AND status='superseded'")),
        "reviews": int(_scalar(db, "SELECT COUNT(*) FROM performance_reviews_v2")),
        "rows": _rows(
            db,
            "SELECT id,production_month,version,status,row_version,supersedes_batch_id,"
            "superseded_by_batch_id,prepared_by,approved_by FROM performance_batches "
            "WHERE production_month BETWEEN '2026-06' AND '2026-07' "
            "ORDER BY production_month,version,id",
        ),
    }


def _flag_value(env_path):
    matches = []
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip() == QUERY_KEY:
            matches.append(value.strip().strip("\"'"))
    if len(matches) > 1:
        raise RuntimeError("生产 .env 中 V2 查询开关重复定义")
    raw = matches[0] if matches else ""
    return {"raw": raw or "false(default)", "enabled": raw.lower() in {"1", "true", "yes", "on"}}


def _atomic_set_flag(env_path, enabled):
    source = env_path.read_text(encoding="utf-8")
    lines = source.splitlines()
    output = []
    replaced = 0
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key == QUERY_KEY:
                output.append(f"{QUERY_KEY}={'true' if enabled else 'false'}")
                replaced += 1
                continue
        output.append(line)
    if replaced > 1:
        raise RuntimeError("生产 .env 中 V2 查询开关重复定义")
    if replaced == 0:
        if output and output[-1] != "":
            output.append("")
        output.append(f"{QUERY_KEY}={'true' if enabled else 'false'}")
    rendered = "\n".join(output) + "\n"
    stat = env_path.stat()
    descriptor, temporary = tempfile.mkstemp(prefix=".env.v2-cutover.", dir=str(env_path.parent))
    temp_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, stat.st_mode & 0o777)
        os.replace(temp_path, env_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _restore_env(env_backup, env_path):
    descriptor, temporary = tempfile.mkstemp(prefix=".env.v2-rollback.", dir=str(env_path.parent))
    temp_path = Path(temporary)
    try:
        with env_backup.open("rb") as source, os.fdopen(descriptor, "wb") as target:
            shutil.copyfileobj(source, target)
            target.flush()
            os.fsync(target.fileno())
        os.chmod(temp_path, env_backup.stat().st_mode & 0o777)
        os.replace(temp_path, env_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _database_backup(source_path, target_path):
    source = _open_ro(source_path)
    target = sqlite3.connect(str(target_path))
    try:
        source.backup(target)
        target.commit()
    finally:
        target.close()
        source.close()


def _restart_service():
    subprocess.run(["systemctl", "--user", "restart", "qr-system"], check=True)


def _service_active():
    result = subprocess.run(
        ["systemctl", "--user", "is-active", "qr-system"],
        text=True,
        capture_output=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "active"


def _health():
    context = ssl._create_unverified_context()
    with urllib.request.urlopen(
        "https://127.0.0.1:3000/api/health", context=context, timeout=5
    ) as response:
        return json.loads(response.read().decode("utf-8"))


def _wait_for_health(expected_commit, timeout_seconds=45):
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        try:
            if _service_active():
                health = _health()
                if (
                    health.get("status") == "ok"
                    and health.get("db") == "connected"
                    and health.get("commit") == expected_commit
                ):
                    return health
                last_error = "健康响应内容不符合预期"
            else:
                last_error = "用户级服务尚未 active"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(1)
    raise RuntimeError("生产服务启动健康检查超时: " + last_error)


def _gunicorn_environment(root):
    output = subprocess.check_output(
        ["pgrep", "-o", "-f", "gunicorn -c gunicorn.conf.py server:app"],
        text=True,
    ).strip()
    pid = int(output)
    cwd = Path(f"/proc/{pid}/cwd").resolve()
    if cwd != root:
        raise RuntimeError(f"Gunicorn 主进程工作目录不正确: {cwd}")
    values = {}
    for item in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0"):
        if b"=" not in item:
            continue
        key, value = item.split(b"=", 1)
        if key.decode("utf-8", errors="ignore") == QUERY_KEY:
            values[QUERY_KEY] = value.decode("utf-8", errors="replace")
    return {"pid": pid, "cwd": str(cwd), "query_flag": values.get(QUERY_KEY, "")}


def _actor(
    db,
    username,
    access_repository,
    collect_permissions,
    *,
    allowed_roles=("worker",),
):
    row = db.execute("SELECT id,username,name,status,role FROM users WHERE username=?", (username,)).fetchone()
    if not row:
        raise RuntimeError(f"验收账号不存在: {username}")
    actor = dict(row)
    if actor["status"] != "active" or actor["role"] not in allowed_roles:
        raise RuntimeError(f"验收账号状态或基础角色错误: {username}")
    actor["_permissions"] = collect_permissions(
        access_repository.get_permission_rows(actor["id"], db=db),
        user_id=actor["id"],
    )
    return actor


def _query_acceptance(db, root):
    os.environ[QUERY_KEY] = "true"
    os.environ.setdefault("SECRET_KEY", "offline-production-v2-cutover-verification")
    sys.path.insert(0, str(root))
    from flask import Flask
    from modules.access_policy import collect_permission_codes
    from modules.repositories.access_policy_repository import AccessPolicyRepository
    from modules.services.performance_service import PerformanceService

    reviewer = _actor(db, "1000_perf", AccessPolicyRepository, collect_permission_codes)
    legacy_admin = _actor(
        db,
        "1000",
        AccessPolicyRepository,
        collect_permission_codes,
        allowed_roles=("admin",),
    )
    if "*" not in legacy_admin["_permissions"] and "performance:view_all" not in legacy_admin["_permissions"]:
        raise RuntimeError("Legacy 回退验收账号缺少全局查询权限")
    scopes = [
        int(row["department_id"])
        for row in db.execute(
            "SELECT department_id FROM performance_department_scopes "
            "WHERE user_id=? ORDER BY department_id",
            (reviewer["id"],),
        ).fetchall()
    ]
    machine_id = int(_scalar(db, "SELECT id FROM departments WHERE name='机加工班组' AND status='active'"))
    expected_scopes = list(range(1, 9)) + [machine_id]
    if scopes != expected_scopes:
        raise RuntimeError(f"复核账号 9 部门范围不正确: {scopes}")

    app = Flask("performance-v2-cutover-verification")
    v2_results = []
    legacy_results = []
    with app.app_context():
        app.config[QUERY_KEY] = True
        for month, batch_id, count in (("2026-06", 3, 27), ("2026-07", 4, 37)):
            result = PerformanceService.list_scores(
                month, page=1, per_page=200, actor=reviewer, db=db
            )
            if (
                result["result_source"] != "ledger_v2"
                or int(result["batch_id"]) != batch_id
                or result["batch_status"] != "approved"
                or int(result["total"]) != count
            ):
                raise RuntimeError(f"{month} V2 正式查询结果不正确")
            departments = sorted(
                {
                    int(item["department_id"])
                    for item in result["items"]
                    if item.get("department_id") is not None
                }
            )
            if not set(departments).issubset(scopes):
                raise RuntimeError(f"{month} V2 查询包含范围外部门")
            v2_results.append(
                {
                    "production_month": month,
                    "batch_id": result["batch_id"],
                    "version": result["version"],
                    "status": result["batch_status"],
                    "result_source": result["result_source"],
                    "score_count": result["total"],
                    "visible_department_ids": departments,
                }
            )

        app.config[QUERY_KEY] = False
        for month, batch_id, count in (("2026-06", 1, 27), ("2026-07", 2, 37)):
            result = PerformanceService.list_scores(
                month, page=1, per_page=200, actor=legacy_admin, db=db
            )
            if (
                result["result_source"] != "legacy_v1"
                or int(result["batch_id"]) != batch_id
                or result["batch_status"] != "superseded"
                or int(result["total"]) != count
            ):
                raise RuntimeError(f"{month} Legacy 回退结果不正确")
            legacy_results.append(
                {
                    "production_month": month,
                    "batch_id": result["batch_id"],
                    "version": result["version"],
                    "status": result["batch_status"],
                    "result_source": result["result_source"],
                    "score_count": result["total"],
                }
            )

        app.config[QUERY_KEY] = True
        try:
            PerformanceService.list_scores(
                "2026-07",
                department_id=9,
                page=1,
                per_page=200,
                actor=reviewer,
                db=db,
            )
        except PermissionError:
            outside_scope_denied = True
        else:
            raise RuntimeError("复核账号意外通过范围外部门 ID 9 查询")
    return {
        "reviewer": {
            "id": reviewer["id"],
            "username": reviewer["username"],
            "name": reviewer["name"],
            "permissions": reviewer["_permissions"],
            "department_scope_ids": scopes,
        },
        "legacy_fallback_actor": {
            "id": legacy_admin["id"],
            "username": legacy_admin["username"],
            "name": legacy_admin["name"],
            "permissions": legacy_admin["_permissions"],
        },
        "v2_results": v2_results,
        "legacy_fallback_results": legacy_results,
        "outside_department_id": 9,
        "outside_scope_denied": outside_scope_denied,
    }


def run(args):
    if not args.confirm_production_cutover:
        raise RuntimeError("必须提供 --confirm-production-cutover")
    root = Path(args.system_root).resolve()
    db_path = Path(args.db).resolve()
    env_path = root / ".env"
    out_base = Path(args.output_dir).resolve()
    if not root.is_dir() or not db_path.is_file() or not env_path.is_file():
        raise RuntimeError("生产目录、数据库或 .env 不存在")
    before_flag = _flag_value(env_path)
    if before_flag["enabled"]:
        raise RuntimeError("生产 V2 查询开关已开启，停止重复切换")

    started_at = datetime.now().astimezone()
    stamp = started_at.strftime("%Y%m%d-%H%M%S")
    run_dir = out_base / stamp
    run_dir.mkdir(parents=True, exist_ok=False)
    os.chmod(run_dir, 0o700)
    env_backup = run_dir / f"production-env-pre-v2-cutover-{stamp}.backup"
    db_backup = run_dir / f"production-pre-v2-cutover-{stamp}.db"
    evidence_path = run_dir / f"performance-v2-cutover-evidence-{stamp}.json"
    failure_path = run_dir / f"performance-v2-cutover-failure-{stamp}.json"

    before_db = _open_ro(db_path)
    try:
        before_checks = _checks(before_db)
        before_payroll = _payroll(before_db)
        before_batches = _batch_state(before_db)
        if before_checks != {"user_version": 57, "integrity_check": "ok", "foreign_key_violations": 0, "query_only": 1}:
            raise RuntimeError(f"切换前数据库门禁失败: {before_checks}")
        if before_payroll != EXPECTED_PAYROLL:
            raise RuntimeError("切换前工资台账指纹不一致")
        if before_batches["approved_v2"] != 2 or before_batches["superseded_legacy"] != 2 or before_batches["reviews"] != 64:
            raise RuntimeError(f"切换前绩效版本门禁失败: {before_batches}")
        _database_backup(db_path, db_backup)
    finally:
        before_db.close()

    backup_db = _open_ro(db_backup)
    try:
        backup_checks = _checks(backup_db)
        backup_payroll = _payroll(backup_db)
        backup_batches = _batch_state(backup_db)
    finally:
        backup_db.close()
    if backup_checks != {"user_version": 57, "integrity_check": "ok", "foreign_key_violations": 0, "query_only": 1}:
        raise RuntimeError(f"切换前数据库备份验证失败: {backup_checks}")
    if backup_payroll != before_payroll or backup_batches != before_batches:
        raise RuntimeError("切换前数据库备份指纹不一致")

    shutil.copy2(env_path, env_backup)
    os.chmod(env_backup, 0o600)
    env_changed = False
    expected_commit = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    try:
        _atomic_set_flag(env_path, True)
        env_changed = True
        after_file_flag = _flag_value(env_path)
        if not after_file_flag["enabled"]:
            raise RuntimeError("生产 .env 的 V2 查询开关未成功写入")
        _restart_service()
        health = _wait_for_health(expected_commit)
        process = _gunicorn_environment(root)
        if process["query_flag"].strip().lower() not in {"1", "true", "yes", "on"}:
            raise RuntimeError("Gunicorn 主进程未加载 V2 查询开关")

        after_db = _open_ro(db_path)
        try:
            acceptance = _query_acceptance(after_db, root)
            after_checks = _checks(after_db)
            after_payroll = _payroll(after_db)
            after_batches = _batch_state(after_db)
        finally:
            after_db.close()
        if after_checks != before_checks or after_payroll != before_payroll or after_batches != before_batches:
            raise RuntimeError("查询切换不应修改数据库、工资或绩效版本指纹")
    except Exception as exc:
        rollback = {"attempted": env_changed, "succeeded": False, "error": ""}
        if env_changed:
            try:
                _restore_env(env_backup, env_path)
                _restart_service()
                rollback_health = _wait_for_health(expected_commit)
                rollback["succeeded"] = True
                rollback["health"] = rollback_health
                rollback["flag"] = _flag_value(env_path)
            except Exception as rollback_exc:
                rollback["error"] = str(rollback_exc)
        failure = {
            "status": "failed",
            "error": str(exc),
            "executed_at": started_at.isoformat(),
            "rollback": rollback,
            "env_backup": str(env_backup),
            "database_backup": str(db_backup),
        }
        failure_path.write_text(json.dumps(failure, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise RuntimeError(str(exc) + "; rollback=" + json.dumps(rollback, ensure_ascii=False)) from exc

    evidence = {
        "status": "passed",
        "mode": "production_performance_v2_query_cutover",
        "executed_at": started_at.isoformat(),
        "hostname": socket.gethostname(),
        "system_root": str(root),
        "database": str(db_path),
        "deployed_commit": expected_commit,
        "query_flag_before": before_flag,
        "query_flag_after_file": after_file_flag,
        "gunicorn_process": process,
        "service_health": health,
        "database_checks_before": before_checks,
        "database_checks_after": after_checks,
        "payroll_before": before_payroll,
        "payroll_after": after_payroll,
        "batch_state_before": before_batches,
        "batch_state_after": after_batches,
        "acceptance": acceptance,
        "backups": {
            "environment": {
                "path": str(env_backup),
                "bytes": env_backup.stat().st_size,
                "sha256": _sha256(env_backup),
                "mode": oct(env_backup.stat().st_mode & 0o777),
            },
            "database": {
                "path": str(db_backup),
                "bytes": db_backup.stat().st_size,
                "sha256": _sha256(db_backup),
                "checks": backup_checks,
            },
        },
        "rollback_required": False,
    }
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "passed",
        "run_directory": str(run_dir),
        "query_flag": after_file_flag,
        "gunicorn_process": process,
        "service_health": health,
        "acceptance": acceptance,
        "backups": evidence["backups"],
        "evidence": {"path": str(evidence_path), "sha256": _sha256(evidence_path)},
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
