#!/usr/bin/env python3
"""Create, verify, and restore atomic deployment evidence manifests."""

import argparse
import hashlib
import io
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


MANAGED_ATTACHMENT_ROOTS = (
    PurePosixPath("data/attachments"),
    PurePosixPath("uploads/employee_docs"),
)
MANAGED_RELEASE_ROOTS = (PurePosixPath("public/static"),)
PUBLIC_STATIC_DIRECTORY_MODE = 0o755
PUBLIC_STATIC_FILE_MODE = 0o644

BACKUP_SCHEMA_V1 = "qr-system-backup-evidence/v1"
BACKUP_SCHEMA = "qr-system-backup-evidence/v2"
DEPLOYMENT_SCHEMA = "qr-system-deployment/v2"
WRITE_FENCE_SCHEMA = "qr-system-write-fence/v1"
DEPLOYMENT_SCOPE_FULL = "full"
DEPLOYMENT_SCOPE_CODE_ONLY = "code_only"
DEPLOYMENT_SCOPE_BACKEND_FRONTEND_STATIC = "backend_frontend_static"
NON_DATA_RELEASE_SCOPES = {
    DEPLOYMENT_SCOPE_CODE_ONLY,
    DEPLOYMENT_SCOPE_BACKEND_FRONTEND_STATIC,
}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def canonical_digest(payload):
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_without_symlinks(path):
    raw = Path(path).expanduser()
    if ".." in raw.parts:
        raise RuntimeError("evidence path cannot contain parent-directory traversal")
    candidate = Path(os.path.abspath(raw))
    cursor = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        cursor = cursor / part
        if cursor.is_symlink():
            raise RuntimeError(f"evidence path cannot traverse symlinks: {cursor}")
    return candidate


def _fsync_directory(path):
    if os.name != "posix":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def sqlite_evidence(path):
    database = Path(path).resolve()
    if not database.is_file():
        raise RuntimeError(f"database backup does not exist: {database}")
    connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"database integrity check failed: {integrity}")
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_keys:
            raise RuntimeError(f"database foreign-key check failed: {foreign_keys[:5]}")
        return {
            "user_version": int(connection.execute("PRAGMA user_version").fetchone()[0]),
            "table_count": int(
                connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
                ).fetchone()[0]
            ),
            "integrity_check": integrity,
            "foreign_key_error_count": 0,
        }
    finally:
        connection.close()


def sqlite_logical_digest(path, *, include_schema_version=True):
    """Hash a consistent SQL snapshot, optionally excluding the backup schema cookie.

    SQLite backup can change schema_version without changing schema or facts.
    Keep the cookie in stored state evidence for compatibility and drift checks;
    exclude it only when comparing a source database with its verified backup.
    """
    database = Path(path).resolve()
    if not database.is_file():
        raise RuntimeError(f"database does not exist: {database}")
    connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    digest = hashlib.sha256()
    try:
        connection.execute("BEGIN")
        for statement in connection.iterdump():
            digest.update(statement.encode("utf-8"))
            digest.update(b"\n")
        schema_identity = {
            "user_version": int(connection.execute("PRAGMA user_version").fetchone()[0]),
        }
        if include_schema_version:
            schema_identity["schema_version"] = int(
                connection.execute("PRAGMA schema_version").fetchone()[0]
            )
        digest.update(canonical_digest(schema_identity).encode("ascii"))
        return digest.hexdigest()
    finally:
        connection.close()


def atomic_write_json(path, payload):
    target = _resolve_without_symlinks(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.tmp.", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, target)
        _fsync_directory(target.parent)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_create_json(path, payload):
    """Create JSON evidence exactly once without a check-then-write race."""
    target = _resolve_without_symlinks(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        target.unlink(missing_ok=True)
        raise
    _fsync_directory(target.parent)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def require_schema(payload, expected, label):
    if not isinstance(payload, dict) or payload.get("schema") != expected:
        observed = payload.get("schema") if isinstance(payload, dict) else None
        raise RuntimeError(
            f"unsupported {label} schema: {observed!r}; expected {expected!r}"
        )
    return payload


def require_backup_schema(payload):
    if not isinstance(payload, dict) or payload.get("schema") not in {
        BACKUP_SCHEMA_V1,
        BACKUP_SCHEMA,
    }:
        observed = payload.get("schema") if isinstance(payload, dict) else None
        raise RuntimeError(f"unsupported backup metadata schema: {observed!r}")
    return payload


def verify_file_evidence(evidence, label):
    path = Path(evidence["path"]).resolve()
    if not path.is_file():
        raise RuntimeError(f"{label} does not exist: {path}")
    actual = sha256_file(path)
    if actual != evidence["sha256"]:
        raise RuntimeError(f"{label} checksum mismatch: {actual} != {evidence['sha256']}")
    return path


def archive_inventory(path, allowed_roots):
    files = []
    total_bytes = 0
    with tarfile.open(path, "r:gz") as archive:
        for member in safe_tar_members(archive, allowed_roots):
            if not member.isfile():
                continue
            source = archive.extractfile(member)
            if source is None:
                raise RuntimeError(f"archive file cannot be read: {member.name}")
            digest = hashlib.sha256()
            size = 0
            with source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
                    size += len(chunk)
            files.append(
                {"path": member.name, "size_bytes": size, "sha256": digest.hexdigest()}
            )
            total_bytes += size
    files.sort(key=lambda item: item["path"])
    return {
        "file_count": len(files),
        "total_bytes": total_bytes,
        "manifest_sha256": canonical_digest(files),
        "files": files,
    }


def create_backup_metadata(args):
    database = Path(args.database).resolve()
    attachments = Path(args.attachments).resolve()
    evidence = sqlite_evidence(database)
    attachment_inventory = archive_inventory(attachments, MANAGED_ATTACHMENT_ROOTS)
    payload = {
        "schema": BACKUP_SCHEMA,
        "created_at": utc_now(),
        "database": {
            "path": str(database),
            "sha256": sha256_file(database),
            "logical_sha256": sqlite_logical_digest(database),
            "size_bytes": database.stat().st_size,
            **evidence,
        },
        "attachments": {
            "path": str(attachments),
            "sha256": sha256_file(attachments),
            "size_bytes": attachments.stat().st_size,
            "archived_roots": list(args.attachment_root or []),
            "inventory": attachment_inventory,
        },
    }
    atomic_create_json(args.output, payload)
    return payload


def verify_backup_metadata(path):
    payload = require_backup_schema(read_json(path))
    database = verify_file_evidence(payload["database"], "database backup")
    attachments = verify_file_evidence(payload["attachments"], "attachment backup")
    attachment_inventory = archive_inventory(attachments, MANAGED_ATTACHMENT_ROOTS)
    expected_inventory = payload["attachments"].get("inventory")
    if expected_inventory is not None and attachment_inventory != expected_inventory:
        raise RuntimeError("attachment backup inventory no longer matches metadata")
    if expected_inventory is None:
        payload = {
            **payload,
            "attachments": {
                **payload["attachments"],
                "inventory": attachment_inventory,
            },
        }
    observed = sqlite_evidence(database)
    expected = payload["database"]
    for field in ("user_version", "table_count", "integrity_check", "foreign_key_error_count"):
        if observed[field] != expected[field]:
            raise RuntimeError(
                f"database backup evidence mismatch for {field}: "
                f"{observed[field]} != {expected[field]}"
            )
    return payload


def prepare_deployment_manifest(args):
    output = Path(args.output).resolve()
    scope = getattr(args, "scope", DEPLOYMENT_SCOPE_FULL)
    if scope not in {
        DEPLOYMENT_SCOPE_FULL,
        DEPLOYMENT_SCOPE_CODE_ONLY,
        DEPLOYMENT_SCOPE_BACKEND_FRONTEND_STATIC,
    }:
        raise RuntimeError(f"unsupported deployment scope: {scope!r}")
    existing = None
    if output.exists():
        if scope not in NON_DATA_RELEASE_SCOPES:
            raise RuntimeError(f"deployment manifest already exists: {output}")
        existing = require_schema(
            read_json(output), DEPLOYMENT_SCHEMA, "deployment manifest"
        )
        if (
            existing.get("scope") != scope
            or existing.get("deployment_key") != args.deployment_key
            or existing.get("before_commit") != args.before_commit
            or existing.get("target_commit") != args.target_commit
            or existing.get("status") != "fenced"
        ):
            raise RuntimeError("preparation manifest does not match request")
        if existing.get("backup") is not None:
            raise RuntimeError("backup evidence is already attached")
    elif scope in NON_DATA_RELEASE_SCOPES:
        raise RuntimeError("non-data deployment requires a started audit manifest")

    backup = verify_backup_metadata(args.backup_metadata)
    source_database_version = int(backup["database"]["user_version"])
    target_database_version = args.target_database_version
    if scope in NON_DATA_RELEASE_SCOPES:
        if target_database_version is None:
            raise RuntimeError(
                "non-data deployment requires an explicit target database version"
            )
        if int(target_database_version) != source_database_version:
            raise RuntimeError(
                "non-data deployment cannot change the database schema version"
            )
    elif target_database_version is None:
        raise RuntimeError("full deployment requires a target database version")
    release_backup = Path(args.release_backup).resolve()
    if not release_backup.is_file():
        raise RuntimeError(f"release backup does not exist: {release_backup}")
    with tarfile.open(release_backup, "r:gz") as archive:
        safe_tar_members(archive, MANAGED_RELEASE_ROOTS)
    target_static = None
    if scope == DEPLOYMENT_SCOPE_BACKEND_FRONTEND_STATIC:
        target_static_path = Path(args.target_static_backup).resolve()
        if not target_static_path.is_file():
            raise RuntimeError("built frontend static backup does not exist")
        target_static = {
            "path": str(target_static_path),
            "sha256": sha256_file(target_static_path),
            "size_bytes": target_static_path.stat().st_size,
            "inventory": archive_inventory(
                target_static_path, MANAGED_RELEASE_ROOTS
            ),
        }
    write_fence_path = _resolve_without_symlinks(args.write_fence)
    write_fence = require_schema(
        read_json(write_fence_path), WRITE_FENCE_SCHEMA, "deployment write fence"
    )
    if write_fence.get("deployment_key") != args.deployment_key:
        raise RuntimeError("deployment write fence key does not match deployment manifest")
    if write_fence.get("target_commit") != args.target_commit:
        raise RuntimeError("deployment write fence target does not match deployment manifest")
    if existing is not None and existing.get("write_fence", {}).get("path") != str(
        write_fence_path
    ):
        raise RuntimeError("code-only write fence path does not match started manifest")
    payload = {
        "schema": DEPLOYMENT_SCHEMA,
        "deployment_key": args.deployment_key,
        "scope": scope,
        "operations": {
            "database_migration": scope == DEPLOYMENT_SCOPE_FULL,
            "attachment_migration": scope == DEPLOYMENT_SCOPE_FULL,
            "frontend_publish": scope
            in {DEPLOYMENT_SCOPE_FULL, DEPLOYMENT_SCOPE_BACKEND_FRONTEND_STATIC},
            "code_switch": True,
            "service_restart": True,
        },
        "created_at": (existing or {}).get("created_at", utc_now()),
        "status": "prepared",
        "before_commit": args.before_commit,
        "target_commit": args.target_commit,
        "source_database_version": source_database_version,
        "target_database_version": int(target_database_version),
        "backup": backup,
        "release": {
            "path": str(release_backup),
            "sha256": sha256_file(release_backup),
            "size_bytes": release_backup.stat().st_size,
        },
        "target_static": target_static,
        "fact_watermark": {
            "captured_at": backup["created_at"],
            "database_sha256": backup["database"]["sha256"],
            "database_user_version": backup["database"]["user_version"],
            "attachment_manifest_sha256": backup["attachments"]["inventory"][
                "manifest_sha256"
            ],
            "attachment_file_count": backup["attachments"]["inventory"]["file_count"],
        },
        "write_fence": {
            **(existing or {}).get("write_fence", {}),
            "path": str(write_fence_path),
            "acquired_at": write_fence["acquired_at"],
            "release_authorized_at": None,
            "released_at": None,
        },
        "rollback": {
            "automatic_restore_allowed": True,
            "restore_scope_verified": False,
            "static_restore_verified": False,
            "failure_snapshot": None,
        },
        "code_only_state": (existing or {}).get("code_only_state"),
        "events": list((existing or {}).get("events", [])),
    }
    if existing is None:
        atomic_create_json(args.output, payload)
    else:
        payload["events"].append(
            {
                "status": "backup_verified",
                "at": payload["created_at"],
                "detail": "database and attachment backups verified without retention cleanup",
            }
        )
        atomic_write_json(args.output, payload)
    return payload


def begin_code_only_deployment(args):
    output = Path(args.output).resolve()
    if output.exists():
        raise RuntimeError(f"deployment manifest already exists: {output}")
    for label, value in (
        ("before commit", args.before_commit),
        ("target commit", args.target_commit),
    ):
        if len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
            raise RuntimeError(f"invalid code-only {label}")
    if not args.deployment_key or len(args.deployment_key) > 128 or any(
        char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
        for char in args.deployment_key
    ):
        raise RuntimeError("invalid code-only deployment key")
    scope = getattr(args, "scope", DEPLOYMENT_SCOPE_CODE_ONLY)
    if scope not in NON_DATA_RELEASE_SCOPES:
        raise RuntimeError("unsupported non-data deployment scope")
    if args.source_database_version != args.target_database_version:
        raise RuntimeError("non-data deployment requires an unchanged database version")
    fence_path = str(Path(args.write_fence).resolve())
    now = utc_now()
    payload = {
        "schema": DEPLOYMENT_SCHEMA,
        "deployment_key": args.deployment_key,
        "scope": scope,
        "operations": {
            "database_migration": False,
            "attachment_migration": False,
            "frontend_publish": scope == DEPLOYMENT_SCOPE_BACKEND_FRONTEND_STATIC,
            "code_switch": True,
            "service_restart": True,
        },
        "created_at": now,
        "updated_at": now,
        "status": "preparing",
        "before_commit": args.before_commit,
        "target_commit": args.target_commit,
        "source_database_version": args.source_database_version,
        "target_database_version": args.target_database_version,
        "backup": None,
        "release": None,
        "fact_watermark": None,
        "write_fence": {
            "path": fence_path,
            "acquired_at": None,
            "release_authorized_at": None,
            "released_at": None,
        },
        "rollback": {
            "automatic_restore_allowed": True,
            "restore_scope_verified": False,
            "static_restore_verified": False,
            "failure_snapshot": None,
        },
        "code_only_state": None,
        "events": [
            {
                "status": "preparing",
                "at": now,
                "detail": (
                    "backend plus static assets requested; database and attachment migration are prohibited"
                    if scope == DEPLOYMENT_SCOPE_BACKEND_FRONTEND_STATIC
                    else "code-only deployment requested; database, attachments, and frontend are excluded"
                ),
            }
        ],
    }
    atomic_create_json(output, payload)
    return payload


def record_code_only_fence(args):
    manifest = require_schema(
        read_json(args.manifest), DEPLOYMENT_SCHEMA, "deployment manifest"
    )
    fence_path, fence = _active_fence_for_manifest(manifest)
    if manifest.get("scope") not in NON_DATA_RELEASE_SCOPES:
        raise RuntimeError("fence recording requires a non-data deployment scope")
    if fence.get("deployment_key") != manifest.get("deployment_key"):
        raise RuntimeError("write fence does not match deployment key")
    if manifest.get("status") != "preparing":
        raise RuntimeError("code-only deployment is not in preparing state")
    now = utc_now()
    manifest["status"] = "fenced"
    manifest["updated_at"] = now
    manifest["write_fence"]["path"] = str(fence_path)
    manifest["write_fence"]["acquired_at"] = fence["acquired_at"]
    manifest.setdefault("events", []).append(
        {
            "status": "fenced",
            "at": now,
            "detail": "atomic application write fence acquired",
        }
    )
    atomic_write_json(args.manifest, manifest)
    return manifest


def managed_path_inventory(project_root, roots):
    """Hash managed files without copying or changing them."""
    root = Path(project_root).resolve()
    files = []
    total_bytes = 0
    for managed_root in roots:
        source = root
        for part in managed_root.parts:
            source = source / part
            if source.is_symlink():
                raise RuntimeError(f"managed state cannot traverse symlinks: {source}")
        if not source.exists():
            continue
        candidates = [source] if source.is_file() else sorted(source.rglob("*"))
        for candidate in candidates:
            if candidate.is_symlink():
                raise RuntimeError(f"managed state cannot contain symlinks: {candidate}")
            if candidate.is_dir():
                continue
            if not candidate.is_file():
                raise RuntimeError(f"managed state contains a non-file entry: {candidate}")
            relative = candidate.relative_to(root).as_posix()
            size = candidate.stat().st_size
            files.append(
                {"path": relative, "size_bytes": size, "sha256": sha256_file(candidate)}
            )
            total_bytes += size
    files.sort(key=lambda item: item["path"])
    return {
        "file_count": len(files),
        "total_bytes": total_bytes,
        "manifest_sha256": canonical_digest(files),
        "files": files,
    }


def code_only_state(database, project_root):
    database = Path(database)
    if database.is_symlink():
        raise RuntimeError(f"production database cannot be a symlink: {database}")
    database = database.resolve()
    evidence = sqlite_evidence(database)
    sidecars = {}
    for suffix in ("-wal", "-journal"):
        path = Path(str(database) + suffix)
        if path.is_file():
            sidecars[suffix] = {
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        else:
            sidecars[suffix] = None
    return {
        "database": {
            "sha256": sha256_file(database),
            "logical_sha256": sqlite_logical_digest(database),
            "size_bytes": database.stat().st_size,
            **evidence,
            "sidecars": sidecars,
        },
        "attachments": managed_path_inventory(
            project_root, MANAGED_ATTACHMENT_ROOTS
        ),
        "release": managed_path_inventory(project_root, MANAGED_RELEASE_ROOTS),
    }


def capture_code_only_state(args):
    manifest = require_schema(
        read_json(args.manifest), DEPLOYMENT_SCHEMA, "deployment manifest"
    )
    if manifest.get("scope", DEPLOYMENT_SCOPE_FULL) not in NON_DATA_RELEASE_SCOPES:
        raise RuntimeError("non-data state capture requires a supported scope")
    _active_fence_for_manifest(manifest)
    if manifest.get("code_only_state"):
        raise RuntimeError("code-only baseline already exists")
    state = code_only_state(args.database, args.project_root)
    if state["database"]["user_version"] != manifest["source_database_version"]:
        raise RuntimeError("production database version changed after backup")
    backup = manifest.get("backup")
    if not isinstance(backup, dict):
        raise RuntimeError("code-only deployment backup evidence is missing")
    backup_database = verify_file_evidence(backup["database"], "database backup")
    if (
        sqlite_logical_digest(args.database, include_schema_version=False)
        != sqlite_logical_digest(backup_database, include_schema_version=False)
    ):
        raise RuntimeError("production database differs from its final backup")
    if (
        state["attachments"]["manifest_sha256"]
        != backup["attachments"]["inventory"]["manifest_sha256"]
    ):
        raise RuntimeError("managed attachments differ from their final backup")
    release = manifest.get("release")
    if not isinstance(release, dict):
        raise RuntimeError("frontend preservation evidence is missing")
    release_inventory = archive_inventory(
        verify_file_evidence(release, "frontend preservation backup"),
        MANAGED_RELEASE_ROOTS,
    )
    if state["release"] != release_inventory:
        raise RuntimeError("frontend files differ from their preservation backup")
    manifest["code_only_state"] = state
    manifest["updated_at"] = utc_now()
    manifest.setdefault("events", []).append(
        {
            "status": "code_only_baseline_captured",
            "at": manifest["updated_at"],
            "detail": "database, managed attachments, and pre-release static fingerprints captured",
            "database_sha256": state["database"]["sha256"],
            "attachment_manifest_sha256": state["attachments"]["manifest_sha256"],
            "release_manifest_sha256": state["release"]["manifest_sha256"],
        }
    )
    atomic_write_json(args.manifest, manifest)
    return state


def verify_code_only_state(args):
    manifest = require_schema(
        read_json(args.manifest), DEPLOYMENT_SCHEMA, "deployment manifest"
    )
    scope = manifest.get("scope", DEPLOYMENT_SCOPE_FULL)
    if scope not in NON_DATA_RELEASE_SCOPES:
        raise RuntimeError("non-data state verification requires a supported scope")
    expected = manifest.get("code_only_state")
    if not isinstance(expected, dict):
        raise RuntimeError("code-only immutable baseline is missing")
    observed = code_only_state(args.database, args.project_root)
    static_before_switch = manifest.get("status") in {
        "preparing",
        "fenced",
        "prepared",
        "backup_verified",
        "deployment_failed",
        "abort_release_authorized",
    }
    static_rollback = bool(manifest.get("rollback", {}).get("static_restore_verified"))
    if (
        scope == DEPLOYMENT_SCOPE_BACKEND_FRONTEND_STATIC
        and not static_rollback
        and not static_before_switch
    ):
        if (
            observed["database"] != expected["database"]
            or observed["attachments"] != expected["attachments"]
        ):
            raise RuntimeError(
                "database or attachment invariant drift detected; keep service fenced for review"
            )
        target_static = manifest.get("target_static")
        if not isinstance(target_static, dict):
            raise RuntimeError("target static asset evidence is missing")
        verify_file_evidence(target_static, "target static asset archive")
        if observed["release"] != target_static["inventory"]:
            raise RuntimeError(
                "published static assets differ from the target build; keep service fenced for review"
            )
    elif observed != expected:
        raise RuntimeError(
            "code-only invariant drift detected; keep service fenced for review"
        )
    manifest["updated_at"] = utc_now()
    manifest.setdefault("events", []).append(
        {
            "status": "code_only_state_verified",
            "at": manifest["updated_at"],
            "detail": (
                "database and managed attachments match the fenced baseline; published static assets match the locked target build"
                if scope == DEPLOYMENT_SCOPE_BACKEND_FRONTEND_STATIC
                else "database, managed attachments, and frontend match the fenced baseline"
            ),
            "state_sha256": canonical_digest(observed),
        }
    )
    atomic_write_json(args.manifest, manifest)
    return observed


def authorize_code_only_abort(args):
    manifest = require_schema(
        read_json(args.manifest), DEPLOYMENT_SCHEMA, "deployment manifest"
    )
    if manifest.get("scope") not in NON_DATA_RELEASE_SCOPES:
        raise RuntimeError("pre-switch abort requires a non-data deployment scope")
    _active_fence_for_manifest(manifest)
    if manifest.get("status") not in {"fenced", "prepared", "deployment_failed"}:
        raise RuntimeError("pre-switch abort is not allowed after code switching began")
    marker = Path(args.project_root).resolve() / ".deployed_commit"
    if (
        marker.is_symlink()
        or not marker.is_file()
        or marker.read_text(encoding="utf-8").strip() != manifest["before_commit"]
    ):
        raise RuntimeError("pre-switch abort refused: deployed commit marker changed")
    if args.current_commit != manifest["before_commit"]:
        raise RuntimeError("pre-switch abort refused: checkout is not the original commit")
    verify_code_only_state(
        argparse.Namespace(
            manifest=args.manifest,
            database=args.database,
            project_root=args.project_root,
        )
    )
    manifest = require_schema(
        read_json(args.manifest), DEPLOYMENT_SCHEMA, "deployment manifest"
    )
    now = utc_now()
    manifest["rollback"]["automatic_restore_allowed"] = False
    manifest["rollback"]["restore_scope_verified"] = True
    manifest["status"] = "abort_release_authorized"
    manifest["updated_at"] = now
    manifest.setdefault("events", []).append(
        {
            "status": "abort_release_authorized",
            "at": now,
            "detail": "original code and unchanged production data verified before releasing an aborted deployment fence",
        }
    )
    atomic_write_json(args.manifest, manifest)
    return manifest


def authorize_code_only_rollback_release(args):
    manifest = require_schema(
        read_json(args.manifest), DEPLOYMENT_SCHEMA, "deployment manifest"
    )
    if manifest.get("scope") not in NON_DATA_RELEASE_SCOPES:
        raise RuntimeError("non-data rollback authorization requires a supported scope")
    _active_fence_for_manifest(manifest)
    if manifest.get("status") != "rollback_accepted_fenced":
        raise RuntimeError("code-only rollback release requires fenced health acceptance")
    if args.current_commit != manifest["before_commit"]:
        raise RuntimeError("code-only rollback refused: checkout is not the original commit")
    marker = Path(args.project_root).resolve() / ".deployed_commit"
    if (
        marker.is_symlink()
        or not marker.is_file()
        or marker.read_text(encoding="utf-8").strip() != manifest["before_commit"]
    ):
        raise RuntimeError("code-only rollback refused: deployed commit marker is not restored")
    verify_code_only_state(
        argparse.Namespace(
            manifest=args.manifest,
            database=args.database,
            project_root=args.project_root,
        )
    )
    manifest = require_schema(
        read_json(args.manifest), DEPLOYMENT_SCHEMA, "deployment manifest"
    )
    manifest["rollback"]["restore_scope_verified"] = True
    manifest["updated_at"] = utc_now()
    manifest.setdefault("events", []).append(
        {
            "status": "code_only_rollback_verified",
            "at": manifest["updated_at"],
            "detail": "original code is running healthy behind the fence and business data fingerprints are unchanged",
        }
    )
    atomic_write_json(args.manifest, manifest)
    return manifest


def update_manifest(args):
    payload = require_schema(
        read_json(args.manifest), DEPLOYMENT_SCHEMA, "deployment manifest"
    )
    payload["status"] = args.status
    payload["updated_at"] = utc_now()
    event = {"status": args.status, "at": payload["updated_at"]}
    if args.detail:
        event["detail"] = args.detail
    if args.database_version is not None:
        event["database_version"] = args.database_version
    payload.setdefault("events", []).append(event)
    atomic_write_json(args.manifest, payload)
    return payload


def record_verified_rollback_scope(manifest_path, status, detail, database_version):
    manifest = require_schema(
        read_json(manifest_path), DEPLOYMENT_SCHEMA, "deployment manifest"
    )
    now = utc_now()
    manifest["rollback"]["restore_scope_verified"] = status != "code_only_data_preserved"
    manifest["status"] = status
    manifest["updated_at"] = now
    manifest.setdefault("events", []).append(
        {
            "status": status,
            "at": now,
            "detail": detail,
            "database_version": database_version,
        }
    )
    atomic_write_json(manifest_path, manifest)
    return manifest


def manifest_field(args):
    value = require_schema(
        read_json(args.manifest), DEPLOYMENT_SCHEMA, "deployment manifest"
    )
    for part in args.path.split("."):
        value = value[part]
    if isinstance(value, (dict, list)):
        print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    else:
        print(value)


def print_database_evidence(args):
    print(json.dumps(sqlite_evidence(args.database), separators=(",", ":")))


def print_non_data_state_evidence(args):
    print(
        json.dumps(
            code_only_state(args.database, args.project_root),
            ensure_ascii=False,
            indent=2,
        )
    )


def write_deployed_commit(args):
    project_root = Path(args.project_root).resolve(strict=True)
    if len(args.commit) != 40 or any(char not in "0123456789abcdef" for char in args.commit):
        raise RuntimeError("deployed commit must be a full lowercase SHA")
    if len(args.expected_current) != 40 or any(
        char not in "0123456789abcdef" for char in args.expected_current
    ):
        raise RuntimeError("expected current commit must be a full lowercase SHA")
    marker = _resolve_without_symlinks(project_root / ".deployed_commit")
    if not marker.is_file():
        raise RuntimeError("deployed commit marker is missing")
    current = marker.read_text(encoding="ascii").strip().lower()
    if current == args.commit:
        return
    if current != args.expected_current:
        raise RuntimeError("deployed commit marker changed unexpectedly")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".deployed_commit.tmp.", dir=project_root
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(args.commit + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, marker)
        _fsync_directory(project_root)
    finally:
        temporary.unlink(missing_ok=True)


def safe_tar_members(archive, allowed_roots):
    allowed = set(allowed_roots)
    members = []
    for member in archive.getmembers():
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts:
            raise RuntimeError(f"unsafe attachment archive path: {member.name}")
        if member.issym() or member.islnk():
            raise RuntimeError(f"attachment archive links are not allowed: {member.name}")
        if not (member.isfile() or member.isdir()):
            raise RuntimeError(
                f"attachment archive contains unsupported entry: {member.name}"
            )
        if not any(path == root or root in path.parents for root in allowed):
            raise RuntimeError(f"unexpected attachment archive path: {member.name}")
        members.append(member)
    return members


def normalize_directory_chain(directory, root, mode):
    directory = Path(directory)
    root = Path(root)
    try:
        relative = directory.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(
            f"directory normalization path escapes root: {directory}"
        ) from exc
    if ".." in relative.parts:
        raise RuntimeError(f"directory normalization path escapes root: {directory}")

    chain = [root]
    current = root
    for part in relative.parts:
        current = current / part
        chain.append(current)
    for current in chain:
        if current.is_symlink() or not current.is_dir():
            raise RuntimeError(f"directory normalization path is unsafe: {current}")
        current.chmod(mode)


def acquire_write_fence(args):
    path = _resolve_without_symlinks(args.path)
    payload = {
        "schema": WRITE_FENCE_SCHEMA,
        "deployment_key": args.deployment_key,
        "target_commit": args.target_commit,
        "acquired_at": utc_now(),
        "reason": "verified deployment in progress",
    }
    try:
        atomic_create_json(path, payload)
    except FileExistsError as exc:
        raise RuntimeError(
            f"another deployment write fence is already active: {path}"
        ) from exc
    return payload


def abandon_write_fence(args):
    path = Path(args.path).resolve()
    if not path.exists():
        return {"abandoned": False, "path": str(path)}
    fence = require_schema(read_json(path), WRITE_FENCE_SCHEMA, "deployment write fence")
    if fence.get("deployment_key") != args.deployment_key:
        raise RuntimeError("write fence abandon refused: deployment key mismatch")
    if fence.get("target_commit") != args.target_commit:
        raise RuntimeError("write fence abandon refused: target commit mismatch")
    path.unlink()
    return {"abandoned": True, "path": str(path)}


def _active_fence_for_manifest(manifest):
    fence_path = _resolve_without_symlinks(manifest["write_fence"]["path"])
    if not fence_path.is_file():
        raise RuntimeError("automatic restore refused: deployment write fence is not active")
    fence = require_schema(
        read_json(fence_path), WRITE_FENCE_SCHEMA, "deployment write fence"
    )
    if fence.get("deployment_key") != manifest.get("deployment_key"):
        raise RuntimeError("automatic restore refused: deployment write fence key mismatch")
    if fence.get("target_commit") != manifest.get("target_commit"):
        raise RuntimeError("automatic restore refused: deployment write fence target mismatch")
    return fence_path, fence


def authorize_write_release(args):
    manifest = require_schema(
        read_json(args.manifest), DEPLOYMENT_SCHEMA, "deployment manifest"
    )
    _active_fence_for_manifest(manifest)
    if not manifest["rollback"].get("automatic_restore_allowed"):
        return manifest
    if manifest.get("status") != "accepted_fenced":
        raise RuntimeError("write release requires fenced health acceptance")
    now = utc_now()
    manifest["rollback"]["automatic_restore_allowed"] = False
    manifest["write_fence"]["release_authorized_at"] = now
    manifest["status"] = "release_authorized"
    manifest["updated_at"] = now
    manifest.setdefault("events", []).append(
        {
            "status": "release_authorized",
            "at": now,
            "detail": "health accepted while fenced; destructive automatic restore disabled",
        }
    )
    atomic_write_json(args.manifest, manifest)
    return manifest


def release_write_fence(args):
    manifest = require_schema(
        read_json(args.manifest), DEPLOYMENT_SCHEMA, "deployment manifest"
    )
    fence_path, _ = _active_fence_for_manifest(manifest)
    mode = args.mode
    if mode == "deployment":
        if manifest["rollback"].get("automatic_restore_allowed"):
            raise RuntimeError("write fence cannot be released before automatic restore is disabled")
        if not manifest["write_fence"].get("release_authorized_at"):
            raise RuntimeError("write fence release has not been authorized")
        status = "succeeded"
        detail = "write fence released after fenced health acceptance"
    elif mode == "rollback":
        non_data = manifest.get("scope", DEPLOYMENT_SCOPE_FULL) in NON_DATA_RELEASE_SCOPES
        rollback_ready_status = "rollback_accepted_fenced" if non_data else "data_restored"
        if not manifest["rollback"].get("restore_scope_verified"):
            raise RuntimeError("rollback fence release requires durable scope verification")
        accepted_statuses = {
            rollback_ready_status,
            "rollback_accepted_fenced",
            "rollback_release_failed",
        }
        if non_data:
            accepted_statuses.add("rollback_code_only")
            accepted_statuses.add("rollback_backend_frontend_static")
        if manifest.get("status") in accepted_statuses:
            now = utc_now()
            manifest["rollback"]["automatic_restore_allowed"] = False
            manifest["write_fence"]["rollback_release_authorized_at"] = now
            manifest["status"] = "rollback_release_authorized"
            manifest["updated_at"] = now
            manifest.setdefault("events", []).append(
                {
                    "status": "rollback_release_authorized",
                    "at": now,
                    "detail": (
                        "rollback scope verified; destructive automatic restore "
                        "disabled before releasing writes"
                    ),
                }
            )
            atomic_write_json(args.manifest, manifest)
        elif manifest.get("status") != "rollback_release_authorized":
            raise RuntimeError("rollback fence release requires restored deployment data")
        if manifest["rollback"].get("automatic_restore_allowed"):
            raise RuntimeError(
                "rollback fence release requires durable automatic-restore disablement"
            )
        if non_data:
            status = (
                "rollback_backend_frontend_static"
                if manifest.get("scope") == DEPLOYMENT_SCOPE_BACKEND_FRONTEND_STATIC
                else "rollback_code_only"
            )
            detail = "write fence released after verified non-data rollback"
        else:
            status = "rollback_data_restored"
            detail = "write fence released after verified rollback data restoration"
    else:
        if manifest.get("scope") not in NON_DATA_RELEASE_SCOPES:
            raise RuntimeError("pre-switch abort is only supported for non-data deployment")
        if manifest.get("status") != "abort_release_authorized":
            raise RuntimeError("code-only abort fence release has not been authorized")
        if manifest["rollback"].get("automatic_restore_allowed"):
            raise RuntimeError("code-only abort was not durably authorized")
        status = "aborted_before_switch"
        detail = "fence released after old-code health acceptance and invariant verification"
    now = utc_now()
    manifest["write_fence"]["released_at"] = now
    manifest["status"] = status
    manifest["updated_at"] = now
    manifest.setdefault("events", []).append(
        {
            "status": status,
            "at": now,
            "detail": detail + "; release authorization durably recorded before removing the write fence",
        }
    )
    atomic_write_json(args.manifest, manifest)
    fence_path.unlink()
    return manifest


def _create_state_archive(path, project_root, roots):
    target = Path(path).resolve()
    temporary = target.with_name(f".{target.name}.tmp.{os.getpid()}")
    try:
        with tarfile.open(temporary, "w:gz") as archive:
            for root in roots:
                source = project_root / Path(*root.parts)
                if not source.exists():
                    continue
                if source.is_symlink():
                    raise RuntimeError(
                        f"failure snapshot source cannot be a symlink: {source}"
                    )
                candidates = [source] if source.is_file() else sorted(source.rglob("*"))
                for candidate in candidates:
                    if candidate.is_symlink():
                        raise RuntimeError(
                            f"failure snapshot source cannot be a symlink: {candidate}"
                        )
                    if not candidate.is_file():
                        continue
                    payload = candidate.read_bytes()
                    relative = candidate.relative_to(source)
                    member_path = root if source.is_file() else root / PurePosixPath(
                        relative.as_posix()
                    )
                    member = tarfile.TarInfo(member_path.as_posix())
                    member.size = len(payload)
                    stat = candidate.stat()
                    member.mode = stat.st_mode & 0o777
                    member.mtime = int(stat.st_mtime)
                    archive.addfile(member, io.BytesIO(payload))
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "path": str(target),
        "sha256": sha256_file(target),
        "size_bytes": target.stat().st_size,
        "inventory": archive_inventory(target, roots),
    }


def capture_failure_state(manifest_path, database, project_root):
    manifest = require_schema(
        read_json(manifest_path), DEPLOYMENT_SCHEMA, "deployment manifest"
    )
    existing = manifest["rollback"].get("failure_snapshot")
    if existing:
        database_evidence = existing["database"]
        if not database_evidence.get("missing"):
            verify_file_evidence(database_evidence, "failure snapshot database")
            for sidecar in database_evidence.get("sidecars", []):
                verify_file_evidence(sidecar, "failure snapshot database sidecar")
        for label in ("attachments", "release"):
            verify_file_evidence(existing[label], f"failure snapshot {label}")
        return existing
    backup_root = Path(manifest["backup"]["database"]["path"]).resolve().parent
    key = manifest["deployment_key"]
    snapshot_root = Path(
        tempfile.mkdtemp(prefix=f"failed_{key}_", dir=backup_root)
    ).resolve()
    try:
        snapshot_root.chmod(0o700)
    except OSError:
        pass
    source_database = Path(database).resolve()
    database_snapshot = snapshot_root / "production.db"
    if source_database.is_file():
        shutil.copy2(source_database, database_snapshot)
        database_evidence = {
            "path": str(database_snapshot),
            "sha256": sha256_file(database_snapshot),
            "size_bytes": database_snapshot.stat().st_size,
        }
        for suffix in ("-wal", "-shm"):
            source_sidecar = Path(str(source_database) + suffix)
            if source_sidecar.is_file():
                sidecar = Path(str(database_snapshot) + suffix)
                shutil.copy2(source_sidecar, sidecar)
                database_evidence.setdefault("sidecars", []).append(
                    {
                        "path": str(sidecar),
                        "sha256": sha256_file(sidecar),
                        "size_bytes": sidecar.stat().st_size,
                    }
                )
        try:
            database_evidence.update(sqlite_evidence(database_snapshot))
        except (RuntimeError, sqlite3.Error) as exc:
            database_evidence["sqlite_error"] = str(exc)
    else:
        database_evidence = {
            "path": str(database_snapshot),
            "missing": True,
            "sqlite_error": f"failed deployment database is missing: {source_database}",
        }
    project_root = Path(project_root).resolve()
    attachment_evidence = _create_state_archive(
        snapshot_root / "attachments.tar.gz",
        project_root,
        MANAGED_ATTACHMENT_ROOTS,
    )
    release_evidence = _create_state_archive(
        snapshot_root / "release.tar.gz",
        project_root,
        MANAGED_RELEASE_ROOTS,
    )
    snapshot = {
        "captured_at": utc_now(),
        "root": str(snapshot_root),
        "database": database_evidence,
        "attachments": attachment_evidence,
        "release": release_evidence,
    }
    manifest["rollback"]["failure_snapshot"] = snapshot
    manifest["updated_at"] = snapshot["captured_at"]
    manifest.setdefault("events", []).append(
        {
            "status": "failure_state_captured",
            "at": snapshot["captured_at"],
            "detail": "failed deployment database, attachments, and release assets preserved",
        }
    )
    atomic_write_json(manifest_path, manifest)
    return snapshot


def restore_archive(archive_path, project_root, managed_roots):
    public_root = project_root / "public"
    managed_paths = [
        (project_root / Path(*root.parts)).resolve() for root in managed_roots
    ]
    for managed in managed_paths:
        if project_root not in managed.parents:
            raise RuntimeError(f"managed restore path escapes project root: {managed}")
        relative = managed.relative_to(project_root)
        cursor = project_root
        for part in relative.parts[:-1]:
            cursor = cursor / part
            if cursor.is_symlink():
                raise RuntimeError(f"managed restore parent cannot be a symlink: {cursor}")

    with tarfile.open(archive_path, "r:gz") as archive:
        members = safe_tar_members(archive, managed_roots)
        for managed in managed_paths:
            if managed.is_symlink() or managed.is_file():
                managed.unlink()
            elif managed.is_dir():
                shutil.rmtree(managed)
        for member in members:
            target = project_root.joinpath(*PurePosixPath(member.name).parts)
            is_public_static = PurePosixPath(member.name).parts[:2] == (
                "public",
                "static",
            )
            if member.isdir():
                target.mkdir(
                    mode=(
                        PUBLIC_STATIC_DIRECTORY_MODE
                        if is_public_static
                        else 0o777
                    ),
                    parents=True,
                    exist_ok=True,
                )
                if is_public_static:
                    normalize_directory_chain(
                        target,
                        public_root,
                        PUBLIC_STATIC_DIRECTORY_MODE,
                    )
                continue
            target.parent.mkdir(
                mode=(
                    PUBLIC_STATIC_DIRECTORY_MODE
                    if is_public_static
                    else 0o777
                ),
                parents=True,
                exist_ok=True,
            )
            if is_public_static:
                normalize_directory_chain(
                    target.parent,
                    public_root,
                    PUBLIC_STATIC_DIRECTORY_MODE,
                )
            source = archive.extractfile(member)
            if source is None:
                raise RuntimeError(
                    f"archive file cannot be read: {member.name}"
                )
            temporary = target.with_name(f".{target.name}.restore.{os.getpid()}")
            try:
                with source, temporary.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
                try:
                    temporary.chmod(
                        PUBLIC_STATIC_FILE_MODE
                        if is_public_static
                        else member.mode & 0o777
                    )
                except OSError:
                    pass
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)


def restore_deployment(args):
    manifest = require_schema(
        read_json(args.manifest), DEPLOYMENT_SCHEMA, "deployment manifest"
    )
    scope = manifest.get("scope", DEPLOYMENT_SCOPE_FULL)
    if (
        not manifest["rollback"].get("automatic_restore_allowed")
        and scope not in NON_DATA_RELEASE_SCOPES
    ):
        raise RuntimeError(
            "automatic restore refused: production writes may have been released"
        )
    _active_fence_for_manifest(manifest)
    capture_failure_state(args.manifest, args.database, args.project_root)
    manifest = require_schema(
        read_json(args.manifest), DEPLOYMENT_SCHEMA, "deployment manifest"
    )
    backup = manifest["backup"]
    database_backup = verify_file_evidence(backup["database"], "database backup")
    attachment_backup = verify_file_evidence(
        backup["attachments"], "attachment backup"
    )
    release_backup = verify_file_evidence(manifest["release"], "release backup")
    observed = sqlite_evidence(database_backup)
    if observed["user_version"] != manifest["source_database_version"]:
        raise RuntimeError("database backup version no longer matches deployment manifest")

    if scope in NON_DATA_RELEASE_SCOPES:
        if manifest["target_database_version"] != manifest["source_database_version"]:
            raise RuntimeError("non-data rollback cannot restore a changed schema version")
        if scope == DEPLOYMENT_SCOPE_BACKEND_FRONTEND_STATIC:
            expected_state = manifest.get("code_only_state")
            observed_state = code_only_state(args.database, args.project_root)
            if (
                not isinstance(expected_state, dict)
                or observed_state["database"] != expected_state["database"]
                or observed_state["attachments"] != expected_state["attachments"]
            ):
                raise RuntimeError(
                    "database or attachment invariant drift detected; refusing static-only rollback"
                )
            release_backup = verify_file_evidence(
                manifest["release"], "previous static release backup"
            )
            restore_archive(
                release_backup, Path(args.project_root).resolve(), MANAGED_RELEASE_ROOTS
            )
            manifest["rollback"]["static_restore_verified"] = True
            manifest["updated_at"] = utc_now()
            manifest.setdefault("events", []).append(
                {
                    "status": "static_rollback_restored",
                    "at": manifest["updated_at"],
                    "detail": "previous static release restored from the verified pre-release archive",
                }
            )
            atomic_write_json(args.manifest, manifest)
        verify_code_only_state(
            argparse.Namespace(
                manifest=args.manifest,
                database=args.database,
                project_root=args.project_root,
            )
        )
        record_verified_rollback_scope(
            args.manifest,
            "code_only_data_preserved",
            (
                "static-only rollback restored the prior frontend release; database and attachments were not restored or modified"
                if scope == DEPLOYMENT_SCOPE_BACKEND_FRONTEND_STATIC
                else "code-only rollback data fingerprints are unchanged; no database, attachment, or frontend restore was performed"
            ),
            observed["user_version"],
        )
        return
    if scope != DEPLOYMENT_SCOPE_FULL:
        raise RuntimeError(f"unsupported deployment scope in rollback: {scope!r}")

    database = Path(args.database).resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    temporary = database.with_name(f".{database.name}.restore.{os.getpid()}")
    try:
        shutil.copy2(database_backup, temporary)
        sqlite_evidence(temporary)
        os.replace(temporary, database)
        for suffix in ("-wal", "-shm"):
            Path(str(database) + suffix).unlink(missing_ok=True)
    finally:
        temporary.unlink(missing_ok=True)

    project_root = Path(args.project_root).resolve()
    restore_archive(attachment_backup, project_root, MANAGED_ATTACHMENT_ROOTS)
    restore_archive(release_backup, project_root, MANAGED_RELEASE_ROOTS)

    record_verified_rollback_scope(
        args.manifest,
        "data_restored",
        "database, attachments, and release assets restored from verified backups",
        observed["user_version"],
    )


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    backup = commands.add_parser("backup")
    backup.add_argument("--output", required=True)
    backup.add_argument("--database", required=True)
    backup.add_argument("--attachments", required=True)
    backup.add_argument("--attachment-root", action="append", default=[])
    backup.set_defaults(handler=create_backup_metadata)

    verify = commands.add_parser("verify-backup")
    verify.add_argument("--metadata", required=True)
    verify.set_defaults(handler=lambda args: verify_backup_metadata(args.metadata))

    prepare = commands.add_parser("prepare")
    prepare.add_argument("--output", required=True)
    prepare.add_argument("--backup-metadata", required=True)
    prepare.add_argument("--release-backup", required=True)
    prepare.add_argument("--target-static-backup")
    prepare.add_argument("--deployment-key", required=True)
    prepare.add_argument("--before-commit", required=True)
    prepare.add_argument("--target-commit", required=True)
    prepare.add_argument("--target-database-version", type=int)
    prepare.add_argument("--write-fence", required=True)
    prepare.add_argument(
        "--scope",
        choices=(
            DEPLOYMENT_SCOPE_FULL,
            DEPLOYMENT_SCOPE_CODE_ONLY,
            DEPLOYMENT_SCOPE_BACKEND_FRONTEND_STATIC,
        ),
        default=DEPLOYMENT_SCOPE_FULL,
    )
    prepare.set_defaults(handler=prepare_deployment_manifest)

    capture_code_state = commands.add_parser("capture-code-only-state")
    capture_code_state.add_argument("--manifest", required=True)
    capture_code_state.add_argument("--database", required=True)
    capture_code_state.add_argument("--project-root", required=True)
    capture_code_state.set_defaults(handler=capture_code_only_state)

    verify_code_state = commands.add_parser("verify-code-only-state")
    verify_code_state.add_argument("--manifest", required=True)
    verify_code_state.add_argument("--database", required=True)
    verify_code_state.add_argument("--project-root", required=True)
    verify_code_state.set_defaults(handler=verify_code_only_state)

    begin_code_only = commands.add_parser("begin-code-only")
    begin_code_only.add_argument("--output", required=True)
    begin_code_only.add_argument("--deployment-key", required=True)
    begin_code_only.add_argument("--before-commit", required=True)
    begin_code_only.add_argument("--target-commit", required=True)
    begin_code_only.add_argument("--source-database-version", required=True, type=int)
    begin_code_only.add_argument("--target-database-version", required=True, type=int)
    begin_code_only.add_argument("--write-fence", required=True)
    begin_code_only.add_argument(
        "--scope",
        choices=tuple(sorted(NON_DATA_RELEASE_SCOPES)),
        default=DEPLOYMENT_SCOPE_CODE_ONLY,
    )
    begin_code_only.set_defaults(handler=begin_code_only_deployment)

    record_fence = commands.add_parser("record-code-only-fence")
    record_fence.add_argument("--manifest", required=True)
    record_fence.set_defaults(handler=record_code_only_fence)

    authorize_abort = commands.add_parser("authorize-code-only-abort")
    authorize_abort.add_argument("--manifest", required=True)
    authorize_abort.add_argument("--database", required=True)
    authorize_abort.add_argument("--project-root", required=True)
    authorize_abort.add_argument("--current-commit", required=True)
    authorize_abort.set_defaults(handler=authorize_code_only_abort)

    authorize_code_rollback = commands.add_parser(
        "authorize-code-only-rollback-release"
    )
    authorize_code_rollback.add_argument("--manifest", required=True)
    authorize_code_rollback.add_argument("--database", required=True)
    authorize_code_rollback.add_argument("--project-root", required=True)
    authorize_code_rollback.add_argument("--current-commit", required=True)
    authorize_code_rollback.set_defaults(handler=authorize_code_only_rollback_release)

    database_evidence = commands.add_parser("database-evidence")
    database_evidence.add_argument("--database", required=True)
    database_evidence.set_defaults(handler=print_database_evidence)

    state_evidence = commands.add_parser("non-data-state-evidence")
    state_evidence.add_argument("--database", required=True)
    state_evidence.add_argument("--project-root", required=True)
    state_evidence.set_defaults(handler=print_non_data_state_evidence)

    deployed_marker = commands.add_parser("write-commit-marker")
    deployed_marker.add_argument("--project-root", required=True)
    deployed_marker.add_argument("--expected-current", required=True)
    deployed_marker.add_argument("--commit", required=True)
    deployed_marker.set_defaults(handler=write_deployed_commit)

    update = commands.add_parser("update")
    update.add_argument("--manifest", required=True)
    update.add_argument("--status", required=True)
    update.add_argument("--detail", default="")
    update.add_argument("--database-version", type=int)
    update.set_defaults(handler=update_manifest)

    field = commands.add_parser("field")
    field.add_argument("--manifest", required=True)
    field.add_argument("--path", required=True)
    field.set_defaults(handler=manifest_field)

    restore = commands.add_parser("restore")
    restore.add_argument("--manifest", required=True)
    restore.add_argument("--database", required=True)
    restore.add_argument("--project-root", required=True)
    restore.set_defaults(handler=restore_deployment)

    acquire_fence = commands.add_parser("acquire-fence")
    acquire_fence.add_argument("--path", required=True)
    acquire_fence.add_argument("--deployment-key", required=True)
    acquire_fence.add_argument("--target-commit", required=True)
    acquire_fence.set_defaults(handler=acquire_write_fence)

    abandon_fence = commands.add_parser("abandon-fence")
    abandon_fence.add_argument("--path", required=True)
    abandon_fence.add_argument("--deployment-key", required=True)
    abandon_fence.add_argument("--target-commit", required=True)
    abandon_fence.set_defaults(handler=abandon_write_fence)

    authorize_release = commands.add_parser("authorize-release")
    authorize_release.add_argument("--manifest", required=True)
    authorize_release.set_defaults(handler=authorize_write_release)

    release_fence = commands.add_parser("release-fence")
    release_fence.add_argument("--manifest", required=True)
    release_fence.add_argument(
        "--mode", required=True, choices=("deployment", "rollback", "abort")
    )
    release_fence.set_defaults(handler=release_write_fence)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.handler(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
