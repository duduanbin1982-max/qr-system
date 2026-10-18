"""Contracts for the reviewed Task 7 execute bootstrap."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import bootstrap_task7_release_execute as bootstrap


ROOT = Path(__file__).resolve().parents[1]


def test_execute_bootstrap_requires_explicit_execute_mode():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/bootstrap_task7_release_execute.py"), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--execute" in result.stdout
    assert "--check-only" not in result.stdout


@pytest.mark.parametrize("operator,approver", [(0, 1004), (1000, 0), (1000, 1000)])
def test_execute_bootstrap_rejects_invalid_identity(operator, approver):
    with pytest.raises(RuntimeError, match="IDs"):
        bootstrap._validate_identity(operator, approver)


def test_receipt_is_immutable_and_binds_code_only_scope(tmp_path):
    approval = {
        "before_commit": "a" * 40,
        "target_commit": "b" * 40,
        "changed_paths": ["modules/services/user_service.py"],
        "launcher_target_blob": "c" * 40,
        "bootstrap_sha256": "d" * 64,
    }
    receipt = tmp_path / "data" / "deployments" / "release.bootstrap.json"
    bootstrap._write_receipt(receipt, approval, "release-key", 1000, 1004)
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["scope"] == "task7_code_only_execute"
    assert payload["database_migration"] is False
    assert payload["attachment_migration"] is False
    assert payload["frontend_migration"] is False
    with pytest.raises(FileExistsError):
        bootstrap._write_receipt(receipt, approval, "release-key", 1000, 1004)


def test_execute_path_invokes_pinned_launcher_in_execute_mode():
    content = (ROOT / "scripts/bootstrap_task7_release_execute.py").read_text(
        encoding="utf-8"
    )
    assert '"--execute"' in content
    assert '"--target-commit"' in content
    assert '"--deployment-key"' in content
    assert "prepare_overlay" in content
    assert "_write_receipt" in content
