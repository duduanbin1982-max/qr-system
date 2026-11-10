#!/usr/bin/env python3
"""Validate and execute the reviewed payroll-settlement V96->V97 migration."""

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from pathlib import Path

from scripts import backend_frontend_static_release as static_release
from scripts import code_only_release, deployment_manifest


BASELINE_COMMIT = "2ffa312769411ee97bf915d18e2154a25b4f109b"
TARGET_COMMIT = "c369cf212a2054e14cff0d17b76e5501d26a0b06"
SOURCE_SCHEMA = 96
TARGET_SCHEMA = 97
MIGRATION_TRANSITIONS = {
    "modules/migration_catalog.py": (
        ("100644", "blob", "3ed236fe10587ef545c69db97027323155cf3479"),
        ("100644", "blob", "b4459cb921d361b15ba5e5fab71ff0ab6d0a9be0"),
    ),
    "modules/migration_payroll_settlement.py": (
        None,
        ("100644", "blob", "94963ac4ede3248494875185454ec386cf12dad3"),
    ),
}
REQUIRED_TABLES = {
    "payroll_settlements",
    "payroll_export_batches",
    "payroll_export_items",
    "payroll_receipt_batches",
    "payroll_receipt_items",
    "payroll_reconciliation_runs",
    "payroll_reconciliation_items",
    "payroll_reconciliation_resolutions",
    "payroll_close_records",
}
REQUIRED_TRIGGERS = {
    "prevent_closed_payroll_export_batch_insert",
    "prevent_closed_payroll_receipt_batch_insert",
    "prevent_closed_payroll_reconciliation_run_insert",
    "protect_payroll_export_item_update",
    "protect_payroll_close_record_delete",
    "protect_closed_payroll_settlement",
    "prevent_payroll_settlement_delete",
}
MIN_FREE_BYTES = 2 * 1024 * 1024 * 1024
TOOL_CHANGE_PATHS = {
    "docs/deployment/payroll-settlement-v97-release.md",
    "scripts/backend_frontend_static_release.py",
    "scripts/bootstrap_payroll_settlement_v97_release.py",
    "scripts/deploy-payroll-settlement-v97.sh",
    "scripts/deployment_manifest.py",
    "scripts/payroll_settlement_v97_release.py",
    "scripts/rollback-deployment.sh",
    "tests/test_payroll_settlement_v97_release.py",
}


def _git(root, *args, check=True):
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if check and result.returncode:
        raise RuntimeError(
            f"git {' '.join(args)} failed: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def _tree_entry(repository, commit, path):
    return static_release._tree_entry(repository, commit, path)


def _assert_clean(root, *, allow_untracked_data):
    output = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    unexpected = []
    for entry in output.split(b"\0"):
        if not entry:
            continue
        status = entry[:2]
        path = os.fsdecode(entry[3:])
        if allow_untracked_data and status == b"??" and (path == "data" or path.startswith("data/")):
            continue
        unexpected.append(f"{status.decode(errors='replace')} {path}")
    if unexpected:
        raise RuntimeError("worktree is not clean: " + "; ".join(unexpected[:10]))


def _json_value(value):
    if isinstance(value, bytes):
        return {"bytes_sha256": hashlib.sha256(value).hexdigest(), "size": len(value)}
    return value


def _table_facts(database, table_names=None):
    facts = {}
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        names = table_names or [
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        for name in names:
            quoted = name.replace('"', '""')
            digest = hashlib.sha256()
            count = 0
            for row in db.execute(f'SELECT * FROM "{quoted}"'):
                encoded = json.dumps(
                    [_json_value(value) for value in row],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                digest.update(encoded)
                digest.update(b"\n")
                count += 1
            facts[name] = {"row_count": count, "sha256": digest.hexdigest()}
    return facts


def _schema_acceptance(database, expected_version):
    evidence = deployment_manifest.sqlite_evidence(database)
    if evidence["user_version"] != expected_version:
        raise RuntimeError(
            f"schema mismatch: expected V{expected_version}, found V{evidence['user_version']}"
        )
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)) as db:
        tables = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        triggers = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            )
        }
    missing_tables = sorted(REQUIRED_TABLES - tables)
    missing_triggers = sorted(REQUIRED_TRIGGERS - triggers)
    if missing_tables or missing_triggers:
        raise RuntimeError(
            f"V97 acceptance missing tables={missing_tables} triggers={missing_triggers}"
        )
    return {
        **evidence,
        "required_tables": sorted(REQUIRED_TABLES),
        "required_triggers": sorted(REQUIRED_TRIGGERS),
    }


def _run_target_migrations(target_root, database):
    command = [
        sys.executable,
        "-c",
        (
            "import sqlite3,sys; "
            "sys.path.insert(0, sys.argv[1]); "
            "from modules.application.operations_facade import OperationsFacade; "
            "db=sqlite3.connect(sys.argv[2]); db.execute('PRAGMA foreign_keys=ON'); "
            "version=OperationsFacade.migrate_database(db); "
            "stored=db.execute('PRAGMA user_version').fetchone()[0]; "
            "db.close(); print(f'{version}:{stored}')"
        ),
        str(target_root),
        str(database),
    ]
    result = subprocess.run(
        command,
        cwd=target_root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTHONPATH": str(target_root)},
    )
    if result.returncode:
        raise RuntimeError("target migration failed: " + result.stderr.strip())
    result_line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    if not result_line.endswith(f":{TARGET_SCHEMA}"):
        raise RuntimeError("target migration returned unexpected version: " + result.stdout.strip())


def _copy_database(source, target):
    source = Path(source).resolve(strict=True)
    target = Path(target)
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
        original.execute("PRAGMA query_only=ON")
        with closing(sqlite3.connect(target)) as replica:
            original.backup(replica)
            replica.commit()


def run_replica_trial(repository, target_commit, database):
    source = deployment_manifest.sqlite_evidence(database)
    if source["user_version"] != SOURCE_SCHEMA:
        raise RuntimeError(
            f"replica trial requires production V{SOURCE_SCHEMA}, found V{source['user_version']}"
        )
    with tempfile.TemporaryDirectory(prefix="qr-payroll-v97-replica-") as directory:
        root = Path(directory)
        target_root = root / "target"
        subprocess.run(
            ["git", "-C", str(repository), "worktree", "add", "--quiet", "--detach", str(target_root), target_commit],
            check=True,
        )
        try:
            replica = root / "production-v97.db"
            _copy_database(database, replica)
            existing_names = sorted(_table_facts(replica))
            facts_before = _table_facts(replica, existing_names)
            _run_target_migrations(target_root, replica)
            acceptance = _schema_acceptance(replica, TARGET_SCHEMA)
            facts_after = _table_facts(replica, existing_names)
            if facts_after != facts_before:
                changed = sorted(
                    name for name in existing_names if facts_before[name] != facts_after[name]
                )
                raise RuntimeError(
                    "V97 migration changed pre-existing table facts: " + ", ".join(changed)
                )
            all_facts = _table_facts(replica)
            _run_target_migrations(target_root, replica)
            if _table_facts(replica) != all_facts:
                raise RuntimeError("V97 migration is not idempotent on a migrated replica")
            _schema_acceptance(replica, TARGET_SCHEMA)
            return {
                "source": source,
                "target": acceptance,
                "preserved_existing_table_count": len(existing_names),
                "source_database_unchanged": deployment_manifest.sqlite_evidence(database) == source,
            }
        finally:
            subprocess.run(
                ["git", "-C", str(repository), "worktree", "remove", "--force", str(target_root)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )


def validate_release(tool_root, project_root, database, before_commit, target_commit, *, replica_trial=True):
    tool = Path(tool_root).resolve(strict=True)
    project = Path(project_root).resolve(strict=True)
    database = Path(database).resolve(strict=True)
    if (before_commit, target_commit) != (BASELINE_COMMIT, TARGET_COMMIT):
        raise RuntimeError("payroll V97 release requires the reviewed baseline and target")
    if tool == project or tool in project.parents or project in tool.parents:
        raise RuntimeError("production and release-tool worktrees must be separate")
    if _git(project, "rev-parse", "HEAD") != before_commit:
        raise RuntimeError("production checkout does not match the reviewed baseline")
    marker = project / ".deployed_commit"
    if marker.is_symlink() or not marker.is_file() or marker.read_text(encoding="ascii").strip() != before_commit:
        raise RuntimeError("production deployed marker does not match the reviewed baseline")
    _assert_clean(project, allow_untracked_data=True)
    _assert_clean(tool, allow_untracked_data=False)
    _git(tool, "cat-file", "-e", f"{target_commit}^{{commit}}")
    tool_head = _git(tool, "rev-parse", "HEAD")
    if subprocess.run(
        ["git", "-C", str(tool), "merge-base", "--is-ancestor", target_commit, tool_head]
    ).returncode:
        raise RuntimeError("release-tool commit does not contain the reviewed target")
    if subprocess.run(
        ["git", "-C", str(tool), "merge-base", "--is-ancestor", before_commit, target_commit]
    ).returncode:
        raise RuntimeError("target is not based on the production baseline")
    tool_changes = set(code_only_release._changed_paths(tool, target_commit, tool_head))
    if tool_changes != TOOL_CHANGE_PATHS:
        raise RuntimeError(
            "release-tool commit contains an unexpected path set: "
            + ", ".join(sorted(tool_changes ^ TOOL_CHANGE_PATHS))
        )

    changed = code_only_release._changed_paths(tool, before_commit, target_commit)
    for path, (expected_before, expected_target) in MIGRATION_TRANSITIONS.items():
        if _tree_entry(tool, before_commit, path) != expected_before or _tree_entry(tool, target_commit, path) != expected_target:
            raise RuntimeError(f"migration mode/blob transition mismatch: {path}")
    observed_migrations = {
        path for path in changed if path.startswith("modules/migration")
    }
    if observed_migrations != set(MIGRATION_TRANSITIONS):
        raise RuntimeError(
            "release contains an unreviewed migration path: "
            + ", ".join(sorted(observed_migrations ^ set(MIGRATION_TRANSITIONS)))
        )
    non_migration = [path for path in changed if path not in MIGRATION_TRANSITIONS]
    static_release._validate_paths(tool, before_commit, target_commit, non_migration)
    for path in ("package.json", "package-lock.json", ".nvmrc", ".node-version", ".npmrc", "vite.config.js"):
        static_release._assert_same_blob(tool, before_commit, target_commit, path)
    if code_only_release._tracked_data_paths(tool, before_commit) or code_only_release._tracked_data_paths(tool, target_commit):
        raise RuntimeError("migration release refuses tracked production data")

    database_evidence = deployment_manifest.sqlite_evidence(database)
    if database_evidence["user_version"] != SOURCE_SCHEMA:
        raise RuntimeError(
            f"production schema must be V{SOURCE_SCHEMA}, found V{database_evidence['user_version']}"
        )
    target_schema = code_only_release._target_schema_version(tool)
    if target_schema != TARGET_SCHEMA:
        raise RuntimeError(f"reviewed target must declare V{TARGET_SCHEMA}, found V{target_schema}")
    attachments = deployment_manifest.managed_path_inventory(
        project, deployment_manifest.MANAGED_ATTACHMENT_ROOTS
    )
    release = deployment_manifest.managed_path_inventory(
        project, deployment_manifest.MANAGED_RELEASE_ROOTS
    )
    free_bytes = shutil.disk_usage(project).free
    required_free = max(
        MIN_FREE_BYTES,
        database.stat().st_size * 4
        + attachments["total_bytes"] * 2
        + release["total_bytes"] * 3,
    )
    if free_bytes < required_free:
        raise RuntimeError(
            f"insufficient free space: need {required_free} bytes, found {free_bytes}"
        )

    trial = run_replica_trial(tool, target_commit, database) if replica_trial else None
    return {
        "scope": "backend_frontend_migration",
        "before_commit": before_commit,
        "target_commit": target_commit,
        "tool_commit": tool_head,
        "changed_paths": changed,
        "database": database_evidence,
        "source_schema_version": SOURCE_SCHEMA,
        "target_schema_version": TARGET_SCHEMA,
        "free_bytes": free_bytes,
        "required_free_bytes": required_free,
        "managed_attachments": attachments,
        "managed_release": release,
        "replica_trial": trial,
        "operations": {
            "database_migration": True,
            "attachment_migration": False,
            "frontend_publish": True,
            "service_restart": True,
        },
    }


def migrate_production(target_root, database, manifest_path, project_root):
    manifest = deployment_manifest.require_schema(
        deployment_manifest.read_json(manifest_path),
        deployment_manifest.DEPLOYMENT_SCHEMA,
        "deployment manifest",
    )
    if manifest.get("scope") != deployment_manifest.DEPLOYMENT_SCOPE_BACKEND_FRONTEND_MIGRATION:
        raise RuntimeError("production migration requires the migration deployment scope")
    deployment_manifest._active_fence_for_manifest(manifest)
    if manifest.get("status") != "backup_verified":
        raise RuntimeError("production migration requires verified final backups")
    if manifest.get("before_commit") != BASELINE_COMMIT or manifest.get("target_commit") != TARGET_COMMIT:
        raise RuntimeError("deployment manifest does not match the reviewed transition")
    project = Path(project_root).resolve(strict=True)
    if _git(project, "rev-parse", "HEAD") != TARGET_COMMIT:
        raise RuntimeError("production checkout must be switched to the target before migration")
    marker = project / ".deployed_commit"
    if marker.read_text(encoding="ascii").strip() != TARGET_COMMIT:
        raise RuntimeError("production marker must be switched to the target before migration")
    if deployment_manifest.sqlite_evidence(database)["user_version"] != SOURCE_SCHEMA:
        raise RuntimeError("production database is not at the reviewed V96 baseline")
    _run_target_migrations(Path(target_root).resolve(strict=True), database)
    return _schema_acceptance(database, TARGET_SCHEMA)


def verify_attachments(project_root, backup_metadata):
    metadata = deployment_manifest.verify_backup_metadata(backup_metadata)
    observed = deployment_manifest.managed_path_inventory(
        project_root, deployment_manifest.MANAGED_ATTACHMENT_ROOTS
    )
    expected = metadata["attachments"]["inventory"]
    if deployment_manifest.inventory_content_identity(
        observed
    ) != deployment_manifest.inventory_content_identity(expected):
        raise RuntimeError("managed attachments changed during the migration release")
    return observed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preflight = commands.add_parser("preflight")
    preflight.add_argument("--tool-root", required=True)
    preflight.add_argument("--project-root", required=True)
    preflight.add_argument("--database", required=True)
    preflight.add_argument("--before-commit", required=True)
    preflight.add_argument("--target-commit", required=True)
    preflight.add_argument("--skip-replica-trial", action="store_true")
    migrate = commands.add_parser("migrate")
    migrate.add_argument("--target-root", required=True)
    migrate.add_argument("--database", required=True)
    migrate.add_argument("--manifest", required=True)
    migrate.add_argument("--project-root", required=True)
    acceptance = commands.add_parser("acceptance")
    acceptance.add_argument("--database", required=True)
    attachments = commands.add_parser("verify-attachments")
    attachments.add_argument("--project-root", required=True)
    attachments.add_argument("--backup-metadata", required=True)
    args = parser.parse_args(argv)
    if args.command == "preflight":
        result = validate_release(
            args.tool_root,
            args.project_root,
            args.database,
            args.before_commit,
            args.target_commit,
            replica_trial=not args.skip_replica_trial,
        )
    elif args.command == "migrate":
        result = migrate_production(
            args.target_root, args.database, args.manifest, args.project_root
        )
    elif args.command == "acceptance":
        result = _schema_acceptance(args.database, TARGET_SCHEMA)
    else:
        result = verify_attachments(args.project_root, args.backup_metadata)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
