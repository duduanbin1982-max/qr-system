#!/usr/bin/env python3
"""Read-only analysis and controlled role-group permission cutover helpers."""

import hashlib
import json
import sqlite3
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.permission_catalog import ALL_PERMISSION_CODES  # noqa: E402


REQUIRED_SCHEMA_VERSION = 68
REQUIRED_TABLES = {"role_groups", "roles", "user_roles", "users"}
EVIDENCE_TABLES = {
    "role_group_permission_cutovers",
    "role_group_permission_archive",
}
REQUIRED_TRIGGER_NAMES = {
    "prevent_role_group_permission_insert",
    "prevent_role_group_permission_update",
    "prevent_role_group_permission_cutovers_update",
    "prevent_role_group_permission_cutovers_delete",
    "prevent_role_group_permission_archive_update",
    "prevent_role_group_permission_archive_delete",
}


def canonical_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def payload_sha256(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _table_exists(db, table):
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def _parse_permissions(
    raw_value,
    *,
    context,
    allow_wildcard,
    blockers,
    warnings=None,
    validate_catalog=True,
):
    if raw_value is None or str(raw_value).strip() == "":
        return []
    try:
        parsed = json.loads(raw_value) if isinstance(raw_value, str) else raw_value
    except (TypeError, json.JSONDecodeError):
        blockers.append(context + ": permissions is not valid JSON")
        return []
    if not isinstance(parsed, list) or any(
        not isinstance(item, str) or not item.strip() for item in parsed
    ):
        blockers.append(context + ": permissions must be an array of non-empty strings")
        return []
    normalized = list(dict.fromkeys(item.strip() for item in parsed))
    if "*" in normalized:
        if not allow_wildcard or normalized != ["*"]:
            blockers.append(context + ": wildcard permission is invalid")
        return normalized
    unknown = sorted(set(normalized) - set(ALL_PERMISSION_CODES))
    if unknown:
        message = context + ": unknown permissions: " + ", ".join(unknown)
        if validate_catalog:
            blockers.append(message)
        elif warnings is not None:
            warnings.append(message)
    return normalized


def _manifest_projection(report):
    return {
        "source_user_version": report["source_user_version"],
        "groups": report["groups_with_permissions"],
        "users": report["user_permission_differences"],
    }


def inspect_role_group_permissions(db):
    """Return a deterministic, read-only permission migration report."""

    db.row_factory = sqlite3.Row
    source_version = int(db.execute("PRAGMA user_version").fetchone()[0])
    existing_tables = {
        row["name"]
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    missing_tables = sorted(REQUIRED_TABLES - existing_tables)
    blockers = ["missing table: " + table for table in missing_tables]
    warnings = []
    if missing_tables:
        report = {
            "status": "blocked",
            "source_user_version": source_version,
            "integrity_check": "not-run",
            "foreign_key_violation_count": 0,
            "summary": {},
            "groups_with_permissions": [],
            "user_permission_differences": [],
            "blockers": blockers,
        }
        report["manifest_sha256"] = payload_sha256(_manifest_projection(report))
        return report

    group_rows = db.execute(
        "SELECT id,name,status,permissions FROM role_groups ORDER BY id"
    ).fetchall()
    role_rows = db.execute(
        "SELECT id,code,status,permissions,group_id FROM roles ORDER BY id"
    ).fetchall()
    assignment_rows = db.execute(
        "SELECT ur.user_id,u.username,u.name,u.status AS user_status,"
        "r.id AS role_id,r.code AS role_code,r.status AS role_status,"
        "r.permissions AS role_permissions,r.group_id "
        "FROM user_roles ur "
        "JOIN users u ON u.id=ur.user_id "
        "JOIN roles r ON r.id=ur.role_id "
        "ORDER BY ur.user_id,r.id"
    ).fetchall()

    groups = {}
    for row in group_rows:
        permissions = _parse_permissions(
            row["permissions"],
            context="role_group:" + str(row["id"]),
            allow_wildcard=False,
            blockers=blockers,
        )
        groups[row["id"]] = {
            "group_id": int(row["id"]),
            "group_name": row["name"],
            "group_status": row["status"],
            "permissions_json": row["permissions"] or "",
            "permissions": permissions,
            "role_codes": [],
            "role_count": 0,
            "user_ids": [],
            "user_count": 0,
        }

    roles = {}
    for row in role_rows:
        permissions = _parse_permissions(
            row["permissions"],
            context="role:" + str(row["id"]),
            allow_wildcard=True,
            blockers=blockers,
            warnings=warnings,
            validate_catalog=False,
        )
        role = {
            "id": int(row["id"]),
            "code": row["code"],
            "status": row["status"],
            "permissions": permissions,
            "group_id": row["group_id"],
        }
        roles[role["id"]] = role
        group = groups.get(role["group_id"])
        if group:
            group["role_codes"].append(role["code"])

    users = {}
    for row in assignment_rows:
        role = roles[row["role_id"]]
        user = users.setdefault(
            int(row["user_id"]),
            {
                "user_id": int(row["user_id"]),
                "username": row["username"],
                "name": row["name"],
                "user_status": row["user_status"],
                "role_codes": [],
                "role_permissions": set(),
                "group_permissions": set(),
                "has_wildcard": False,
            },
        )
        user["role_codes"].append(role["code"])
        group = groups.get(role["group_id"])
        if group:
            group["user_ids"].append(user["user_id"])
        if role["status"] != "active":
            continue
        if "*" in role["permissions"]:
            user["has_wildcard"] = True
        else:
            user["role_permissions"].update(role["permissions"])
        if group:
            user["group_permissions"].update(group["permissions"])

    groups_with_permissions = []
    for group in groups.values():
        group["role_codes"] = sorted(set(group["role_codes"]))
        group["role_count"] = len(group["role_codes"])
        group["user_ids"] = sorted(set(group["user_ids"]))
        group["user_count"] = len(group["user_ids"])
        if group["permissions"]:
            groups_with_permissions.append(group)

    user_differences = []
    for user in users.values():
        if not user["group_permissions"]:
            continue
        role_permissions = ["*"] if user["has_wildcard"] else sorted(user["role_permissions"])
        group_permissions = sorted(user["group_permissions"])
        group_only = [] if user["has_wildcard"] else sorted(
            user["group_permissions"] - user["role_permissions"]
        )
        user_differences.append({
            "user_id": user["user_id"],
            "username": user["username"],
            "name": user["name"],
            "user_status": user["user_status"],
            "role_codes": sorted(set(user["role_codes"])),
            "role_permissions": role_permissions,
            "group_permissions": group_permissions,
            "group_only_permissions": group_only,
        })
    user_differences.sort(key=lambda item: item["user_id"])

    referenced_role_ids = {
        role["id"]
        for role in roles.values()
        if role["group_id"] in groups
        and groups[role["group_id"]]["permissions"]
    }
    referenced_user_ids = {
        item["user_id"] for item in user_differences
    }
    report = {
        "status": "blocked" if blockers else "ready",
        "source_user_version": source_version,
        "integrity_check": db.execute("PRAGMA integrity_check").fetchone()[0],
        "foreign_key_violation_count": len(db.execute("PRAGMA foreign_key_check").fetchall()),
        "summary": {
            "role_group_count": len(groups),
            "groups_with_permissions": len(groups_with_permissions),
            "roles_in_groups_with_permissions": len(referenced_role_ids),
            "users_in_groups_with_permissions": len(referenced_user_ids),
            "users_with_group_only_permissions": sum(
                bool(item["group_only_permissions"]) for item in user_differences
            ),
        },
        "groups_with_permissions": groups_with_permissions,
        "user_permission_differences": user_differences,
        "blockers": blockers,
        "warnings": warnings,
    }
    if report["integrity_check"] != "ok":
        report["blockers"].append("database integrity check failed")
    if report["foreign_key_violation_count"]:
        report["blockers"].append("database contains foreign-key violations")
    report["status"] = "blocked" if report["blockers"] else "ready"
    report["manifest_sha256"] = payload_sha256(_manifest_projection(report))
    return report


def open_read_only(path):
    db_path = Path(path).expanduser().resolve()
    db = sqlite3.connect("file:" + db_path.as_posix() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    return db


def _require_actual_admin(db, user_id, label):
    row = db.execute(
        "SELECT u.name FROM users u "
        "JOIN user_roles ur ON ur.user_id=u.id "
        "JOIN roles r ON r.id=ur.role_id "
        "WHERE u.id=? AND u.status='active' AND r.code='admin' "
        "AND r.status='active' LIMIT 1",
        (user_id,),
    ).fetchone()
    if not row:
        raise ValueError(label + "必须是启用的系统管理员")


def verify_cutover(db, idempotency_key):
    db.row_factory = sqlite3.Row
    row = db.execute(
        "SELECT * FROM role_group_permission_cutovers WHERE idempotency_key=?",
        (idempotency_key,),
    ).fetchone()
    if not row:
        return {
            "status": "blocked",
            "idempotency_key": idempotency_key,
            "blockers": ["cutover evidence does not exist"],
        }
    archive_count = int(db.execute(
        "SELECT COUNT(*) FROM role_group_permission_archive WHERE cutover_id=?",
        (row["id"],),
    ).fetchone()[0])
    nonempty_count = int(db.execute(
        "SELECT COUNT(*) FROM role_groups "
        "WHERE trim(COALESCE(permissions,'')) NOT IN ('','[]')"
    ).fetchone()[0])
    trigger_names = {
        item["name"]
        for item in db.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' "
            "AND name IN (?,?,?,?,?,?)",
            tuple(sorted(REQUIRED_TRIGGER_NAMES)),
        ).fetchall()
    }
    blockers = []
    if archive_count != int(row["group_count"]):
        blockers.append("archive count does not match cutover manifest")
    if nonempty_count:
        blockers.append("role_groups still contains non-empty permissions")
    if trigger_names != REQUIRED_TRIGGER_NAMES:
        blockers.append("role-group permission immutability guards are incomplete")
    integrity_check = db.execute("PRAGMA integrity_check").fetchone()[0]
    foreign_key_violation_count = len(db.execute("PRAGMA foreign_key_check").fetchall())
    if integrity_check != "ok":
        blockers.append("database integrity check failed")
    if foreign_key_violation_count:
        blockers.append("database contains foreign-key violations")
    return {
        "status": "blocked" if blockers else "passed",
        "idempotency_key": idempotency_key,
        "manifest_sha256": row["manifest_sha256"],
        "cutover_id": int(row["id"]),
        "archive_count": archive_count,
        "expected_archive_count": int(row["group_count"]),
        "nonempty_role_group_permissions": nonempty_count,
        "write_guard_count": len(trigger_names),
        "integrity_check": integrity_check,
        "foreign_key_violation_count": foreign_key_violation_count,
        "blockers": blockers,
    }


def apply_cutover(
    db,
    *,
    idempotency_key,
    expected_manifest_sha256,
    actor_user_id,
    actor_name,
    approved_by_user_id,
    approved_by_name,
):
    """Archive and clear legacy group permissions in one immediate transaction."""

    if not str(idempotency_key or "").strip():
        raise ValueError("幂等键不能为空")
    if len(str(expected_manifest_sha256 or "")) != 64:
        raise ValueError("预检清单 SHA-256 无效")
    if int(actor_user_id) == int(approved_by_user_id):
        raise ValueError("执行人与批准人必须分离")
    if not str(actor_name or "").strip() or not str(approved_by_name or "").strip():
        raise ValueError("执行人和批准人姓名不能为空")

    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    if db.in_transaction:
        raise RuntimeError("迁移连接必须处于清洁事务状态")
    try:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute(
            "SELECT manifest_sha256 FROM role_group_permission_cutovers "
            "WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        if existing:
            if existing["manifest_sha256"] != expected_manifest_sha256:
                raise ValueError("幂等键已存在，但预检清单不一致")
            db.commit()
            result = verify_cutover(db, idempotency_key)
            result["idempotent"] = True
            return result

        version = int(db.execute("PRAGMA user_version").fetchone()[0])
        if version < REQUIRED_SCHEMA_VERSION:
            raise RuntimeError("必须先执行 v068 数据库结构迁移")
        if not EVIDENCE_TABLES.issubset({
            row["name"]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }):
            raise RuntimeError("v068 权限归档表不完整")
        _require_actual_admin(db, int(actor_user_id), "执行人")
        _require_actual_admin(db, int(approved_by_user_id), "批准人")

        report = inspect_role_group_permissions(db)
        if report["status"] != "ready":
            raise RuntimeError("预检存在阻断项：" + "; ".join(report["blockers"]))
        if report["manifest_sha256"] != expected_manifest_sha256:
            raise ValueError("生产数据已变化，预检清单 SHA-256 不匹配")

        from modules.audit_writer import insert_audit_log

        manifest = _manifest_projection(report)
        cursor = db.execute(
            "INSERT INTO role_group_permission_cutovers "
            "(idempotency_key,manifest_sha256,source_user_version,actor_user_id,"
            "actor_name,approved_by_user_id,approved_by_name,group_count,role_count,"
            "user_count,manifest_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                idempotency_key,
                expected_manifest_sha256,
                report["source_user_version"],
                int(actor_user_id),
                str(actor_name).strip(),
                int(approved_by_user_id),
                str(approved_by_name).strip(),
                report["summary"]["groups_with_permissions"],
                report["summary"]["roles_in_groups_with_permissions"],
                report["summary"]["users_in_groups_with_permissions"],
                canonical_json(manifest),
            ),
        )
        cutover_id = int(cursor.lastrowid)
        for group in report["groups_with_permissions"]:
            db.execute(
                "INSERT INTO role_group_permission_archive "
                "(cutover_id,group_id,group_name,group_status,permissions_json,"
                "role_codes_json,role_count,user_count) VALUES (?,?,?,?,?,?,?,?)",
                (
                    cutover_id,
                    group["group_id"],
                    group["group_name"],
                    group["group_status"],
                    group["permissions_json"],
                    canonical_json(group["role_codes"]),
                    group["role_count"],
                    group["user_count"],
                ),
            )
            updated = db.execute(
                "UPDATE role_groups SET permissions='[]', "
                "updated_at=datetime('now','localtime') "
                "WHERE id=? AND COALESCE(permissions,'')=?",
                (group["group_id"], group["permissions_json"]),
            )
            if updated.rowcount != 1:
                raise RuntimeError(
                    "角色组权限在迁移事务中发生并发变化：" + str(group["group_id"])
                )

        insert_audit_log(
            db,
            int(actor_user_id),
            "role_group_permission_cutover",
            "role_group_permissions",
            cutover_id,
            canonical_json({
                "idempotency_key": idempotency_key,
                "manifest_sha256": expected_manifest_sha256,
                "approved_by_user_id": int(approved_by_user_id),
                "group_count": report["summary"]["groups_with_permissions"],
                "role_count": report["summary"]["roles_in_groups_with_permissions"],
                "user_count": report["summary"]["users_in_groups_with_permissions"],
            }),
            event_id="role-group-permission-v68-" + payload_sha256(idempotency_key)[:24],
        )
        remaining = db.execute(
            "SELECT COUNT(*) FROM role_groups "
            "WHERE trim(COALESCE(permissions,'')) NOT IN ('','[]')"
        ).fetchone()[0]
        if remaining:
            raise RuntimeError("仍存在未清理的角色组权限")
        db.commit()
    except Exception:
        db.rollback()
        raise

    result = verify_cutover(db, idempotency_key)
    result["idempotent"] = False
    return result
