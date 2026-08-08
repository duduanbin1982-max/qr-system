#!/usr/bin/env python3
"""Generate production V2 performance preflight and difference evidence read-only."""

import argparse
from collections import Counter
import csv
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys


EXPECTED_COUNTS = {
    "overwritten_score_count": 64,
    "missing_position_count": 30,
    "cross_month_work_count": 5,
    "cross_month_quality_count": 11,
}
EXPECTED_PAYROLL = {
    "payroll_batches": 4,
    "payroll_employee_lines": 119,
    "payroll_adjustments": 0,
    "payroll_detail_lines": 2975,
    "payroll_work_price_resolutions": 2638,
    "payroll_events": 4,
    "payroll_migration_manifests": 1,
}
EXPECTED_ACCOUNTS = {
    "1000_perf": {
        "name": "杜斌",
        "role_code": "performance_reviewer_v57",
        "permissions": {
            "page:performance",
            "performance:view_department",
            "performance:review_department",
        },
    },
    "1004_plan": {
        "name": "Dooley",
        "role_code": "performance_plan_manager_v57",
        "permissions": {
            "page:performance",
            "performance:view_department",
            "performance:plan_manage",
        },
    },
    "1005_reassess": {
        "name": "王晓璐",
        "role_code": "performance_reassessor_v57",
        "permissions": {
            "page:performance",
            "performance:view_department",
            "performance:plan_reassess",
        },
    },
}
DIFFERENCE_COMPONENTS = {
    "prior_revisions_unavailable",
    "missing_position_snapshot",
    "production_month_boundary",
    "quality_source_confirmation_required",
    "missing_position_target",
    "explicit_source_relation",
}


def _parser():
    parser = argparse.ArgumentParser(
        description="Read-only production V2 historical performance preflight"
    )
    parser.add_argument("--system-root", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--from-month", default="2026-06")
    parser.add_argument("--to-month", default="2026-07")
    parser.add_argument("--confirm-production-preflight", action="store_true")
    return parser


def _canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


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


def _open_read_only(db_path):
    uri = "file:" + Path(db_path).resolve().as_posix() + "?mode=ro"
    db = sqlite3.connect(uri, uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=10000")
    db.execute("PRAGMA query_only=ON")
    if int(_scalar(db, "PRAGMA query_only")) != 1:
        db.close()
        raise RuntimeError("SQLite query_only 未生效")
    db.execute("BEGIN")
    return db


def _table_digest(db, table, order_by="id"):
    rows = _rows(db, f"SELECT * FROM {table} ORDER BY {order_by}")
    return {"count": len(rows), "sha256": _digest(rows)}


def _batch_fingerprint(db):
    return {
        "legacy_batches": int(
            _scalar(db, "SELECT COUNT(*) FROM performance_batches WHERE version=1")
        ),
        "v2_batches": int(
            _scalar(db, "SELECT COUNT(*) FROM performance_batches WHERE version>=2")
        ),
        "legacy_scores": int(
            _scalar(
                db,
                "SELECT COUNT(*) FROM performance_score_revisions score "
                "JOIN performance_batches batch ON batch.id=score.batch_id "
                "WHERE batch.version=1",
            )
        ),
    }


def _authorization_fingerprint(db):
    machine = db.execute(
        "SELECT id,name,status FROM departments WHERE name='机加工班组'"
    ).fetchone()
    if not machine or machine["status"] != "active":
        raise RuntimeError("机加工班组不存在或未启用")
    expected_scope_ids = list(range(1, 9)) + [int(machine["id"])]
    result = {}
    for username, expected in EXPECTED_ACCOUNTS.items():
        user = db.execute(
            "SELECT id,username,name,role,employee_no,status,password_version "
            "FROM users WHERE username=?",
            (username,),
        ).fetchone()
        if not user:
            raise RuntimeError(f"专用账号不存在: {username}")
        user = dict(user)
        roles = _rows(
            db,
            "SELECT role.id,role.code,role.name,role.permissions,role.status "
            "FROM user_roles relation JOIN roles role ON role.id=relation.role_id "
            "WHERE relation.user_id=? ORDER BY role.id",
            (user["id"],),
        )
        scopes = _rows(
            db,
            "SELECT scope.department_id,department.name AS department_name "
            "FROM performance_department_scopes scope "
            "JOIN departments department ON department.id=scope.department_id "
            "WHERE scope.user_id=? ORDER BY scope.department_id",
            (user["id"],),
        )
        if user["name"] != expected["name"]:
            raise RuntimeError(f"专用账号姓名不一致: {username}")
        if user["role"] != "worker" or user["status"] != "active":
            raise RuntimeError(f"专用账号基础角色或状态不正确: {username}")
        if len(roles) != 1 or roles[0]["code"] != expected["role_code"]:
            raise RuntimeError(f"专用账号绩效角色不正确: {username}")
        if roles[0]["status"] != "active":
            raise RuntimeError(f"专用账号绩效角色未启用: {username}")
        try:
            permissions = set(json.loads(roles[0]["permissions"] or "[]"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"专用账号权限 JSON 无效: {username}") from exc
        if permissions != expected["permissions"]:
            raise RuntimeError(f"专用账号最小权限不一致: {username}")
        if any(code == "*" or code.endswith(":*") for code in permissions):
            raise RuntimeError(f"专用账号包含通配权限: {username}")
        scope_ids = [int(row["department_id"]) for row in scopes]
        if scope_ids != expected_scope_ids:
            raise RuntimeError(f"专用账号部门范围不一致: {username}")
        result[username] = {
            "user": user,
            "role": roles[0],
            "permissions": sorted(permissions),
            "scopes": scopes,
        }
    return {
        "machine_department": dict(machine),
        "expected_scope_ids": expected_scope_ids,
        "accounts": result,
        "sha256": _digest(result),
    }


def _fingerprint(db, payroll_fingerprint):
    assignment_rows = _rows(
        db,
        "SELECT * FROM performance_assignment_history "
        "WHERE created_by=10304 AND source_type IN "
        "('manual_history_confirmation','legacy_score_snapshot') ORDER BY id",
    )
    department_revisions = _rows(
        db,
        "SELECT * FROM performance_assignment_department_revisions "
        "WHERE status='approved' AND source_key LIKE "
        "'performance-v57:department-supplement:%' ORDER BY id",
    )
    protected_tables = {
        table: _table_digest(db, table)
        for table in (
            "performance_batches",
            "performance_score_revisions",
            "performance_rule_versions",
            "performance_position_target_versions",
            "performance_assignment_history",
            "performance_assignment_department_revisions",
            "performance_migration_manifests",
            "performance_source_facts",
        )
    }
    payroll = payroll_fingerprint(db)
    return {
        "database": {
            "user_version": int(_scalar(db, "PRAGMA user_version")),
            "integrity_check": _scalar(db, "PRAGMA integrity_check"),
            "foreign_key_violations": len(_rows(db, "PRAGMA foreign_key_check")),
            "query_only": int(_scalar(db, "PRAGMA query_only")),
        },
        "batches": _batch_fingerprint(db),
        "payroll": payroll,
        "confirmed_assignment_rows": {
            "count": len(assignment_rows),
            "sha256": _digest(assignment_rows),
        },
        "approved_department_revisions": {
            "count": len(department_revisions),
            "sha256": _digest(department_revisions),
        },
        "authorization": _authorization_fingerprint(db),
        "protected_tables": protected_tables,
    }


def _validate_fingerprint(fingerprint):
    database = fingerprint["database"]
    if database != {
        "user_version": 57,
        "integrity_check": "ok",
        "foreign_key_violations": 0,
        "query_only": 1,
    }:
        raise RuntimeError(f"生产 V57 数据库门禁失败: {database}")
    if fingerprint["batches"] != {
        "legacy_batches": 2,
        "v2_batches": 0,
        "legacy_scores": 64,
    }:
        raise RuntimeError(f"绩效批次基线不一致: {fingerprint['batches']}")
    if fingerprint["payroll"] != EXPECTED_PAYROLL:
        raise RuntimeError(f"工资台账指纹不一致: {fingerprint['payroll']}")
    if fingerprint["confirmed_assignment_rows"]["count"] != 37:
        raise RuntimeError("已确认历史任职记录不是 37 条")
    if fingerprint["approved_department_revisions"]["count"] != 37:
        raise RuntimeError("已批准部门补充修订不是 37 条")


def _validate_plan(plan, migration_service):
    migration_service.validate_counts(plan, EXPECTED_COUNTS)
    totals = plan.get("totals") or {}
    if int(totals.get("quality_ambiguity_count") or 0) != 0:
        raise RuntimeError("历史质量来源仍有歧义")
    if int(totals.get("missing_target_count") or 0) != 0:
        raise RuntimeError("历史岗位仍缺少已批准目标")
    if len(plan.get("months") or []) != 2:
        raise RuntimeError("预检月份数量不是 2")


def _assignment_coverage(plan, assignment_repository, db):
    checked = 0
    users = set()
    missing = []
    for month in plan["months"]:
        for record in month["records"]:
            user_id = record.get("user_id")
            business_at = str(record.get("business_at") or "")
            if user_id is None or not business_at:
                continue
            checked += 1
            users.add(int(user_id))
            assignment = assignment_repository.assignment_at(
                int(user_id), business_at, db=db
            )
            if assignment is None:
                missing.append(
                    {
                        "production_month": month["production_month"],
                        "source_type": record["source_type"],
                        "source_id": record["source_id"],
                        "user_id": int(user_id),
                        "business_at": business_at,
                    }
                )
    return {
        "checked_records": checked,
        "unique_user_count": len(users),
        "user_ids": sorted(users),
        "missing_assignment_history": len(missing),
        "missing_records": missing,
    }


def _difference_document(plan, coverage, metadata):
    selected = []
    month_summaries = []
    all_classifications = Counter()
    all_components = Counter()
    selected_components = Counter()
    for month in plan["months"]:
        classifications = Counter()
        components = Counter()
        month_selected = 0
        for record in month["records"]:
            classification = record["classification"]
            record_components = set(classification.split("+"))
            classifications[classification] += 1
            components.update(record_components)
            all_classifications[classification] += 1
            all_components.update(record_components)
            matched = sorted(record_components & DIFFERENCE_COMPONENTS)
            if not matched:
                continue
            month_selected += 1
            selected_components.update(matched)
            selected.append(
                {
                    "production_month": month["production_month"],
                    "matched_components": matched,
                    **record,
                }
            )
        month_summaries.append(
            {
                "production_month": month["production_month"],
                "period_start": month["period_start"],
                "period_end": month["period_end"],
                "legacy_batch_id": month["legacy_batch_id"],
                "legacy_manifest_sha256": month["legacy_manifest_sha256"],
                "manifest_sha256": month["manifest_sha256"],
                "record_count": len(month["records"]),
                "selected_difference_record_count": month_selected,
                "classification_counts": dict(sorted(classifications.items())),
                "classification_component_counts": dict(sorted(components.items())),
                "cross_month_work_ids": month["cross_month_work_ids"],
                "cross_month_quality_ids": month["cross_month_quality_ids"],
                "quality_ambiguity_ids": month["quality_ambiguity_ids"],
                "cross_month_work_user_ids": month["cross_month_work_user_ids"],
                "cross_month_quality_user_ids": month[
                    "cross_month_quality_user_ids"
                ],
                "multi_source_quality_user_ids": month[
                    "multi_source_quality_user_ids"
                ],
                "missing_target_user_ids": month["missing_target_user_ids"],
            }
        )
    selected.sort(
        key=lambda item: (
            item["production_month"],
            item["stable_key"],
            item["classification"],
        )
    )
    return {
        "format": "performance_v2_history_difference_list_v1",
        "metadata": metadata,
        "start_month": plan["start_month"],
        "end_month": plan["end_month"],
        "preflight_manifest_sha256": plan["manifest_sha256"],
        "totals": plan["totals"],
        "assignment_coverage": coverage,
        "selected_components": sorted(DIFFERENCE_COMPONENTS),
        "selected_difference_record_count": len(selected),
        "selected_component_counts": dict(sorted(selected_components.items())),
        "all_classification_counts": dict(sorted(all_classifications.items())),
        "all_classification_component_counts": dict(sorted(all_components.items())),
        "months": month_summaries,
        "records": selected,
    }


def _write_json(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _write_csv(path, records):
    fields = (
        "production_month",
        "source_type",
        "source_id",
        "classification",
        "matched_components",
        "user_id",
        "business_at",
        "stable_key",
        "source_digest",
        "payload_json",
    )
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "production_month": record["production_month"],
                    "source_type": record["source_type"],
                    "source_id": record["source_id"],
                    "classification": record["classification"],
                    "matched_components": "+".join(record["matched_components"]),
                    "user_id": record.get("user_id"),
                    "business_at": record.get("business_at") or "",
                    "stable_key": record["stable_key"],
                    "source_digest": record["source_digest"],
                    "payload_json": _canonical(record.get("payload") or {}),
                }
            )


def _git_commit(system_root):
    return subprocess.check_output(
        ["git", "-C", str(system_root), "rev-parse", "HEAD"], text=True
    ).strip()


def _query_flag(system_root):
    env_path = system_root / ".env"
    value = ""
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, candidate = stripped.split("=", 1)
            if key.strip() == "PERFORMANCE_LEDGER_V2_QUERY_ENABLED":
                value = candidate.strip().strip("\"'")
    enabled = value.lower() in {"1", "true", "yes", "on"}
    return {"raw": value or "false(default)", "enabled": enabled}


def run(args):
    if not args.confirm_production_preflight:
        raise RuntimeError("必须提供 --confirm-production-preflight")
    system_root = Path(args.system_root).resolve()
    db_path = Path(args.db).resolve()
    output_base = Path(args.output_dir).resolve()
    if not system_root.is_dir() or not db_path.is_file():
        raise RuntimeError("生产系统目录或数据库不存在")
    query_flag = _query_flag(system_root)
    if query_flag["enabled"]:
        raise RuntimeError("V2 查询开关已经开启，停止历史预检")

    sys.path.insert(0, str(system_root))
    os.environ.setdefault("SECRET_KEY", "offline-production-read-only-preflight")
    from modules.repositories.performance_assignment_repository import (
        PerformanceAssignmentRepository,
    )
    from modules.repositories.performance_history_migration_repository import (
        PerformanceHistoryMigrationRepository,
    )
    from modules.services.performance_history_migration_service import (
        PerformanceHistoryMigrationService,
    )

    started_at = datetime.now().astimezone()
    metadata = {
        "executed_at": started_at.isoformat(),
        "hostname": socket.gethostname(),
        "system_root": str(system_root),
        "database": str(db_path),
        "deployed_commit": _git_commit(system_root),
        "read_only_controls": {
            "sqlite_uri_mode": "ro",
            "pragma_query_only": True,
            "apply_mode": False,
            "v2_query_flag": query_flag,
        },
    }

    before_db = _open_read_only(db_path)
    try:
        before = _fingerprint(
            before_db, PerformanceHistoryMigrationRepository.payroll_fingerprint
        )
        _validate_fingerprint(before)
        plan = PerformanceHistoryMigrationService.analyze(
            before_db, args.from_month, args.to_month
        )
        _validate_plan(plan, PerformanceHistoryMigrationService)
        coverage = _assignment_coverage(
            plan, PerformanceAssignmentRepository, before_db
        )
        if coverage["missing_assignment_history"] != 0:
            raise RuntimeError("V2 来源仍存在缺失任职历史")
    finally:
        before_db.close()

    after_db = _open_read_only(db_path)
    try:
        after = _fingerprint(
            after_db, PerformanceHistoryMigrationRepository.payroll_fingerprint
        )
        _validate_fingerprint(after)
        verification_plan = PerformanceHistoryMigrationService.analyze(
            after_db, args.from_month, args.to_month
        )
        _validate_plan(verification_plan, PerformanceHistoryMigrationService)
    finally:
        after_db.close()

    if before != after:
        raise RuntimeError("预检前后受保护数据指纹发生变化")
    if plan["manifest_sha256"] != verification_plan["manifest_sha256"]:
        raise RuntimeError("预检前后历史来源 manifest 发生变化")

    difference = _difference_document(plan, coverage, metadata)
    stamp = started_at.strftime("%Y%m%d-%H%M%S")
    run_dir = output_base / stamp
    run_dir.mkdir(parents=True, exist_ok=False)
    full_path = run_dir / f"performance-v2-preflight-full-{stamp}.json"
    difference_path = run_dir / f"performance-v2-differences-{stamp}.json"
    csv_path = run_dir / f"performance-v2-differences-{stamp}.csv"
    index_path = run_dir / f"performance-v2-preflight-evidence-{stamp}.json"
    checksum_path = run_dir / "SHA256SUMS"

    full_document = {
        "status": "passed",
        "mode": "production_read_only_preflight",
        "metadata": metadata,
        "fingerprint_before": before,
        "fingerprint_after": after,
        "protected_data_unchanged": True,
        "source_manifest_unchanged": True,
        "assignment_coverage": coverage,
        "plan": plan,
    }
    _write_json(full_path, full_document)
    _write_json(difference_path, difference)
    _write_csv(csv_path, difference["records"])

    artifact_hashes = {
        full_path.name: _sha256(full_path),
        difference_path.name: _sha256(difference_path),
        csv_path.name: _sha256(csv_path),
    }
    index = {
        "status": "passed",
        "mode": "production_read_only_preflight",
        "metadata": metadata,
        "run_directory": str(run_dir),
        "preflight_manifest_sha256": plan["manifest_sha256"],
        "totals": plan["totals"],
        "assignment_coverage": coverage,
        "selected_difference_record_count": difference[
            "selected_difference_record_count"
        ],
        "selected_component_counts": difference["selected_component_counts"],
        "protected_data_unchanged": True,
        "source_manifest_unchanged": True,
        "artifacts": {
            name: {"path": str(run_dir / name), "sha256": sha256}
            for name, sha256 in artifact_hashes.items()
        },
    }
    _write_json(index_path, index)
    artifact_hashes[index_path.name] = _sha256(index_path)
    checksum_path.write_text(
        "".join(f"{value}  {name}\n" for name, value in artifact_hashes.items()),
        encoding="utf-8",
    )

    return {
        **index,
        "artifacts": {
            **index["artifacts"],
            index_path.name: {
                "path": str(index_path),
                "sha256": artifact_hashes[index_path.name],
            },
            checksum_path.name: {
                "path": str(checksum_path),
                "sha256": _sha256(checksum_path),
            },
        },
    }


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        result = run(args)
    except Exception as exc:
        print(
            json.dumps(
                {"status": "failed", "error": str(exc)}, ensure_ascii=False
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
