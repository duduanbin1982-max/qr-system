#!/usr/bin/env python3
"""Run the exact Task 7 release preflight through a temporary trusted overlay.

This bridge only supports --check-only. It does not write production evidence,
install release controls, acquire a write fence, or expose deployment mode.
"""

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import tempfile
from pathlib import Path


BEFORE_COMMIT = "7f9b5e0c1968eb5913e4f9176efe690741ae38b8"
TARGET_COMMIT = "dd97f9ffeee558299d8b83c3f86d86a3097ca962"
LAUNCHER_PATH = "scripts/deploy-code-only.sh"
APPROVED_LAUNCHER_BLOB = "98868bc7b612e59bae7b923085a1b8567a60a739"

CONTROL_ENTRIES = {
    "scripts/code_only_release.py": ("100644", "f619adedac535e03735f98f40adaa049b6eb9c1b"),
    "scripts/deployment_manifest.py": ("100644", "4ab0cf4e0b834426e22e10f24f11611313f0f494"),
    LAUNCHER_PATH: ("100644", "f916286b10611284f279ce1a722b0c2874d10258"),
    "scripts/backup-db.sh": ("100755", "0a8af7990690f6153731a3d67123ffa230df9aa6"),
    "scripts/rollback-deployment.sh": ("100644", "aa8591c6c3a97424c07e74fd45e8d5f1b4abed99"),
}

RUNTIME_PATHS = (
    "modules/app.py",
    "modules/config.py",
    "modules/app_extensions.py",
    "modules/db.py",
    "modules/deployment_write_fence.py",
    "modules/runtime_version.py",
)

TARGET_ENTRIES = {
    "modules/services/employee_document_storage.py": ("100644", "e6b0be7f386f59cadaa85f2850d50d9fe0a4daf0"),
    "modules/services/user_account_use_cases.py": ("100644", "bd5a463324165610a8d2ba158b680f39cf87bf25"),
    "modules/services/user_import_adapter.py": ("100644", "3de5549343c72e2ad8af3d94b4dd816e36578d44"),
    "modules/services/user_performance_assignment_coordinator.py": ("100644", "dab8a95eb657457386ae1e4cdf0177144be79189"),
    "modules/services/user_role_use_cases.py": ("100644", "86755b9d111bd06847d2c21c93dadeef184375c4"),
    "modules/services/user_service.py": ("100644", "bcb92ad7e6f7bc2932e2aaa90bb34c8b666a2ba8"),
    "scripts/bootstrap_release_tool.py": ("100644", "4e04dc31289a82f2af171ccf2569e5bf01e73895"),
    LAUNCHER_PATH: ("100644", APPROVED_LAUNCHER_BLOB),
    "tests/test_code_only_deployment.py": ("100644", "d665ae5fcf38670e03fc2b6c43603926880c7a02"),
    "tests/test_deployment_contracts.py": ("100644", "bb24c769588b8fd9dd5668c7a45c5ac272432c20"),
    "tests/test_release_tool_bootstrap.py": ("100644", "9ad921a27fafb9bac784ec89575d1381cf8eca9a"),
    "tests/test_user_task7_adapters.py": ("100644", "74d8d104bf6064e76843afc60aeb2330f7ae3083"),
}


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
    """Validate the one approved production-to-Task-7 transition."""
    project_input = Path(project_root)
    tool_input = Path(tool_root)
    if project_input.is_symlink() or tool_input.is_symlink():
        raise RuntimeError("production and tool worktree roots cannot be symlinks")
    project = project_input.resolve(strict=True)
    tool = tool_input.resolve(strict=True)
    if project == tool or _is_nested(project, tool) or _is_nested(tool, project):
        raise RuntimeError("production and release-tool worktrees must be separate")
    if not re.fullmatch(r"[0-9a-f]{40}", target_commit or "") or target_commit != TARGET_COMMIT:
        raise RuntimeError("target commit is not the approved Task 7 merge")

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
        raise RuntimeError("release-tool worktree HEAD must equal the Task 7 merge")
    _assert_clean(tool, "release-tool")
    _git(tool, "cat-file", "-e", f"{BEFORE_COMMIT}^{{commit}}")
    if _git(tool, "merge-base", "--is-ancestor", BEFORE_COMMIT, TARGET_COMMIT, check=False).returncode:
        raise RuntimeError("Task 7 merge is not based on the production baseline")

    changed = _changed_paths(tool, BEFORE_COMMIT, TARGET_COMMIT)
    if changed != sorted(TARGET_ENTRIES):
        raise RuntimeError(f"Task 7 changed paths mismatch: {changed}")
    for path, (expected_mode, expected_blob) in TARGET_ENTRIES.items():
        if _entry(tool, TARGET_COMMIT, path) != (expected_mode, "blob", expected_blob):
            raise RuntimeError(f"Task 7 target entry mismatch: {path}")

    controls = {}
    for path, (mode, blob) in CONTROL_ENTRIES.items():
        expected_before = (mode, "blob", blob)
        if _entry(project, BEFORE_COMMIT, path) != expected_before:
            raise RuntimeError(f"production baseline control entry mismatch: {path}")
        if _blob(_regular_file(project, path)) != blob:
            raise RuntimeError(f"production release control bytes changed: {path}")
        expected_target = (
            (mode, "blob", APPROVED_LAUNCHER_BLOB)
            if path == LAUNCHER_PATH
            else expected_before
        )
        if _entry(tool, TARGET_COMMIT, path) != expected_target:
            raise RuntimeError(f"Task 7 release control transition mismatch: {path}")
        controls[path] = {"mode": mode, "before_blob": blob}

    for path in RUNTIME_PATHS:
        if _entry(tool, BEFORE_COMMIT, path) != _entry(tool, TARGET_COMMIT, path):
            raise RuntimeError(f"Task 7 changes protected runtime path: {path}")
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
        "launcher_target_blob": APPROVED_LAUNCHER_BLOB,
        "bootstrap_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "mode": "check_only",
    }


def _replace_once(source, old, new):
    if source.count(old) != 1:
        raise RuntimeError(f"trusted release source patch point drifted: {old[:90]}")
    return source.replace(old, new)


def prepare_overlay(overlay_root, approval, project_root, tool_root):
    """Build temporary controls from production plus the exact approved launcher."""
    overlay_input = Path(overlay_root)
    project = Path(project_root).resolve(strict=True)
    tool = Path(tool_root).resolve(strict=True)
    overlay = overlay_input.resolve()
    if overlay in (project, tool) or _is_nested(overlay, project) or _is_nested(overlay, tool):
        raise RuntimeError("bootstrap overlay must be outside production and tool worktrees")
    overlay.mkdir(mode=0o700, parents=True, exist_ok=False)
    scripts = overlay / "scripts"
    scripts.mkdir(mode=0o700)

    for path, (_, expected_blob) in CONTROL_ENTRIES.items():
        if path == LAUNCHER_PATH:
            continue
        content = _regular_file(project, path)
        if _blob(content) != approval["controls"][path]["before_blob"]:
            raise RuntimeError(f"production control drifted during overlay preparation: {path}")
        destination = scripts / Path(path).name
        destination.write_bytes(content)
        destination.chmod(0o700)

    launcher_content = _git(tool, "show", f"{TARGET_COMMIT}:{LAUNCHER_PATH}").stdout
    if _blob(launcher_content) != approval["launcher_target_blob"]:
        raise RuntimeError("Task 7 launcher drifted after bootstrap approval")
    launcher = scripts / Path(LAUNCHER_PATH).name
    launcher.write_bytes(launcher_content)
    launcher.chmod(0o700)

    policy = scripts / "code_only_release.py"
    source = policy.read_text(encoding="utf-8")
    source = _replace_once(
        source,
        "def _assert_release_controls_unchanged(repository, before_commit, target_commit):\n"
        "    for path in PROTECTED_RELEASE_CONTROL_PATHS:\n",
        "def _assert_release_controls_unchanged(repository, before_commit, target_commit):\n"
        "    for path in PROTECTED_RELEASE_CONTROL_PATHS:\n"
        '        if path == "scripts/deploy-code-only.sh":\n'
        '            target = _git(repository, "rev-parse", f"{target_commit}:{path}", check=False)\n'
        f'            if target.returncode or target.stdout.strip().decode("ascii") != "{APPROVED_LAUNCHER_BLOB}":\n'
        '                raise RuntimeError("code-only release cannot change an unapproved launcher")\n'
        "            continue\n",
    )
    source = _replace_once(
        source,
        "        if _path_is_forbidden(path) and path not in documentation_only\n",
        "        if (\n"
        "            _path_is_forbidden(path)\n"
        "            and path not in documentation_only\n"
        '            and path != "scripts/deploy-code-only.sh"\n'
        "        )\n",
    )
    policy.write_text(source, encoding="utf-8", newline="\n")
    policy.chmod(0o700)

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
    subprocess.run(["bash", "-n", str(launcher)], check=True)
    return launcher


def _remove_target_worktree(tool_root, destination):
    result = subprocess.run(
        ["git", "-C", str(tool_root), "worktree", "remove", "--force", str(destination)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"failed to remove temporary Task 7 worktree: {destination}")


def run_check_only(
    *, project_root, tool_root, target_commit, deployment_key, approved_bootstrap_sha256
):
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", deployment_key or ""):
        raise RuntimeError("invalid check-only key")
    if not re.fullmatch(r"[0-9a-f]{64}", approved_bootstrap_sha256 or ""):
        raise RuntimeError("approved bootstrap SHA256 must be a full lowercase digest")
    approval = validate_transition(project_root, tool_root, target_commit)
    if approval["bootstrap_sha256"] != approved_bootstrap_sha256:
        raise RuntimeError("bootstrap SHA256 does not match the independently reviewed file")
    print(json.dumps({**approval, "check_only_key": deployment_key}, ensure_ascii=False, indent=2), flush=True)

    project = Path(project_root).resolve(strict=True)
    tool = Path(tool_root).resolve(strict=True)
    initial_head = _git(project, "rev-parse", "HEAD").stdout.decode().strip()
    initial_marker = (project / ".deployed_commit").read_bytes()
    with tempfile.TemporaryDirectory(prefix=f"qr-task7-check-{deployment_key}-") as temporary:
        temporary_root = Path(temporary)
        temporary_root.chmod(0o700)
        launcher = prepare_overlay(temporary_root / "overlay", approval, project, tool)
        target_worktree = temporary_root / "target-worktree"
        _git(tool, "worktree", "add", "--quiet", "--detach", str(target_worktree), TARGET_COMMIT)
        try:
            command = [
                "bash", str(launcher),
                "--project-root", str(project),
                "--tool-root", str(target_worktree),
                "--expected-before", BEFORE_COMMIT,
                "--target-commit", TARGET_COMMIT,
                "--deployment-key", deployment_key,
                "--check-only",
            ]
            environment = os.environ.copy()
            environment["TMPDIR"] = str(temporary_root)
            result = subprocess.run(command, check=False, env=environment)
            if result.returncode:
                raise RuntimeError(f"real code-only --check-only failed with exit {result.returncode}")
        finally:
            _remove_target_worktree(tool, target_worktree)

    _assert_clean(tool, "release-tool")
    if _git(project, "rev-parse", "HEAD").stdout.decode().strip() != initial_head:
        raise RuntimeError("production code HEAD changed during check-only")
    if (project / ".deployed_commit").read_bytes() != initial_marker:
        raise RuntimeError("production deployed marker changed during check-only")
    return approval


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--tool-root", required=True)
    parser.add_argument("--target-commit", required=True)
    parser.add_argument("--check-only-key", required=True)
    parser.add_argument("--approved-bootstrap-sha256", required=True)
    parser.add_argument("--check-only", action="store_true", required=True)
    args = parser.parse_args(argv)
    run_check_only(
        project_root=args.project_root,
        tool_root=args.tool_root,
        target_commit=args.target_commit,
        deployment_key=args.check_only_key,
        approved_bootstrap_sha256=args.approved_bootstrap_sha256,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
