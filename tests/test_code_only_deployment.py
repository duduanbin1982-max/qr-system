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


def _create_release_repositories(tmp_path, changed_path="modules/services/sample.py"):
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
    _git(repository, "add", ".")
    _git(repository, "commit", "--quiet", "-m", "baseline")
    before = _git(repository, "rev-parse", "HEAD")
    _write(repository / changed_path, "VALUE = 2\n")
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
        "modules/migration_catalog.py",
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

