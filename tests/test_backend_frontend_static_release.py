import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tarfile
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import backend_frontend_static_release as release
from scripts import code_only_release, deployment_manifest
from tests.test_code_only_deployment import (
    _create_database,
    _prepare_code_only_manifest,
    _write,
)


@pytest.mark.parametrize("drift", [None, "row", "schema", "user_version", "backup_bytes"])
def test_final_sqlite_backup_matches_facts_despite_schema_cookie_and_rejects_drift(tmp_path, drift):
    project, database, _, _, manifest_path, _ = _prepare_code_only_manifest(tmp_path)
    with sqlite3.connect(database) as source:
        source.execute("CREATE TABLE facts (id INTEGER PRIMARY KEY, amount INTEGER)")
        source.execute("INSERT INTO facts VALUES (1, 42)")
    backup_database = tmp_path / "final-backup.db"
    with sqlite3.connect(database) as source, sqlite3.connect(backup_database) as backup:
        source.backup(backup)
        assert source.execute("PRAGMA schema_version").fetchone() != backup.execute("PRAGMA schema_version").fetchone()
    # Preserve legacy stored digests, including schema_version, unchanged.
    assert deployment_manifest.sqlite_logical_digest(database) != deployment_manifest.sqlite_logical_digest(backup_database)
    manifest = deployment_manifest.read_json(manifest_path)
    metadata = deployment_manifest.create_backup_metadata(SimpleNamespace(
        database=str(backup_database), attachments=manifest["backup"]["attachments"]["path"],
        attachment_root=["data/attachments"], output=str(tmp_path / "final-backup.json"),
    ))
    manifest["backup"] = metadata
    manifest["code_only_state"] = None
    deployment_manifest.atomic_write_json(manifest_path, manifest)
    args = SimpleNamespace(manifest=str(manifest_path), database=str(database), project_root=str(project))
    statements = {
        "row": "UPDATE facts SET amount = 43 WHERE id = 1",
        "schema": "CREATE INDEX facts_amount ON facts(amount)",
        "user_version": "PRAGMA user_version=97",
    }
    if drift in statements:
        with sqlite3.connect(database) as source:
            source.execute(statements[drift])
    elif drift == "backup_bytes":
        with sqlite3.connect(backup_database) as backup:
            backup.execute("UPDATE facts SET amount = 99 WHERE id = 1")
    if drift:
        with pytest.raises(RuntimeError, match="differs from its final backup|version changed|checksum mismatch"):
            deployment_manifest.capture_code_only_state(args)
        assert deployment_manifest.read_json(manifest_path)["code_only_state"] is None
    else:
        captured = deployment_manifest.capture_code_only_state(args)
        assert captured["database"]["logical_sha256"] == deployment_manifest.sqlite_logical_digest(database)
        assert deployment_manifest.verify_code_only_state(args) == captured
        with sqlite3.connect(database) as source:
            source.execute("PRAGMA schema_version=99")
        with pytest.raises(RuntimeError, match="invariant drift"):
            deployment_manifest.verify_code_only_state(args)


def test_static_release_path_allows_backend_and_frontend_source_only(tmp_path):
    _, repository, before, target = _release_repository(tmp_path)
    release._validate_paths(
        repository,
        before,
        target,
        [
            "modules/services/schedule.py",
        ],
    )


def test_static_release_rejects_symlink_removed_from_target_tree(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    code_only_release._git(repository, "init", "--quiet", "--initial-branch=master")
    code_only_release._git(repository, "config", "user.name", "Codex Test")
    code_only_release._git(repository, "config", "user.email", "codex-test@example.invalid")
    _write(repository / "modules/services/schedule.py", "VALUE = 1\n")
    code_only_release._git(repository, "add", ".")
    code_only_release._git(repository, "commit", "--quiet", "-m", "regular baseline")
    regular = code_only_release._git(repository, "rev-parse", "HEAD").stdout.decode().strip()
    link_blob = code_only_release._git(
        repository, "rev-parse", f"{regular}:modules/services/schedule.py"
    ).stdout.decode().strip()
    code_only_release._git(
        repository,
        "update-index",
        "--add",
        "--cacheinfo",
        f"120000,{link_blob},modules/services/legacy.py",
    )
    code_only_release._git(repository, "commit", "--quiet", "-m", "add tracked symlink")
    symlink_baseline = code_only_release._git(repository, "rev-parse", "HEAD").stdout.decode().strip()
    code_only_release._git(repository, "rm", "--cached", "--quiet", "modules/services/legacy.py")
    code_only_release._git(repository, "commit", "--quiet", "-m", "remove tracked symlink")
    target = code_only_release._git(repository, "rev-parse", "HEAD").stdout.decode().strip()

    with pytest.raises(RuntimeError, match="symlink or submodule"):
        release._validate_paths(repository, symlink_baseline, target, ["modules/services/legacy.py"])


@pytest.mark.parametrize(
    "path",
    [
        "public/static/index.html",
        "frontend/scripts/check-toolchain.mjs",
        "frontend/package.json",
        "dist/assets/app.js",
        "data/production.db",
        "modules/migrations.py",
        "modules/services/performance_history_migration_service.py",
        "scripts/migrate-data.py",
        "deploy/qr-system.service",
    ],
)
def test_static_release_path_rejects_migrations_runtime_assets_and_tooling(path):
    with pytest.raises(RuntimeError):
        release._validate_paths(Path("."), "before", "target", [path])


def _release_repository(tmp_path, changed_path="frontend/src/App.vue"):
    repository = tmp_path / "repository"
    repository.mkdir()
    code_only_release._git(repository, "init", "--quiet", "--initial-branch=master")
    code_only_release._git(repository, "config", "user.name", "Codex Test")
    code_only_release._git(repository, "config", "user.email", "codex-test@example.invalid")
    _write(repository / ".gitignore", ".deployed_commit\n")
    for path in code_only_release.PROTECTED_RELEASE_CONTROL_PATHS:
        _write(repository / path, "TRUSTED_CONTROL = True\n")
    for path in code_only_release.PROTECTED_RUNTIME_PATHS:
        _write(repository / path, "FENCE = True\n")
    _write(repository / "modules/__init__.py", "")
    _write(repository / "modules/migrations.py", "LATEST_VERSION = 96\n")
    _write(repository / "modules/migration_catalog.py", "MIGRATION_VERSION_CHAIN = (96,)\n")
    _write(repository / "modules/services/schedule.py", "VALUE = 1\n")
    _write(repository / "frontend/src/App.vue", "<template><main>before</main></template>\n")
    _write(repository / "frontend/index.html", "<html><body></body></html>\n")
    _write(repository / "package.json", json.dumps({
        "engines": {"node": "24.22.0", "npm": "11.19.1"},
    }))
    _write(repository / "package-lock.json", json.dumps({"lockfileVersion": 3, "packages": {"": {"engines": {"node": "24.22.0", "npm": "11.19.1"}}}}))
    _write(repository / ".nvmrc", "24.22.0\n")
    _write(repository / ".node-version", "24.22.0\n")
    _write(repository / ".npmrc", "engine-strict=true\n")
    _write(repository / "vite.config.js", "export default {}\n")
    code_only_release._git(repository, "add", ".")
    code_only_release._git(repository, "commit", "--quiet", "-m", "baseline")
    before = code_only_release._git(repository, "rev-parse", "HEAD").stdout.decode().strip()
    _write(repository / changed_path, "VALUE = 2\n")
    _write(repository / "modules/services/schedule.py", "VALUE = 2\n")
    code_only_release._git(repository, "add", ".")
    code_only_release._git(repository, "commit", "--quiet", "-m", "target")
    target = code_only_release._git(repository, "rev-parse", "HEAD").stdout.decode().strip()
    production = tmp_path / "production"
    tool = tmp_path / "tool"
    code_only_release._git(repository, "worktree", "add", "--quiet", "--detach", str(production), before)
    code_only_release._git(repository, "worktree", "add", "--quiet", "--detach", str(tool), target)
    _create_database(production / "data/production.db", version=96)
    _write(production / ".deployed_commit", before + "\n")
    return production, tool, before, target


def test_reviewed_support_constants_match_actual_production_and_business_trees():
    repository = Path(__file__).resolve().parents[1]
    reviewed_business_tree = "a7db48376478b10ad3aded9814ab30b2bb0cb89d"
    for path, (expected_before, expected_target) in release.PINNED_SUPPORT_TRANSITIONS.items():
        assert release._tree_entry(repository, release.SUPPORT_BASELINE, path) == expected_before, path
        assert release._tree_entry(repository, reviewed_business_tree, path) == expected_target, path
        release._validate_paths(repository, release.SUPPORT_BASELINE, reviewed_business_tree, [path])


@pytest.mark.parametrize("drift", [None, "baseline", "before_blob", "target_blob", "deleted", "mode", "symlink", "submodule", "unlisted"])
def test_support_exception_requires_exact_baseline_modes_and_blobs(tmp_path, monkeypatch, drift):
    _, tool, before, target = _release_repository(tmp_path)
    path = "scripts/bootstrap_task7_release_execute.py"
    code_only_release._git(tool, "checkout", "--quiet", "--detach", before)
    _write(tool / path, "BASELINE = True\n")
    code_only_release._git(tool, "add", path)
    code_only_release._git(tool, "commit", "--quiet", "-m", "support baseline")
    support_before = release._git(tool, "rev-parse", "HEAD")
    expected_before = release._tree_entry(tool, support_before, path)
    _write(tool / path, "TARGET = True\n")
    code_only_release._git(tool, "add", path)
    code_only_release._git(tool, "commit", "--quiet", "-m", "support target")
    support_target = release._git(tool, "rev-parse", "HEAD")
    expected_target = release._tree_entry(tool, support_target, path)
    monkeypatch.setattr(release, "SUPPORT_BASELINE", support_before)
    monkeypatch.setattr(release, "PINNED_SUPPORT_TRANSITIONS", {path: (expected_before, expected_target)})
    if drift == "baseline":
        monkeypatch.setattr(release, "SUPPORT_BASELINE", before)
    elif drift == "before_blob":
        monkeypatch.setattr(release, "PINNED_SUPPORT_TRANSITIONS", {path: (expected_target, expected_target)})
    elif drift == "target_blob":
        _write(tool / path, "UNREVIEWED = True\n")
        code_only_release._git(tool, "add", path)
    elif drift == "deleted":
        code_only_release._git(tool, "rm", "--quiet", path)
    elif drift in {"mode", "symlink", "submodule"}:
        mode = {"mode": "100755", "symlink": "120000", "submodule": "160000"}[drift]
        object_id = support_target if drift == "submodule" else expected_target[2]
        code_only_release._git(tool, "update-index", "--cacheinfo", f"{mode},{object_id},{path}")
    elif drift == "unlisted":
        path = "scripts/another_bootstrap.py"
        _write(tool / path, "TARGET = True\n")
        code_only_release._git(tool, "add", path)
    if drift in {"target_blob", "deleted", "mode", "symlink", "submodule", "unlisted"}:
        code_only_release._git(tool, "commit", "--quiet", "-m", "unreviewed drift")
        support_target = release._git(tool, "rev-parse", "HEAD")
    if drift:
        with pytest.raises(RuntimeError, match="reviewed baseline|transition mismatch|outside backend/frontend scope"):
            release._validate_paths(tool, support_before, support_target, [path])
    else:
        release._validate_paths(tool, support_before, support_target, [path])


def test_static_release_preflight_accepts_source_changes_and_reports_no_migrations(tmp_path):
    production, tool, before, target = _release_repository(tmp_path)

    result = release.validate_release(
        tool,
        production,
        production / "data/production.db",
        before,
        target,
    )

    assert result["scope"] == "backend_frontend_static"
    assert result["operations"] == {
        "database_migration": False,
        "attachment_migration": False,
        "frontend_publish": True,
    }
    assert result["database"]["user_version"] == result["target_schema_version"] == 96
    assert result["toolchain_required"] == {"node": "24.22.0", "npm": "11.19.1"}
    assert result["changed_paths"] == [
        "frontend/src/App.vue",
        "modules/services/schedule.py",
    ]


def test_static_check_only_does_not_require_target_object_in_production_git(tmp_path):
    _, tool, before, target = _release_repository(tmp_path)
    source_repository = tmp_path / "repository"
    production = tmp_path / "independent-production"
    production.mkdir()
    code_only_release._git(production, "init", "--quiet", "--initial-branch=master")
    code_only_release._git(production, "remote", "add", "source", str(source_repository))
    code_only_release._git(production, "fetch", "--quiet", "source", before)
    code_only_release._git(production, "checkout", "--quiet", "--detach", "FETCH_HEAD")
    _create_database(production / "data/production.db", version=96)
    _write(production / ".deployed_commit", before + "\n")
    assert code_only_release._git(
        production, "cat-file", "-e", f"{target}^{{commit}}", check=False
    ).returncode != 0

    result = release.validate_release(
        tool,
        production,
        production / "data/production.db",
        before,
        target,
        require_target_object=False,
    )

    assert result["target_commit"] == target
    with pytest.raises(subprocess.CalledProcessError):
        release.validate_release(
            tool,
            production,
            production / "data/production.db",
            before,
            target,
        )


def test_static_release_preflight_rejects_target_without_production_ancestry(tmp_path):
    production, _, before, target = _release_repository(tmp_path)
    repository = tmp_path / "repository"
    tree = code_only_release._git(repository, "rev-parse", f"{target}^{{tree}}").stdout.decode().strip()
    unrelated = code_only_release._git(
        repository, "commit-tree", tree, "-m", "same tree without production ancestry"
    ).stdout.decode().strip()
    unrelated_tool = tmp_path / "unrelated-tool"
    code_only_release._git(
        repository, "worktree", "add", "--quiet", "--detach", str(unrelated_tool), unrelated
    )

    with pytest.raises(RuntimeError, match="not provably based"):
        release.validate_release(
            unrelated_tool,
            production,
            production / "data/production.db",
            before,
            unrelated,
            require_target_object=False,
        )


def test_static_release_preflight_rejects_migration_logic_change(tmp_path):
    production, tool, before, _ = _release_repository(tmp_path, "modules/migrations.py")
    target = code_only_release._git(tool, "rev-parse", "HEAD").stdout.decode().strip()
    with pytest.raises(RuntimeError, match="migration logic"):
        release.validate_release(
            tool,
            production,
            production / "data/production.db",
            before,
            target,
        )


def test_static_manifest_verifies_target_assets_and_rollback_preserves_database_and_attachments(tmp_path):
    project, database, attachment, old_static, manifest_path, fence = _prepare_code_only_manifest(tmp_path)
    before_db = database.read_bytes()
    before_attachment = attachment.read_bytes()
    before_static = old_static.read_bytes()
    target_build = tmp_path / "target-build"
    _write(target_build / "index.html", "<html>new build</html>\n")
    _write(target_build / "assets/app-new.js", "window.newRelease = true;\n")
    target_archive = tmp_path / "target-static.tar.gz"
    release.create_static_archive(target_build, target_archive)
    target_inventory = deployment_manifest.archive_inventory(
        target_archive, deployment_manifest.MANAGED_RELEASE_ROOTS
    )

    manifest = deployment_manifest.read_json(manifest_path)
    manifest["scope"] = deployment_manifest.DEPLOYMENT_SCOPE_BACKEND_FRONTEND_STATIC
    manifest["status"] = "starting"
    manifest["operations"] = {
        "database_migration": False,
        "attachment_migration": False,
        "frontend_publish": True,
        "code_switch": True,
        "service_restart": True,
    }
    manifest["target_static"] = {
        "path": str(target_archive),
        "sha256": deployment_manifest.sha256_file(target_archive),
        "size_bytes": target_archive.stat().st_size,
        "inventory": target_inventory,
    }
    manifest["before_commit"] = "a" * 40
    manifest["target_commit"] = "b" * 40
    manifest["rollback"]["static_restore_verified"] = False
    deployment_manifest.atomic_write_json(manifest_path, manifest)
    _write(project / ".deployed_commit", "b" * 40 + "\n")
    shutil.rmtree(project / "public/static")
    release.extract_target_static(target_archive, project / "public/static")

    deployment_manifest.verify_code_only_state(
        SimpleNamespace(
            manifest=str(manifest_path),
            database=str(database),
            project_root=str(project),
        )
    )
    accepted = deployment_manifest.read_json(manifest_path)
    assert accepted["operations"]["database_migration"] is False
    assert accepted["operations"]["attachment_migration"] is False
    assert accepted["operations"]["frontend_publish"] is True
    assert accepted["events"][-1]["state_sha256"]

    deployment_manifest.restore_deployment(
        SimpleNamespace(
            manifest=str(manifest_path),
            database=str(database),
            project_root=str(project),
        )
    )
    restored = deployment_manifest.read_json(manifest_path)
    assert restored["status"] == "code_only_data_preserved"
    assert restored["rollback"]["restore_scope_verified"] is False
    assert restored["rollback"]["static_restore_verified"] is True
    assert database.read_bytes() == before_db
    assert attachment.read_bytes() == before_attachment
    assert old_static.read_bytes() == before_static
    assert fence.exists()

    with pytest.raises(RuntimeError, match="durable scope verification"):
        deployment_manifest.release_write_fence(
            SimpleNamespace(manifest=str(manifest_path), mode="rollback")
        )


def test_static_manifest_preparation_declares_migrations_prohibited(tmp_path):
    project = tmp_path / "project"
    database = project / "data/production.db"
    _create_database(database, version=96)
    attachment = project / "data/attachments/employee_docs/doc.pdf"
    _write(attachment, b"protected attachment")
    old_static = project / "public/static"
    _write(old_static / "index.html", "<html>old</html>")
    build_static = tmp_path / "build"
    _write(build_static / "index.html", "<html>new</html>")

    backup_root = project / "data/backups"
    backup_root.mkdir(parents=True)
    database_backup = backup_root / "database.db"
    shutil.copy2(database, database_backup)
    attachment_backup = backup_root / "attachments.tar.gz"
    with tarfile.open(attachment_backup, "w:gz") as archive:
        archive.add(project / "data/attachments", arcname="data/attachments")
    backup_metadata = backup_root / "backup.json"
    deployment_manifest.create_backup_metadata(
        SimpleNamespace(
            database=str(database_backup),
            attachments=str(attachment_backup),
            attachment_root=["data/attachments"],
            output=str(backup_metadata),
        )
    )
    old_archive = backup_root / "old-static.tar.gz"
    target_archive = backup_root / "target-static.tar.gz"
    release.create_static_archive(old_static, old_archive)
    release.create_static_archive(build_static, target_archive)
    manifest_path = project / "data/deployments/deploy.json"
    fence_path = project / "data/deployments/write-fence.json"
    deployment_manifest.begin_code_only_deployment(
        SimpleNamespace(
            output=str(manifest_path),
            deployment_key="backend-static-test",
            before_commit="a" * 40,
            target_commit="b" * 40,
            source_database_version=96,
            target_database_version=96,
            write_fence=str(fence_path),
            scope=deployment_manifest.DEPLOYMENT_SCOPE_BACKEND_FRONTEND_STATIC,
        )
    )
    deployment_manifest.acquire_write_fence(
        SimpleNamespace(
            path=str(fence_path),
            deployment_key="backend-static-test",
            target_commit="b" * 40,
        )
    )
    deployment_manifest.record_code_only_fence(SimpleNamespace(manifest=str(manifest_path)))
    deployment_manifest.prepare_deployment_manifest(
        SimpleNamespace(
            output=str(manifest_path),
            backup_metadata=str(backup_metadata),
            release_backup=str(old_archive),
            target_static_backup=str(target_archive),
            deployment_key="backend-static-test",
            before_commit="a" * 40,
            target_commit="b" * 40,
            target_database_version=96,
            write_fence=str(fence_path),
            scope=deployment_manifest.DEPLOYMENT_SCOPE_BACKEND_FRONTEND_STATIC,
        )
    )

    manifest = deployment_manifest.read_json(manifest_path)
    assert manifest["scope"] == "backend_frontend_static"
    assert manifest["operations"] == {
        "database_migration": False,
        "attachment_migration": False,
        "frontend_publish": True,
        "code_switch": True,
        "service_restart": True,
    }
    assert manifest["target_static"]["inventory"]["file_count"] == 1


def test_static_release_refuses_data_drift_before_restoring_static(tmp_path):
    project, database, attachment, _, manifest_path, fence = _prepare_code_only_manifest(tmp_path)
    manifest = deployment_manifest.read_json(manifest_path)
    manifest["scope"] = deployment_manifest.DEPLOYMENT_SCOPE_BACKEND_FRONTEND_STATIC
    manifest["target_static"] = {"path": "", "sha256": "", "size_bytes": 0, "inventory": {}}
    deployment_manifest.atomic_write_json(manifest_path, manifest)
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO users (username) VALUES ('business-change')")
    observed_db = database.read_bytes()
    observed_attachment = attachment.read_bytes()

    with pytest.raises(RuntimeError, match="database or attachment invariant drift"):
        deployment_manifest.restore_deployment(
            SimpleNamespace(
                manifest=str(manifest_path),
                database=str(database),
                project_root=str(project),
            )
        )

    assert database.read_bytes() == observed_db
    assert attachment.read_bytes() == observed_attachment
    assert fence.exists()


@pytest.mark.skipif(os.name != "posix", reason="atomic directory exchange is Linux/POSIX-only")
def test_static_directory_exchange_swaps_sibling_trees(tmp_path):
    active = tmp_path / "static"
    staged = tmp_path / ".static-stage"
    active.mkdir()
    staged.mkdir()
    (active / "index.html").write_text("old", encoding="utf-8")
    (staged / "index.html").write_text("new", encoding="utf-8")

    result = release.exchange_directories(active, staged)

    assert result == {"active": str(active.resolve()), "previous": str(staged.resolve())}
    assert (active / "index.html").read_text(encoding="utf-8") == "new"
    assert (staged / "index.html").read_text(encoding="utf-8") == "old"


def test_static_archive_rejects_symlinked_build_root(tmp_path):
    source = tmp_path / "source"
    _write(source / "index.html", "<html>built</html>\n")
    link = tmp_path / "source-link"
    try:
        link.symlink_to(source, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlink creation is unavailable: {error}")
    with pytest.raises(RuntimeError, match="symlink"):
        release.create_static_archive(link, tmp_path / "release.tar.gz")


def test_swapped_out_static_tree_matches_verified_archive_inventory(tmp_path):
    original = tmp_path / "original-static"
    _write(original / "index.html", "<html>previous</html>\n")
    _write(original / "assets/app.js", "window.previous = true;\n")
    archive = tmp_path / "previous-static.tar.gz"
    release.create_static_archive(original, archive)
    exchanged = tmp_path / ".static-test.previous"
    shutil.copytree(original, exchanged)

    assert release.verify_static_backup(exchanged, archive)["file_count"] == 2
    _write(exchanged / "assets/app.js", "window.changed = true;\n")
    with pytest.raises(RuntimeError, match="differs from its verified backup"):
        release.verify_static_backup(exchanged, archive)


def test_static_archive_normalizes_public_file_mode_in_tar(tmp_path):
    source = tmp_path / "source"
    file_path = source / "assets" / "app.js"
    _write(file_path, "window.release = true;\n")
    _write(source / "index.html", "<html></html>\n")
    if os.name != "nt":
        file_path.chmod(0o600)

    archive = tmp_path / "release.tar.gz"
    release.create_static_archive(source, archive)

    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        assert [member.name for member in members] == [
            "public/static/assets/app.js",
            "public/static/index.html",
        ]
        assert all(member.mode == release.STATIC_FILE_MODE for member in members)


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode semantics are required")
def test_static_extract_normalizes_tree_modes_under_restrictive_umask(tmp_path):
    source = tmp_path / "source"
    file_path = source / "assets" / "app.js"
    _write(file_path, "window.release = true;\n")
    _write(source / "index.html", "<html></html>\n")
    source.chmod(0o700)
    (source / "assets").chmod(0o700)
    file_path.chmod(0o600)
    archive = tmp_path / "release.tar.gz"
    release.create_static_archive(source, archive)

    destination = tmp_path / "staged"
    previous_umask = os.umask(0o077)
    try:
        release.extract_target_static(archive, destination)
    finally:
        os.umask(previous_umask)

    assert stat.S_IMODE(destination.stat().st_mode) == release.STATIC_DIRECTORY_MODE
    assert stat.S_IMODE((destination / "assets").stat().st_mode) == release.STATIC_DIRECTORY_MODE
    assert stat.S_IMODE(file_path.stat().st_mode) == 0o600
    assert stat.S_IMODE((destination / "assets" / "app.js").stat().st_mode) == release.STATIC_FILE_MODE
    assert release.static_directory_inventory(destination)["files"] == release.static_directory_inventory(source)["files"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode semantics are required")
def test_static_restore_normalizes_tree_modes_under_restrictive_umask(tmp_path):
    source = tmp_path / "source"
    file_path = source / "assets" / "app.js"
    _write(file_path, "window.release = true;\n")
    _write(source / "index.html", "<html></html>\n")
    source.chmod(0o700)
    (source / "assets").chmod(0o700)
    file_path.chmod(0o600)
    archive = tmp_path / "release.tar.gz"
    release.create_static_archive(source, archive)

    project = tmp_path / "project"
    project.mkdir()
    previous_umask = os.umask(0o077)
    try:
        deployment_manifest.restore_archive(
            archive,
            project,
            deployment_manifest.MANAGED_RELEASE_ROOTS,
        )
    finally:
        os.umask(previous_umask)

    restored = project / "public" / "static"
    assert stat.S_IMODE(restored.stat().st_mode) == 0o755
    assert stat.S_IMODE((restored / "assets").stat().st_mode) == 0o755
    assert stat.S_IMODE((restored / "assets" / "app.js").stat().st_mode) == 0o644
    assert release.static_directory_inventory(restored)["files"] == release.static_directory_inventory(source)["files"]


def test_static_release_shell_keeps_migrations_out_of_path_and_uses_isolated_build(tmp_path):
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts/deploy-backend-frontend-static.sh").read_text(encoding="utf-8")

    assert "--check-only|--execute" in script
    assert "--launcher-root) LAUNCHER_ROOT=" in script
    assert "args+=(--check-only)" in script
    assert "backend_frontend_static" in script
    assert '$(dirname "${BASH_SOURCE[0]}")' in script
    assert "$${BASH_SOURCE[0]}" not in script
    assert '"$NPM_BIN" ci --ignore-scripts --no-audit --no-fund' in script
    assert 'worktree add --quiet --detach "$WORKTREE"' in script
    assert "exchange-static" in script
    assert "authorize-release" in script
    assert "rollback-deployment.sh" in script or '"$ROLLBACK"' in script
    assert "migrate-employee-documents.sh" not in script
    assert "migrate_default_database" not in script
    assert "migrations are prohibited" in script


LINUX_LAUNCHER = pytest.mark.skipif(
    not sys.platform.startswith("linux") or not Path("/usr/bin/sqlite3").is_file(),
    reason="real launcher requires Linux directory exchange and /usr/bin/sqlite3",
)


def _shell_release_fixture(tmp_path, scenario="success"):
    """Exercise real release/Git/SQLite/tar; replace only host service/build IO."""
    source = Path(__file__).resolve().parents[1]
    repository = tmp_path / "repository"
    repository.mkdir()
    code_only_release._git(repository, "init", "--quiet", "--initial-branch=master")
    code_only_release._git(repository, "config", "user.name", "Release Contract")
    code_only_release._git(repository, "config", "user.email", "release@example.invalid")
    files = {
        ".gitignore": "data/\npublic/static/\n.deployed_commit\n",
        "modules/migrations.py": "LATEST_VERSION = 96\n",
        "modules/migration_catalog.py": "MIGRATION_VERSION_CHAIN = (96,)\n",
        "modules/services/schedule.py": "VALUE = 1\n",
        "frontend/src/App.vue": "<template>before</template>\n",
        "package.json": json.dumps({"engines": {"node": "24.22.0", "npm": "11.19.1"}}),
        "package-lock.json": '{"lockfileVersion":3}\n',
        ".nvmrc": "24.22.0\n",
        ".node-version": "24.22.0\n",
        ".npmrc": "engine-strict=true\n",
        "vite.config.js": "export default {}\n",
    }
    for path in code_only_release.PROTECTED_RUNTIME_PATHS:
        files[path] = "# immutable runtime fixture\n"
    for path in code_only_release.PROTECTED_RELEASE_CONTROL_PATHS:
        files[path] = (source / path).read_text(encoding="utf-8")
    for path, content in files.items():
        _write(repository / path, content)
    code_only_release._git(repository, "add", ".")
    code_only_release._git(repository, "commit", "--quiet", "-m", "baseline")
    before = code_only_release._git(repository, "rev-parse", "HEAD").stdout.decode().strip()
    _write(repository / "modules/services/schedule.py", "VALUE = 2\n")
    _write(repository / "frontend/src/App.vue", "<template>target</template>\n")
    code_only_release._git(repository, "add", ".")
    code_only_release._git(repository, "commit", "--quiet", "-m", "target")
    target = code_only_release._git(repository, "rev-parse", "HEAD").stdout.decode().strip()
    production, tool = tmp_path / "production", tmp_path / "tool"
    for directory, commit in ((production, before), (tool, target)):
        code_only_release._git(repository, "worktree", "add", "--quiet", "--detach", str(directory), commit)
    database = production / "data/production.db"
    _create_database(database)
    with sqlite3.connect(database) as connection:
        for index in range(9):
            connection.execute(f"CREATE TABLE facts_{index} (id INTEGER PRIMARY KEY)")
    _write(production / "data/attachments/doc.pdf", b"protected attachment\x00\xff")
    _write(production / "public/static/index.html", "<html>previous static</html>\n")
    _write(production / "public/static/assets/previous.js", "window.previous = true;\n")
    _write(production / ".deployed_commit", before + "\n")
    launcher = tmp_path / "launcher"
    for name in (
        "deploy-backend-frontend-static.sh", "backend_frontend_static_release.py",
        "code_only_release.py", "deployment_manifest.py", "rollback-deployment.sh", "backup-db.sh",
    ):
        _write(launcher / "scripts" / name, (source / "scripts" / name).read_text(encoding="utf-8"))

    state = tmp_path / "state"
    state.mkdir()
    _write(state / "service", "active")
    bin_dir = tmp_path / "bin"
    stub = textwrap.dedent('''\
        #!/usr/bin/env python3
        import json, os, sqlite3, sys
        from pathlib import Path
        name, args = Path(sys.argv[0]).name, sys.argv[1:]
        state, project = Path(os.environ["FIXTURE_STATE"]), Path(os.environ["FIXTURE_PROJECT"])
        target, scenario = os.environ["FIXTURE_TARGET"], os.environ["FIXTURE_SCENARIO"]
        marker = (project / ".deployed_commit").read_text().strip()
        fence_path = project / "data/deployments/write-fence.json"
        fence = json.loads(fence_path.read_text()) if fence_path.exists() else {}
        manifest_path = project / "data/deployments/shell-release.json"
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        event = {"command": name, "args": args, "commit": marker, "fenced": bool(fence), "status": manifest.get("status")}
        with (state / "calls.jsonl").open("a") as output:
            output.write(json.dumps(event) + "\\n")
        if name == "git":
            if args == ["-C", str(project), "switch", "--detach", target] and scenario.startswith("switch_fail"):
                if scenario == "switch_fail_dirty":
                    (project / "modules/services/schedule.py").write_text("VALUE = 'partial checkout'\\n")
                (state / "switch_failed").touch()
                sys.exit(1)
            os.execv(os.environ["FIXTURE_REAL_GIT"], [os.environ["FIXTURE_REAL_GIT"], *args])
        elif name == "systemctl":
            assert args[0] == "--user" and args[-1] == "qr-system.service", args
            action = args[1]
            assert action in {"start", "stop", "is-active"}, args
            if action == "is-active":
                sys.exit(0 if (state / "service").read_text() == "active" else 3)
            (state / "service").write_text("active" if action == "start" else "inactive")
        elif name == "curl":
            assert args[-1] == "https://fixture.invalid/api/health", args
            if (state / "service").read_text() != "active":
                sys.exit(22)
            if scenario == "switch_fail_abort_drift" and (state / "switch_failed").exists():
                (project / "modules/services/schedule.py").write_text("VALUE = 'partial checkout'\\n")
            if marker == target:
                (state / "switched").touch()
                if scenario == "data_drift" and not (state / "drifted").exists():
                    with sqlite3.connect(project / "data/production.db") as db:
                        db.execute("INSERT INTO users (username) VALUES ('external-fact')")
                    (state / "drifted").touch()
                if scenario == "static_backup_drift" and not (state / "drifted").exists():
                    previous_static = project / "public/.static-shell-release.previous/assets/previous.js"
                    if previous_static.is_file():
                        previous_static.write_text("window.tampered = true;\\n")
                        (state / "drifted").touch()
            broken = marker == target and scenario in {"target_health", "rollback_health"}
            broken = broken or (scenario == "rollback_health" and (state / "switched").exists())
            print(json.dumps({"status": "error" if broken else "ok", "db": "connected", "commit": marker,
                              "write_fenced": bool(fence), "deployment_key": fence.get("deployment_key")}))
        elif name == "node":
            if args == ["--version"]:
                print("v24.22.0")
            else:
                assert args == ["frontend/scripts/check-toolchain.mjs"], args
        elif name == "npm":
            if args == ["--version"]:
                print("11.19.1")
            elif args[:2] == ["run", "build"]:
                output = Path(args[args.index("--outDir") + 1])
                (output / "assets").mkdir(parents=True)
                (output / "index.html").write_text("<html>target static</html>\\n")
                (output / "assets/target.js").write_text("window.target = true;\\n")
            else:
                assert args[0] == "ci" or args in [["run", "check:api"], ["run", "check:imports"], ["run", "check:layers"]], args
        elif name != "sleep":
            raise AssertionError(name)
    ''')
    for name in ("node", "npm", "systemctl", "curl", "sleep", "git"):
        path = bin_dir / name
        _write(path, stub)
        path.chmod(0o700)
    environment = os.environ.copy()
    environment.update({
        "PATH": str(bin_dir) + os.pathsep + environment.get("PATH", ""),
        "NODE_BIN": str(bin_dir / "node"), "NPM_BIN": str(bin_dir / "npm"),
        "HEALTH_URL": "https://fixture.invalid/api/health",
        "FIXTURE_PROJECT": str(production), "FIXTURE_STATE": str(state),
        "FIXTURE_TARGET": target, "FIXTURE_SCENARIO": scenario,
        "FIXTURE_REAL_GIT": shutil.which("git"),
    })
    command = [
        "bash", str(launcher / "scripts/deploy-backend-frontend-static.sh"),
        "--project-root", str(production), "--tool-root", str(tool),
        "--launcher-root", str(launcher), "--expected-before", before,
        "--target-commit", target, "--deployment-key", "shell-release",
    ]
    return SimpleNamespace(
        production=production, tool=tool, database=database, before=before, target=target,
        state=state, command=command, environment=environment,
        baseline=deployment_manifest.code_only_state(database, production),
    )


def _run_shell_release(fixture, mode="--execute"):
    return subprocess.run(
        [*fixture.command, mode], env=fixture.environment,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120,
    )


@LINUX_LAUNCHER
def test_real_static_launcher_check_only_has_no_production_side_effects(tmp_path):
    fixture = _shell_release_fixture(tmp_path)
    result = _run_shell_release(fixture, "--check-only")
    assert result.returncode == 0, result.stdout
    assert deployment_manifest.code_only_state(fixture.database, fixture.production) == fixture.baseline
    assert not (fixture.production / "data/deployments").exists()
    assert not (fixture.production / "data/backups").exists()
    assert (fixture.state / "service").read_text() == "active"
    calls = [json.loads(line) for line in (fixture.state / "calls.jsonl").read_text().splitlines()]
    assert all(call["args"][1] == "is-active" for call in calls if call["command"] == "systemctl")
    assert (fixture.production / ".deployed_commit").read_text().strip() == fixture.before


@LINUX_LAUNCHER
def test_real_static_launcher_publishes_and_persists_acceptance_before_release(tmp_path):
    fixture = _shell_release_fixture(tmp_path)
    result = _run_shell_release(fixture)
    assert result.returncode == 0, result.stdout
    observed = deployment_manifest.code_only_state(fixture.database, fixture.production)
    assert observed["database"] == fixture.baseline["database"]
    assert observed["attachments"] == fixture.baseline["attachments"]
    manifest = deployment_manifest.read_json(fixture.production / "data/deployments/shell-release.json")
    assert manifest["status"] == "succeeded"
    assert observed["release"] == manifest["target_static"]["inventory"]
    assert manifest["write_fence"]["release_authorized_at"]
    assert manifest["rollback"]["automatic_restore_allowed"] is False
    assert manifest["operations"]["database_migration"] is False
    assert manifest["operations"]["attachment_migration"] is False
    assert not (fixture.production / "data/deployments/write-fence.json").exists()
    assert (fixture.production / ".deployed_commit").read_text().strip() == fixture.target
    assert (fixture.state / "service").read_text() == "active"
    assert not (fixture.production / "public/.static-shell-release.previous").exists()
    assert deployment_manifest.verify_backup_metadata(
        fixture.production / "data/backups/backup_shell-release.json"
    ) == manifest["backup"]
    statuses = [event["status"] for event in manifest["events"]]
    assert statuses.index("accepted_fenced") < statuses.index("release_authorized") < statuses.index("succeeded")


@LINUX_LAUNCHER
def test_real_static_launcher_health_failure_restores_code_static_and_preserves_facts(tmp_path):
    fixture = _shell_release_fixture(tmp_path, "target_health")
    result = _run_shell_release(fixture)
    assert result.returncode != 0, result.stdout
    manifest = deployment_manifest.read_json(fixture.production / "data/deployments/shell-release.json")
    assert manifest["status"] == "rollback_backend_frontend_static", result.stdout
    assert manifest["rollback"]["static_restore_verified"] is True
    assert deployment_manifest.code_only_state(fixture.database, fixture.production) == fixture.baseline
    assert (fixture.production / ".deployed_commit").read_text().strip() == fixture.before
    assert (fixture.state / "service").read_text() == "active"
    assert not (fixture.production / "data/deployments/write-fence.json").exists()


@LINUX_LAUNCHER
def test_real_static_launcher_refuses_to_discard_unverified_previous_assets(tmp_path):
    fixture = _shell_release_fixture(tmp_path, "static_backup_drift")
    result = _run_shell_release(fixture)
    assert result.returncode != 0, result.stdout
    manifest = deployment_manifest.read_json(fixture.production / "data/deployments/shell-release.json")
    assert manifest["status"] == "rollback_backend_frontend_static", result.stdout
    assert manifest["rollback"]["static_restore_verified"] is True
    assert deployment_manifest.code_only_state(fixture.database, fixture.production) == fixture.baseline
    assert (fixture.production / ".deployed_commit").read_text().strip() == fixture.before
    assert (fixture.state / "service").read_text() == "active"
    assert not (fixture.production / "data/deployments/write-fence.json").exists()


@LINUX_LAUNCHER
@pytest.mark.parametrize("scenario", ["data_drift", "rollback_health"])
def test_real_static_launcher_failed_verification_keeps_service_stopped_and_fenced(tmp_path, scenario):
    fixture = _shell_release_fixture(tmp_path, scenario)
    result = _run_shell_release(fixture)
    assert result.returncode != 0, result.stdout
    manifest = deployment_manifest.read_json(fixture.production / "data/deployments/shell-release.json")
    assert manifest["status"] == "rollback_failed", result.stdout
    assert (fixture.state / "service").read_text() == "inactive"
    assert (fixture.production / "data/deployments/write-fence.json").exists()
    observed = deployment_manifest.code_only_state(fixture.database, fixture.production)
    assert observed["attachments"] == fixture.baseline["attachments"]
    if scenario == "data_drift":
        with sqlite3.connect(fixture.database) as connection:
            assert connection.execute("SELECT username FROM users ORDER BY id").fetchall() == [("operator",), ("external-fact",)]
    else:
        assert observed == fixture.baseline


@LINUX_LAUNCHER
@pytest.mark.parametrize("scenario", ["switch_fail_dirty", "switch_fail_abort_drift"])
def test_real_static_launcher_partial_checkout_retains_fence_and_stops_service(tmp_path, scenario):
    fixture = _shell_release_fixture(tmp_path, scenario)
    result = _run_shell_release(fixture)
    assert result.returncode != 0, result.stdout
    assert "abort verification failed; fence retained" in result.stdout
    assert (fixture.state / "service").read_text() == "inactive"
    assert (fixture.production / "data/deployments/write-fence.json").exists()
    assert (fixture.production / "modules/services/schedule.py").read_text() == "VALUE = 'partial checkout'\n"
    assert code_only_release._git(fixture.production, "rev-parse", "HEAD").stdout.decode().strip() == fixture.before
    assert (fixture.production / ".deployed_commit").read_text().strip() == fixture.before
    assert deployment_manifest.code_only_state(fixture.database, fixture.production) == fixture.baseline
    manifest = deployment_manifest.read_json(fixture.production / "data/deployments/shell-release.json")
    assert manifest["status"] != "succeeded"
    if scenario == "switch_fail_dirty":
        calls = [json.loads(line) for line in (fixture.state / "calls.jsonl").read_text().splitlines()]
        assert not any(call["command"] == "systemctl" and call["args"][1] == "start" for call in calls)


@LINUX_LAUNCHER
def test_real_static_launcher_clean_switch_failure_can_safely_abort(tmp_path):
    fixture = _shell_release_fixture(tmp_path, "switch_fail_clean")
    result = _run_shell_release(fixture)
    assert result.returncode != 0, result.stdout
    assert "fence safely released" in result.stdout
    assert (fixture.state / "service").read_text() == "active"
    assert not (fixture.production / "data/deployments/write-fence.json").exists()
    assert deployment_manifest.code_only_state(fixture.database, fixture.production) == fixture.baseline
    assert (fixture.production / ".deployed_commit").read_text().strip() == fixture.before


@LINUX_LAUNCHER
def test_real_static_launcher_reused_key_does_not_overwrite_evidence(tmp_path):
    fixture = _shell_release_fixture(tmp_path)
    evidence = fixture.production / "data/deployments/shell-release.log"
    _write(evidence, "prior evidence\n")
    result = _run_shell_release(fixture)
    assert result.returncode != 0, result.stdout
    assert "Idempotency/evidence path already exists" in result.stdout
    assert evidence.read_text() == "prior evidence\n"
    assert deployment_manifest.code_only_state(fixture.database, fixture.production) == fixture.baseline
    assert (fixture.state / "service").read_text() == "active"
