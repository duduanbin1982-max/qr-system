import shutil
import sqlite3
import tarfile
import io
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import backend_frontend_static_release as static_release
from scripts import deployment_manifest
from scripts import payroll_risk_closure_v98_release as payroll_release


def _database(path, version=97):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE preserved_facts (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("INSERT INTO preserved_facts VALUES (1, 'kept')")
        db.execute(
            "CREATE TABLE payroll_batches ("
            "id INTEGER PRIMARY KEY, status TEXT NOT NULL, "
            "superseded_by_batch_id INTEGER, legacy_imported INTEGER NOT NULL DEFAULT 0)"
        )
        db.execute(
            "CREATE TABLE payroll_settlements (id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL)"
        )
        db.execute(
            "CREATE TABLE payroll_export_items ("
            "id INTEGER PRIMARY KEY, export_batch_id INTEGER NOT NULL, payable_cents INTEGER NOT NULL)"
        )
        db.execute("CREATE TABLE payroll_adjustments (id INTEGER PRIMARY KEY, reason TEXT NOT NULL)")
        db.execute("INSERT INTO payroll_adjustments VALUES (1, 'kept adjustment')")
        db.execute(
            "CREATE TABLE payroll_employee_lines ("
            "id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL, payable_wage_cents INTEGER NOT NULL)"
        )
        for table in sorted(
            payroll_release.REQUIRED_TABLES
            - {"payroll_settlements", "payroll_export_items"}
        ):
            db.execute(f'CREATE TABLE IF NOT EXISTS "{table}" (id INTEGER PRIMARY KEY)')
        for trigger in sorted(
            payroll_release.REQUIRED_TRIGGERS
            - {
                "trg_payroll_settlement_current_batch_insert",
                "trg_payroll_settlement_batch_immutable",
                "trg_payroll_settled_batch_immutable",
                "trg_payroll_batch_nonnegative_transition",
                "trg_payroll_employee_line_insert_immutable",
                "trg_payroll_export_item_nonnegative",
            }
        ):
            db.execute(
                f'CREATE TRIGGER "{trigger}" BEFORE INSERT ON preserved_facts '
                "BEGIN SELECT 1; END"
            )
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


def test_reviewed_payroll_risk_closure_pins_match_actual_history():
    repository = Path(__file__).resolve().parents[1]
    transitions = {
        **payroll_release.MIGRATION_TRANSITIONS,
        **payroll_release.SUPPORT_TRANSITIONS,
        **payroll_release.CONTROL_TRANSITIONS,
    }
    for path, transition in transitions.items():
        assert static_release._tree_entry(repository, payroll_release.BASELINE_COMMIT, path) == transition[0]
        assert static_release._tree_entry(repository, payroll_release.TARGET_COMMIT, path) == transition[1]
    with pytest.raises(RuntimeError, match="frontend release permits source files only"):
        static_release._validate_paths(
            repository,
            payroll_release.BASELINE_COMMIT,
            payroll_release.TARGET_COMMIT,
            ["frontend/tests/unit/unreviewed-payroll.spec.js"],
        )
    with pytest.raises(RuntimeError, match="migration logic"):
        static_release._validate_paths(
            repository,
            payroll_release.BASELINE_COMMIT,
            payroll_release.TARGET_COMMIT,
            ["modules/migration_catalog.py"],
        )


def test_v98_replica_trial_preserves_existing_facts_and_is_idempotent(
    tmp_path, monkeypatch
):
    repository = Path(__file__).resolve().parents[1]
    monkeypatch.delenv("SECRET_KEY", raising=False)
    database = _database(tmp_path / "production.db")
    report = payroll_release.run_replica_trial(
        repository, payroll_release.TARGET_COMMIT, database
    )
    assert report["source"]["user_version"] == 97
    assert report["target"]["user_version"] == 98
    assert report["preserved_existing_table_count"] >= 13
    assert report["source_database_unchanged"] is True
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 97
        assert db.execute("SELECT value FROM preserved_facts").fetchone()[0] == "kept"
        assert db.execute(
            "SELECT reason FROM payroll_adjustments WHERE id=1"
        ).fetchone()[0] == "kept adjustment"


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
            deployment_key="payroll-v98-test",
            target_commit=payroll_release.TARGET_COMMIT,
        )
    )
    manifest = project / "data/deployments/payroll-v98-test.json"
    payload = deployment_manifest.prepare_deployment_manifest(
        SimpleNamespace(
            scope=deployment_manifest.DEPLOYMENT_SCOPE_BACKEND_FRONTEND_MIGRATION,
            output=str(manifest),
            backup_metadata=str(metadata),
            release_backup=str(release),
            target_static_backup=str(target_static),
            deployment_key="payroll-v98-test",
            before_commit=payroll_release.BASELINE_COMMIT,
            target_commit=payroll_release.TARGET_COMMIT,
            target_database_version=98,
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
    assert manifest["source_database_version"] == 97
    assert manifest["target_database_version"] == 98


def test_migration_rollback_refuses_attachment_drift_before_database_restore(tmp_path):
    project, database, manifest, _ = _prepared_migration_manifest(tmp_path)
    with closing(sqlite3.connect(database)) as db:
        db.execute("PRAGMA user_version=98")
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
        assert db.execute("PRAGMA user_version").fetchone()[0] == 98


def test_migration_rollback_restores_v97_and_static_without_restoring_attachments(tmp_path):
    project, database, manifest, _ = _prepared_migration_manifest(tmp_path)
    with closing(sqlite3.connect(database)) as db:
        db.execute("PRAGMA user_version=98")
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
        assert db.execute("PRAGMA user_version").fetchone()[0] == 97
    assert (project / "public/static/index.html").read_text(encoding="utf-8") == "old"
    assert (project / "data/attachments/document.txt").read_bytes() == b"o" * 8192
    restored = deployment_manifest.read_json(manifest)
    assert restored["status"] == "data_restored"
    assert restored["rollback"]["restore_scope_verified"] is True


def test_launcher_switches_marker_before_checkout_and_bootstrap_pins_controls():
    repository = Path(__file__).resolve().parents[1]
    launcher = (repository / "scripts/deploy-payroll-risk-closure-v98.sh").read_text(encoding="utf-8")
    rollback = (repository / "scripts/rollback-deployment.sh").read_text(encoding="utf-8")
    marker = launcher.index("write-commit-marker")
    checkout = launcher.index('git -C "$PROJECT_ROOT" switch --detach "$TARGET_COMMIT"')
    assert marker < checkout
    assert "--scope backend_frontend_migration" in launcher
    assert "--target-database-version 98" in launcher
    assert "verify-attachments" in launcher
    early_failure = launcher.index('if [[ "$PREPARED" == true ]]')
    early_recovery = launcher.index(
        'systemctl --user start qr-system.service || true', early_failure
    )
    fenced_health = launcher.index(
        'wait_health "$EXPECTED_BEFORE" true "$DEPLOYMENT_KEY"', early_recovery
    )
    abandon = launcher.index('abandon-fence', fenced_health)
    unfenced_health = launcher.index(
        'wait_health "$EXPECTED_BEFORE" false ""', abandon
    )
    assert early_recovery < fenced_health < abandon < unfenced_health
    assert "service stopped and fence retained" in launcher
    assert "service stopped and fence restored" in launcher
    assert (
        'deployment_scope" == "backend_frontend_static" || "$deployment_scope" == "backend_frontend_migration"'
        in rollback
    )
    assert "unchanged attachments verified" in rollback

    bootstrap = (repository / "scripts/bootstrap_payroll_risk_closure_v98_release.py").read_text(encoding="utf-8")
    for path in (
        "scripts/payroll_risk_closure_v98_release.py",
        "scripts/deploy-payroll-risk-closure-v98.sh",
        "scripts/deployment_manifest.py",
        "scripts/rollback-deployment.sh",
        "scripts/backup-db.sh",
    ):
        assert path in bootstrap
