"""Contracts for the one-time PR #132 release-control bootstrap."""

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import bootstrap_task132_release_control as bootstrap


pytestmark = pytest.mark.unit


ROOT = Path(__file__).resolve().parents[1]

EXPECTED_TARGET_ENTRIES = {
    "scripts/backend_frontend_static_release.py": (
        "100644",
        "8303fb9cd6fee5bb658fe57f92a1e0df6f203599",
    ),
    "scripts/deploy-backend-frontend-static.sh": (
        "100644",
        "5c6817665ed341fd855343ed5e1856bd1407bc32",
    ),
    "scripts/deployment_manifest.py": (
        "100644",
        "1141f927614232cdbaad881cd0d5d6655e4b9531",
    ),
    "scripts/rollback-deployment.sh": (
        "100644",
        "559193c74c4cf88210eea1ef06ea5cd077b8942e",
    ),
}

EXPECTED_SUPPORT_PATHS = {
    ".github/workflows/full-test.yml",
    "docs/deployment-backend-frontend-static.md",
    "frontend/tests/e2e/admin-pages.spec.js",
    "frontend/tests/e2e/helpers.js",
    "frontend/tests/e2e/wage-price-versions.spec.js",
    "frontend/tests/unit/GanttChartProductionNodes.spec.js",
    "frontend/tests/unit/MasterDataRelease.spec.js",
    "frontend/tests/unit/useOrderQuery.spec.js",
    "package.json",
    "scripts/bootstrap_backend_frontend_static_check.py",
    "scripts/bootstrap_release_tool.py",
    "scripts/bootstrap_task7_release_check.py",
    "scripts/bootstrap_task8_release_control.py",
    "scripts/test-full.mjs",
    "tests/conftest.py",
    "tests/test_architecture_imports.py",
    "tests/test_backend_frontend_static_bootstrap.py",
    "tests/test_backend_frontend_static_release.py",
    "tests/test_bootstrap_bash_resolution.py",
    "tests/test_operations_script_boundary.py",
    "tests/test_release_tool_bootstrap.py",
    "tests/test_task7_release_check_bootstrap.py",
    "tests/test_task8_release_control_bootstrap.py",
}


def git(root, *arguments):
    return subprocess.check_output(["git", "-C", str(root), *arguments])


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))


def load_overlay_policy(path):
    import sys as _sys
    import types

    package_name = "_task132_overlay_package"
    package = types.ModuleType(package_name)
    package.__path__ = [str(path.parent)]
    _sys.modules[package_name] = package
    try:
        module_name = f"{package_name}.code_only_release"
        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        _sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        _sys.modules.pop(f"{package_name}.deployment_manifest", None)
        _sys.modules.pop(f"{package_name}.code_only_release", None)
        _sys.modules.pop(package_name, None)


@pytest.fixture
def transition(tmp_path, monkeypatch):
    project = tmp_path / "production"
    tool = tmp_path / "tool"
    git(
        ROOT,
        "-c",
        "core.autocrlf=false",
        "worktree",
        "add",
        "--quiet",
        "--detach",
        str(project),
        bootstrap.BEFORE_COMMIT,
    )
    git(
        ROOT,
        "-c",
        "core.autocrlf=false",
        "worktree",
        "add",
        "--quiet",
        "--detach",
        str(tool),
        bootstrap.TARGET_COMMIT,
    )
    try:
        subprocess.run(
            [
                "git", "-C", str(tool), "-c", "user.name=Bootstrap Test",
                "-c", "user.email=bootstrap@example.invalid", "commit", "--quiet",
                "--allow-empty",
                "-m", "independently reviewed Task 132 tool checkout",
            ],
            check=True,
        )
        reviewed_tool_commit = git(tool, "rev-parse", "HEAD").decode().strip()
        original_validate = bootstrap.validate_transition

        def validate_with_reviewed_tool(project_root, tool_root, target_commit=None, tool_commit=None):
            if target_commit is None:
                target_commit = bootstrap.TARGET_COMMIT
            if tool_commit is None:
                tool_commit = reviewed_tool_commit
            return original_validate(project_root, tool_root, target_commit, tool_commit)

        monkeypatch.setattr(bootstrap, "validate_transition", validate_with_reviewed_tool)
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


def commit_change(root, path, content, message="unapproved change"):
    write(root / path, content)
    subprocess.run(["git", "-C", str(root), "add", "--", path], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Bootstrap Test",
            "-c",
            "user.email=bootstrap@example.invalid",
            "commit",
            "--quiet",
            "-m",
            message,
        ],
        check=True,
    )
    return git(root, "rev-parse", "HEAD").decode().strip()


def commit_review_followup(root):
    return commit_change(
        root,
        ".task132-review-followup",
        "independently reviewed follow-up\n",
        "independently reviewed follow-up",
    )


def add_target_worktree(tmp_path):
    target_tool = tmp_path / "target-tool"
    git(
        ROOT,
        "-c",
        "core.autocrlf=false",
        "worktree",
        "add",
        "--quiet",
        "--detach",
        str(target_tool),
        bootstrap.TARGET_COMMIT,
    )
    return target_tool


def remove_worktree(path):
    subprocess.run(
        ["git", "-C", str(ROOT), "worktree", "remove", "--force", str(path)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_exact_allowlist_blob_and_mode_are_pinned(transition):
    project, tool, _ = transition
    approval = bootstrap.validate_transition(project, tool)

    assert approval["before_commit"] == bootstrap.BEFORE_COMMIT
    assert approval["target_commit"] == bootstrap.TARGET_COMMIT
    assert bootstrap.TARGET_ENTRIES == EXPECTED_TARGET_ENTRIES
    assert set(bootstrap.SUPPORT_ENTRIES) == EXPECTED_SUPPORT_PATHS
    all_entries = {**bootstrap.SUPPORT_ENTRIES, **bootstrap.TARGET_ENTRIES}
    assert approval["changed_paths"] == sorted(all_entries)
    for path, (mode, blob) in EXPECTED_TARGET_ENTRIES.items():
        assert bootstrap._entry(tool, bootstrap.TARGET_COMMIT, path) == (mode, "blob", blob)
    for path, (mode, blob) in bootstrap.SUPPORT_ENTRIES.items():
        assert bootstrap._entry(tool, bootstrap.TARGET_COMMIT, path) == (mode, "blob", blob)

    for path, (mode, before_blob) in bootstrap.CONTROL_ENTRIES.items():
        assert bootstrap._entry(project, bootstrap.BEFORE_COMMIT, path) == (
            mode,
            "blob",
            before_blob,
        )
        target_blob = bootstrap.TARGET_ENTRIES.get(path, (mode, before_blob))[1]
        assert bootstrap._entry(tool, bootstrap.TARGET_COMMIT, path) == (
            mode,
            "blob",
            target_blob,
        )


def test_real_overlay_policy_preflight_preserves_controls_and_skips_static_launcher(transition, tmp_path):
    project, tool, database = transition
    approval = bootstrap.validate_transition(project, tool)
    target_tool = add_target_worktree(tmp_path)
    baseline_controls = {
        path: (project / path).read_bytes()
        for path in bootstrap.PRODUCTION_OVERLAY_CONTROLS
    }
    launcher = bootstrap.prepare_overlay(tmp_path / "overlay", approval, project, tool)
    policy = load_overlay_policy(launcher.parent / "code_only_release.py")
    try:
        result = policy.validate_code_only_release(
            target_tool, project, database, bootstrap.BEFORE_COMMIT, bootstrap.TARGET_COMMIT
        )
    finally:
        remove_worktree(target_tool)

    assert result["target_commit"] == bootstrap.TARGET_COMMIT
    assert result["changed_paths"] == sorted((*bootstrap.TARGET_ENTRIES, *bootstrap.SUPPORT_ENTRIES))
    assert result["database"]["user_version"] == 96
    for path, content in baseline_controls.items():
        assert (project / path).read_bytes() == content
    assert not (launcher.parent / bootstrap.STATIC_LAUNCHER_PATH.split("/", 1)[-1]).exists()
    assert not (project / "data/deployments").exists()


def test_overlay_policy_revalidates_target_and_production_drift(transition, tmp_path):
    project, tool, database = transition
    approval = bootstrap.validate_transition(project, tool)
    target_tool = add_target_worktree(tmp_path)
    launcher = bootstrap.prepare_overlay(tmp_path / "overlay", approval, project, tool)
    policy = load_overlay_policy(launcher.parent / "code_only_release.py")
    try:
        write(project / bootstrap.POLICY_PATH, b"# post-approval production drift\n")
        with pytest.raises(RuntimeError, match="production release control|production.*changed|worktree is not clean"):
            policy.validate_code_only_release(
                target_tool, project, database, bootstrap.BEFORE_COMMIT, bootstrap.TARGET_COMMIT
            )
    finally:
        remove_worktree(target_tool)


def test_overlay_policy_rejects_tool_head_drift_after_approval(transition, tmp_path):
    project, tool, database = transition
    approval = bootstrap.validate_transition(project, tool)
    target_tool = add_target_worktree(tmp_path)
    launcher = bootstrap.prepare_overlay(tmp_path / "overlay", approval, project, tool)
    policy = load_overlay_policy(launcher.parent / "code_only_release.py")
    try:
        target = commit_change(target_tool, "tests/task132-post-approval.py", "DRIFT = True\n")
        with pytest.raises(RuntimeError, match="target commit|bootstrap|worktree HEAD|changed paths"):
            policy.validate_code_only_release(
                target_tool, project, database, bootstrap.BEFORE_COMMIT, target
            )
    finally:
        remove_worktree(target_tool)


@pytest.mark.parametrize("kind", ["symlink", "submodule"])
def test_rejects_non_regular_git_target_entry(transition, kind, monkeypatch):
    _, tool, _ = transition
    path = next(iter(bootstrap.TARGET_ENTRIES))
    if kind == "symlink":
        result = subprocess.run(
            ["git", "-C", str(tool), "hash-object", "-w", "--stdin"],
            input=b"../untrusted-target",
            stdout=subprocess.PIPE,
            check=True,
        )
        mode, value = "120000", result.stdout.decode().strip()
    else:
        mode, value = "160000", git(tool, "rev-parse", "HEAD").decode().strip()
    subprocess.run(
        ["git", "-C", str(tool), "update-index", "--add", "--cacheinfo", f"{mode},{value},{path}"],
        check=True,
    )
    subprocess.run(
        [
            "git", "-C", str(tool), "-c", "user.name=Bootstrap Test",
            "-c", "user.email=bootstrap@example.invalid", "commit", "--quiet",
            "-m", f"unapproved {kind} entry",
        ],
        check=True,
    )
    target = git(tool, "rev-parse", "HEAD").decode().strip()
    reviewed = commit_review_followup(tool)
    monkeypatch.setattr(bootstrap, "TARGET_COMMIT", target)
    with pytest.raises(RuntimeError, match="regular Git file|entry mismatch|changed paths|worktree is not clean"):
        bootstrap.validate_transition(transition[0], tool, target, tool_commit=reviewed)


def test_replace_once_fails_closed_on_patch_point_drift():
    with pytest.raises(RuntimeError, match="patch point drifted"):
        bootstrap._replace_once("different source", "expected source", "replacement")


def test_bootstrap_exposes_explicit_check_only_and_execute_modes():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/bootstrap_task132_release_control.py"), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--check-only" in result.stdout
    assert "--execute" in result.stdout


def test_cli_requires_independently_reviewed_tool_commit():
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/bootstrap_task132_release_control.py"),
            "--project-root", str(ROOT),
            "--tool-root", str(ROOT),
            "--target-commit", bootstrap.TARGET_COMMIT,
            "--deployment-key", "task132",
            "--check-only",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "--tool-commit" in result.stderr


def test_rejects_unapproved_changed_path(transition, monkeypatch):
    _, tool, _ = transition
    target = commit_change(tool, "tests/unapproved_task132_scope.py", "VALUE = True\n")
    reviewed = commit_review_followup(tool)
    monkeypatch.setattr(bootstrap, "TARGET_COMMIT", target)
    with pytest.raises(RuntimeError, match="changed paths mismatch"):
        bootstrap.validate_transition(transition[0], tool, target, tool_commit=reviewed)


def test_rejects_target_blob_drift(transition, monkeypatch):
    _, tool, _ = transition
    path = next(iter(bootstrap.TARGET_ENTRIES))
    target = commit_change(tool, path, "# unapproved Task 132 blob drift\n")
    reviewed = commit_review_followup(tool)
    monkeypatch.setattr(bootstrap, "TARGET_COMMIT", target)
    with pytest.raises(RuntimeError, match="entry mismatch|blob"):
        bootstrap.validate_transition(transition[0], tool, target, tool_commit=reviewed)


def test_rejects_support_blob_drift(transition, monkeypatch):
    _, tool, _ = transition
    path = next(iter(bootstrap.SUPPORT_ENTRIES))
    target = commit_change(tool, path, "# unapproved Task 132 support drift\n")
    reviewed = commit_review_followup(tool)
    monkeypatch.setattr(bootstrap, "TARGET_COMMIT", target)
    with pytest.raises(RuntimeError, match="entry mismatch|blob"):
        bootstrap.validate_transition(transition[0], tool, target, tool_commit=reviewed)


@pytest.mark.parametrize("path", sorted(EXPECTED_TARGET_ENTRIES))
def test_rejects_target_mode_drift(transition, path, monkeypatch):
    _, tool, _ = transition
    subprocess.run(["git", "-C", str(tool), "update-index", "--chmod=+x", path], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tool),
            "-c",
            "user.name=Bootstrap Test",
            "-c",
            "user.email=bootstrap@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "unapproved mode drift",
        ],
        check=True,
    )
    target = git(tool, "rev-parse", "HEAD").decode().strip()
    reviewed = commit_review_followup(tool)
    monkeypatch.setattr(bootstrap, "TARGET_COMMIT", target)
    with pytest.raises(RuntimeError, match="entry mismatch|mode|worktree is not clean"):
        bootstrap.validate_transition(transition[0], tool, target, tool_commit=reviewed)


@pytest.mark.parametrize("path", sorted(EXPECTED_TARGET_ENTRIES))
def test_rejects_deleted_target_entry(transition, path, monkeypatch):
    _, tool, _ = transition
    subprocess.run(["git", "-C", str(tool), "rm", "--quiet", "--", path], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tool),
            "-c",
            "user.name=Bootstrap Test",
            "-c",
            "user.email=bootstrap@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "unapproved deletion",
        ],
        check=True,
    )
    target = git(tool, "rev-parse", "HEAD").decode().strip()
    reviewed = commit_review_followup(tool)
    monkeypatch.setattr(bootstrap, "TARGET_COMMIT", target)
    with pytest.raises(RuntimeError, match="entry mismatch|missing|changed paths"):
        bootstrap.validate_transition(transition[0], tool, target, tool_commit=reviewed)


@pytest.mark.parametrize("path", sorted(bootstrap.CONTROL_ENTRIES))
def test_rejects_production_control_byte_drift(transition, path):
    project, tool, _ = transition
    write(project / path, b"# local release-control drift\n")
    with pytest.raises(RuntimeError, match="not clean|release control|control bytes|drift"):
        bootstrap.validate_transition(project, tool)


def test_rejects_wrong_marker_head_target_tool_commit_dirty_nested_and_fence(transition):
    project, tool, _ = transition

    write(project / ".deployed_commit", "0" * 40 + "\n")
    with pytest.raises(RuntimeError, match="marker|deployed commit"):
        bootstrap.validate_transition(project, tool)
    write(project / ".deployed_commit", bootstrap.BEFORE_COMMIT + "\n")

    with pytest.raises(RuntimeError, match="approved Task 132 merge"):
        bootstrap.validate_transition(project, tool, "0" * 40)
    with pytest.raises(RuntimeError, match="tool commit"):
        bootstrap.validate_transition(project, tool, bootstrap.TARGET_COMMIT, tool_commit="0" * 40)
    with pytest.raises(RuntimeError, match="separate and non-nested|not a git repository"):
        bootstrap.validate_transition(project, project.parent, bootstrap.TARGET_COMMIT)

    write(tool / "untracked-task132-drift.txt", "dirty\n")
    with pytest.raises(RuntimeError, match="release-tool worktree is not clean"):
        bootstrap.validate_transition(project, tool)
    (tool / "untracked-task132-drift.txt").unlink()

    fence = project / "data/deployments/write-fence.json"
    write(fence, "{}\n")
    with pytest.raises(RuntimeError, match="write-fence"):
        bootstrap.validate_transition(project, tool)


def test_rejects_production_head_drift(transition):
    project, tool, _ = transition
    commit_change(project, ".task132-production-head-drift", "HEAD_DRIFT = True\n")
    with pytest.raises(RuntimeError, match="production HEAD changed"):
        bootstrap.validate_transition(project, tool)


def test_check_only_has_no_production_side_effects(transition, monkeypatch, capsys):
    project, tool, database = transition
    marker_before = (project / ".deployed_commit").read_bytes()
    database_before = database.read_bytes()
    status_before = git(project, "status", "--porcelain=v1")
    observed = {}

    def fake_launcher(**kwargs):
        observed.update(kwargs)

    monkeypatch.setattr(bootstrap, "_invoke_launcher", fake_launcher)
    approval = bootstrap.run_check_only(
        project_root=project,
        tool_root=tool,
        target_commit=bootstrap.TARGET_COMMIT,
        deployment_key="task132-check-only",
    )

    assert approval["mode"] == "check_only"
    assert observed["mode"] == "--check-only"
    assert (project / ".deployed_commit").read_bytes() == marker_before
    assert database.read_bytes() == database_before
    assert git(project, "status", "--porcelain=v1") == status_before
    assert not (project / "data/deployments").exists()
    assert json.loads(capsys.readouterr().out)["deployment_key"] == "task132-check-only"


@pytest.mark.parametrize("operator,approver", [(0, 1004), (1000, 0), (1000, 1000)])
def test_execute_rejects_invalid_or_non_independent_identity(operator, approver):
    with pytest.raises(RuntimeError, match="IDs must|positive|differ"):
        bootstrap._validate_identity(operator, approver)


def test_execute_requires_identity_and_approved_digest():
    command = [
        sys.executable,
        str(ROOT / "scripts/bootstrap_task132_release_control.py"),
        "--project-root",
        str(ROOT),
        "--tool-root",
        str(ROOT),
        "--target-commit",
        bootstrap.TARGET_COMMIT,
        "--tool-commit",
        "1" * 40,
        "--deployment-key",
        "task132",
        "--execute",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert "requires" in result.stderr


def test_execute_digest_mismatch_creates_no_receipt(transition):
    project, tool, _ = transition
    with pytest.raises(RuntimeError, match="does not match"):
        bootstrap.run_execute(
            project_root=project,
            tool_root=tool,
            target_commit=bootstrap.TARGET_COMMIT,
            deployment_key="task132-digest-mismatch",
            approved_bootstrap_sha256="0" * 64,
            operator_user_id=1000,
            approver_user_id=1004,
        )
    assert not (project / "data/deployments/task132-digest-mismatch.bootstrap.json").exists()


def test_receipt_file_fsync_failure_removes_partial_receipt(tmp_path, monkeypatch):
    receipt = tmp_path / "data/deployments/fsync.bootstrap.json"
    approval = {"before_commit": bootstrap.BEFORE_COMMIT, "target_commit": bootstrap.TARGET_COMMIT}
    original_fsync = bootstrap.os.fsync

    def fail_fsync(_descriptor):
        raise OSError("simulated receipt fsync failure")

    monkeypatch.setattr(bootstrap.os, "fsync", fail_fsync)
    with pytest.raises(OSError, match="fsync"):
        bootstrap._write_receipt(receipt, approval, "fsync", 1000, 1004)
    assert not receipt.exists()
    monkeypatch.setattr(bootstrap.os, "fsync", original_fsync)


@pytest.mark.skipif(os.name == "nt", reason="directory fsync is intentionally unavailable on Windows")
def test_receipt_directory_fsync_failure_does_not_invoke_launcher(tmp_path, monkeypatch):
    receipt = tmp_path / "data/deployments/directory-fsync.bootstrap.json"
    approval = {"before_commit": bootstrap.BEFORE_COMMIT, "target_commit": bootstrap.TARGET_COMMIT}
    calls = []
    original_fsync = bootstrap.os.fsync

    def fail_directory_fsync(descriptor):
        calls.append(descriptor)
        if len(calls) > 1:
            raise OSError("simulated directory fsync failure")
        return original_fsync(descriptor)

    monkeypatch.setattr(bootstrap.os, "fsync", fail_directory_fsync)
    with pytest.raises(OSError, match="fsync"):
        bootstrap._write_receipt(receipt, approval, "directory-fsync", 1000, 1004)
    assert calls


def test_check_only_launcher_failure_leaves_no_receipt_or_fence(transition, monkeypatch):
    project, tool, _ = transition

    def fail_launcher(**_kwargs):
        raise RuntimeError("simulated launcher failure")

    monkeypatch.setattr(bootstrap, "_invoke_launcher", fail_launcher)
    with pytest.raises(RuntimeError, match="launcher failure"):
        bootstrap.run_check_only(
            project_root=project,
            tool_root=tool,
            target_commit=bootstrap.TARGET_COMMIT,
            deployment_key="task132-launcher-failure",
        )
    assert not (project / "data/deployments/task132-launcher-failure.bootstrap.json").exists()
    assert not (project / "data/deployments/write-fence.json").exists()


def test_execute_receipt_is_exclusive_and_records_scope(tmp_path):
    receipt = tmp_path / "data/deployments/task132.bootstrap.json"
    approval = {
        "before_commit": bootstrap.BEFORE_COMMIT,
        "target_commit": bootstrap.TARGET_COMMIT,
        "changed_paths": sorted((*EXPECTED_TARGET_ENTRIES, *EXPECTED_SUPPORT_PATHS)),
        "bootstrap_sha256": "a" * 64,
        "mode": "check_only",
    }
    bootstrap._write_receipt(receipt, approval, "task132", 1000, 1004)
    saved = receipt.read_bytes()
    payload = json.loads(saved)
    assert payload["scope"].endswith("execute")
    assert "release_control" in payload["scope"]
    assert payload["operator_user_id"] == 1000
    assert payload["approver_user_id"] == 1004
    assert payload["database_migration"] is False
    assert payload["attachment_migration"] is False
    assert payload["frontend_publish"] is False
    with pytest.raises(FileExistsError):
        bootstrap._write_receipt(receipt, approval, "task132", 1000, 1004)
    assert receipt.read_bytes() == saved
