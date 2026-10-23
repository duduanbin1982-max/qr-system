#!/usr/bin/env python3
"""Read-only validation for the controlled code-only production release path."""

import argparse
import ast
import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath

try:
    from .deployment_manifest import sqlite_evidence
except ImportError:  # Executed directly by the production shell entry point.
    from deployment_manifest import sqlite_evidence


SHA_RE = re.compile(r"^[0-9a-f]{40}$")
MAX_MIGRATION_VERSION_ITEMS = 10_000
PROTECTED_RUNTIME_PATHS = (
    "modules/app.py",
    "modules/config.py",
    "modules/app_extensions.py",
    "modules/db.py",
    "modules/deployment_write_fence.py",
    "modules/runtime_version.py",
)
PROTECTED_RELEASE_CONTROL_PATHS = (
    "scripts/code_only_release.py",
    "scripts/deploy-code-only.sh",
    "scripts/deployment_manifest.py",
    "scripts/rollback-deployment.sh",
    "scripts/backup-db.sh",
)
APPROVED_RELEASE_CONTROL_BLOB_TRANSITIONS = {
    "scripts/deploy-code-only.sh": (
        "f916286b10611284f279ce1a722b0c2874d10258",
        "98868bc7b612e59bae7b923085a1b8567a60a739",
    ),
}

# Task 4 moved operational entry points behind OperationsFacade. These executable
# adapters are allowed in a code-only release only while their target Git blobs
# exactly match the independently reviewed Task 4 content. Any later byte-level
# change is fail-closed until this manifest is deliberately reviewed and updated.
APPROVED_OPERATION_ADAPTER_BLOBS = {
    "deploy.sh": "954b03b3b4ad4b90faa917a93c3f5cf6c5c3b908",
    "modules/application/operations_migrations.py": (
        "94914a8a8eb42a46d718739a8fbef6888d9baa11"
    ),
    "scripts/migrate_payroll_history.py": (
        "4ad27f86c823430a005abd84b2bc8a516af0c131"
    ),
    "scripts/migrate_performance_history.py": (
        "042c13abed6cad1e17247c9bb72f14949cd1f660"
    ),
    "scripts/plan_migrations.py": "9cd4781dbd547fb25b4c5ec6d93527b1517da290",
}

# Task 5 moves the performance persistence decision to two reviewed repository
# owners. These files are allowed through the migration-name guard only when
# their target blobs are exactly the independently reviewed content.
APPROVED_TASK5_REPOSITORY_BLOBS = {
    "modules/repositories/performance_history_migration_repository.py": (
        "183a566e992623b781a8bb94633783fb4bfce767"
    ),
    "modules/repositories/performance_ledger_repository.py": (
        "46661899eb83f653e6fe0cb7e89695e1bdc48f27"
    ),
}

# Task 5 changes only the reviewed frontend architecture tooling and its
# package metadata. These paths are not runtime frontend assets and may be
# carried by a code-only release; every other frontend path remains forbidden.
APPROVED_FRONTEND_TOOLING_PATHS = frozenset(
    {
        "frontend/scripts/check-frontend-layers.mjs",
        "frontend/scripts/check-import-cycles.mjs",
        "frontend/scripts/frontend-layer-baseline.json",
        "frontend/scripts/frontend-source-graph.mjs",
        "frontend/tests/architecture/frontend-layers.test.mjs",
        "package.json",
        "package-lock.json",
    }
)
DOCUMENTATION_ONLY_PATHS = frozenset({"modules/migration_catalog.py"})


def _blob_oid(repository, commit, path):
    result = _git(repository, "rev-parse", f"{commit}:{path}", check=False)
    oid = result.stdout.decode("ascii", errors="strict").strip().lower()
    if result.returncode or not SHA_RE.fullmatch(oid):
        raise RuntimeError(
            "code-only release cannot verify approved operation adapter blob: "
            f"{path}"
        )
    return oid


def _assert_operation_adapter_content(repository, target_commit, changed):
    for path in changed:
        approved_blob = APPROVED_OPERATION_ADAPTER_BLOBS.get(path)
        if approved_blob is None:
            continue
        target_blob = _blob_oid(repository, target_commit, path)
        if target_blob != approved_blob:
            raise RuntimeError(
                "code-only release operation adapter does not match approved content: "
                f"{path}"
            )


def _assert_task5_repository_content(repository, target_commit, changed):
    for path in changed:
        approved_blob = APPROVED_TASK5_REPOSITORY_BLOBS.get(path)
        if approved_blob is None:
            continue
        target_blob = _blob_oid(repository, target_commit, path)
        if target_blob != approved_blob:
            raise RuntimeError(
                "code-only release Task 5 repository content does not match "
                f"approved content: {path}"
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
        "--no-renames",
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
    if normalized in APPROVED_TASK5_REPOSITORY_BLOBS:
        return False
    if normalized in APPROVED_OPERATION_ADAPTER_BLOBS:
        return False
    if normalized in APPROVED_FRONTEND_TOOLING_PATHS:
        return False
    if normalized in APPROVED_RELEASE_CONTROL_BLOB_TRANSITIONS:
        return False
    if parts[0] in {"data", "frontend", "public", "uploads", "dist"}:
        return True
    if normalized in {
        *PROTECTED_RELEASE_CONTROL_PATHS,
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
    if basename.startswith("package.json") or basename.startswith("package-lock.json"):
        return normalized not in APPROVED_FRONTEND_TOOLING_PATHS
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


def _module_executable_body(source):
    try:
        tree = ast.parse(source)
    except (SyntaxError, TypeError):
        return None
    if not tree.body:
        return None
    first = tree.body[0]
    if not (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return None
    return ast.dump(
        ast.Module(body=tree.body[1:], type_ignores=tree.type_ignores),
        annotate_fields=True,
        include_attributes=False,
    )


def _module_docstring_only_sources(before_source, target_source):
    """Return true only when a module's executable AST is unchanged."""
    before_body = _module_executable_body(before_source)
    target_body = _module_executable_body(target_source)
    return before_body is not None and before_body == target_body


def _module_docstring_only(repository, before_commit, target_commit, path):
    try:
        before_source = _git(repository, "show", f"{before_commit}:{path}").stdout.decode(
            "utf-8"
        )
        target_source = _git(repository, "show", f"{target_commit}:{path}").stdout.decode(
            "utf-8"
        )
    except (UnicodeError, RuntimeError):
        return False
    return _module_docstring_only_sources(before_source, target_source)


def _assert_runtime_fence_unchanged(repository, before_commit, target_commit):
    for path in PROTECTED_RUNTIME_PATHS:
        before = _git(repository, "rev-parse", f"{before_commit}:{path}", check=False)
        target = _git(repository, "rev-parse", f"{target_commit}:{path}", check=False)
        if before.returncode or target.returncode or before.stdout.strip() != target.stdout.strip():
            raise RuntimeError(f"code-only release cannot change write-fence runtime: {path}")


def _assert_release_controls_unchanged(repository, before_commit, target_commit):
    for path in PROTECTED_RELEASE_CONTROL_PATHS:
        before = _git(repository, "rev-parse", f"{before_commit}:{path}", check=False)
        target = _git(repository, "rev-parse", f"{target_commit}:{path}", check=False)
        before_blob = before.stdout.decode("ascii", errors="replace").strip()
        target_blob = target.stdout.decode("ascii", errors="replace").strip()
        if before.returncode or target.returncode or not before_blob or not target_blob:
            raise RuntimeError(
                f"code-only release cannot change trusted release control: {path}"
            )
        if before_blob == target_blob:
            continue
        if APPROVED_RELEASE_CONTROL_BLOB_TRANSITIONS.get(path) == (
            before_blob,
            target_blob,
        ):
            continue
        raise RuntimeError(
            f"code-only release cannot change trusted release control: {path}"
        )


def _parse_python_file(path, label):
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"target {label} is missing or unsafe")
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, SyntaxError) as error:
        raise RuntimeError(f"target {label} cannot be parsed safely") from error


def _assigned_value(tree, name):
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(target, ast.Name) and target.id == name for target in targets):
            continue
        return node.value
    return None


def _integer_literal(node):
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value
    raise RuntimeError("migration version expression contains a non-integer value")


def _migration_version_items(node):
    if isinstance(node, (ast.Tuple, ast.List)):
        values = []
        for item in node.elts:
            if isinstance(item, ast.Starred):
                values.extend(_migration_version_items(item.value))
            else:
                values.append(_integer_literal(item))
            if len(values) > MAX_MIGRATION_VERSION_ITEMS:
                raise RuntimeError("migration version chain is unreasonably large")
        return values
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "range"
        and not node.keywords
        and 1 <= len(node.args) <= 3
    ):
        arguments = [_integer_literal(argument) for argument in node.args]
        try:
            result = range(*arguments)
        except ValueError as error:
            raise RuntimeError("migration version range is invalid") from error
        if len(result) > MAX_MIGRATION_VERSION_ITEMS:
            raise RuntimeError("migration version chain is unreasonably large")
        return list(result)
    raise RuntimeError("migration version chain contains an unsafe expression")


def _target_schema_version(target_root):
    target_root = Path(target_root).resolve(strict=True)
    migrations_tree = _parse_python_file(
        target_root / "modules/migrations.py", "migration runner"
    )
    latest_version = _assigned_value(migrations_tree, "LATEST_VERSION")
    if isinstance(latest_version, ast.Constant) and type(latest_version.value) is int:
        return latest_version.value

    catalog_tree = _parse_python_file(
        target_root / "modules/migration_catalog.py", "migration catalog"
    )
    version_chain = _assigned_value(catalog_tree, "MIGRATION_VERSION_CHAIN")
    if version_chain is None:
        raise RuntimeError("target migration version chain is missing")
    versions = _migration_version_items(version_chain)
    if not versions:
        raise RuntimeError("target migration version chain is empty")
    if any(version < 0 for version in versions):
        raise RuntimeError("target migration version chain contains a negative version")
    return max(versions)


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
    _assert_release_controls_unchanged(tool_root, before_commit, target_commit)
    _assert_runtime_fence_unchanged(tool_root, before_commit, target_commit)
    _assert_operation_adapter_content(tool_root, target_commit, changed)
    _assert_task5_repository_content(tool_root, target_commit, changed)
    documentation_only = {
        path
        for path in changed
        if path in DOCUMENTATION_ONLY_PATHS
        and _module_docstring_only(tool_root, before_commit, target_commit, path)
    }
    invalid_documentation_exceptions = [
        path
        for path in changed
        if path in DOCUMENTATION_ONLY_PATHS and path not in documentation_only
    ]
    if invalid_documentation_exceptions:
        raise RuntimeError(
            "code-only documentation exception changed executable content: "
            + ", ".join(invalid_documentation_exceptions)
        )
    forbidden = [
        path
        for path in changed
        if _path_is_forbidden(path) and path not in documentation_only
    ]
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
