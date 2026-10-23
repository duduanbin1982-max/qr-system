"""Contracts for the exact, check-only Task 7 release bootstrap."""

import importlib.util
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import bootstrap_task7_release_check as bootstrap
from scripts import code_only_release


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


def load_overlay_policy(path):
    sys.path.insert(0, str(path.parent))
    try:
        spec = importlib.util.spec_from_file_location("task7_bootstrap_policy", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)
        sys.modules.pop("deployment_manifest", None)


def test_exact_task7_transition_passes_overlay_preflight_without_production_writes(transition, tmp_path):
    project, tool, database = transition
    direct_result = code_only_release.validate_code_only_release(
        tool, project, database, bootstrap.BEFORE_COMMIT, bootstrap.TARGET_COMMIT,
    )
    assert direct_result["target_commit"] == bootstrap.TARGET_COMMIT

    approval = bootstrap.validate_transition(project, tool)
    database_before = database.read_bytes()
    marker_before = (project / ".deployed_commit").read_bytes()
    status_before = git(project, "status", "--porcelain=v1")
    launcher = bootstrap.prepare_overlay(tmp_path / "overlay", approval, project, tool)
    policy = load_overlay_policy(launcher.parent / "code_only_release.py")

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
    assert launcher.exists()


def test_task7_bootstrap_has_no_execute_mode():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/bootstrap_task7_release_check.py"), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--check-only" in result.stdout
    assert "--execute" not in result.stdout


def test_bootstrap_rejects_unexpected_changed_path(transition, monkeypatch):
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
    changed_target = git(tool, "rev-parse", "HEAD").decode().strip()
    monkeypatch.setattr(bootstrap, "TARGET_COMMIT", changed_target)

    with pytest.raises(RuntimeError, match="changed paths mismatch"):
        bootstrap.validate_transition(transition[0], tool, changed_target)


def test_bootstrap_rejects_target_launcher_blob_drift(transition, monkeypatch):
    _, tool, _ = transition
    write(tool / bootstrap.LAUNCHER_PATH, "#!/bin/sh\nexit 0\n")
    git(tool, "add", "--", bootstrap.LAUNCHER_PATH)
    subprocess.run(
        [
            "git", "-C", str(tool), "-c", "user.name=Bootstrap Test",
            "-c", "user.email=bootstrap@example.invalid", "commit", "--quiet",
            "-m", "unapproved launcher content",
        ],
        check=True,
    )
    changed_target = git(tool, "rev-parse", "HEAD").decode().strip()
    monkeypatch.setattr(bootstrap, "TARGET_COMMIT", changed_target)

    with pytest.raises(RuntimeError, match="target entry mismatch"):
        bootstrap.validate_transition(transition[0], tool, changed_target)


def test_bootstrap_rejects_production_changes_outside_data(transition):
    project, tool, _ = transition
    write(project / "unexpected.txt", "local mutation\n")
    with pytest.raises(RuntimeError, match="production worktree is not clean"):
        bootstrap.validate_transition(project, tool)


def test_overlay_patch_points_fail_closed(transition, tmp_path, monkeypatch):
    project, tool, _ = transition
    approval = bootstrap.validate_transition(project, tool)
    original = bootstrap._regular_file

    def drifted_file(root, path):
        content = original(root, path)
        if path == "scripts/code_only_release.py":
            return content + b"\n# unreviewed drift\n"
        return content

    monkeypatch.setattr(bootstrap, "_regular_file", drifted_file)
    with pytest.raises(RuntimeError, match="control drifted"):
        bootstrap.prepare_overlay(tmp_path / "overlay", approval, project, tool)
