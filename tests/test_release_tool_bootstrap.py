"""Behavior tests for the Task 6 release-tool bootstrap bridge."""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import bootstrap_release_tool as bootstrap


ROOT = Path(__file__).resolve().parents[1]


def git(root, *args, input_bytes=None):
    return subprocess.check_output(["git", "-C", str(root), *args], input=input_bytes)


def git_exists(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False).returncode == 0


def write(root, relative, content):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode())


def stage(root, relative, mode="100644"):
    oid = git(root, "hash-object", "-w", "--stdin", input_bytes=(root / relative).read_bytes()).decode().strip()
    git(root, "update-index", "--add", "--cacheinfo", mode, oid, relative)
    git(root, "checkout-index", "--force", "--", relative)


@pytest.fixture
def transition(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    repository.mkdir()
    git(repository, "init", "--quiet", "--initial-branch=master")
    git(repository, "config", "user.name", "Bootstrap Test")
    git(repository, "config", "user.email", "bootstrap@example.invalid")
    write(repository, ".gitignore", ".deployed_commit\n")
    stage(repository, ".gitignore")
    for path, (mode, _) in bootstrap.CONTROL_ENTRIES.items():
        write(repository, path, git(ROOT, "show", f"{bootstrap.BEFORE}:{path}"))
        stage(repository, path, mode)
    for path, (mode, _) in bootstrap.TARGET_ENTRIES.items():
        baseline = git(ROOT, "show", f"{bootstrap.BEFORE}:{path}") if git_exists(ROOT, "cat-file", "-e", f"{bootstrap.BEFORE}:{path}") else b""
        write(repository, path, baseline)
        stage(repository, path, mode)
    git(repository, "commit", "--quiet", "-m", "approved baseline")
    before = git(repository, "rev-parse", "HEAD").decode().strip()
    for path, (mode, _) in bootstrap.TARGET_ENTRIES.items():
        write(repository, path, git(ROOT, "show", f"{bootstrap.TARGET_COMMIT}:{path}"))
        stage(repository, path, mode)
    git(repository, "commit", "--quiet", "-m", "approved target")
    target = git(repository, "rev-parse", "HEAD").decode().strip()
    launcher = git(ROOT, "show", f"{bootstrap.MERGED_TOOL_COMMIT}:{bootstrap.LAUNCHER_PATH}")
    write(repository, bootstrap.LAUNCHER_PATH, launcher)
    stage(repository, bootstrap.LAUNCHER_PATH)
    git(repository, "commit", "--quiet", "-m", "merged launcher")
    merged = git(repository, "rev-parse", "HEAD").decode().strip()
    project = tmp_path / "production"
    tool = tmp_path / "tool"
    git(repository, "worktree", "add", "--quiet", "--detach", str(project), before)
    git(repository, "worktree", "add", "--quiet", "--detach", str(tool), merged)
    write(project, ".deployed_commit", before + "\n")
    monkeypatch.setattr(bootstrap, "BEFORE", before)
    monkeypatch.setattr(bootstrap, "TARGET_COMMIT", target)
    monkeypatch.setattr(bootstrap, "MERGED_TOOL_COMMIT", merged)
    monkeypatch.setattr(bootstrap, "TARGET_ENTRIES", {
        path: (mode, git(repository, "rev-parse", f"{target}:{path}").decode().strip())
        for path, (mode, _) in bootstrap.TARGET_ENTRIES.items()
    })
    monkeypatch.setattr(bootstrap, "CONTROL_ENTRIES", {
        path: (mode, git(repository, "rev-parse", f"{before}:{path}").decode().strip())
        for path, (mode, _) in bootstrap.CONTROL_ENTRIES.items()
    })
    monkeypatch.setattr(bootstrap, "LAUNCHER_BLOB", git(repository, "rev-parse", f"{merged}:{bootstrap.LAUNCHER_PATH}").decode().strip())
    return SimpleNamespace(repository=repository, project=project, tool=tool, before=before, target=target, merged=merged)


def test_exact_transition_and_overlay_are_approved(transition, tmp_path):
    approval = bootstrap.validate_bootstrap(transition.project, transition.tool, transition.target)
    launcher = bootstrap.prepare_overlay(tmp_path / "overlay", approval, transition.project, transition.tool)
    source = launcher.read_text(encoding="utf-8")
    assert "qr-release-tool-bootstrap" not in source
    assert '"$SCRIPT_ROOT/scripts/$control"' in source
    assert str(transition.project.resolve()) in source
    assert str((tmp_path / "overlay").resolve()) in source


def test_wrong_tool_head_is_rejected(transition, monkeypatch):
    monkeypatch.setattr(bootstrap, "MERGED_TOOL_COMMIT", transition.target)
    with pytest.raises(RuntimeError, match="merged launcher fix"):
        bootstrap.validate_bootstrap(transition.project, transition.tool, transition.target)


def test_wrong_launcher_blob_is_rejected(transition, monkeypatch):
    monkeypatch.setattr(bootstrap, "LAUNCHER_BLOB", "0" * 40)
    with pytest.raises(RuntimeError, match="launcher blob"):
        bootstrap.validate_bootstrap(transition.project, transition.tool, transition.target)


def test_overlay_rejects_control_file_drift_after_approval(transition, tmp_path, monkeypatch):
    approval = bootstrap.validate_bootstrap(transition.project, transition.tool, transition.target)
    original = bootstrap._regular_file

    def drifted_file(root, path):
        content = original(root, path)
        if path == "scripts/code_only_release.py":
            return content + b"\n# drift\n"
        return content

    monkeypatch.setattr(bootstrap, "_regular_file", drifted_file)
    with pytest.raises(RuntimeError, match="drifted during overlay preparation"):
        bootstrap.prepare_overlay(tmp_path / "overlay", approval, transition.project, transition.tool)


def test_overlay_rejects_launcher_blob_drift_after_approval(transition, tmp_path, monkeypatch):
    approval = bootstrap.validate_bootstrap(transition.project, transition.tool, transition.target)
    original = bootstrap._git

    def drifted_git(root, *args, **kwargs):
        result = original(root, *args, **kwargs)
        if args == ("show", f"{bootstrap.MERGED_TOOL_COMMIT}:{bootstrap.LAUNCHER_PATH}"):
            result.stdout = result.stdout + b"\n# drift\n"
        return result

    monkeypatch.setattr(bootstrap, "_git", drifted_git)
    with pytest.raises(RuntimeError, match="merged launcher drifted"):
        bootstrap.prepare_overlay(tmp_path / "overlay", approval, transition.project, transition.tool)


def test_target_worktree_cleanup_failure_is_fatal(tmp_path, monkeypatch):
    class FailedRemoval:
        returncode = 1

    monkeypatch.setattr(bootstrap.subprocess, "run", lambda *args, **kwargs: FailedRemoval())
    with pytest.raises(RuntimeError, match="failed to remove temporary target worktree"):
        bootstrap._remove_target_worktree(tmp_path / "tool", tmp_path / "target")


def test_target_commit_is_fixed_and_no_execute_mode_is_available(transition):
    with pytest.raises(RuntimeError, match="approved Task 6 release"):
        bootstrap.validate_bootstrap(transition.project, transition.tool, "0" * 40)
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/bootstrap_release_tool.py"), "--execute"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
