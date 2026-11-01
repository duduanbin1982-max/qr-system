"""Exact support-file approvals for the PR #136 business release."""

import os
import subprocess
from pathlib import Path

import pytest

from scripts import backend_frontend_static_release as release
from scripts import code_only_release
from tests.test_code_only_deployment import _write


ORDERS_PATHS = (
    "frontend/tests/e2e/admin-pages.spec.js",
    "frontend/tests/e2e/helpers.js",
    "frontend/tests/unit/order-mode-progress.spec.js",
    "scripts/e2e_server.py",
    "scripts/backend_frontend_static_release.py",
)


def test_orders_approval_matches_the_reviewed_production_and_merge_trees():
    repository = Path(__file__).resolve().parents[1]
    before = "a1bdb0a4fa3d6aec1139a8db1e2f72707646f1ef"
    target = "971a7a3deb307efe0cae765d71abf833e6bf03aa"

    assert release.ORDERS_SUPPORT_BASELINE == before
    assert release.ORDERS_SUPPORT_TARGET == target
    assert set(release.PINNED_ORDERS_SUPPORT_TRANSITIONS) == set(ORDERS_PATHS)
    for path in ORDERS_PATHS:
        expected_before, expected_target = release.PINNED_ORDERS_SUPPORT_TRANSITIONS[path]
        assert release._tree_entry(repository, before, path) == expected_before, path
        assert release._tree_entry(repository, target, path) == expected_target, path

    changed = code_only_release._changed_paths(repository, before, target)
    assert len(changed) == 17
    release._validate_paths(repository, before, target, changed)


@pytest.mark.parametrize("path", ORDERS_PATHS)
@pytest.mark.parametrize("side", ["baseline", "target"])
@pytest.mark.parametrize("drift", ["same_tree_commit", "abbreviated_sha", "uppercase_sha"])
def test_orders_support_requires_both_exact_commit_shas(path, side, drift):
    repository = Path(__file__).resolve().parents[1]
    before = release.ORDERS_SUPPORT_BASELINE
    target = release.ORDERS_SUPPORT_TARGET
    original = before if side == "baseline" else target
    if drift == "same_tree_commit":
        alternate = (
            "1c9ae2d58c4169a5cc86ff4682aa34e7a951b4d3" if side == "baseline"
            else "4c6748cb6f3ee9fd51c4cc47dbb3845b7cc388f5"
        )
        assert alternate != original
        assert release._git(repository, "rev-parse", f"{alternate}^{{tree}}") == (
            release._git(repository, "rev-parse", f"{original}^{{tree}}")
        )
    elif drift == "abbreviated_sha":
        alternate = original[:7]
    else:
        alternate = original.upper()
    if side == "baseline":
        before = alternate
    else:
        target = alternate
    with pytest.raises(RuntimeError, match="orders support exception requires the reviewed baseline and target"):
        release._validate_paths(repository, before, target, [path])


@pytest.fixture(scope="module")
def support_repository(tmp_path_factory):
    repository = tmp_path_factory.mktemp("orders-support")
    code_only_release._git(repository, "init", "--quiet", "--initial-branch=master")
    code_only_release._git(repository, "config", "user.name", "Codex Test")
    code_only_release._git(repository, "config", "user.email", "codex-test@example.invalid")
    commits = []
    for label in ("baseline", "target"):
        for path in ORDERS_PATHS:
            _write(repository / path, f"VALUE = '{label}'\n")
            code_only_release._git(repository, "add", path)
            if path == "scripts/e2e_server.py":
                code_only_release._git(repository, "update-index", "--chmod=+x", path)
        code_only_release._git(repository, "commit", "--quiet", "-m", label)
        commits.append(release._git(repository, "rev-parse", "HEAD"))
    return repository, *commits


@pytest.mark.parametrize("path", ORDERS_PATHS)
@pytest.mark.parametrize("side", ["baseline", "target"])
@pytest.mark.parametrize("drift", ["blob", "missing", "mode", "symlink", "submodule", "directory"])
def test_orders_support_rejects_git_entry_drift(
    tmp_path, monkeypatch, support_repository, path, side, drift,
):
    repository, before, target = support_repository
    transitions = {
        name: (
            release._tree_entry(repository, before, name),
            release._tree_entry(repository, target, name),
        )
        for name in ORDERS_PATHS
    }
    source = before if side == "baseline" else target
    opposite = target if side == "baseline" else before
    original_entry = release._tree_entry(repository, source, path)
    environment = {**os.environ, "GIT_INDEX_FILE": str(tmp_path / "index")}

    def indexed_git(*args):
        return subprocess.run(
            ["git", "-C", str(repository), *args], env=environment,
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        ).stdout.strip()

    indexed_git("read-tree", source)
    if drift in {"missing", "directory"}:
        indexed_git("update-index", "--force-remove", path)
        if drift == "directory":
            indexed_git(
                "update-index", "--add", "--cacheinfo",
                f"100644,{original_entry[2]},{path}/unreviewed.txt",
            )
    else:
        mode, _, blob = original_entry
        if drift == "blob":
            blob = release._tree_entry(repository, opposite, path)[2]
        elif drift == "mode":
            mode = "100644" if mode == "100755" else "100755"
        elif drift == "symlink":
            mode = "120000"
        elif drift == "submodule":
            mode, blob = "160000", source
        indexed_git("update-index", "--cacheinfo", f"{mode},{blob},{path}")
    tree = indexed_git("write-tree")
    changed_commit = indexed_git("commit-tree", tree, "-p", source, "-m", "unreviewed drift")
    assert release._tree_entry(repository, changed_commit, path) != original_entry
    if side == "baseline":
        before = changed_commit
    else:
        target = changed_commit
    monkeypatch.setattr(release, "ORDERS_SUPPORT_BASELINE", before)
    monkeypatch.setattr(release, "ORDERS_SUPPORT_TARGET", target)
    monkeypatch.setattr(release, "PINNED_ORDERS_SUPPORT_TRANSITIONS", transitions)

    with pytest.raises(RuntimeError, match="support exception mode/blob transition mismatch"):
        release._validate_paths(repository, before, target, [path])


@pytest.mark.parametrize("path", [
    "frontend/tests/e2e/unreviewed.spec.js",
    "frontend/tests/unit/unreviewed.spec.js",
    "scripts/bootstrap_unreviewed.py",
    "scripts/deployment_manifest.py",
    "scripts/backup-db.sh",
    "modules/migrations.py",
    "data/production.db",
    "data/attachments/unreviewed.pdf",
    "public/static/index.html",
    "package.json",
    ".github/workflows/full-test.yml",
])
def test_orders_approval_does_not_allow_other_support_or_protected_paths(path):
    repository = Path(__file__).resolve().parents[1]
    with pytest.raises(RuntimeError):
        release._validate_paths(
            repository, release.ORDERS_SUPPORT_BASELINE, release.ORDERS_SUPPORT_TARGET, [path],
        )
