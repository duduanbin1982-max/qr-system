#!/usr/bin/env python3
"""Execute the reviewed Task 7 code-only release through a temporary overlay.

The production checkout keeps its existing release controls.  This bridge
copies those controls to a private temporary overlay, replaces only the pinned
Task 7 launcher and validator exception, records an immutable operator receipt,
and invokes the reviewed launcher in ``--execute`` mode.
"""

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def _load_check_bootstrap():
    path = Path(__file__).with_name("bootstrap_task7_release_check.py")
    spec = importlib.util.spec_from_file_location("task7_check_bootstrap", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load reviewed check bootstrap: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check_bootstrap = _load_check_bootstrap()


KEY_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _validate_identity(operator_user_id, approver_user_id):
    if operator_user_id <= 0 or approver_user_id <= 0:
        raise RuntimeError("operator and independent approver IDs must be positive")
    if operator_user_id == approver_user_id:
        raise RuntimeError("operator and independent approver IDs must differ")


def _write_receipt(path, approval, deployment_key, operator_user_id, approver_user_id):
    receipt = Path(path)
    for candidate in (receipt, *receipt.parents):
        if candidate.is_symlink():
            raise RuntimeError("bootstrap receipt path cannot be a symlink")
    receipt.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = {
        "before_commit": approval["before_commit"],
        "target_commit": approval["target_commit"],
        "changed_paths": approval["changed_paths"],
        "launcher_target_blob": approval["launcher_target_blob"],
        "bootstrap_sha256": approval["bootstrap_sha256"],
        "deployment_key": deployment_key,
        "operator_user_id": operator_user_id,
        "approver_user_id": approver_user_id,
        "scope": "task7_code_only_execute",
        "database_migration": False,
        "attachment_migration": False,
        "frontend_migration": False,
    }
    descriptor = os.open(
        receipt,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            json.dump(payload, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        try:
            receipt.unlink()
        except FileNotFoundError:
            pass
        raise
    directory = os.open(receipt.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def run_execute(
    *,
    project_root,
    tool_root,
    target_commit,
    deployment_key,
    approved_bootstrap_sha256,
    operator_user_id,
    approver_user_id,
):
    if not KEY_RE.fullmatch(deployment_key or ""):
        raise RuntimeError("invalid deployment key")
    if not re.fullmatch(r"[0-9a-f]{64}", approved_bootstrap_sha256 or ""):
        raise RuntimeError("approved bootstrap SHA256 must be a full lowercase digest")
    _validate_identity(operator_user_id, approver_user_id)
    approval = check_bootstrap.validate_transition(project_root, tool_root, target_commit)
    if approval["bootstrap_sha256"] != approved_bootstrap_sha256:
        raise RuntimeError("bootstrap SHA256 does not match the independently reviewed file")

    project = Path(project_root).resolve(strict=True)
    tool = Path(tool_root).resolve(strict=True)
    receipt = project / "data" / "deployments" / f"{deployment_key}.bootstrap.json"
    _write_receipt(receipt, approval, deployment_key, operator_user_id, approver_user_id)

    with tempfile.TemporaryDirectory(prefix=f"qr-task7-execute-{deployment_key}-") as temporary:
        temporary_root = Path(temporary)
        temporary_root.chmod(0o700)
        launcher = check_bootstrap.prepare_overlay(temporary_root / "overlay", approval, project, tool)
        target_worktree = temporary_root / "target-worktree"
        check_bootstrap._git(
            tool,
            "worktree",
            "add",
            "--quiet",
            "--detach",
            str(target_worktree),
            check_bootstrap.TARGET_COMMIT,
        )
        try:
            command = [
                "bash",
                str(launcher),
                "--project-root",
                str(project),
                "--tool-root",
                str(target_worktree),
                "--expected-before",
                check_bootstrap.BEFORE_COMMIT,
                "--target-commit",
                target_commit,
                "--deployment-key",
                deployment_key,
                "--execute",
            ]
            environment = os.environ.copy()
            environment["TMPDIR"] = str(temporary_root)
            result = subprocess.run(command, check=False, env=environment)
            if result.returncode:
                raise RuntimeError(f"real code-only --execute failed with exit {result.returncode}")
        finally:
            check_bootstrap._remove_target_worktree(tool, target_worktree)
    return approval


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--tool-root", required=True)
    parser.add_argument("--target-commit", required=True)
    parser.add_argument("--deployment-key", required=True)
    parser.add_argument("--approved-bootstrap-sha256", required=True)
    parser.add_argument("--operator-user-id", required=True, type=int)
    parser.add_argument("--approver-user-id", required=True, type=int)
    parser.add_argument("--execute", action="store_true", required=True)
    args = parser.parse_args(argv)
    run_execute(
        project_root=args.project_root,
        tool_root=args.tool_root,
        target_commit=args.target_commit,
        deployment_key=args.deployment_key,
        approved_bootstrap_sha256=args.approved_bootstrap_sha256,
        operator_user_id=args.operator_user_id,
        approver_user_id=args.approver_user_id,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
