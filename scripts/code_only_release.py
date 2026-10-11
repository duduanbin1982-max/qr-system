#!/usr/bin/env python3
"""Read-only validation for the controlled code-only production release path."""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

try:
    from .deployment_manifest import sqlite_evidence
except ImportError:  # Executed directly by the production shell entry point.
    from deployment_manifest import sqlite_evidence


SHA_RE = re.compile(r"^[0-9a-f]{40}$")
PROTECTED_RUNTIME_PATHS = (
    "modules/app.py",
    "modules/config.py",
    "modules/app_extensions.py",
    "modules/db.py",
    "modules/deployment_write_fence.py",
    "modules/runtime_version.py",
)


def _git(repository, *args, check=True):
    result = subprocess.run(
        ["git", "-C", str(repository), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return result


def _validate_sha(value, label):
    if not SHA_RE.fullmatch(value or ""):
        raise RuntimeError(f"{label} must be a full 40-character lowercase SHA")


def _changed_paths(repository, before_commit, target_commit):
    result = _git(
        repository,
        "diff",
        "--name-only",
        "-z",
        before_commit,
        target_commit,
        "--",
    )
    return sorted(
        os.fsdecode(path)
        for path in result.stdout.split(b"\0")
        if path
    )


def _tracked_data_paths(repository, commit):
    result = _git(repository, "ls-tree", "-r", "--name-only", "-z", commit, "--", "data")
    return [os.fsdecode(path) for path in result.stdout.split(b"\0") if path]


def _assert_clean_except_data(repository, *, allow_data):
    result = _git(repository, "status", "--porcelain=v1", "-z", "--untracked-files=normal")
    unexpected = []
    for entry in result.stdout.split(b"\0"):
        if not entry:
            continue
        status = entry[:2]
        path = os.fsdecode(entry[3:])
        if allow_data and status == b"??" and (path == "data" or path.startswith("data/")):
            continue
        unexpected.append(f"{status.decode('ascii', errors='replace')} {path}")
    if unexpected:
        raise RuntimeError(
            f"worktree is not clean{'; only untracked data/ is allowed' if allow_data else ''}: "
            + ", ".join(unexpected[:10])
        )


def _path_is_forbidden(path):
    normalized = PurePosixPath(path).as_posix()
    parts = PurePosixPath(normalized).parts
    lower = normalized.lower()
    basename = parts[-1].lower() if parts else ""
    if not parts:
        return True
    if parts[0] in {"data", "frontend", "public", "uploads", "dist"}:
        return True
    if normalized in {
        "deploy.sh",
        "scripts/deploy.sh",
        "gunicorn.conf.py",
        "package.json",
        "package-lock.json",
        "vite.config.js",
        "modules/app.py",
        "modules/config.py",
        "modules/app_extensions.py",
        "modules/db.py",
        "modules/deployment_write_fence.py",
        "modules/runtime_version.py",
        "modules/migrations.py",
        "modules/migration_catalog.py",
        "modules/migration_planning.py",
    }:
        return True
    if (
        ("migration" in lower or (parts[0] == "scripts" and "migrate" in basename))
        and parts[0] != "tests"
        and normalized != "modules/services/performance_history_migration_service.py"
    ):
        return True
    if parts[0] in {"migrations", "alembic", "deploy", "systemd"}:
        return True
    if basename in {
        ".env",
        "pyproject.toml",
        "requirements.txt",
        "requirements-prod.txt",
        "requirements-dev.txt",
        "poetry.lock",
        "pdm.lock",
        "uv.lock",
    } or basename.startswith("requirements-"):
        return True
    if lower.startswith("public/") or lower.startswith("frontend/"):
        return True
    return False


def _assert_runtime_fence_unchanged(repository, before_commit, target_commit):
    for path in PROTECTED_RUNTIME_PATHS:
        before = _git(repository, "rev-parse", f"{before_commit}:{path}", check=False)
        target = _git(repository, "rev-parse", f"{target_commit}:{path}", check=False)
        if before.returncode or target.returncode or before.stdout.strip() != target.stdout.strip():
            raise RuntimeError(f"code-only release cannot change write-fence runtime: {path}")


def _target_schema_version(target_root):
    result = subprocess.run(
        [sys.executable, "-c", "from modules.migrations import LATEST_VERSION; print(LATEST_VERSION)"],
        cwd=target_root,
        env={**os.environ, "PYTHONPATH": str(target_root)},
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(
            "cannot read target schema version without running migrations: "
            + result.stderr.strip()
        )
    try:
        return int(result.stdout.strip())
    except ValueError as exc:
        raise RuntimeError("target schema version is not an integer") from exc


def validate_code_only_release(tool_root, project_root, database, before_commit, target_commit):
    tool_root = Path(tool_root).resolve(strict=True)
    project_root = Path(project_root).resolve(strict=True)
    database_input = Path(database)
    if database_input.is_symlink():
        raise RuntimeError("production database path cannot be a symlink")
    database = database_input.resolve(strict=True)
    try:
        database.relative_to(project_root / "data")
    except ValueError as exc:
        raise RuntimeError("production database must remain under project-root/data/") from exc

    _validate_sha(before_commit, "expected before commit")
    _validate_sha(target_commit, "target commit")
    if before_commit == target_commit:
        raise RuntimeError("target commit must differ from the current production commit")

    tool_head = _git(tool_root, "rev-parse", "--verify", "HEAD").stdout.decode().strip()
    if tool_head != target_commit:
        raise RuntimeError("release tool worktree HEAD must equal the target commit")
    _assert_clean_except_data(tool_root, allow_data=False)
    _assert_clean_except_data(project_root, allow_data=True)

    production_head = _git(project_root, "rev-parse", "--verify", "HEAD").stdout.decode().strip()
    if production_head != before_commit:
        raise RuntimeError("production checkout HEAD does not match the confirmed before commit")
    marker = project_root / ".deployed_commit"
    if not marker.is_file() or marker.is_symlink():
        raise RuntimeError("production .deployed_commit marker is missing or unsafe")
    if marker.read_text(encoding="ascii").strip().lower() != before_commit:
        raise RuntimeError("production .deployed_commit does not match the confirmed before commit")
    _git(project_root, "cat-file", "-e", f"{target_commit}^{{commit}}")

    tracked_data = {
        "before": _tracked_data_paths(project_root, before_commit),
        "target": _tracked_data_paths(project_root, target_commit),
    }
    if any(tracked_data.values()):
        raise RuntimeError("code-only release refuses commits that track production data/")

    changed = _changed_paths(tool_root, before_commit, target_commit)
    if not changed:
        raise RuntimeError("target commit contains no changes from production baseline")
    _assert_runtime_fence_unchanged(tool_root, before_commit, target_commit)
    forbidden = [path for path in changed if _path_is_forbidden(path)]
    if forbidden:
        raise RuntimeError("code-only release contains out-of-scope paths: " + ", ".join(forbidden))

    database_evidence = sqlite_evidence(database)
    target_schema_version = _target_schema_version(tool_root)
    if target_schema_version != database_evidence["user_version"]:
        raise RuntimeError(
            "code-only release schema mismatch: target expects "
            f"V{target_schema_version}, production is V{database_evidence['user_version']}"
        )

    return {
        "tool_root": str(tool_root),
        "project_root": str(project_root),
        "before_commit": before_commit,
        "target_commit": target_commit,
        "changed_paths": changed,
        "database": database_evidence,
        "target_schema_version": target_schema_version,
        "tracked_data": tracked_data,
        "production_worktree": "clean_except_untracked_data",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--tool-root", required=True)
    preflight.add_argument("--project-root", required=True)
    preflight.add_argument("--database", required=True)
    preflight.add_argument("--before-commit", required=True)
    preflight.add_argument("--target-commit", required=True)
    args = parser.parse_args(argv)
    if args.command == "preflight":
        result = validate_code_only_release(
            args.tool_root,
            args.project_root,
            args.database,
            args.before_commit,
            args.target_commit,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
