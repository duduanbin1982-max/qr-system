"""Exact support-file approvals for the PR #140 material release."""

from pathlib import Path

import pytest

from scripts import backend_frontend_static_release as release
from scripts import code_only_release


MATERIALS_TRANSITIONS = {
    "frontend/tests/e2e/material-audit-regressions.spec.js": (
        None,
        ("100644", "blob", "bded26987d853a57d9bb35eb62dbed07b4c19e19"),
    ),
    "frontend/tests/unit/material-audit-behavior.spec.js": (
        None,
        ("100644", "blob", "1a2db529ef36691796a71819637b624a64fa25a2"),
    ),
    "frontend/tests/unit/material-options-pagination.spec.js": (
        None,
        ("100644", "blob", "05ebe7fa70fd4f26a8f854258ff7ae6b32a42d29"),
    ),
    "scripts/backend_frontend_static_release.py": (
        ("100644", "blob", "347a25db4b7ac0504f2933a612c42ad46e35f5f7"),
        ("100644", "blob", "01f4fdc4ae6cd25c0abce7afffcaec91268dba4f"),
    ),
}


def test_materials_approval_matches_the_reviewed_production_and_merge_trees():
    repository = Path(__file__).resolve().parents[1]
    before = "2a5a014d5e99655ad1e9ecdc9ac0ebc670e15875"
    target = "d532973ef8e6b427d8018700182059bb737900c7"

    assert release.MATERIALS_SUPPORT_BASELINE == before
    assert release.MATERIALS_SUPPORT_TARGET == target
    assert release.PINNED_MATERIALS_SUPPORT_TRANSITIONS == MATERIALS_TRANSITIONS
    for path, (expected_before, expected_target) in MATERIALS_TRANSITIONS.items():
        assert release._tree_entry(repository, before, path) == expected_before, path
        assert release._tree_entry(repository, target, path) == expected_target, path

    changed = code_only_release._changed_paths(repository, before, target)
    release._validate_paths(repository, before, target, changed)


@pytest.mark.parametrize("path", MATERIALS_TRANSITIONS)
@pytest.mark.parametrize(
    "before,target",
    [
        ("2a5a014d5e99655ad1e9ecdc9ac0ebc670e15875", "a1bdb0a4fa3d6aec1139a8db1e2f72707646f1ef"),
        ("971a7a3deb307efe0cae765d71abf833e6bf03aa", "d532973ef8e6b427d8018700182059bb737900c7"),
        ("2a5a014", "d532973ef8e6b427d8018700182059bb737900c7"),
    ],
)
def test_materials_support_requires_the_exact_baseline_and_target(path, before, target):
    repository = Path(__file__).resolve().parents[1]

    with pytest.raises(RuntimeError, match="reviewed baseline and target"):
        release._validate_paths(repository, before, target, [path])


@pytest.mark.parametrize("path", MATERIALS_TRANSITIONS)
@pytest.mark.parametrize("side", ["baseline", "target"])
def test_materials_support_rejects_reviewed_blob_or_mode_drift(monkeypatch, path, side):
    repository = Path(__file__).resolve().parents[1]
    before = release.MATERIALS_SUPPORT_BASELINE
    target = release.MATERIALS_SUPPORT_TARGET
    transitions = dict(release.PINNED_MATERIALS_SUPPORT_TRANSITIONS)
    expected_before, expected_target = transitions[path]

    if side == "baseline":
        drifted = ("100755", "blob", "0" * 40) if expected_before else ("100644", "blob", "0" * 40)
        transitions[path] = (drifted, expected_target)
    else:
        transitions[path] = (
            expected_before,
            ("100755", "blob", "0" * 40),
        )
    monkeypatch.setattr(release, "PINNED_MATERIALS_SUPPORT_TRANSITIONS", transitions)

    with pytest.raises(RuntimeError, match="mode/blob transition mismatch"):
        release._validate_paths(repository, before, target, [path])


def test_shared_release_script_is_pinned_separately_for_each_reviewed_business_pair():
    repository = Path(__file__).resolve().parents[1]
    path = "scripts/backend_frontend_static_release.py"

    release._validate_paths(
        repository,
        release.MATERIALS_SUPPORT_BASELINE,
        release.MATERIALS_SUPPORT_TARGET,
        [path],
    )
    release._validate_paths(
        repository,
        release.CUSTOMER_SUPPORT_BASELINE,
        release.CUSTOMER_SUPPORT_TARGET,
        [path],
    )
    release._validate_paths(
        repository,
        release.ORDERS_SUPPORT_BASELINE,
        release.ORDERS_SUPPORT_TARGET,
        [path],
    )
    with pytest.raises(RuntimeError, match="reviewed baseline and target"):
        release._validate_paths(
            repository,
            release.MATERIALS_SUPPORT_BASELINE,
            release.CUSTOMER_SUPPORT_TARGET,
            [path],
        )


@pytest.mark.parametrize(
    "path",
    [
        "frontend/tests/e2e/unreviewed.spec.js",
        "frontend/tests/unit/unreviewed.spec.js",
        "scripts/bootstrap_unreviewed.py",
    ],
)
def test_materials_approval_does_not_allow_unlisted_support_files(path):
    repository = Path(__file__).resolve().parents[1]

    with pytest.raises(RuntimeError):
        release._validate_paths(
            repository,
            release.MATERIALS_SUPPORT_BASELINE,
            release.MATERIALS_SUPPORT_TARGET,
            [path],
        )
