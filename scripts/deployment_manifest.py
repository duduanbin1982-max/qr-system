#!/usr/bin/env python3
"""Create, verify, and restore atomic deployment evidence manifests."""

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import tarfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


MANAGED_ATTACHMENT_ROOTS = (
    PurePosixPath("data/attachments"),
    PurePosixPath("uploads/employee_docs"),
)
MANAGED_RELEASE_ROOTS = (PurePosixPath("public/static"),)

BACKUP_SCHEMA = "qr-system-backup-evidence/v1"
DEPLOYMENT_SCHEMA = "qr-system-deployment/v1"


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


def verify_file_evidence(evidence, label):
    path = Path(evidence["path"]).resolve()
    if not path.is_file():
        raise RuntimeError(f"{label} does not exist: {path}")
    actual = sha256_file(path)
    if actual != evidence["sha256"]:
        raise RuntimeError(f"{label} checksum mismatch: {actual} != {evidence['sha256']}")
    return path


def create_backup_metadata(args):
    database = Path(args.database).resolve()
    attachments = Path(args.attachments).resolve()
    evidence = sqlite_evidence(database)
    payload = {
        "schema": BACKUP_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
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
        },
    }
    atomic_write_json(args.output, payload)
    return payload


def verify_backup_metadata(path):
    payload = require_schema(read_json(path), BACKUP_SCHEMA, "backup metadata")
    database = verify_file_evidence(payload["database"], "database backup")
    attachments = verify_file_evidence(payload["attachments"], "attachment backup")
    with tarfile.open(attachments, "r:gz") as archive:
        safe_tar_members(archive, MANAGED_ATTACHMENT_ROOTS)
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
    payload = {
        "schema": DEPLOYMENT_SCHEMA,
        "deployment_key": args.deployment_key,
        "created_at": datetime.now(timezone.utc).isoformat(),
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
        "events": [],
    }
    atomic_write_json(args.output, payload)
    return payload


def update_manifest(args):
    payload = require_schema(
        read_json(args.manifest), DEPLOYMENT_SCHEMA, "deployment manifest"
    )
    payload["status"] = args.status
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
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
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.handler(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
