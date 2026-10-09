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

BACKUP_SCHEMA_V1 = "qr-system-backup-evidence/v1"
BACKUP_SCHEMA = "qr-system-backup-evidence/v2"
DEPLOYMENT_SCHEMA = "qr-system-deployment/v2"
WRITE_FENCE_SCHEMA = "qr-system-write-fence/v1"


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


def atomic_write_json(path, payload):
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp.{os.getpid()}")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


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
    atomic_write_json(args.output, payload)
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
    if output.exists():
        raise RuntimeError(f"deployment manifest already exists: {output}")
    backup = verify_backup_metadata(args.backup_metadata)
    release_backup = Path(args.release_backup).resolve()
    if not release_backup.is_file():
        raise RuntimeError(f"release backup does not exist: {release_backup}")
    with tarfile.open(release_backup, "r:gz") as archive:
        safe_tar_members(archive, MANAGED_RELEASE_ROOTS)
    write_fence_path = Path(args.write_fence).resolve()
    write_fence = require_schema(
        read_json(write_fence_path), WRITE_FENCE_SCHEMA, "deployment write fence"
    )
    if write_fence.get("deployment_key") != args.deployment_key:
        raise RuntimeError("deployment write fence key does not match deployment manifest")
    if write_fence.get("target_commit") != args.target_commit:
        raise RuntimeError("deployment write fence target does not match deployment manifest")
    payload = {
        "schema": DEPLOYMENT_SCHEMA,
        "deployment_key": args.deployment_key,
        "created_at": utc_now(),
        "status": "prepared",
        "before_commit": args.before_commit,
        "target_commit": args.target_commit,
        "source_database_version": backup["database"]["user_version"],
        "target_database_version": args.target_database_version,
        "backup": backup,
        "release": {
            "path": str(release_backup),
            "sha256": sha256_file(release_backup),
            "size_bytes": release_backup.stat().st_size,
        },
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
            "path": str(write_fence_path),
            "acquired_at": write_fence["acquired_at"],
            "release_authorized_at": None,
            "released_at": None,
        },
        "rollback": {
            "automatic_restore_allowed": True,
            "failure_snapshot": None,
        },
        "events": [],
    }
    atomic_write_json(args.output, payload)
    return payload


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


def acquire_write_fence(args):
    path = Path(args.path).resolve()
    if path.exists():
        require_schema(read_json(path), WRITE_FENCE_SCHEMA, "deployment write fence")
        raise RuntimeError(f"another deployment write fence is already active: {path}")
    payload = {
        "schema": WRITE_FENCE_SCHEMA,
        "deployment_key": args.deployment_key,
        "target_commit": args.target_commit,
        "acquired_at": utc_now(),
        "reason": "verified deployment in progress",
    }
    atomic_write_json(path, payload)
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
    fence_path = Path(manifest["write_fence"]["path"]).resolve()
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
    else:
        if manifest.get("status") != "data_restored":
            raise RuntimeError("rollback fence release requires restored deployment data")
        manifest["rollback"]["automatic_restore_allowed"] = False
        status = "rollback_data_restored"
        detail = "write fence released after verified rollback data restoration"
    fence_path.unlink()
    now = utc_now()
    manifest["write_fence"]["released_at"] = now
    manifest["status"] = status
    manifest["updated_at"] = now
    manifest.setdefault("events", []).append(
        {"status": status, "at": now, "detail": detail}
    )
    atomic_write_json(args.manifest, manifest)
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
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
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
                    temporary.chmod(member.mode & 0o777)
                except OSError:
                    pass
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)


def restore_deployment(args):
    manifest = require_schema(
        read_json(args.manifest), DEPLOYMENT_SCHEMA, "deployment manifest"
    )
    if not manifest["rollback"].get("automatic_restore_allowed"):
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

    update_args = argparse.Namespace(
        manifest=args.manifest,
        status="data_restored",
        detail="database, attachments, and release assets restored from verified backups",
        database_version=observed["user_version"],
    )
    update_manifest(update_args)


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
    prepare.add_argument("--deployment-key", required=True)
    prepare.add_argument("--before-commit", required=True)
    prepare.add_argument("--target-commit", required=True)
    prepare.add_argument("--target-database-version", required=True, type=int)
    prepare.add_argument("--write-fence", required=True)
    prepare.set_defaults(handler=prepare_deployment_manifest)

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
        "--mode", required=True, choices=("deployment", "rollback")
    )
    release_fence.set_defaults(handler=release_write_fence)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.handler(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
