"""Exact support-file approvals for the PR #138 customer release."""

import os
import subprocess
from pathlib import Path

import pytest

from scripts import backend_frontend_static_release as release
from scripts import code_only_release


CUSTOMER_TRANSITIONS = {
    "frontend/tests/e2e/customer-management.spec.js": (
        None,
        ("100644", "blob", "d478125c6e610d01db284e75166c916ac4d2abb3"),
    ),
    "frontend/tests/unit/CustomerListRequests.spec.js": (
        None,
        ("100644", "blob", "083f92a6a0a06a20799ddd92d640e09da6ecea5d"),
    ),
    "scripts/backend_frontend_static_release.py": (
        ("100644", "blob", "d0abe1a02d23bee4b9327b0eaaaaaccb8e4f37ce"),
        ("100644", "blob", "347a25db4b7ac0504f2933a612c42ad46e35f5f7"),
    ),
}
SHARED_SCRIPT = "scripts/backend_frontend_static_release.py"


def test_customer_approval_matches_the_reviewed_production_and_merge_trees():
    repository = Path(__file__).resolve().parents[1]
    before = "971a7a3deb307efe0cae765d71abf833e6bf03aa"
    target = "2a5a014d5e99655ad1e9ecdc9ac0ebc670e15875"

    assert release.CUSTOMER_SUPPORT_BASELINE == before
    assert release.CUSTOMER_SUPPORT_TARGET == target
    assert release.PINNED_CUSTOMER_SUPPORT_TRANSITIONS == CUSTOMER_TRANSITIONS
    for path, (expected_before, expected_target) in CUSTOMER_TRANSITIONS.items():
        assert release._tree_entry(repository, before, path) == expected_before, path
        assert release._tree_entry(repository, target, path) == expected_target, path

    changed = code_only_release._changed_paths(repository, before, target)
    assert len(changed) == 8
    release._validate_paths(repository, before, target, changed)


@pytest.mark.parametrize("path", CUSTOMER_TRANSITIONS)
@pytest.mark.parametrize("side", ["baseline", "target"])
@pytest.mark.parametrize("drift", ["same_tree_commit", "abbreviated_sha", "uppercase_sha"])
def test_customer_support_requires_both_exact_commit_shas(path, side, drift):
    repository = Path(__file__).resolve().parents[1]
    before = release.CUSTOMER_SUPPORT_BASELINE
    target = release.CUSTOMER_SUPPORT_TARGET
    original = before if side == "baseline" else target
    if drift == "same_tree_commit":
        alternate = (
            "4c6748cb6f3ee9fd51c4cc47dbb3845b7cc388f5" if side == "baseline"
            else "2f5d8451fcc4e4c2ef34a508ad5cc839de6ee54f"
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
    with pytest.raises(RuntimeError, match="support exception requires the reviewed baseline and target"):
        release._validate_paths(repository, before, target, [path])


def test_shared_release_script_retains_orders_approval():
    repository = Path(__file__).resolve().parents[1]
    release._validate_paths(
        repository, release.ORDERS_SUPPORT_BASELINE, release.ORDERS_SUPPORT_TARGET,
        [SHARED_SCRIPT],
    )
    release._validate_paths(
        repository, release.CUSTOMER_SUPPORT_BASELINE, release.CUSTOMER_SUPPORT_TARGET,
        [SHARED_SCRIPT],
    )
    for before, target in (
        (release.ORDERS_SUPPORT_BASELINE, release.CUSTOMER_SUPPORT_TARGET),
        (release.CUSTOMER_SUPPORT_BASELINE, release.ORDERS_SUPPORT_TARGET),
    ):
        with pytest.raises(RuntimeError, match="reviewed baseline and target"):
            release._validate_paths(repository, before, target, [SHARED_SCRIPT])
    for path in CUSTOMER_TRANSITIONS.keys() - {SHARED_SCRIPT}:
        with pytest.raises(RuntimeError, match="reviewed baseline and target"):
            release._validate_paths(
                repository, release.ORDERS_SUPPORT_BASELINE, release.ORDERS_SUPPORT_TARGET,
                [path],
            )


@pytest.fixture(scope="module")
def support_repository(tmp_path_factory):
    repository = tmp_path_factory.mktemp("customer-support")
    code_only_release._git(repository, "init", "--quiet", "--initial-branch=master")
    code_only_release._git(repository, "config", "user.name", "Codex Test")
    code_only_release._git(repository, "config", "user.email", "codex-test@example.invalid")
    commits = []
    for label in ("baseline", "target"):
        blob = subprocess.run(
            ["git", "-C", str(repository), "hash-object", "-w", "--stdin"],
            input=f"VALUE = '{label}'\n", check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        ).stdout.strip()
        paths = [SHARED_SCRIPT] if label == "baseline" else CUSTOMER_TRANSITIONS
        for path in paths:
            code_only_release._git(
                repository, "update-index", "--add", "--cacheinfo", f"100644,{blob},{path}",
            )
        code_only_release._git(repository, "commit", "--quiet", "-m", label)
        commits.append(release._git(repository, "rev-parse", "HEAD"))
    return repository, *commits


ENTRY_DRIFTS = [
    (path, side, drift)
    for path, entries in CUSTOMER_TRANSITIONS.items()
    for side, entry in zip(("baseline", "target"), entries)
    for drift in (
        ("present", "mode", "symlink", "submodule", "directory") if entry is None
        else ("blob", "missing", "mode", "symlink", "submodule", "directory")
    )
]


@pytest.mark.parametrize("path,side,drift", ENTRY_DRIFTS)
def test_customer_support_rejects_git_entry_drift(
    tmp_path, monkeypatch, support_repository, path, side, drift,
):
    repository, before, target = support_repository
    transitions = {
        name: (
            release._tree_entry(repository, before, name),
            release._tree_entry(repository, target, name),
        )
        for name in CUSTOMER_TRANSITIONS
    }
    source = before if side == "baseline" else target
    original_entry = release._tree_entry(repository, source, path)
    baseline_blob = release._tree_entry(repository, before, SHARED_SCRIPT)[2]
    target_blob = release._tree_entry(repository, target, SHARED_SCRIPT)[2]
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
                f"100644,{target_blob},{path}/unreviewed.txt",
            )
    else:
        mode, blob = "100644", target_blob
        if drift == "blob":
            blob = baseline_blob if side == "target" else target_blob
        elif drift == "mode":
            mode = "100755"
        elif drift == "symlink":
            mode = "120000"
        elif drift == "submodule":
            mode, blob = "160000", source
        indexed_git("update-index", "--add", "--cacheinfo", f"{mode},{blob},{path}")
    tree = indexed_git("write-tree")
    changed_commit = indexed_git("commit-tree", tree, "-p", source, "-m", "unreviewed drift")
    assert release._tree_entry(repository, changed_commit, path) != original_entry
    if side == "baseline":
        before = changed_commit
    else:
        target = changed_commit
    monkeypatch.setattr(release, "CUSTOMER_SUPPORT_BASELINE", before)
    monkeypatch.setattr(release, "CUSTOMER_SUPPORT_TARGET", target)
    monkeypatch.setattr(release, "PINNED_CUSTOMER_SUPPORT_TRANSITIONS", transitions)

    with pytest.raises(RuntimeError, match="support exception mode/blob transition mismatch"):
        release._validate_paths(repository, before, target, [path])


@pytest.mark.parametrize("path", [
    "frontend/tests/e2e/unreviewed.spec.js",
    "frontend/tests/unit/unreviewed.spec.js",
    "scripts/bootstrap_unreviewed.py",
    "scripts/deployment_manifest.py",
    "scripts/backup-db.sh",
    "modules/migrations.py",
    "modules/deployment_write_fence.py",
    "modules/config.py",
    "data/production.db",
    "data/attachments/unreviewed.pdf",
    "public/static/index.html",
    "frontend/dist/app.js",
    "package.json",
    ".github/workflows/full-test.yml",
])
def test_customer_approval_does_not_allow_other_support_or_protected_paths(path):
    repository = Path(__file__).resolve().parents[1]
    with pytest.raises(RuntimeError):
        release._validate_paths(
            repository, release.CUSTOMER_SUPPORT_BASELINE, release.CUSTOMER_SUPPORT_TARGET,
            [path],
        )
