"""Contracts for the one-time Task 8 release-control bootstrap."""

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import bootstrap_task8_release_control as bootstrap


ROOT = Path(__file__).resolve().parents[1]


def git(root, *arguments):
    return subprocess.check_output(["git", "-C", str(root), *arguments])


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))


@pytest.fixture
def transition(tmp_path):
    project = tmp_path / "production"
    tool = tmp_path / "tool"
    # Preserve committed bytes without changing the developer's Git configuration.
    git(ROOT, "-c", "core.autocrlf=false", "worktree", "add", "--quiet", "--detach", str(project), bootstrap.BEFORE_COMMIT)
    git(ROOT, "-c", "core.autocrlf=false", "worktree", "add", "--quiet", "--detach", str(tool), bootstrap.TARGET_COMMIT)
    try:
        write(project / ".deployed_commit", bootstrap.BEFORE_COMMIT + "\n")
        database = project / "data/production.db"
        database.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE facts (quantity INTEGER)")
            connection.execute("INSERT INTO facts VALUES (12)")
            connection.execute("PRAGMA user_version=96")
        yield project, tool, database
    finally:
        subprocess.run(
            ["git", "-C", str(ROOT), "worktree", "remove", "--force", str(tool)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["git", "-C", str(ROOT), "worktree", "remove", "--force", str(project)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def load_policy(path):
    import importlib.util

    sys.path.insert(0, str(path.parent))
    try:
        spec = importlib.util.spec_from_file_location("task8_bootstrap_policy", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)
        sys.modules.pop("deployment_manifest", None)


def test_exact_transition_passes_only_in_overlay_and_preserves_production(transition, tmp_path):
    project, tool, database = transition
    approval = bootstrap.validate_transition(project, tool)
    database_before = database.read_bytes()
    marker_before = (project / ".deployed_commit").read_bytes()
    status_before = git(project, "status", "--porcelain=v1")

    launcher = bootstrap.prepare_overlay(tmp_path / "overlay", approval, project, tool)
    policy = load_policy(launcher.parent / "code_only_release.py")
    result = policy.validate_code_only_release(
        tool, project, database, bootstrap.BEFORE_COMMIT, bootstrap.TARGET_COMMIT,
    )

    assert result["target_commit"] == bootstrap.TARGET_COMMIT
    assert result["changed_paths"] == sorted(bootstrap.TARGET_ENTRIES)
    assert result["database"]["user_version"] == 96
    assert database.read_bytes() == database_before
    assert (project / ".deployed_commit").read_bytes() == marker_before
    assert git(project, "status", "--porcelain=v1") == status_before
    assert git(project, "rev-parse", "HEAD").decode().strip() == bootstrap.BEFORE_COMMIT
    assert not (project / "data/deployments").exists()


def test_bootstrap_exposes_separate_check_only_and_execute_modes():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/bootstrap_task8_release_control.py"), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--check-only" in result.stdout
    assert "--execute" in result.stdout


def test_execute_receipt_is_exclusive_and_records_fixed_scope(tmp_path):
    receipt = tmp_path / "data/deployments/task8.bootstrap.json"
    approval = {
        "before_commit": bootstrap.BEFORE_COMMIT,
        "target_commit": bootstrap.TARGET_COMMIT,
        "changed_paths": sorted(bootstrap.TARGET_ENTRIES),
        "bootstrap_sha256": "a" * 64,
        "mode": "check_only",
    }
    bootstrap._write_receipt(receipt, approval, "task8-key", 1000, 1004)
    saved = receipt.read_bytes()
    import json

    payload = json.loads(saved)
    assert payload["scope"] == "task8_release_control_code_only_execute"
    assert payload["operator_user_id"] == 1000
    assert payload["approver_user_id"] == 1004
    assert payload["database_migration"] is False
    assert payload["attachment_migration"] is False
    assert payload["frontend_migration"] is False
    with pytest.raises(FileExistsError):
        bootstrap._write_receipt(receipt, approval, "task8-key", 1000, 1004)
    assert receipt.read_bytes() == saved


@pytest.mark.parametrize("operator,approver", [(0, 1004), (1000, 0), (1000, 1000)])
def test_execute_rejects_invalid_or_non_independent_identity(operator, approver):
    with pytest.raises(RuntimeError, match="IDs must"):
        bootstrap._validate_identity(operator, approver)


def test_execute_rejects_unreviewed_bootstrap_digest_before_receipt(transition):
    project, tool, _ = transition
    with pytest.raises(RuntimeError, match="does not match"):
        bootstrap.run_execute(
            project_root=project,
            tool_root=tool,
            target_commit=bootstrap.TARGET_COMMIT,
            deployment_key="task8-digest-mismatch",
            approved_bootstrap_sha256="0" * 64,
            operator_user_id=1000,
            approver_user_id=1004,
        )
    assert not (project / "data/deployments/task8-digest-mismatch.bootstrap.json").exists()


def test_execute_persists_scope_receipt_before_invoking_launcher(transition, monkeypatch):
    project, tool, database = transition
    approval = bootstrap.validate_transition(project, tool)
    database_before = database.read_bytes()
    observed = {}

    def record_invocation(**arguments):
        receipt = project / "data/deployments/task8-execute.bootstrap.json"
        observed["receipt_exists_before_launcher"] = receipt.is_file()
        observed["mode"] = arguments["mode"]
        observed["project"] = arguments["project"]
        observed["target"] = arguments["approval"]["target_commit"]

    monkeypatch.setattr(bootstrap, "_invoke_launcher", record_invocation)
    bootstrap.run_execute(
        project_root=project,
        tool_root=tool,
        target_commit=bootstrap.TARGET_COMMIT,
        deployment_key="task8-execute",
        approved_bootstrap_sha256=approval["bootstrap_sha256"],
        operator_user_id=1000,
        approver_user_id=1004,
    )

    import json

    receipt = project / "data/deployments/task8-execute.bootstrap.json"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert observed == {
        "receipt_exists_before_launcher": True,
        "mode": "--execute",
        "project": project.resolve(),
        "target": bootstrap.TARGET_COMMIT,
    }
    assert payload["operator_user_id"] == 1000
    assert payload["approver_user_id"] == 1004
    assert payload["database_migration"] is False
    assert payload["attachment_migration"] is False
    assert payload["frontend_migration"] is False
    assert database.read_bytes() == database_before
    assert git(project, "rev-parse", "HEAD").decode().strip() == bootstrap.BEFORE_COMMIT


def test_execute_requires_explicit_identity_and_bootstrap_digest():
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/bootstrap_task8_release_control.py"),
            "--project-root",
            str(ROOT),
            "--tool-root",
            str(ROOT),
            "--target-commit",
            bootstrap.TARGET_COMMIT,
            "--deployment-key",
            "task8",
            "--execute",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "requires" in result.stderr


def test_rejects_unapproved_changed_path(transition, monkeypatch):
    _, tool, _ = transition
    write(tool / "tests/unapproved_bootstrap_scope.py", "VALUE = True\n")
    git(tool, "add", "--", "tests/unapproved_bootstrap_scope.py")
    subprocess.run(
        [
            "git", "-C", str(tool), "-c", "user.name=Bootstrap Test",
            "-c", "user.email=bootstrap@example.invalid", "commit", "--quiet",
            "-m", "unapproved extra path",
        ],
        check=True,
    )
    monkeypatch.setattr(bootstrap, "TARGET_COMMIT", git(tool, "rev-parse", "HEAD").decode().strip())
    with pytest.raises(RuntimeError, match="changed paths mismatch"):
        bootstrap.validate_transition(transition[0], tool, git(tool, "rev-parse", "HEAD").decode().strip())


def test_rejects_policy_blob_drift(transition, monkeypatch):
    _, tool, _ = transition
    write(tool / bootstrap.POLICY_PATH, "# unapproved policy drift\n")
    git(tool, "add", "--", bootstrap.POLICY_PATH)
    subprocess.run(
        [
            "git", "-C", str(tool), "-c", "user.name=Bootstrap Test",
            "-c", "user.email=bootstrap@example.invalid", "commit", "--quiet",
            "-m", "unapproved policy drift",
        ],
        check=True,
    )
    monkeypatch.setattr(bootstrap, "TARGET_COMMIT", git(tool, "rev-parse", "HEAD").decode().strip())
    with pytest.raises(RuntimeError, match="target entry mismatch"):
        bootstrap.validate_transition(transition[0], tool, git(tool, "rev-parse", "HEAD").decode().strip())


def test_overlay_patch_fails_closed_when_target_policy_drifts(transition, tmp_path, monkeypatch):
    project, tool, _ = transition
    approval = bootstrap.validate_transition(project, tool)
    original = bootstrap._git

    def drifted_git(root, *arguments, **kwargs):
        result = original(root, *arguments, **kwargs)
        if arguments[:2] == ("show", f"{bootstrap.TARGET_COMMIT}:{bootstrap.POLICY_PATH}"):
            result.stdout += b"\n# unapproved drift\n"
        return result

    monkeypatch.setattr(bootstrap, "_git", drifted_git)
    with pytest.raises(RuntimeError, match="target release policy drifted"):
        bootstrap.prepare_overlay(tmp_path / "overlay", approval, project, tool)
