"""Exact support-file approvals for the PR #134 business release."""

from pathlib import Path

import pytest

from scripts import backend_frontend_static_release as release
from scripts import code_only_release
from tests.test_backend_frontend_static_release import _release_repository
from tests.test_code_only_deployment import _write


PAYROLL_PATHS = (
    "frontend/tests/e2e/payroll-audit-regressions.spec.js",
    "frontend/tests/unit/payroll-audit-behavior.spec.js",
    "frontend/tests/unit/task2d-wage-layers.spec.js",
    "scripts/bootstrap_task132_release_control.py",
)


def test_payroll_approval_matches_the_reviewed_production_and_merge_trees():
    repository = Path(__file__).resolve().parents[1]
    before = "df7a6e398ab82eef02160d1efd143e1676d3db08"
    target = "a1bdb0a4fa3d6aec1139a8db1e2f72707646f1ef"

    assert release.PAYROLL_SUPPORT_BASELINE == before, "approval must bind the verified production SHA"
    assert release.PAYROLL_SUPPORT_TARGET == target, "approval must bind the reviewed business merge SHA"
    assert set(release.PINNED_PAYROLL_SUPPORT_TRANSITIONS) == set(PAYROLL_PATHS), (
        "only the four reviewed support paths may be approved"
    )
    for path in PAYROLL_PATHS:
        expected_before, expected_target = release.PINNED_PAYROLL_SUPPORT_TRANSITIONS[path]
        assert release._tree_entry(repository, before, path) == expected_before, path
        assert release._tree_entry(repository, target, path) == expected_target, path

    changed = code_only_release._changed_paths(repository, before, target)
    release._validate_paths(repository, before, target, changed)


@pytest.mark.parametrize("path", PAYROLL_PATHS)
@pytest.mark.parametrize("side", ["baseline", "target"])
def test_payroll_support_rejects_other_commits_even_with_the_same_tree(path, side):
    repository = Path(__file__).resolve().parents[1]
    before = release.PAYROLL_SUPPORT_BASELINE
    target = release.PAYROLL_SUPPORT_TARGET
    if side == "baseline":
        before = "6b4668272693449c2e94a3d8e81f0923646ba648"
    else:
        # The reviewed PR head has the same tree as its merge, but it is not
        # the approved release commit.
        target = "1c9ae2d58c4169a5cc86ff4682aa34e7a951b4d3"

    with pytest.raises(RuntimeError, match="reviewed baseline and target"):
        release._validate_paths(repository, before, target, [path])


@pytest.mark.parametrize("path", PAYROLL_PATHS)
@pytest.mark.parametrize("drift", [None, "before_blob", "target_blob", "deleted", "mode", "symlink", "submodule"])
def test_payroll_support_requires_exact_existence_modes_and_blobs(tmp_path, monkeypatch, path, drift):
    _, tool, before, _ = _release_repository(tmp_path)
    code_only_release._git(tool, "checkout", "--quiet", "--detach", before)
    _write(tool / path, "BASELINE = True\n")
    code_only_release._git(tool, "add", path)
    code_only_release._git(tool, "commit", "--quiet", "-m", "support baseline")
    support_before = release._git(tool, "rev-parse", "HEAD")
    expected_before = release._tree_entry(tool, support_before, path)

    _write(tool / path, "TARGET = True\n")
    code_only_release._git(tool, "add", path)
    code_only_release._git(tool, "commit", "--quiet", "-m", "support target")
    support_target = release._git(tool, "rev-parse", "HEAD")
    expected_target = release._tree_entry(tool, support_target, path)

    if drift == "before_blob":
        expected_before = expected_target
    elif drift == "target_blob":
        _write(tool / path, "UNREVIEWED = True\n")
        code_only_release._git(tool, "add", path)
    elif drift == "deleted":
        code_only_release._git(tool, "rm", "--quiet", path)
    elif drift in {"mode", "symlink", "submodule"}:
        mode = {"mode": "100755", "symlink": "120000", "submodule": "160000"}[drift]
        object_id = support_target if drift == "submodule" else expected_target[2]
        code_only_release._git(tool, "update-index", "--cacheinfo", f"{mode},{object_id},{path}")

    if drift in {"target_blob", "deleted", "mode", "symlink", "submodule"}:
        code_only_release._git(tool, "commit", "--quiet", "-m", "unreviewed support drift")
        support_target = release._git(tool, "rev-parse", "HEAD")
    monkeypatch.setattr(release, "PAYROLL_SUPPORT_BASELINE", support_before)
    monkeypatch.setattr(release, "PAYROLL_SUPPORT_TARGET", support_target)
    monkeypatch.setattr(
        release, "PINNED_PAYROLL_SUPPORT_TRANSITIONS",
        {path: (expected_before, expected_target)},
    )

    if drift:
        with pytest.raises(RuntimeError, match="transition mismatch"):
            release._validate_paths(tool, support_before, support_target, [path])
    else:
        release._validate_paths(tool, support_before, support_target, [path])


@pytest.mark.parametrize("path", [
    "frontend/tests/unit/unreviewed.spec.js",
    "scripts/bootstrap_unreviewed.py",
    "modules/migrations.py",
    "data/production.db",
    "public/static/index.html",
])
def test_payroll_approval_does_not_allow_other_support_or_protected_paths(path):
    repository = Path(__file__).resolve().parents[1]
    with pytest.raises(RuntimeError):
        release._validate_paths(
            repository, release.PAYROLL_SUPPORT_BASELINE, release.PAYROLL_SUPPORT_TARGET, [path],
        )
