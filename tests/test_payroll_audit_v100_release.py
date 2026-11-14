import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path

import pytest

from scripts import backend_frontend_static_release as static_release
from scripts import payroll_audit_v100_release as payroll_release


def _database(path, version=98):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript(
            """
            CREATE TABLE users(id INTEGER PRIMARY KEY);
            CREATE TABLE payroll_batches(
                id INTEGER PRIMARY KEY,
                status TEXT NOT NULL,
                superseded_by_batch_id INTEGER,
                legacy_imported INTEGER NOT NULL DEFAULT 0,
                payroll_month TEXT NOT NULL DEFAULT '',
                version INTEGER NOT NULL DEFAULT 1,
                period_start TEXT NOT NULL DEFAULT '',
                period_end TEXT NOT NULL DEFAULT '',
                source_cutoff_at TEXT NOT NULL DEFAULT '',
                input_digest TEXT NOT NULL DEFAULT '',
                normal_wage_cents INTEGER NOT NULL DEFAULT 0,
                rework_wage_cents INTEGER NOT NULL DEFAULT 0,
                bonus_cents INTEGER NOT NULL DEFAULT 0,
                allowance_cents INTEGER NOT NULL DEFAULT 0,
                deduction_cents INTEGER NOT NULL DEFAULT 0,
                payable_wage_cents INTEGER NOT NULL DEFAULT 0,
                source_record_count INTEGER NOT NULL DEFAULT 0,
                priced_record_count INTEGER NOT NULL DEFAULT 0,
                exception_count INTEGER NOT NULL DEFAULT 0,
                prepared_by INTEGER,
                prepared_at TEXT NOT NULL DEFAULT '',
                row_version INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE payroll_employee_lines(
                id INTEGER PRIMARY KEY,
                batch_id INTEGER NOT NULL,
                payable_wage_cents INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(batch_id) REFERENCES payroll_batches(id)
            );
            CREATE TABLE payroll_adjustments(
                id INTEGER PRIMARY KEY,
                reason TEXT NOT NULL
            );
            CREATE TABLE payroll_settlements(
                id INTEGER PRIMARY KEY,
                batch_id INTEGER NOT NULL,
                FOREIGN KEY(batch_id) REFERENCES payroll_batches(id)
            );
            CREATE TABLE payroll_export_items(
                id INTEGER PRIMARY KEY,
                export_batch_id INTEGER NOT NULL,
                payable_cents INTEGER NOT NULL
            );
            CREATE TABLE preserved_facts(id INTEGER PRIMARY KEY, value TEXT NOT NULL);
            """
        )
        for table in sorted(
            payroll_release.REQUIRED_TABLES
            - {
                "payroll_audit_findings",
                "payroll_batches",
                "payroll_employee_lines",
                "payroll_adjustments",
                "payroll_settlements",
                "payroll_export_items",
            }
        ):
            db.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY)')
        v98_triggers = payroll_release.REQUIRED_TRIGGERS - {
            "trg_payroll_settlement_current_batch_insert",
            "trg_payroll_settlement_batch_immutable",
            "trg_payroll_settled_batch_immutable",
            "trg_payroll_batch_nonnegative_transition",
            "trg_payroll_employee_line_insert_immutable",
            "trg_payroll_export_item_nonnegative",
            "trg_payroll_audit_finding_definition_immutable",
            "trg_payroll_audit_finding_resolution_once",
            "trg_payroll_audit_finding_no_delete",
            "prevent_invalid_payroll_batch_transition",
            "protect_payroll_batch_amounts",
            "protect_payroll_audit_rule_version",
        }
        for trigger in sorted(v98_triggers):
            db.execute(
                f'CREATE TRIGGER "{trigger}" BEFORE INSERT ON preserved_facts '
                "BEGIN SELECT 1; END"
            )
        db.execute("INSERT INTO users(id) VALUES (1)")
        db.execute("INSERT INTO payroll_batches(id, status) VALUES (1, 'draft')")
        db.execute("INSERT INTO payroll_employee_lines(id, batch_id, payable_wage_cents) VALUES (1, 1, 12500)")
        db.execute("INSERT INTO payroll_adjustments(id, reason) VALUES (1, 'preserve')")
        db.execute("INSERT INTO preserved_facts VALUES (1, 'unchanged')")
        db.commit()
        from modules.migration_payroll_risk_closure import m098_payroll_risk_closure

        m098_payroll_risk_closure(db)
        db.execute(f"PRAGMA user_version={version}")
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


def test_preflight_accepts_only_reviewed_tool_commit_and_v98_production(tmp_path):
    repository = Path(__file__).resolve().parents[1]
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
