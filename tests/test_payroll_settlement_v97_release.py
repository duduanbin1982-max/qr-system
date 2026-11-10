import shutil
import sqlite3
import subprocess
import tarfile
import io
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import backend_frontend_static_release as static_release
from scripts import deployment_manifest
from scripts import payroll_settlement_v97_release as payroll_release


def _database(path, version=96):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE preserved_facts (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("INSERT INTO preserved_facts VALUES (1, 'kept')")
        db.execute(f"PRAGMA user_version={version}")
        db.commit()
    return path


def _archive(path, root, relative):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as archive:
        source = root / relative
        directory = tarfile.TarInfo(relative.as_posix())
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o700
        archive.addfile(directory)
        for file in sorted(source.rglob("*")):
            if not file.is_file():
                continue
            payload = file.read_bytes()
            member = tarfile.TarInfo((relative / file.relative_to(source)).as_posix())
            member.size = len(payload)
            member.mode = 0o600
            archive.addfile(member, io.BytesIO(payload))
    return path


def test_reviewed_payroll_settlement_pins_match_actual_history():
    repository = Path(__file__).resolve().parents[1]
    for path, transition in static_release.PINNED_PAYROLL_SETTLEMENT_SUPPORT_TRANSITIONS.items():
        assert static_release._tree_entry(repository, payroll_release.BASELINE_COMMIT, path) == transition[0]
        assert static_release._tree_entry(repository, payroll_release.TARGET_COMMIT, path) == transition[1]
        static_release._validate_paths(
            repository, payroll_release.BASELINE_COMMIT, payroll_release.TARGET_COMMIT, [path]
        )
    for path, transition in static_release.PINNED_PAYROLL_SETTLEMENT_CONTROL_TRANSITIONS.items():
        assert static_release._tree_entry(repository, payroll_release.BASELINE_COMMIT, path) == transition[0]
        assert static_release._tree_entry(repository, payroll_release.TARGET_COMMIT, path) == transition[1]
        static_release._validate_paths(
            repository, payroll_release.BASELINE_COMMIT, payroll_release.TARGET_COMMIT, [path]
        )
    with pytest.raises(RuntimeError, match="frontend release permits source files only"):
        static_release._validate_paths(
            repository,
            payroll_release.BASELINE_COMMIT,
            payroll_release.TARGET_COMMIT,
            ["frontend/tests/unit/unreviewed-payroll.spec.js"],
        )
    changed = subprocess.run(
        [
            "git", "-C", str(repository), "diff", "--name-only",
            payroll_release.BASELINE_COMMIT, payroll_release.TARGET_COMMIT,
        ],
        check=True, stdout=subprocess.PIPE, text=True,
    ).stdout.splitlines()
    with pytest.raises(RuntimeError, match="migration logic"):
        static_release._validate_paths(
            repository, payroll_release.BASELINE_COMMIT, payroll_release.TARGET_COMMIT, changed
        )


def test_v97_replica_trial_preserves_existing_facts_and_is_idempotent(tmp_path):
    repository = Path(__file__).resolve().parents[1]
    database = _database(tmp_path / "production.db")
    report = payroll_release.run_replica_trial(
        repository, payroll_release.TARGET_COMMIT, database
    )
    assert report["source"]["user_version"] == 96
    assert report["target"]["user_version"] == 97
    assert report["preserved_existing_table_count"] == 1
    assert report["source_database_unchanged"] is True
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 96
        assert db.execute("SELECT value FROM preserved_facts").fetchone()[0] == "kept"


def _prepared_migration_manifest(tmp_path):
    project = tmp_path / "project"
    (project / "data/attachments").mkdir(parents=True)
    (project / "public/static").mkdir(parents=True)
    (project / "data/attachments/document.txt").write_bytes(b"o" * 8192)
    (project / "public/static/index.html").write_text("old", encoding="utf-8")
    database = _database(project / "data/production.db")
    database_backup = tmp_path / "backup.db"
    shutil.copy2(database, database_backup)
    attachments = _archive(
        tmp_path / "attachments.tar.gz", project, Path("data/attachments")
    )
    release = _archive(
        tmp_path / "release.tar.gz", project, Path("public/static")
    )
    target_static = tmp_path / "target-static.tar.gz"
    (tmp_path / "target/public/static").mkdir(parents=True)
    (tmp_path / "target/public/static/index.html").write_text("new", encoding="utf-8")
    _archive(target_static, tmp_path / "target", Path("public/static"))
    metadata = tmp_path / "backup.json"
    deployment_manifest.create_backup_metadata(
        SimpleNamespace(
            database=str(database_backup),
            attachments=str(attachments),
            attachment_root=["data/attachments"],
            output=str(metadata),
        )
    )
    fence = project / "data/deployments/write-fence.json"
    fence.parent.mkdir(parents=True)
    deployment_manifest.acquire_write_fence(
        SimpleNamespace(
            path=str(fence),
            deployment_key="payroll-v97-test",
            target_commit=payroll_release.TARGET_COMMIT,
        )
    )
    manifest = project / "data/deployments/payroll-v97-test.json"
    payload = deployment_manifest.prepare_deployment_manifest(
        SimpleNamespace(
            scope=deployment_manifest.DEPLOYMENT_SCOPE_BACKEND_FRONTEND_MIGRATION,
            output=str(manifest),
            backup_metadata=str(metadata),
            release_backup=str(release),
            target_static_backup=str(target_static),
            deployment_key="payroll-v97-test",
            before_commit=payroll_release.BASELINE_COMMIT,
            target_commit=payroll_release.TARGET_COMMIT,
            target_database_version=97,
            write_fence=str(fence),
        )
    )
    return project, database, manifest, payload


def test_migration_manifest_declares_database_only_migration(tmp_path):
    _, _, _, manifest = _prepared_migration_manifest(tmp_path)
    assert manifest["operations"] == {
        "database_migration": True,
        "attachment_migration": False,
        "frontend_publish": True,
        "code_switch": True,
        "service_restart": True,
    }
    assert manifest["source_database_version"] == 96
    assert manifest["target_database_version"] == 97


def test_migration_rollback_refuses_attachment_drift_before_database_restore(tmp_path):
    project, database, manifest, _ = _prepared_migration_manifest(tmp_path)
    with closing(sqlite3.connect(database)) as db:
        db.execute("PRAGMA user_version=97")
        db.commit()
    (project / "data/attachments/document.txt").write_bytes(b"c" * 8192)
    with pytest.raises(RuntimeError, match="attachments changed"):
        deployment_manifest.restore_deployment(
            SimpleNamespace(
                manifest=str(manifest),
                database=str(database),
                project_root=str(project),
            )
        )
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 97


def test_migration_rollback_restores_v96_and_static_without_restoring_attachments(tmp_path):
    project, database, manifest, _ = _prepared_migration_manifest(tmp_path)
    with closing(sqlite3.connect(database)) as db:
        db.execute("PRAGMA user_version=97")
        db.commit()
    (project / "public/static/index.html").write_text("new", encoding="utf-8")
    deployment_manifest.restore_deployment(
        SimpleNamespace(
            manifest=str(manifest),
            database=str(database),
            project_root=str(project),
        )
    )
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 96
    assert (project / "public/static/index.html").read_text(encoding="utf-8") == "old"
    assert (project / "data/attachments/document.txt").read_bytes() == b"o" * 8192
    restored = deployment_manifest.read_json(manifest)
    assert restored["status"] == "data_restored"
    assert restored["rollback"]["restore_scope_verified"] is True


def test_launcher_switches_marker_before_checkout_and_bootstrap_pins_controls():
    repository = Path(__file__).resolve().parents[1]
    launcher = (repository / "scripts/deploy-payroll-settlement-v97.sh").read_text(encoding="utf-8")
    rollback = (repository / "scripts/rollback-deployment.sh").read_text(encoding="utf-8")
    marker = launcher.index("write-commit-marker")
    checkout = launcher.index('git -C "$PROJECT_ROOT" switch --detach "$TARGET_COMMIT"')
    assert marker < checkout
    assert "--scope backend_frontend_migration" in launcher
    assert "--target-database-version 97" in launcher
    assert "verify-attachments" in launcher
    assert (
        'deployment_scope" == "backend_frontend_static" || "$deployment_scope" == "backend_frontend_migration"'
        in rollback
    )
    assert "unchanged attachments verified" in rollback

    bootstrap = (repository / "scripts/bootstrap_payroll_settlement_v97_release.py").read_text(encoding="utf-8")
    for path in (
        "scripts/payroll_settlement_v97_release.py",
        "scripts/deploy-payroll-settlement-v97.sh",
        "scripts/deployment_manifest.py",
        "scripts/rollback-deployment.sh",
        "scripts/backup-db.sh",
    ):
        assert path in bootstrap
