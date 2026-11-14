import sqlite3
import shutil
import subprocess
from contextlib import closing
from pathlib import Path

import pytest
import conftest

from scripts import backend_frontend_static_release as static_release
from scripts import payroll_audit_v100_release as payroll_release


def _database(path, version=98):
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(conftest.TEST_TEMPLATE_DB, path)
    with closing(sqlite3.connect(path)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        if version == payroll_release.SOURCE_SCHEMA:
            for trigger in (
                "trg_payroll_audit_finding_definition_immutable",
                "trg_payroll_audit_finding_resolution_once",
                "trg_payroll_audit_finding_no_delete",
                "prevent_invalid_payroll_batch_transition",
                "protect_payroll_batch_amounts",
                "protect_payroll_audit_rule_version",
            ):
                db.execute(f'DROP TRIGGER IF EXISTS "{trigger}"')
            db.execute("DROP TABLE payroll_audit_findings")
            db.execute("ALTER TABLE payroll_batches DROP COLUMN audit_rule_version")
            db.execute("ALTER TABLE payroll_batches DROP COLUMN audit_run_version")
            db.execute(f"PRAGMA user_version={payroll_release.SOURCE_SCHEMA}")
        elif version != payroll_release.TARGET_SCHEMA:
            raise ValueError(f"unsupported test schema version: {version}")
        db.execute(
            "INSERT INTO users(id, username, password, name, role) "
            "VALUES (999999, 'release-test', 'x', 'Release Test', 'admin')"
        )
        db.execute(
            "INSERT INTO payroll_batches(id, payroll_month, version, period_start, period_end, "
            "source_cutoff_at, status) VALUES (1, '2026-01', 1, '2026-01-01', "
            "'2026-01-31', '2026-02-01', 'draft')"
        )
        db.execute(
            "INSERT INTO payroll_employee_lines(id, batch_id, employee_name_snapshot, payable_wage_cents) "
            "VALUES (1, 1, 'Release Test', 12500)"
        )
        db.execute(
            "INSERT INTO payroll_adjustments(id, employee_name_snapshot, payroll_month, "
            "adjustment_type, amount_cents, reason) VALUES (1, 'Release Test', '2026-01', "
            "'bonus', 100, 'preserve')"
        )
        db.execute("CREATE TABLE preserved_facts(id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("INSERT INTO preserved_facts VALUES (1, 'unchanged')")
        db.commit()
    return path


def test_reviewed_v98_to_v100_transition_matches_actual_history():
    repository = Path(__file__).resolve().parents[1]
    changed = payroll_release.validate_business_transition(
        repository,
        payroll_release.BASELINE_COMMIT,
        payroll_release.TARGET_COMMIT,
    )

    assert len(changed) == 28
    assert set(payroll_release.MIGRATION_TRANSITIONS) == {
        "modules/migration_catalog.py",
        "modules/migration_payroll_audit.py",
        "modules/migration_payroll_audit_policy.py",
    }
    assert payroll_release.TARGET_COMMIT == "4c662f8b807a82bcaa298f663d49b39a28823d0f"


def test_unreviewed_or_repointed_paths_fail_closed(monkeypatch):
    repository = Path(__file__).resolve().parents[1]
    monkeypatch.setitem(
        payroll_release.SUPPORT_TRANSITIONS,
        "scripts/unreviewed-helper.py",
        (None, None),
    )
    with pytest.raises(RuntimeError, match="reviewed V98->V100 transition"):
        payroll_release.validate_business_transition(
            repository,
            payroll_release.BASELINE_COMMIT,
            payroll_release.TARGET_COMMIT,
        )

    monkeypatch.delitem(payroll_release.SUPPORT_TRANSITIONS, "scripts/unreviewed-helper.py")
    monkeypatch.setitem(
        payroll_release.MIGRATION_TRANSITIONS,
        "modules/migration_catalog.py",
        (None, ("100644", "blob", "0" * 40)),
    )
    with pytest.raises(RuntimeError, match="mode/blob transition mismatch"):
        payroll_release.validate_business_transition(
            repository,
            payroll_release.BASELINE_COMMIT,
            payroll_release.TARGET_COMMIT,
        )


def test_generic_static_gate_still_rejects_migrations_and_tests():
    repository = Path(__file__).resolve().parents[1]
    with pytest.raises(RuntimeError, match="migration logic"):
        static_release._validate_paths(
            repository,
            payroll_release.BASELINE_COMMIT,
            payroll_release.TARGET_COMMIT,
            ["modules/migration_catalog.py"],
        )
    with pytest.raises(RuntimeError):
        static_release._validate_paths(
            repository,
            payroll_release.BASELINE_COMMIT,
            payroll_release.TARGET_COMMIT,
            ["frontend/tests/unit/payroll-audit-behavior.spec.js"],
        )


@pytest.mark.parametrize(
    ("corruption", "message"),
    [
        ("column", "columns"),
        ("column-definition", "invalid_column_definitions"),
        ("index", "invalid_indexes"),
        ("trigger", "invalid_triggers"),
    ],
)
def test_schema_acceptance_rejects_wrong_v100_columns_indexes_and_triggers(
    tmp_path, corruption, message
):
    database = _database(tmp_path / "schema.db", version=payroll_release.TARGET_SCHEMA)
    with closing(sqlite3.connect(database)) as db:
        if corruption == "column":
            db.execute(
                "ALTER TABLE payroll_reconciliation_items DROP COLUMN detail_json"
            )
        elif corruption == "column-definition":
            db.execute(
                "ALTER TABLE payroll_reconciliation_items DROP COLUMN detail_json"
            )
            db.execute(
                "ALTER TABLE payroll_reconciliation_items "
                "ADD COLUMN detail_json INTEGER NOT NULL DEFAULT 1"
            )
        elif corruption == "index":
            db.execute("DROP INDEX idx_payroll_audit_findings_current")
            db.execute(
                "CREATE INDEX idx_payroll_audit_findings_current "
                "ON payroll_audit_findings(subject_id)"
            )
        else:
            db.execute("DROP TRIGGER protect_closed_payroll_settlement")
            db.execute(
                "CREATE TRIGGER protect_closed_payroll_settlement "
                "BEFORE UPDATE ON payroll_settlements "
                "BEGIN SELECT 1; END"
            )
        db.commit()

    with pytest.raises(RuntimeError, match=message):
        payroll_release._schema_acceptance(database, payroll_release.TARGET_SCHEMA)


@pytest.mark.parametrize("mismatch", ["directory", "sha"])
def test_production_migration_rejects_unverified_target_root(tmp_path, monkeypatch, mismatch):
    project = tmp_path / "production-target"
    other_target = tmp_path / "other-target"
    project.mkdir()
    other_target.mkdir()
    database = tmp_path / "production.db"
    database.touch()
    manifest = {
        "scope": payroll_release.deployment_manifest.DEPLOYMENT_SCOPE_BACKEND_FRONTEND_MIGRATION,
        "status": "backup_verified",
        "before_commit": payroll_release.BASELINE_COMMIT,
        "target_commit": payroll_release.TARGET_COMMIT,
    }
    monkeypatch.setattr(
        payroll_release.deployment_manifest,
        "read_json",
        lambda _path: {},
    )
    monkeypatch.setattr(
        payroll_release.deployment_manifest,
        "require_schema",
        lambda *_args: manifest,
    )
    monkeypatch.setattr(
        payroll_release.deployment_manifest,
        "_active_fence_for_manifest",
        lambda _manifest: None,
    )
    observed_head = (
        payroll_release.BASELINE_COMMIT if mismatch == "sha" else payroll_release.TARGET_COMMIT
    )
    monkeypatch.setattr(
        payroll_release,
        "_git",
        lambda *_args, **_kwargs: observed_head,
    )
    target_root = other_target if mismatch == "directory" else project

    expected_error = "migration target root" if mismatch == "directory" else "target checkout"
    with pytest.raises(RuntimeError, match=expected_error):
        payroll_release.migrate_production(
            target_root,
            database,
            tmp_path / "manifest.json",
            project,
        )


def test_database_space_estimate_includes_sqlite_wal_file(tmp_path):
    database = tmp_path / "production.db"
    database.write_bytes(b"database")
    wal = Path(str(database) + "-wal")
    wal.write_bytes(b"live-wal-pages")

    assert payroll_release._database_footprint(database) == database.stat().st_size + wal.stat().st_size


def test_launcher_keeps_v100_migration_inside_the_backup_fence_and_rollback_flow():
    repository = Path(__file__).resolve().parents[1]
    launcher = (repository / "scripts/deploy-payroll-audit-v100.sh").read_text(
        encoding="utf-8"
    )
    bootstrap = (
        repository / "scripts/bootstrap_payroll_audit_v100_release.py"
    ).read_text(encoding="utf-8")
    backup = launcher.index('bash "$BACKUP"')
    prepare = launcher.index('prepare --scope backend_frontend_migration')
    marker = launcher.index('write-commit-marker --project-root "$PROJECT_ROOT"')
    checkout = launcher.index('git -C "$PROJECT_ROOT" switch --detach "$TARGET_COMMIT"')
    migrate = launcher.index('python3 "$RELEASE_TOOL" migrate')
    accept = launcher.index('python3 "$RELEASE_TOOL" acceptance')
    release_fence = launcher.index('release-fence --manifest "$MANIFEST" --mode deployment')

    assert backup < prepare < marker < checkout < migrate < accept < release_fence
    assert "--target-database-version 100" in launcher
    assert "payroll_audit_v100_release.py" in bootstrap
    assert "deploy-payroll-audit-v100.sh" in bootstrap
    assert "payroll_risk_closure_v98_release.py" not in bootstrap
    assert 'bash "$ROLLBACK" "$MANIFEST"' in launcher
    assert "service stopped and fence retained" in launcher


def test_v100_replica_trial_preserves_v98_facts_and_is_idempotent(tmp_path):
    repository = Path(__file__).resolve().parents[1]
    database = _database(tmp_path / "production.db")

    report = payroll_release.run_replica_trial(
        repository, payroll_release.TARGET_COMMIT, database
    )

    assert report["source"]["user_version"] == 98
    assert report["target"]["user_version"] == 100
    assert report["target"]["integrity_check"] == "ok"
    assert report["target"]["foreign_key_error_count"] == 0
    assert report["preserved_existing_table_count"] >= 10
    assert report["source_database_read_only"] is True
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 98
        assert db.execute("SELECT value FROM preserved_facts").fetchone()[0] == "unchanged"
        assert db.execute(
            "SELECT payable_wage_cents FROM payroll_employee_lines WHERE id=1"
        ).fetchone()[0] == 12500
        assert db.execute("SELECT reason FROM payroll_adjustments WHERE id=1").fetchone()[0] == "preserve"


def test_preflight_accepts_only_reviewed_tool_commit_and_v98_production(tmp_path, monkeypatch):
    repository = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(payroll_release, "_assert_clean", lambda *_args, **_kwargs: None)
    project = tmp_path / "production"
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "worktree",
            "add",
            "--quiet",
            "--detach",
            str(project),
            payroll_release.BASELINE_COMMIT,
        ],
        check=True,
    )
    try:
        (project / ".deployed_commit").write_text(
            payroll_release.BASELINE_COMMIT + "\n", encoding="ascii"
        )
        database = _database(project / "data/production.db")
        result = payroll_release.validate_release(
            repository,
            project,
            database,
            payroll_release.BASELINE_COMMIT,
            payroll_release.TARGET_COMMIT,
        )

        assert result["tool_commit"] == subprocess.check_output(
            ["git", "-C", str(repository), "rev-parse", "HEAD"], text=True
        ).strip()
        assert result["source_schema_version"] == 98
        assert result["target_schema_version"] == 100
        assert result["replica_trial"]["target"]["user_version"] == 100
        assert set(result["changed_paths"]) == set(
            {
                *payroll_release.MIGRATION_TRANSITIONS,
                *payroll_release.SUPPORT_TRANSITIONS,
                *payroll_release.CONTROL_TRANSITIONS,
            }
        )
    finally:
        subprocess.run(
            ["git", "-C", str(repository), "worktree", "remove", "--force", str(project)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def test_failed_replica_migration_does_not_change_source_database(tmp_path, monkeypatch):
    repository = Path(__file__).resolve().parents[1]
    database = _database(tmp_path / "production.db")

    def fail_migration(_target_root, _replica):
        raise RuntimeError("injected replica failure")

    monkeypatch.setattr(payroll_release, "_run_target_migrations", fail_migration)
    with pytest.raises(RuntimeError, match="injected replica failure"):
        payroll_release.run_replica_trial(
            repository, payroll_release.TARGET_COMMIT, database
        )

    with closing(sqlite3.connect(database)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 98
        assert db.execute("SELECT value FROM preserved_facts").fetchone()[0] == "unchanged"
