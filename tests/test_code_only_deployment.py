import json
import shutil
import sqlite3
import subprocess
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import code_only_release, deployment_manifest


def _git(path, *args):
    return subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def _create_database(path, version=96):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    try:
        db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
        db.execute("INSERT INTO users (username) VALUES ('operator')")
        db.execute(f"PRAGMA user_version={version}")
        db.commit()
    finally:
        db.close()


def _create_release_repositories(
    tmp_path,
    changed_path="modules/services/sample.py",
    target_overrides=None,
    baseline_overrides=None,
):
    changed_paths = [changed_path] if isinstance(changed_path, str) else list(changed_path)
    target_overrides = target_overrides or {}
    baseline_overrides = baseline_overrides or {}
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "--quiet", "--initial-branch=master")
    _git(repository, "config", "user.name", "Codex Test")
    _git(repository, "config", "user.email", "codex-test@example.invalid")
    _write(repository / ".gitignore", ".deployed_commit\n")
    _write(repository / "modules/__init__.py", "")
    _write(repository / "modules/app.py", "APP = True\n")
    _write(repository / "modules/app_extensions.py", "EXTENSIONS = True\n")
    _write(repository / "modules/config.py", "CONFIG = True\n")
    _write(repository / "modules/db.py", "DATABASE = True\n")
    _write(repository / "modules/deployment_write_fence.py", "FENCE = True\n")
    _write(repository / "modules/runtime_version.py", "VERSION = True\n")
    _write(repository / "modules/migrations.py", "LATEST_VERSION = 96\n")
    _write(repository / "modules/services/sample.py", "VALUE = 1\n")
    for path in code_only_release.PROTECTED_RELEASE_CONTROL_PATHS:
        _write(repository / path, "TRUSTED_CONTROL = True\n")
    for path in changed_paths:
        _write(repository / path, baseline_overrides.get(path, "VALUE = 1\n"))
    _git(repository, "add", ".")
    _git(repository, "commit", "--quiet", "-m", "baseline")
    before = _git(repository, "rev-parse", "HEAD")
    for path in changed_paths:
        _write(repository / path, target_overrides.get(path, "VALUE = 2\n"))
    _git(repository, "add", ".")
    _git(repository, "commit", "--quiet", "-m", "target")
    target = _git(repository, "rev-parse", "HEAD")
    production = tmp_path / "production"
    tool = tmp_path / "release-tool"
    _git(repository, "worktree", "add", "--quiet", "--detach", str(production), before)
    _git(repository, "worktree", "add", "--quiet", "--detach", str(tool), target)
    _create_database(production / "data/production.db")
    _write(production / ".deployed_commit", before + "\n")
    return repository, production, tool, before, target


def _prepare_code_only_manifest(tmp_path):
    project_root = tmp_path / "project"
    database = project_root / "data/production.db"
    _create_database(database)
    attachment = project_root / "data/attachments/employee_docs/original.pdf"
    attachment.parent.mkdir(parents=True)
    attachment.write_bytes(b"original attachment")
    frontend_file = project_root / "public/static/app.js"
    frontend_file.parent.mkdir(parents=True)
    frontend_file.write_bytes(b"original frontend")

    backup_root = project_root / "data/backups"
    backup_root.mkdir(parents=True)
    database_backup = backup_root / "production.db"
    shutil.copy2(database, database_backup)
    attachment_backup = backup_root / "attachments.tar.gz"
    with tarfile.open(attachment_backup, "w:gz") as archive:
        archive.add(attachment.parent.parent, arcname="data/attachments")
    release_backup = backup_root / "release.tar.gz"
    with tarfile.open(release_backup, "w:gz") as archive:
        archive.add(project_root / "public/static", arcname="public/static")

    metadata_path = backup_root / "backup.json"
    deployment_manifest.create_backup_metadata(
        SimpleNamespace(
            database=str(database_backup),
            attachments=str(attachment_backup),
            attachment_root=["data/attachments"],
            output=str(metadata_path),
        )
    )
    manifest_path = project_root / "data/deployments/code-only-test.json"
    fence_path = project_root / "data/deployments/write-fence.json"
    deployment_manifest.begin_code_only_deployment(
        SimpleNamespace(
            output=str(manifest_path),
            deployment_key="code-only-test",
            before_commit="a" * 40,
            target_commit="b" * 40,
            source_database_version=96,
            target_database_version=96,
            write_fence=str(fence_path),
        )
    )
    deployment_manifest.acquire_write_fence(
        SimpleNamespace(
            path=str(fence_path),
            deployment_key="code-only-test",
            target_commit="b" * 40,
        )
    )
    deployment_manifest.record_code_only_fence(
        SimpleNamespace(manifest=str(manifest_path))
    )
    deployment_manifest.prepare_deployment_manifest(
        SimpleNamespace(
            output=str(manifest_path),
            backup_metadata=str(metadata_path),
            release_backup=str(release_backup),
            deployment_key="code-only-test",
            before_commit="a" * 40,
            target_commit="b" * 40,
            target_database_version=96,
            write_fence=str(fence_path),
            scope="code_only",
        )
    )
    deployment_manifest.capture_code_only_state(
        SimpleNamespace(
            manifest=str(manifest_path),
            database=str(database),
            project_root=str(project_root),
        )
    )
    return project_root, database, attachment, frontend_file, manifest_path, fence_path


def test_code_only_preflight_accepts_clean_backend_change_and_untracked_data(tmp_path):
    _, production, tool, before, target = _create_release_repositories(tmp_path)

    result = code_only_release.validate_code_only_release(
        tool,
        production,
        production / "data/production.db",
        before,
        target,
    )

    assert result["before_commit"] == before
    assert result["target_commit"] == target
    assert result["database"]["user_version"] == 96
    assert result["target_schema_version"] == 96
    assert result["production_worktree"] == "clean_except_untracked_data"
    assert result["changed_paths"] == ["modules/services/sample.py"]


def test_target_schema_version_reads_real_repository_without_importing_target_code():
    root = Path(__file__).resolve().parents[1]

    assert code_only_release._target_schema_version(root) == 96


def test_target_schema_version_accepts_integer_literal_fixture(tmp_path):
    root = tmp_path / "target"
    _write(root / "modules/migrations.py", "LATEST_VERSION = 96\n")

    assert code_only_release._target_schema_version(root) == 96


def test_target_schema_version_safely_parses_restricted_version_chain(tmp_path):
    root = tmp_path / "target"
    _write(
        root / "modules/migrations.py",
        "LATEST_VERSION = max(version for version in MIGRATIONS)\n",
    )
    _write(
        root / "modules/migration_catalog.py",
        "MIGRATION_VERSION_CHAIN = (1, *range(13, 97))\n",
    )

    assert code_only_release._target_schema_version(root) == 96


@pytest.mark.parametrize(
    "catalog_content",
    [
        "OTHER_VALUE = (1, 2, 3)\n",
        "MIGRATION_VERSION_CHAIN = (1, '96')\n",
        "MIGRATION_VERSION_CHAIN = __import__('os').system('echo unsafe')\n",
        "MIGRATION_VERSION_CHAIN = (1, *range(0, 1000000))\n",
    ],
)
def test_target_schema_version_rejects_missing_invalid_or_unsafe_chain(
    tmp_path, catalog_content
):
    root = tmp_path / "target"
    marker = tmp_path / "unsafe"
    _write(root / "modules/migrations.py", "LATEST_VERSION = calculate_version()\n")
    _write(
        root / "modules/migration_catalog.py",
        catalog_content.replace("echo unsafe", f"touch {marker.as_posix()}"),
    )

    with pytest.raises(RuntimeError, match="migration version"):
        code_only_release._target_schema_version(root)
    assert not marker.exists()


@pytest.mark.parametrize(
    "changed_path",
    [
        "modules/services/performance_history_migration_service.py",
        "tests/test_performance_history_migration_service.py",
    ],
)
def test_code_only_preflight_allows_non_schema_history_migration_code_and_tests(
    tmp_path, changed_path
):
    _, production, tool, before, target = _create_release_repositories(
        tmp_path, changed_path
    )

    result = code_only_release.validate_code_only_release(
        tool,
        production,
        production / "data/production.db",
        before,
        target,
    )

    assert result["changed_paths"] == [changed_path]


@pytest.mark.parametrize(
    "changed_path",
    [
        "frontend/src/App.vue",
        "public/static/app.js",
        "modules/migrations.py",
        "scripts/migrate-records.sh",
        "deploy/qr-system.service",
        "requirements-prod.txt",
    ],
)
def test_code_only_preflight_rejects_migrations_frontend_and_runtime_changes(
    tmp_path, changed_path
):
    _, production, tool, before, target = _create_release_repositories(
        tmp_path, changed_path
    )

    with pytest.raises(RuntimeError, match="out-of-scope paths"):
        code_only_release.validate_code_only_release(
            tool,
            production,
            production / "data/production.db",
            before,
            target,
        )


def test_code_only_preflight_allows_migration_catalog_docstring_only_change(
    tmp_path, monkeypatch
):
    _, production, tool, before, target = _create_release_repositories(
        tmp_path,
        "modules/migration_catalog.py",
        baseline_overrides={
            "modules/migration_catalog.py": (
                b'"""Baseline catalog docs."""\nVALUE = 1\n'
            )
        },
        target_overrides={
            "modules/migration_catalog.py": (
                b'"""Updated catalog composition-root docs."""\nVALUE = 1\n'
            )
        },
    )

    baseline_source = '"""Baseline catalog docs."""\nVALUE = 1\n'
    target_source = '"""Updated catalog composition-root docs."""\nVALUE = 1\n'
    assert code_only_release._module_docstring_only_sources(
        baseline_source, target_source
    )

    real_git = code_only_release._git

    def fake_git(repository, *args, check=True):
        if args and args[0] == "show":
            commit, path = args[1].split(":", 1)
            source = {
                before: baseline_source,
                target: target_source,
            }[commit]
            return SimpleNamespace(
                returncode=0,
                stdout=source.encode("utf-8"),
                stderr=b"",
            )
        return real_git(repository, *args, check=check)

    monkeypatch.setattr(code_only_release, "_git", fake_git)

    result = code_only_release.validate_code_only_release(
        tool,
        production,
        production / "data/production.db",
        before,
        target,
    )

    assert result["changed_paths"] == ["modules/migration_catalog.py"]


def test_code_only_preflight_rejects_migration_catalog_logic_change(tmp_path):
    _, production, tool, before, target = _create_release_repositories(
        tmp_path,
        "modules/migration_catalog.py",
        baseline_overrides={
            "modules/migration_catalog.py": (
                b'"""Baseline catalog docs."""\nVALUE = 1\n'
            )
        },
        target_overrides={
            "modules/migration_catalog.py": (
                b'"""Updated catalog docs."""\nVALUE = 2\n'
            )
        },
    )

    with pytest.raises(
        RuntimeError,
        match="documentation exception changed executable content",
    ):
        code_only_release.validate_code_only_release(
            tool,
            production,
            production / "data/production.db",
            before,
            target,
        )


@pytest.mark.parametrize(
    "changed_path",
    sorted(code_only_release.APPROVED_FRONTEND_TOOLING_PATHS),
)
def test_code_only_preflight_allows_reviewed_frontend_architecture_tooling(
    tmp_path, changed_path
):
    _, production, tool, before, target = _create_release_repositories(
        tmp_path, changed_path
    )

    result = code_only_release.validate_code_only_release(
        tool,
        production,
        production / "data/production.db",
        before,
        target,
    )

    assert result["changed_paths"] == [changed_path]


@pytest.mark.parametrize(
    "changed_path",
    [
        "frontend/src/App.vue",
        "frontend/src/composables/useInventory.js",
        "frontend/components/UnknownWidget.vue",
        "frontend/scripts/unknown-release-helper.mjs",
        "frontend/tests/unknown-runtime.test.mjs",
        "public/static/app.js",
        "dist/index.js",
        "package.json.bak",
    ],
)
def test_code_only_preflight_rejects_unapproved_frontend_and_package_paths(
    tmp_path, changed_path
):
    _, production, tool, before, target = _create_release_repositories(
        tmp_path, changed_path
    )

    with pytest.raises(RuntimeError, match="out-of-scope paths"):
        code_only_release.validate_code_only_release(
            tool,
            production,
            production / "data/production.db",
            before,
            target,
        )


def test_approved_task4_operation_adapter_manifest_stays_pinned():
    # Approval is for historical content, not every later HEAD of these paths.
    assert code_only_release.APPROVED_OPERATION_ADAPTER_BLOBS == {
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


@pytest.mark.parametrize(
    "path", sorted(code_only_release.APPROVED_OPERATION_ADAPTER_BLOBS)
)
def test_current_operation_adapter_content_requires_reviewed_blob(path):
    root = Path(__file__).resolve().parents[1]
    approved_blob = code_only_release.APPROVED_OPERATION_ADAPTER_BLOBS[path]
    target_blob = code_only_release._blob_oid(root, "HEAD", path)

    if target_blob == approved_blob:
        code_only_release._assert_operation_adapter_content(root, "HEAD", [path])
    else:
        with pytest.raises(RuntimeError, match="does not match approved content"):
            code_only_release._assert_operation_adapter_content(root, "HEAD", [path])


def test_current_deploy_script_is_not_implicitly_approved_for_code_only(tmp_path):
    root = Path(__file__).resolve().parents[1]
    content = (root / "deploy.sh").read_text(encoding="utf-8")
    assert "node frontend/scripts/check-toolchain.mjs" in content
    _, production, tool, before, target = _create_release_repositories(
        tmp_path, "deploy.sh", target_overrides={"deploy.sh": content}
    )

    with pytest.raises(RuntimeError, match="does not match approved content: deploy.sh"):
        code_only_release.validate_code_only_release(
            tool,
            production,
            production / "data/production.db",
            before,
            target,
        )


def test_task4_facade_release_paths_pass_code_only_preflight(tmp_path, monkeypatch):
    changed_paths = [
        "deploy.sh",
        "modules/application/operations_migrations.py",
        "scripts/migrate_payroll_history.py",
        "scripts/migrate_performance_history.py",
        "scripts/plan_migrations.py",
    ]
    repository, production, tool, before, target = _create_release_repositories(
        tmp_path, changed_paths
    )
    monkeypatch.setattr(
        code_only_release,
        "APPROVED_OPERATION_ADAPTER_BLOBS",
        {
            path: _git(repository, "rev-parse", f"{target}:{path}")
            for path in changed_paths
        },
    )

    result = code_only_release.validate_code_only_release(
        tool,
        production,
        production / "data/production.db",
        before,
        target,
    )

    assert result["changed_paths"] == sorted(changed_paths)
    assert result["database"]["user_version"] == 96
    assert result["target_schema_version"] == 96


@pytest.mark.parametrize(
    ("changed_path", "unsafe_content"),
    [
        ("deploy.sh", "bash scripts/publish-frontend.sh\n"),
        (
            "modules/application/operations_migrations.py",
            "class Unsafe:\n    def apply(self):\n        run_migrations()\n",
        ),
        (
            "scripts/migrate_payroll_history.py",
            "import importlib\nimportlib.import_module('modules.services.secret')\n",
        ),
        (
            "scripts/migrate_performance_history.py",
            "__import__('modules.repositories.secret')\n",
        ),
        ("scripts/plan_migrations.py", "from modules.migrations import run_migrations\n"),
    ],
)
def test_task4_facade_release_paths_reject_unapproved_content_through_preflight(
    tmp_path, monkeypatch, changed_path, unsafe_content
):
    repository, production, tool, before, reviewed_target = (
        _create_release_repositories(tmp_path, changed_path)
    )
    monkeypatch.setattr(
        code_only_release,
        "APPROVED_OPERATION_ADAPTER_BLOBS",
        {
            changed_path: _git(
                repository, "rev-parse", f"{reviewed_target}:{changed_path}"
            )
        },
    )
    _write(repository / changed_path, unsafe_content)
    _git(repository, "add", changed_path)
    _git(repository, "commit", "--quiet", "-m", "unreviewed adapter change")
    target = _git(repository, "rev-parse", "HEAD")
    _git(repository, "worktree", "remove", "--force", str(tool))
    _git(repository, "worktree", "add", "--quiet", "--detach", str(tool), target)

    with pytest.raises(RuntimeError, match="does not match approved content"):
        code_only_release.validate_code_only_release(
            tool,
            production,
            production / "data/production.db",
            before,
            target,
        )


def test_task4_facade_release_path_rejects_binary_content_through_preflight(
    tmp_path, monkeypatch
):
    changed_path = "deploy.sh"
    repository, production, tool, before, reviewed_target = (
        _create_release_repositories(tmp_path, changed_path)
    )
    monkeypatch.setattr(
        code_only_release,
        "APPROVED_OPERATION_ADAPTER_BLOBS",
        {
            changed_path: _git(
                repository, "rev-parse", f"{reviewed_target}:{changed_path}"
            )
        },
    )
    _write(repository / changed_path, b"#!/bin/sh\x00run-migrations\n")
    _git(repository, "add", changed_path)
    _git(repository, "commit", "--quiet", "-m", "binary adapter change")
    target = _git(repository, "rev-parse", "HEAD")
    _git(repository, "worktree", "remove", "--force", str(tool))
    _git(repository, "worktree", "add", "--quiet", "--detach", str(tool), target)

    with pytest.raises(RuntimeError, match="does not match approved content"):
        code_only_release.validate_code_only_release(
            tool,
            production,
            production / "data/production.db",
            before,
            target,
        )


def test_task4_facade_release_path_rejects_missing_target_blob_through_preflight(
    tmp_path, monkeypatch
):
    changed_path = "scripts/plan_migrations.py"
    repository, production, tool, before, reviewed_target = (
        _create_release_repositories(tmp_path, changed_path)
    )
    monkeypatch.setattr(
        code_only_release,
        "APPROVED_OPERATION_ADAPTER_BLOBS",
        {
            changed_path: _git(
                repository, "rev-parse", f"{reviewed_target}:{changed_path}"
            )
        },
    )
    (repository / changed_path).unlink()
    _git(repository, "add", changed_path)
    _git(repository, "commit", "--quiet", "-m", "delete adapter")
    target = _git(repository, "rev-parse", "HEAD")
    _git(repository, "worktree", "remove", "--force", str(tool))
    _git(repository, "worktree", "add", "--quiet", "--detach", str(tool), target)

    with pytest.raises(RuntimeError, match="cannot verify approved operation adapter blob"):
        code_only_release.validate_code_only_release(
            tool,
            production,
            production / "data/production.db",
            before,
            target,
        )


def test_task4_facade_release_path_rejects_renamed_adapter_through_preflight(
    tmp_path, monkeypatch
):
    changed_path = "scripts/plan_migrations.py"
    repository, production, tool, before, reviewed_target = (
        _create_release_repositories(tmp_path, changed_path)
    )
    monkeypatch.setattr(
        code_only_release,
        "APPROVED_OPERATION_ADAPTER_BLOBS",
        {
            changed_path: _git(
                repository, "rev-parse", f"{reviewed_target}:{changed_path}"
            )
        },
    )
    renamed_path = "modules/application/renamed_migration_adapter.py"
    (repository / renamed_path).parent.mkdir(parents=True, exist_ok=True)
    (repository / changed_path).rename(repository / renamed_path)
    _git(repository, "add", "-A")
    _git(repository, "commit", "--quiet", "-m", "rename adapter")
    target = _git(repository, "rev-parse", "HEAD")
    _git(repository, "worktree", "remove", "--force", str(tool))
    _git(repository, "worktree", "add", "--quiet", "--detach", str(tool), target)

    with pytest.raises(RuntimeError, match="cannot verify approved operation adapter blob"):
        code_only_release.validate_code_only_release(
            tool,
            production,
            production / "data/production.db",
            before,
            target,
        )


@pytest.mark.parametrize(
    "changed_path", code_only_release.PROTECTED_RELEASE_CONTROL_PATHS
)
def test_code_only_preflight_rejects_release_control_self_modification(
    tmp_path, changed_path
):
    _, production, tool, before, target = _create_release_repositories(
        tmp_path, changed_path
    )

    with pytest.raises(RuntimeError, match="cannot change trusted release control"):
        code_only_release.validate_code_only_release(
            tool,
            production,
            production / "data/production.db",
            before,
            target,
        )


def test_code_only_preflight_rejects_fence_runtime_changes(tmp_path):
    repository, production, tool, before, _ = _create_release_repositories(tmp_path)
    _write(repository / "modules/deployment_write_fence.py", "FENCE = False\n")
    _git(repository, "add", ".")
    _git(repository, "commit", "--quiet", "-m", "change fence")
    target = _git(repository, "rev-parse", "HEAD")
    _git(repository, "worktree", "remove", "--force", str(tool))
    _git(repository, "worktree", "add", "--quiet", "--detach", str(tool), target)

    with pytest.raises(RuntimeError, match="write-fence runtime"):
        code_only_release.validate_code_only_release(
            tool,
            production,
            production / "data/production.db",
            before,
            target,
        )


def test_code_only_preflight_rejects_production_changes_outside_data(tmp_path):
    _, production, tool, before, target = _create_release_repositories(tmp_path)
    _write(production / "unexpected.txt", "do not ignore")

    with pytest.raises(RuntimeError, match="worktree is not clean"):
        code_only_release.validate_code_only_release(
            tool,
            production,
            production / "data/production.db",
            before,
            target,
        )


def test_code_only_preflight_rejects_schema_mismatch(tmp_path):
    _, production, tool, before, target = _create_release_repositories(tmp_path)
    database = production / "data/production.db"
    database.unlink()
    _create_database(database, version=95)

    with pytest.raises(RuntimeError, match="schema mismatch"):
        code_only_release.validate_code_only_release(
            tool,
            production,
            production / "data/production.db",
            before,
            target,
        )


def test_code_only_manifest_backs_up_and_fingerprints_excluded_state(tmp_path):
    project, database, attachment, frontend, manifest_path, fence = (
        _prepare_code_only_manifest(tmp_path)
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["scope"] == "code_only"
    assert manifest["operations"] == {
        "database_migration": False,
        "attachment_migration": False,
        "frontend_publish": False,
        "code_switch": True,
        "service_restart": True,
    }
    assert manifest["code_only_state"]["database"]["logical_sha256"]
    assert manifest["code_only_state"]["attachments"]["file_count"] == 1
    assert manifest["code_only_state"]["release"]["file_count"] == 1
    assert fence.exists()
    assert database.exists() and attachment.exists() and frontend.exists()
    assert project.exists()


def test_deployed_commit_marker_update_is_atomic_and_requires_expected_current(tmp_path):
    marker = tmp_path / ".deployed_commit"
    marker.write_text("a" * 40 + "\n", encoding="ascii")

    deployment_manifest.write_deployed_commit(
        SimpleNamespace(
            project_root=str(tmp_path),
            expected_current="a" * 40,
            commit="b" * 40,
        )
    )

    assert marker.read_text(encoding="ascii") == "b" * 40 + "\n"
    with pytest.raises(RuntimeError, match="changed unexpectedly"):
        deployment_manifest.write_deployed_commit(
            SimpleNamespace(
                project_root=str(tmp_path),
                expected_current="a" * 40,
                commit="c" * 40,
            )
        )
    assert marker.read_text(encoding="ascii") == "b" * 40 + "\n"


def test_backup_metadata_creation_never_overwrites_existing_evidence(tmp_path):
    _, database, _, _, manifest_path, _ = _prepare_code_only_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    metadata_path = Path(manifest["backup"]["database"]["path"]).parent / "backup.json"
    original = metadata_path.read_bytes()

    with pytest.raises(FileExistsError):
        deployment_manifest.create_backup_metadata(
            SimpleNamespace(
                database=manifest["backup"]["database"]["path"],
                attachments=manifest["backup"]["attachments"]["path"],
                attachment_root=["data/attachments"],
                output=str(metadata_path),
            )
        )

    assert metadata_path.read_bytes() == original
    assert database.exists()


def test_code_only_rollback_preserves_data_without_restoring_or_releasing_early(
    tmp_path,
):
    project, database, attachment, frontend, manifest_path, fence = (
        _prepare_code_only_manifest(tmp_path)
    )
    original_database = database.read_bytes()
    original_attachment = attachment.read_bytes()
    original_frontend = frontend.read_bytes()

    deployment_manifest.restore_deployment(
        SimpleNamespace(
            manifest=str(manifest_path),
            database=str(database),
            project_root=str(project),
        )
    )

    persisted = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "code_only_data_preserved"
    assert persisted["rollback"]["restore_scope_verified"] is False
    assert database.read_bytes() == original_database
    assert attachment.read_bytes() == original_attachment
    assert frontend.read_bytes() == original_frontend
    with pytest.raises(RuntimeError, match="durable scope verification"):
        deployment_manifest.release_write_fence(
            SimpleNamespace(manifest=str(manifest_path), mode="rollback")
        )
    assert fence.exists()


def test_code_only_rollback_drift_fails_closed_without_overwriting_business_data(
    tmp_path,
):
    project, database, attachment, frontend, manifest_path, fence = (
        _prepare_code_only_manifest(tmp_path)
    )
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO users (username) VALUES ('new-business-fact')")
    attachment.write_bytes(b"new-business-attachment")
    frontend.write_bytes(b"unexpected-frontend-change")
    observed_database = database.read_bytes()
    observed_attachment = attachment.read_bytes()
    observed_frontend = frontend.read_bytes()

    with pytest.raises(RuntimeError, match="invariant drift"):
        deployment_manifest.restore_deployment(
            SimpleNamespace(
                manifest=str(manifest_path),
                database=str(database),
                project_root=str(project),
            )
        )

    assert database.read_bytes() == observed_database
    assert attachment.read_bytes() == observed_attachment
    assert frontend.read_bytes() == observed_frontend
    assert fence.exists()


def test_code_only_code_rollback_stays_allowed_with_fence_when_release_intent_was_saved(
    tmp_path,
):
    project, database, _, _, manifest_path, fence = _prepare_code_only_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["rollback"]["automatic_restore_allowed"] = False
    manifest["status"] = "release_authorized"
    deployment_manifest.atomic_write_json(manifest_path, manifest)

    deployment_manifest.restore_deployment(
        SimpleNamespace(
            manifest=str(manifest_path),
            database=str(database),
            project_root=str(project),
        )
    )

    persisted = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "code_only_data_preserved"
    assert persisted["rollback"]["restore_scope_verified"] is False
    assert fence.exists()


def test_code_only_rollback_release_requires_original_code_marker_and_health_state(
    tmp_path,
):
    project, database, _, _, manifest_path, fence = _prepare_code_only_manifest(tmp_path)
    deployment_manifest.restore_deployment(
        SimpleNamespace(
            manifest=str(manifest_path),
            database=str(database),
            project_root=str(project),
        )
    )
    with pytest.raises(RuntimeError, match="fenced health acceptance"):
        deployment_manifest.authorize_code_only_rollback_release(
            SimpleNamespace(
                manifest=str(manifest_path),
                database=str(database),
                project_root=str(project),
                current_commit="a" * 40,
            )
        )
    assert fence.exists()

    (project / ".deployed_commit").write_text("a" * 40, encoding="ascii")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["status"] = "rollback_accepted_fenced"
    deployment_manifest.atomic_write_json(manifest_path, manifest)
    deployment_manifest.authorize_code_only_rollback_release(
        SimpleNamespace(
            manifest=str(manifest_path),
            database=str(database),
            project_root=str(project),
            current_commit="a" * 40,
        )
    )
    deployment_manifest.release_write_fence(
        SimpleNamespace(manifest=str(manifest_path), mode="rollback")
    )

    final = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert final["status"] == "rollback_code_only"
    assert final["rollback"]["automatic_restore_allowed"] is False
    assert final["rollback"]["restore_scope_verified"] is True
    assert not fence.exists()


def test_code_only_abort_requires_old_code_health_and_persists_before_release(tmp_path):
    project, database, _, _, manifest_path, fence = _prepare_code_only_manifest(tmp_path)
    (project / ".deployed_commit").write_text("a" * 40, encoding="ascii")
    deployment_manifest.authorize_code_only_abort(
        SimpleNamespace(
            manifest=str(manifest_path),
            database=str(database),
            project_root=str(project),
            current_commit="a" * 40,
        )
    )
    persisted = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "abort_release_authorized"
    assert persisted["rollback"]["automatic_restore_allowed"] is False
    assert fence.exists()

    deployment_manifest.release_write_fence(
        SimpleNamespace(manifest=str(manifest_path), mode="abort")
    )
    assert not fence.exists()
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["status"] == "aborted_before_switch"


def test_code_only_shell_path_has_no_migration_or_frontend_steps_and_keeps_evidence():
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts" / "deploy-code-only.sh").read_text(encoding="utf-8")
    backup = (root / "scripts" / "backup-db.sh").read_text(encoding="utf-8")

    assert "--check-only" in script and "--execute" in script
    assert "acquire-fence" in script
    assert "record-code-only-fence" in script
    assert "PRESERVE_EXISTING_BACKUPS=1" in script
    assert 'DEPLOYMENT_MANIFEST_TOOL_SOURCE="$deployment_manifest"' in script
    assert "capture-code-only-state" in script
    assert "verify-code-only-state" in script
    assert "authorize-release" in script
    assert "scripts/rollback-deployment.sh" in script
    assert "scripts/migrate-employee-documents.sh" not in script
    assert "run_migrations" not in script
    assert "publish-frontend.sh" not in script
    assert "npm " not in script
    assert "cleanup skipped" in backup
    assert "if [[ \"$PRESERVE_EXISTING_BACKUPS\" == \"0\" ]]" in backup
    assert 'DEPLOYMENT_MANIFEST_TOOL_SOURCE="${DEPLOYMENT_MANIFEST_TOOL_SOURCE:-$QR_PROJECT_ROOT/scripts/deployment_manifest.py}"' in backup
    assert 'python3 "$DEPLOYMENT_MANIFEST_TOOL_SOURCE"' in backup


def test_code_only_shell_uses_production_trust_root_and_separate_target_tool():
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts" / "deploy-code-only.sh").read_text(encoding="utf-8")

    assert "--tool-root TARGET_WORKTREE" in script
    assert 'SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"' in script
    assert '"$SCRIPT_ROOT" != "$PROJECT_ROOT"' in script
    assert '"$TOOL_ROOT" == "$PROJECT_ROOT"' in script
    assert 'TRUST_ROOT="$TMP_DIR/trusted-controls"' in script
    assert 'install -m 0700 "$PROJECT_ROOT/scripts/$control"' in script
    assert 'python3 "$code_only_release" preflight' in script
    assert 'bash "$backup_script"' in script
    assert 'bash "$rollback_script"' in script

