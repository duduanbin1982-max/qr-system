#!/usr/bin/env python3
"""Bridge the reviewed release-control transition for check and execute modes.

The production checkout still contains the previous release policy while the
Task 8 target carries a reviewed update to that policy. This bootstrap builds a
temporary trusted overlay, permits only that exact policy blob transition, and
invokes the normal code-only release flow. Check-only is read-only; execute
requires a separately reviewed digest and records a durable receipt first.
"""

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


BEFORE_COMMIT = "dd97f9ffeee558299d8b83c3f86d86a3097ca962"
TARGET_COMMIT = "1882fc1af015927041fd341b4b357398460db42d"
POLICY_PATH = "scripts/code_only_release.py"
LAUNCHER_PATH = "scripts/deploy-code-only.sh"
OLD_POLICY_BLOB = "f619adedac535e03735f98f40adaa049b6eb9c1b"
TARGET_POLICY_BLOB = "7fa3364f958b588246b865ab2cbf0da12d2c3a4a"
LAUNCHER_BLOB = "98868bc7b612e59bae7b923085a1b8567a60a739"

CONTROL_ENTRIES = {
    POLICY_PATH: ("100644", OLD_POLICY_BLOB),
    LAUNCHER_PATH: ("100644", LAUNCHER_BLOB),
    "scripts/deployment_manifest.py": (
        "100644",
        "4ab0cf4e0b834426e22e10f24f11611313f0f494",
    ),
    "scripts/rollback-deployment.sh": (
        "100644",
        "aa8591c6c3a97424c07e74fd45e8d5f1b4abed99",
    ),
    "scripts/backup-db.sh": (
        "100755",
        "0a8af7990690f6153731a3d67123ffa230df9aa6",
    ),
}

TARGET_ENTRIES = {
    "docs/deployment/task7-release-check-bootstrap.md": (
        "100644",
        "564dca53a7b3e829dd4ef0dde121d45d58b19316",
    ),
    "modules/domain/legacy_process_line_admission.py": (
        "100644",
        "4e54461e366a62483efdcbf03b1d50b2a3915026",
    ),
    "modules/services/order_service.py": (
        "100644",
        "91574fd33aaf11795fea1f2bc54c6a5581191daf",
    ),
    "modules/services/schedule_service.py": (
        "100644",
        "91d5cadfa5c4d9cf46df6a911f41ea324861eca6",
    ),
    "scripts/bootstrap_task7_release_check.py": (
        "100644",
        "5a3a55416a4f19cd2da996572a87a804e9a0eff9",
    ),
    "scripts/bootstrap_task7_release_execute.py": (
        "100644",
        "7eca491d49bc684528a9199a5b9ce6329f02c792",
    ),
    POLICY_PATH: ("100644", TARGET_POLICY_BLOB),
    "tests/test_code_only_deployment.py": (
        "100644",
        "119b13bd49adae196096ac62a0b59b351d950a37",
    ),
    "tests/test_legacy_process_line_admission.py": (
        "100644",
        "28e0264572fe5025b7c86c82620a3ed1ec13b3b2",
    ),
    "tests/test_release_gate_bootstrap.py": (
        "100644",
        "4f465d4cf58cbd6ebb8ffc280c3beda9b74208f2",
    ),
    "tests/test_task7_release_check_bootstrap.py": (
        "100644",
        "3acfc529e329c5e4e7d386d3a1b4bff4c153f9cb",
    ),
    "tests/test_task7_release_execute_bootstrap.py": (
        "100644",
        "60352102176c859ed461872c3597dbd52d7409a4",
    ),
}

RUNTIME_PATHS = (
    "modules/app.py",
    "modules/config.py",
    "modules/app_extensions.py",
    "modules/db.py",
    "modules/deployment_write_fence.py",
    "modules/runtime_version.py",
)


def _bash_executable():
    """Use Git Bash on Windows instead of the WSL bash launcher."""
    if sys.platform != "win32":
        return "bash"
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        directory = os.environ.get(variable)
        if directory:
            candidate = Path(directory) / "Git" / "bin" / "bash.exe"
            if candidate.is_file():
                return str(candidate.resolve())
    candidate = shutil.which("bash")
    if candidate:
        executable = Path(candidate)
        excluded = {"windowsapps", "system32", "sysnative"}
        if not excluded.intersection(part.casefold() for part in executable.parts) and executable.is_file():
            return str(executable.resolve())
    raise RuntimeError("Git Bash is required on Windows; WSL and WindowsApps bash launchers are unsupported")


def _git(root, *arguments, check=True):
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(arguments)} failed: {detail}")
    return result


def _entry(root, commit, path):
    result = _git(root, "ls-tree", commit, "--", path)
    lines = result.stdout.rstrip(b"\n").splitlines()
    if len(lines) != 1:
        raise RuntimeError(f"missing or ambiguous Git entry: {path}")
    metadata, name = lines[0].split(b"\t", 1)
    if name.decode("utf-8") != path:
        raise RuntimeError(f"Git entry path mismatch: {path}")
    return tuple(metadata.decode("ascii").split())


def _blob(content):
    header = b"blob " + str(len(content)).encode("ascii") + b"\0"
    return hashlib.sha1(header + content).hexdigest()


def _regular_file(root, relative_path):
    path = Path(root) / relative_path
    if not path.is_file() or any(part.is_symlink() for part in (path, *path.parents)):
        raise RuntimeError(f"unsafe file: {path}")
    return path.read_bytes()


def _changed_paths(repository, before_commit, target_commit):
    result = _git(
        repository,
        "diff",
        "--no-renames",
        "--name-only",
        "-z",
        before_commit,
        target_commit,
        "--",
    )
    return sorted(os.fsdecode(path) for path in result.stdout.split(b"\0") if path)


def _tracked_data_paths(repository, commit):
    result = _git(repository, "ls-tree", "-r", "--name-only", "-z", commit, "--", "data")
    return [os.fsdecode(path) for path in result.stdout.split(b"\0") if path]


def _is_nested(path, parent):
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _assert_clean(root, label, *, allow_untracked_data=False):
    result = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    unexpected = []
    for entry in result.stdout.split(b"\0"):
        if not entry:
            continue
        status = entry[:2]
        path = os.fsdecode(entry[3:])
        if allow_untracked_data and status == b"??" and (path == "data" or path.startswith("data/")):
            continue
        unexpected.append(f"{status.decode('ascii', errors='replace')} {path}")
    if unexpected:
        raise RuntimeError(f"{label} worktree is not clean: {'; '.join(unexpected[:10])}")


def validate_transition(project_root, tool_root, target_commit=TARGET_COMMIT):
    """Validate the exact production-to-Task-8 transition."""
    project_input = Path(project_root)
    tool_input = Path(tool_root)
    if project_input.is_symlink() or tool_input.is_symlink():
        raise RuntimeError("production and tool worktree roots cannot be symlinks")
    project = project_input.resolve(strict=True)
    tool = tool_input.resolve(strict=True)
    if project == tool or _is_nested(project, tool) or _is_nested(tool, project):
        raise RuntimeError("production and release-tool worktrees must be separate")
    if not re.fullmatch(r"[0-9a-f]{40}", target_commit or "") or target_commit != TARGET_COMMIT:
        raise RuntimeError("target commit is not the approved Task 8 merge")

    project_head = _git(project, "rev-parse", "--verify", "HEAD").stdout.decode().strip()
    if project_head != BEFORE_COMMIT:
        raise RuntimeError("production HEAD changed from the approved baseline")
    marker = project / ".deployed_commit"
    if marker.is_symlink() or not marker.is_file():
        raise RuntimeError("production deployed marker is missing or unsafe")
    if marker.read_text(encoding="ascii").strip().lower() != BEFORE_COMMIT:
        raise RuntimeError("production deployed marker changed")
    _assert_clean(project, "production", allow_untracked_data=True)

    tool_head = _git(tool, "rev-parse", "--verify", "HEAD").stdout.decode().strip()
    if tool_head != TARGET_COMMIT:
        raise RuntimeError("release-tool worktree HEAD must equal the Task 8 merge")
    _assert_clean(tool, "release-tool")
    _git(tool, "cat-file", "-e", f"{BEFORE_COMMIT}^{{commit}}")
    if _git(tool, "merge-base", "--is-ancestor", BEFORE_COMMIT, TARGET_COMMIT, check=False).returncode:
        raise RuntimeError("Task 8 merge is not based on the production baseline")

    changed = _changed_paths(tool, BEFORE_COMMIT, TARGET_COMMIT)
    if changed != sorted(TARGET_ENTRIES):
        raise RuntimeError(f"Task 8 changed paths mismatch: {changed}")
    for path, (expected_mode, expected_blob) in TARGET_ENTRIES.items():
        if _entry(tool, TARGET_COMMIT, path) != (expected_mode, "blob", expected_blob):
            raise RuntimeError(f"Task 8 target entry mismatch: {path}")

    controls = {}
    for path, (mode, before_blob) in CONTROL_ENTRIES.items():
        expected_before = (mode, "blob", before_blob)
        if _entry(project, BEFORE_COMMIT, path) != expected_before:
            raise RuntimeError(f"production baseline control entry mismatch: {path}")
        if _blob(_regular_file(project, path)) != before_blob:
            raise RuntimeError(f"production release control bytes changed: {path}")
        target_blob = TARGET_POLICY_BLOB if path == POLICY_PATH else before_blob
        if _entry(tool, TARGET_COMMIT, path) != (mode, "blob", target_blob):
            raise RuntimeError(f"Task 8 release control transition mismatch: {path}")
        controls[path] = {"mode": mode, "before_blob": before_blob, "target_blob": target_blob}

    for path in RUNTIME_PATHS:
        if _entry(tool, BEFORE_COMMIT, path) != _entry(tool, TARGET_COMMIT, path):
            raise RuntimeError(f"Task 8 changes protected runtime path: {path}")
    if _tracked_data_paths(tool, BEFORE_COMMIT) or _tracked_data_paths(tool, TARGET_COMMIT):
        raise RuntimeError("code-only release refuses commits that track production data/")

    return {
        "before_commit": BEFORE_COMMIT,
        "target_commit": TARGET_COMMIT,
        "changed_paths": changed,
        "target_entries": {
            path: {"mode": mode, "blob": blob}
            for path, (mode, blob) in TARGET_ENTRIES.items()
        },
        "controls": controls,
        "bootstrap_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "mode": "check_only",
    }


def _replace_once(source, old, new):
    if source.count(old) != 1:
        raise RuntimeError(f"trusted release source patch point drifted: {old[:90]}")
    return source.replace(old, new)


def prepare_overlay(overlay_root, approval, project_root, tool_root):
    """Build a temporary control overlay with one exact policy exception."""
    overlay_input = Path(overlay_root)
    project = Path(project_root).resolve(strict=True)
    tool = Path(tool_root).resolve(strict=True)
    overlay = overlay_input.resolve()
    if overlay in (project, tool) or _is_nested(overlay, project) or _is_nested(overlay, tool):
        raise RuntimeError("bootstrap overlay must be outside production and tool worktrees")
    overlay.mkdir(mode=0o700, parents=True, exist_ok=False)
    scripts = overlay / "scripts"
    scripts.mkdir(mode=0o700)

    for path, metadata in CONTROL_ENTRIES.items():
        if path == POLICY_PATH:
            continue
        content = _regular_file(project, path)
        if _blob(content) != metadata[1]:
            raise RuntimeError(f"production control drifted during overlay preparation: {path}")
        destination = scripts / Path(path).name
        destination.write_bytes(content)
        destination.chmod(0o700)

    policy_content = _git(tool, "show", f"{TARGET_COMMIT}:{POLICY_PATH}").stdout
    if _blob(policy_content) != TARGET_POLICY_BLOB:
        raise RuntimeError("Task 8 target release policy drifted after approval")
    policy = scripts / Path(POLICY_PATH).name
    source = policy_content.decode("utf-8")
    source = _replace_once(
        source,
        '        if APPROVED_RELEASE_CONTROL_BLOB_TRANSITIONS.get(path) == (\n',
        '        if path == "scripts/code_only_release.py":\n'
        f'            if (before_blob, target_blob) != ("{OLD_POLICY_BLOB}", "{TARGET_POLICY_BLOB}"):\n'
        '                raise RuntimeError("code-only release cannot change an unapproved policy")\n'
        '            continue\n'
        '        if APPROVED_RELEASE_CONTROL_BLOB_TRANSITIONS.get(path) == (\n',
    )
    source = _replace_once(
        source,
        'def _path_is_forbidden(path):\n'
        '    normalized = PurePosixPath(path).as_posix()\n',
        'def _path_is_forbidden(path):\n'
        '    normalized = PurePosixPath(path).as_posix()\n'
        '    if normalized == "scripts/code_only_release.py":\n'
        '        return False\n',
    )
    policy.write_text(source, encoding="utf-8", newline="\n")
    policy.chmod(0o700)

    launcher_content = _git(tool, "show", f"{TARGET_COMMIT}:{LAUNCHER_PATH}").stdout
    if _blob(launcher_content) != LAUNCHER_BLOB:
        raise RuntimeError("Task 8 launcher drifted after approval")
    launcher = scripts / Path(LAUNCHER_PATH).name
    launcher.write_bytes(launcher_content)
    launcher.chmod(0o700)
    launcher_source = launcher.read_text(encoding="utf-8")
    launcher_source = _replace_once(
        launcher_source,
        'if [[ "$SCRIPT_ROOT" != "$PROJECT_ROOT" ]]; then',
        "if [[ \"$SCRIPT_ROOT\" != " + shlex.quote(str(overlay))
        + " || \"$PROJECT_ROOT\" != " + shlex.quote(str(project)) + " ]]; then",
    )
    launcher_source = _replace_once(
        launcher_source,
        'install -m 0700 "$PROJECT_ROOT/scripts/$control" "$TRUST_ROOT/scripts/$control"',
        'install -m 0700 "$SCRIPT_ROOT/scripts/$control" "$TRUST_ROOT/scripts/$control"',
    )
    launcher.write_text(launcher_source, encoding="utf-8", newline="\n")
    launcher.chmod(0o700)
    subprocess.run([_bash_executable(), "-n", str(launcher)], check=True)
    return launcher


def _remove_target_worktree(tool_root, destination):
    result = subprocess.run(
        ["git", "-C", str(tool_root), "worktree", "remove", "--force", str(destination)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"failed to remove temporary Task 8 worktree: {destination}")


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
        **approval,
        "deployment_key": deployment_key,
        "operator_user_id": operator_user_id,
        "approver_user_id": approver_user_id,
        "scope": "task8_release_control_code_only_execute",
        "database_migration": False,
        "attachment_migration": False,
        "frontend_migration": False,
    }
    descriptor = os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
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
    if hasattr(os, "O_DIRECTORY"):
        directory = os.open(receipt.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def _invoke_launcher(*, project, tool, approval, deployment_key, mode, temporary_root):
    launcher = prepare_overlay(temporary_root / "overlay", approval, project, tool)
    target_worktree = temporary_root / "target-worktree"
    _git(tool, "worktree", "add", "--quiet", "--detach", str(target_worktree), TARGET_COMMIT)
    try:
        command = [
            _bash_executable(),
            str(launcher),
            "--project-root",
            str(project),
            "--tool-root",
            str(target_worktree),
            "--expected-before",
            BEFORE_COMMIT,
            "--target-commit",
            TARGET_COMMIT,
            "--deployment-key",
            deployment_key,
            mode,
        ]
        environment = os.environ.copy()
        environment["TMPDIR"] = str(temporary_root)
        result = subprocess.run(command, check=False, env=environment)
        if result.returncode:
            raise RuntimeError(f"real code-only {mode} failed with exit {result.returncode}")
    finally:
        _remove_target_worktree(tool, target_worktree)


def run_check_only(*, project_root, tool_root, target_commit, deployment_key):
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", deployment_key or ""):
        raise RuntimeError("invalid check-only key")
    approval = validate_transition(project_root, tool_root, target_commit)
    print(json.dumps({**approval, "check_only_key": deployment_key}, ensure_ascii=False, indent=2), flush=True)

    project = Path(project_root).resolve(strict=True)
    tool = Path(tool_root).resolve(strict=True)
    initial_head = _git(project, "rev-parse", "HEAD").stdout.decode().strip()
    initial_marker = (project / ".deployed_commit").read_bytes()
    with tempfile.TemporaryDirectory(prefix=f"qr-task8-check-{deployment_key}-") as temporary:
        temporary_root = Path(temporary)
        temporary_root.chmod(0o700)
        _invoke_launcher(
            project=project,
            tool=tool,
            approval=approval,
            deployment_key=deployment_key,
            mode="--check-only",
            temporary_root=temporary_root,
        )

    _assert_clean(tool, "release-tool")
    if _git(project, "rev-parse", "HEAD").stdout.decode().strip() != initial_head:
        raise RuntimeError("production code HEAD changed during check-only")
    if (project / ".deployed_commit").read_bytes() != initial_marker:
        raise RuntimeError("production deployed marker changed during check-only")
    return approval


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
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", deployment_key or ""):
        raise RuntimeError("invalid deployment key")
    if not re.fullmatch(r"[0-9a-f]{64}", approved_bootstrap_sha256 or ""):
        raise RuntimeError("approved bootstrap SHA256 must be a full lowercase digest")
    _validate_identity(operator_user_id, approver_user_id)
    approval = validate_transition(project_root, tool_root, target_commit)
    if approval["bootstrap_sha256"] != approved_bootstrap_sha256:
        raise RuntimeError("bootstrap SHA256 does not match the independently reviewed file")

    project = Path(project_root).resolve(strict=True)
    tool = Path(tool_root).resolve(strict=True)
    receipt = project / "data" / "deployments" / f"{deployment_key}.bootstrap.json"
    _write_receipt(receipt, approval, deployment_key, operator_user_id, approver_user_id)
    with tempfile.TemporaryDirectory(prefix=f"qr-task8-execute-{deployment_key}-") as temporary:
        temporary_root = Path(temporary)
        temporary_root.chmod(0o700)
        _invoke_launcher(
            project=project,
            tool=tool,
            approval=approval,
            deployment_key=deployment_key,
            mode="--execute",
            temporary_root=temporary_root,
        )
    return approval


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--tool-root", required=True)
    parser.add_argument("--target-commit", required=True)
    parser.add_argument("--deployment-key", "--check-only-key", dest="deployment_key", required=True)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check-only", action="store_true")
    modes.add_argument("--execute", action="store_true")
    parser.add_argument("--approved-bootstrap-sha256")
    parser.add_argument("--operator-user-id", type=int)
    parser.add_argument("--approver-user-id", type=int)
    args = parser.parse_args(argv)
    if args.execute:
        if not args.approved_bootstrap_sha256 or args.operator_user_id is None or args.approver_user_id is None:
            parser.error("--execute requires --approved-bootstrap-sha256, --operator-user-id and --approver-user-id")
        run_execute(
            project_root=args.project_root,
            tool_root=args.tool_root,
            target_commit=args.target_commit,
            deployment_key=args.deployment_key,
            approved_bootstrap_sha256=args.approved_bootstrap_sha256,
            operator_user_id=args.operator_user_id,
            approver_user_id=args.approver_user_id,
        )
    else:
        run_check_only(
            project_root=args.project_root,
            tool_root=args.tool_root,
            target_commit=args.target_commit,
            deployment_key=args.deployment_key,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
