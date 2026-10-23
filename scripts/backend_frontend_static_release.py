#!/usr/bin/env python3
"""Validate a backend plus built-static release without data migrations."""

import argparse
import ctypes
import json
import os
import subprocess
import tarfile
from pathlib import Path, PurePosixPath

from scripts import code_only_release, deployment_manifest
from scripts.deployment_manifest import sqlite_evidence
from scripts.deployment_manifest import MANAGED_RELEASE_ROOTS, safe_tar_members


ALLOWED_ROOTS = {"modules", "frontend", "tests", "docs"}
ALLOWED_FRONTEND_PATHS = ("frontend/src/", "frontend/index.html")
# Reviewed support changes accompanying this production baseline only. These
# entries authorize exact Git objects, not a general scripts/tests exception.
SUPPORT_BASELINE = "c0448bfc945bcfa9c09e94ab1d4bf11f93a3c022"
PINNED_SUPPORT_TRANSITIONS = {
    "frontend/tests/unit/inventory-view-state.spec.js": (
        ("100644", "blob", "6c41cf45757bd91eba126dcc002cc4c4c353f58c"),
        ("100644", "blob", "c5c727c2a5278a6d5540695f05bd184e3e736439"),
    ),
    "scripts/bootstrap_task7_release_execute.py": (
        ("100644", "blob", "7eca491d49bc684528a9199a5b9ce6329f02c792"),
        ("100644", "blob", "9adebbb8beae69699c070d5b196ea420318eac7f"),
    ),
    "scripts/bootstrap_task8_release_control.py": (
        None,
        ("100644", "blob", "d61b9b957ed6d1e88a0ba9afcffb7db3a3cdd877"),
    ),
}
PROTECTED_EXACT_PATHS = {
    "modules/app.py",
    "modules/app_extensions.py",
    "modules/config.py",
    "modules/db.py",
    "modules/deployment_write_fence.py",
    "modules/migrations.py",
    "modules/migration_catalog.py",
    "modules/migration_planning.py",
    "scripts/deploy.sh",
    "scripts/deploy-code-only.sh",
    "scripts/deployment_manifest.py",
    "scripts/rollback-deployment.sh",
    "scripts/backup-db.sh",
    "package.json",
    "package-lock.json",
    ".nvmrc",
    ".node-version",
    ".npmrc",
    "vite.config.js",
}


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def _assert_same_blob(repository, before, target, path):
    before_blob = _git(repository, "rev-parse", f"{before}:{path}")
    target_blob = _git(repository, "rev-parse", f"{target}:{path}")
    if before_blob != target_blob:
        raise RuntimeError(f"release cannot change protected path: {path}")


def _tracked_tree_modes(repository, commit):
    result = subprocess.run(
        ["git", "-C", str(repository), "ls-tree", "-r", "-t", "-z", "--full-tree", commit],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    modes = {}
    for entry in result.stdout.split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode = metadata.split(b" ", 1)[0].decode("ascii")
        path = raw_path.decode("utf-8", errors="surrogateescape")
        modes[path] = mode
    return modes


def _tree_entry(repository, commit, path):
    entry = _git(repository, "ls-tree", commit, "--", path)
    if not entry:
        return None
    metadata, actual_path = entry.split("\t", 1)
    if actual_path != path:
        raise RuntimeError(f"unexpected support tree entry: {path}")
    return tuple(metadata.split(" "))


def _validate_support_transition(repository, before, target, path):
    if before != SUPPORT_BASELINE:
        raise RuntimeError(f"support exception requires the reviewed baseline: {path}")
    expected_before, expected_target = PINNED_SUPPORT_TRANSITIONS[path]
    if (
        _tree_entry(repository, before, path) != expected_before
        or _tree_entry(repository, target, path) != expected_target
    ):
        raise RuntimeError(f"support exception mode/blob transition mismatch: {path}")


def _validate_paths(repository, before, target, changed):
    for path in changed:
        normalized = PurePosixPath(path).as_posix()
        parts = PurePosixPath(normalized).parts
        lower = normalized.lower()
        target_path = Path(repository, *parts)
        if (
            not parts
            or normalized.startswith("/")
            or ".." in parts
        ):
            raise RuntimeError(f"release contains a path outside backend/frontend scope: {path}")
        if target_path.is_symlink():
            raise RuntimeError(f"release cannot change a symlinked path: {path}")
        if normalized in PINNED_SUPPORT_TRANSITIONS:
            _validate_support_transition(repository, before, target, normalized)
            continue
        if parts[0] not in ALLOWED_ROOTS:
            raise RuntimeError(f"release contains a path outside backend/frontend scope: {path}")
        if parts[0] == "modules" and "migration" in lower:
            raise RuntimeError(f"release cannot change migration logic: {path}")
        if normalized in PROTECTED_EXACT_PATHS:
            raise RuntimeError(f"release cannot change protected path: {path}")
        if parts[0] == "frontend" and not any(
            normalized == prefix or normalized.startswith(prefix)
            for prefix in ALLOWED_FRONTEND_PATHS
        ):
            raise RuntimeError(f"frontend release permits source files only: {path}")
        if any(token in lower for token in ("/attachments/", "production.db", "public/static", "dist/")):
            raise RuntimeError(f"release cannot change protected runtime data/assets: {path}")
        if parts[0] == "modules" and code_only_release._path_is_forbidden(normalized):
            raise RuntimeError(f"release contains a forbidden backend path: {path}")
        if parts[0] in {"tests", "docs"}:
            continue
        if parts[0] == "modules":
            continue
        if not any(normalized == prefix or normalized.startswith(prefix) for prefix in ALLOWED_FRONTEND_PATHS):
            raise RuntimeError(f"release path is not deployable code or static source: {path}")

    tree_modes = (
        _tracked_tree_modes(repository, before),
        _tracked_tree_modes(repository, target),
    )
    for path in changed:
        parts = PurePosixPath(path).parts
        prefixes = ["/".join(parts[:index]) for index in range(1, len(parts) + 1)]
        if any(
            modes.get(prefix) in {"120000", "160000"}
            for modes in tree_modes
            for prefix in prefixes
        ):
            raise RuntimeError(f"release cannot change a symlink or submodule path: {path}")


def validate_release(
    tool_root,
    project_root,
    database,
    before_commit,
    target_commit,
    *,
    require_target_object=True,
):
    tool_root = Path(tool_root).resolve(strict=True)
    project_root = Path(project_root).resolve(strict=True)
    if (
        tool_root == project_root
        or tool_root in project_root.parents
        or project_root in tool_root.parents
    ):
        raise RuntimeError("production and target worktrees must be separate and non-nested")
    database_input = Path(database)
    if database_input.is_symlink():
        raise RuntimeError("production database path cannot be a symlink")
    database = database_input.resolve(strict=True)
    try:
        database.relative_to(project_root / "data")
    except ValueError as error:
        raise RuntimeError("production database must remain under project-root/data/") from error

    code_only_release._validate_sha(before_commit, "expected before commit")
    code_only_release._validate_sha(target_commit, "target commit")
    if before_commit == target_commit:
        raise RuntimeError("target commit must differ from the current production commit")
    if _git(tool_root, "rev-parse", "--verify", "HEAD") != target_commit:
        raise RuntimeError("release tool worktree HEAD must equal the target commit")
    code_only_release._assert_clean_except_data(tool_root, allow_data=False)
    code_only_release._assert_clean_except_data(project_root, allow_data=True)
    if _git(project_root, "rev-parse", "--verify", "HEAD") != before_commit:
        raise RuntimeError("production checkout HEAD does not match the confirmed before commit")
    marker = project_root / ".deployed_commit"
    if marker.is_symlink() or not marker.is_file():
        raise RuntimeError("production deployed-commit marker is missing or unsafe")
    if marker.read_text(encoding="ascii").strip().lower() != before_commit:
        raise RuntimeError("production deployed-commit marker does not match the confirmed before commit")
    if require_target_object:
        _git(project_root, "cat-file", "-e", f"{target_commit}^{{commit}}")

    ancestry = subprocess.run(
        ["git", "-C", str(tool_root), "merge-base", "--is-ancestor", before_commit, target_commit],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if ancestry.returncode:
        raise RuntimeError(
            "target commit is not provably based on the confirmed production commit"
        )

    changed = code_only_release._changed_paths(tool_root, before_commit, target_commit)
    if not changed:
        raise RuntimeError("target commit contains no changes from production baseline")
    if not any(
        path.startswith("modules/")
        or any(path == prefix or path.startswith(prefix) for prefix in ALLOWED_FRONTEND_PATHS)
        for path in changed
    ):
        raise RuntimeError("target commit has no backend or frontend source changes to publish")
    tracked_data = {
        "before": code_only_release._tracked_data_paths(tool_root, before_commit),
        "target": code_only_release._tracked_data_paths(tool_root, target_commit),
    }
    if any(tracked_data.values()):
        raise RuntimeError("backend/static release refuses commits that track production data/")
    _validate_paths(tool_root, before_commit, target_commit, changed)
    code_only_release._assert_release_controls_unchanged(tool_root, before_commit, target_commit)
    code_only_release._assert_runtime_fence_unchanged(tool_root, before_commit, target_commit)

    database_evidence = sqlite_evidence(database)
    target_schema = code_only_release._target_schema_version(tool_root)
    if target_schema != database_evidence["user_version"]:
        raise RuntimeError(
            f"schema mismatch: target expects V{target_schema}, production is V{database_evidence['user_version']}"
        )
    package = json.loads((tool_root / "package.json").read_text(encoding="utf-8"))
    toolchain = {
        "node": package["engines"]["node"],
        "npm": package["engines"]["npm"],
    }
    for path in ("package.json", "package-lock.json", ".nvmrc", ".node-version", ".npmrc", "vite.config.js"):
        _assert_same_blob(tool_root, before_commit, target_commit, path)
    return {
        "scope": "backend_frontend_static",
        "operations": {
            "database_migration": False,
            "attachment_migration": False,
            "frontend_publish": True,
        },
        "before_commit": before_commit,
        "target_commit": target_commit,
        "changed_paths": changed,
        "database": database_evidence,
        "target_schema_version": target_schema,
        "tracked_data": tracked_data,
        "toolchain_required": toolchain,
        "production_worktree": "clean_except_untracked_data",
    }


def verify_baseline_checkout(project_root, before_commit):
    """Reject a partial/dirty checkout even when Git HEAD did not move."""
    project_root = Path(project_root).resolve(strict=True)
    if _git(project_root, "rev-parse", "HEAD") != before_commit:
        raise RuntimeError("abort checkout HEAD does not match the baseline")
    marker = project_root / ".deployed_commit"
    if marker.is_symlink() or not marker.is_file():
        raise RuntimeError("abort deployed-commit marker is missing or unsafe")
    if marker.read_text(encoding="ascii").strip() != before_commit:
        raise RuntimeError("abort deployed-commit marker does not match the baseline")
    code_only_release._assert_clean_except_data(project_root, allow_data=True)
    return {"baseline_commit": before_commit, "worktree": "clean_except_untracked_data"}


def extract_target_static(archive_path, destination):
    destination = Path(destination)
    if ".." in destination.parts:
        raise RuntimeError("static staging destination cannot contain parent traversal")
    parent = destination.absolute().parent
    cursor = parent
    while cursor != cursor.parent:
        if cursor.is_symlink():
            raise RuntimeError(f"static staging path cannot traverse a symlink: {cursor}")
        cursor = cursor.parent
    if destination.exists() or destination.is_symlink():
        raise RuntimeError("static staging destination already exists or is unsafe")
    destination.mkdir(mode=0o755, parents=False)
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            members = safe_tar_members(archive, MANAGED_RELEASE_ROOTS)
            for member in members:
                path = PurePosixPath(member.name)
                relative = Path(*path.parts[2:])
                if path.parts[:2] != ("public", "static"):
                    raise RuntimeError("static archive path is outside public/static")
                target = destination / relative
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise RuntimeError(f"static archive entry cannot be read: {member.name}")
                with source, target.open("xb") as output:
                    output.write(source.read())
                target.chmod(member.mode & 0o755)
        if not (destination / "index.html").is_file():
            raise RuntimeError("built static release is missing index.html")
        return str(destination)
    except BaseException:
        import shutil

        shutil.rmtree(destination, ignore_errors=True)
        raise


def exchange_directories(left, right):
    left_input = Path(left).absolute()
    right_input = Path(right).absolute()
    if ".." in left_input.parts or ".." in right_input.parts:
        raise RuntimeError("atomic static exchange refuses parent traversal")
    for path in (*left_input.parents, left_input, *right_input.parents, right_input):
        if path.is_symlink():
            raise RuntimeError("atomic static exchange refuses symlink paths")
    left = left_input.resolve(strict=True)
    right = right_input.resolve(strict=True)
    if left.parent != right.parent or not left.is_dir() or not right.is_dir():
        raise RuntimeError("atomic static exchange requires sibling directories")
    if left.is_symlink() or right.is_symlink():
        raise RuntimeError("atomic static exchange refuses symlinks")
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise RuntimeError("atomic static exchange is unsupported by this Linux runtime")
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    result = renameat2(-100, os.fsencode(left), -100, os.fsencode(right), 2)
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    return {"active": str(left), "previous": str(right)}


def create_static_archive(source_directory, archive_path):
    source_input = Path(source_directory).absolute()
    output = Path(archive_path).absolute()
    if ".." in source_input.parts or ".." in output.parts:
        raise RuntimeError("static archive paths cannot contain parent traversal")
    for path in (*source_input.parents, source_input):
        if path.is_symlink():
            raise RuntimeError(f"static build path cannot traverse a symlink: {path}")
    source = source_input.resolve(strict=True)
    for path in (*output.parents, output):
        if path.is_symlink():
            raise RuntimeError(f"static archive path cannot traverse a symlink: {path}")
    if output.exists():
        raise RuntimeError(f"static archive destination already exists: {output}")
    if not source.is_dir():
        raise RuntimeError("static build output is missing or unsafe")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz") as archive:
        for item in sorted(source.rglob("*")):
            if item.is_symlink():
                raise RuntimeError(f"static build contains a symlink: {item}")
            if not item.is_file():
                continue
            relative = item.relative_to(source).as_posix()
            member = tarfile.TarInfo(f"public/static/{relative}")
            member.size = item.stat().st_size
            member.mode = item.stat().st_mode & 0o755
            member.mtime = int(item.stat().st_mtime)
            with item.open("rb") as content:
                archive.addfile(member, content)
    with tarfile.open(output, "r:gz") as archive:
        safe_tar_members(archive, MANAGED_RELEASE_ROOTS)
    with tarfile.open(output, "r:gz") as archive:
        if not any(
            item.isfile() and item.name == "public/static/index.html"
            for item in archive.getmembers()
        ):
            raise RuntimeError("static archive is missing public/static/index.html")
    return {"path": str(output), "sha256": code_only_release_sha256(output)}


def code_only_release_sha256(path):
    import hashlib

    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def static_directory_inventory(directory):
    root_input = Path(directory).absolute()
    if ".." in root_input.parts:
        raise RuntimeError("static backup path cannot contain parent traversal")
    for path in (*root_input.parents, root_input):
        if path.is_symlink():
            raise RuntimeError(f"static backup path cannot traverse a symlink: {path}")
    root = root_input.resolve(strict=True)
    if not root.is_dir():
        raise RuntimeError("static backup directory is missing or unsafe")
    files = []
    total_bytes = 0
    for item in sorted(root.rglob("*")):
        if item.is_symlink():
            raise RuntimeError(f"static backup cannot contain a symlink: {item}")
        if item.is_dir():
            continue
        if not item.is_file():
            raise RuntimeError(f"static backup contains an unsupported entry: {item}")
        size = item.stat().st_size
        files.append(
            {
                "path": f"public/static/{item.relative_to(root).as_posix()}",
                "size_bytes": size,
                "sha256": code_only_release_sha256(item),
            }
        )
        total_bytes += size
    return {
        "file_count": len(files),
        "total_bytes": total_bytes,
        "manifest_sha256": deployment_manifest.canonical_digest(files),
        "files": files,
    }


def verify_static_backup(directory, archive_path):
    expected = deployment_manifest.archive_inventory(
        archive_path, MANAGED_RELEASE_ROOTS
    )
    observed = static_directory_inventory(directory)
    if observed != expected:
        raise RuntimeError(
            "swapped-out static directory differs from its verified backup archive"
        )
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
    preflight.add_argument("--check-only", action="store_true")
    baseline = commands.add_parser("verify-baseline-checkout")
    baseline.add_argument("--project-root", required=True)
    baseline.add_argument("--before-commit", required=True)
    extract = commands.add_parser("extract-static")
    extract.add_argument("--archive", required=True)
    extract.add_argument("--destination", required=True)
    exchange = commands.add_parser("exchange-static")
    exchange.add_argument("--active", required=True)
    exchange.add_argument("--staged", required=True)
    archive = commands.add_parser("archive-static")
    archive.add_argument("--source", required=True)
    archive.add_argument("--archive", required=True)
    verify_backup = commands.add_parser("verify-static-backup")
    verify_backup.add_argument("--directory", required=True)
    verify_backup.add_argument("--archive", required=True)
    args = parser.parse_args(argv)
    if args.command == "preflight":
        result = validate_release(
            args.tool_root,
            args.project_root,
            args.database,
            args.before_commit,
            args.target_commit,
            require_target_object=not args.check_only,
        )
    elif args.command == "verify-baseline-checkout":
        result = verify_baseline_checkout(args.project_root, args.before_commit)
    elif args.command == "extract-static":
        result = extract_target_static(args.archive, args.destination)
    elif args.command == "exchange-static":
        result = exchange_directories(args.active, args.staged)
    elif args.command == "verify-static-backup":
        result = verify_static_backup(args.directory, args.archive)
    else:
        result = create_static_archive(args.source, args.archive)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
