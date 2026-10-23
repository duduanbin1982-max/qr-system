#!/usr/bin/env python3
"""Bootstrap the independently reviewed Task 6 release launcher.

This is a one-time, read-only bridge for installing the launcher fix merged in
PR #115 while the production checkout still contains the previous launcher.
It creates a temporary overlay containing the current production release
controls plus the reviewed launcher, then invokes that overlay in check-only
mode.  It never writes production evidence, acquires a fence, stops a service,
or exposes an execute mode.
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


SHA_RE = re.compile(r"^[0-9a-f]{40}$")
BEFORE = "8f928c2e6040346b986dac97d10fd50eb659140e"
TARGET_COMMIT = "7f9b5e0c1968eb5913e4f9176efe690741ae38b8"
MERGED_TOOL_COMMIT = "7fe3b80469607e4332ece71b082ff04fb09973fc"
REQUIRED_NODE_VERSION = "v24.22.0"
REQUIRED_NPM_VERSION = "11.19.1"
LAUNCHER_PATH = "scripts/deploy-code-only.sh"
LAUNCHER_BLOB = "98868bc7b612e59bae7b923085a1b8567a60a739"
CONTROL_ENTRIES = {
    "scripts/code_only_release.py": ("100644", "f619adedac535e03735f98f40adaa049b6eb9c1b"),
    "scripts/deployment_manifest.py": ("100644", "4ab0cf4e0b834426e22e10f24f11611313f0f494"),
    "scripts/backup-db.sh": ("100755", "0a8af7990690f6153731a3d67123ffa230df9aa6"),
    "scripts/rollback-deployment.sh": ("100644", "aa8591c6c3a97424c07e74fd45e8d5f1b4abed99"),
}
TARGET_ENTRIES = {
    "docs/deployment/release-gate-bootstrap.md": ("100644", "64d7351f4afd0748d2625bd2ec23771cd36f311b"),
    "modules/services/performance_history_planning.py": ("100644", "b7cdcaad1fe7abdbcc27a376bfd32d0194b6f5cb"),
    "modules/services/performance_quality_planning.py": ("100644", "abda4ee63e9fefa48f24c2080669a01b89acb233"),
    "scripts/bootstrap_release_gate.py": ("100644", "d7b5de416ebee7f058b940639da69090c0f89c65"),
    "tests/test_performance_quality_planning.py": ("100644", "ac11e90da54abba4e259553efe23f699ec9f8c67"),
    "tests/test_release_gate_bootstrap.py": ("100644", "4dcfa2eaa1f568125a08c8537c4a865c623afd4f"),
}


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


def _git(root, *args, check=True):
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=False,
    )
    if check and result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
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
    return hashlib.sha1(
        b"blob " + str(len(content)).encode("ascii") + b"\0" + content
    ).hexdigest()


def _regular_file(root, relative_path):
    path = Path(root) / relative_path
    if not path.is_file() or any(part.is_symlink() for part in (path, *path.parents)):
        raise RuntimeError(f"unsafe file: {path}")
    return path.read_bytes()


def _changed_paths(root, before, target):
    result = _git(root, "diff", "--no-renames", "--name-only", "-z", before, target, "--")
    return sorted(os.fsdecode(item) for item in result.stdout.split(b"\0") if item)


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


def validate_bootstrap(project_root, tool_root, target_commit=TARGET_COMMIT):
    """Return an immutable approval record without importing target code."""
    project = Path(project_root).resolve(strict=True)
    tool = Path(tool_root).resolve(strict=True)
    if project == tool or _is_nested(project, tool) or _is_nested(tool, project):
        raise RuntimeError("production and release-tool worktrees must be separate")
    if not SHA_RE.fullmatch(target_commit or "") or target_commit != TARGET_COMMIT:
        raise RuntimeError("target commit is not the approved Task 6 release")
    if _git(project, "rev-parse", "--verify", "HEAD").stdout.decode().strip() != BEFORE:
        raise RuntimeError("production checkout changed from the approved baseline")
    marker = project / ".deployed_commit"
    if marker.is_symlink() or not marker.is_file() or marker.read_text(encoding="ascii").strip() != BEFORE:
        raise RuntimeError("production deployed marker changed")
    _assert_clean(project, "production", allow_untracked_data=True)
    if _git(tool, "rev-parse", "--verify", "HEAD").stdout.decode().strip() != MERGED_TOOL_COMMIT:
        raise RuntimeError("release-tool worktree must be at the merged launcher fix")
    _assert_clean(tool, "release-tool")
    _git(tool, "cat-file", "-e", f"{target_commit}^{{commit}}")
    if _git(tool, "merge-base", "--is-ancestor", BEFORE, target_commit, check=False).returncode:
        raise RuntimeError("approved target is not based on the production baseline")
    changed = _changed_paths(tool, BEFORE, target_commit)
    if changed != sorted(TARGET_ENTRIES):
        raise RuntimeError(f"Task 6 target paths mismatch: {changed}")
    for path, (mode, blob) in TARGET_ENTRIES.items():
        if _entry(tool, target_commit, path) != (mode, "blob", blob):
            raise RuntimeError(f"Task 6 target entry mismatch: {path}")
    if _entry(tool, MERGED_TOOL_COMMIT, LAUNCHER_PATH) != ("100644", "blob", LAUNCHER_BLOB):
        raise RuntimeError("merged launcher blob does not match the approved PR #115 fix")
    controls = {}
    for path, (mode, blob) in CONTROL_ENTRIES.items():
        if _entry(project, BEFORE, path) != (mode, "blob", blob):
            raise RuntimeError(f"production baseline control entry mismatch: {path}")
        if _blob(_regular_file(project, path)) != blob:
            raise RuntimeError(f"production release control bytes changed: {path}")
        controls[path] = {"mode": mode, "blob": blob}
    return {
        "before_commit": BEFORE,
        "target_commit": TARGET_COMMIT,
        "merged_tool_commit": MERGED_TOOL_COMMIT,
        "launcher_path": LAUNCHER_PATH,
        "launcher_blob": LAUNCHER_BLOB,
        "changed_paths": changed,
        "controls": controls,
        "bootstrap_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }


def _replace_once(source, old, new):
    if source.count(old) != 1:
        raise RuntimeError(f"trusted launcher patch point drifted: {old}")
    return source.replace(old, new)


def prepare_overlay(overlay_root, approval, project_root, tool_root):
    overlay = Path(overlay_root).resolve()
    project = Path(project_root).resolve(strict=True)
    tool = Path(tool_root).resolve(strict=True)
    if _is_nested(overlay, project) or _is_nested(overlay, tool) or overlay in (project, tool):
        raise RuntimeError("bootstrap overlay must be outside production and tool worktrees")
    scripts = overlay / "scripts"
    scripts.mkdir(mode=0o700, parents=True)
    for path in CONTROL_ENTRIES:
        content = _regular_file(project, path)
        expected_blob = approval["controls"][path]["blob"]
        if _blob(content) != expected_blob:
            raise RuntimeError(f"production release control drifted during overlay preparation: {path}")
        destination = scripts / Path(path).name
        destination.write_bytes(content)
        destination.chmod(0o700)
    launcher = scripts / Path(LAUNCHER_PATH).name
    launcher_content = _git(tool, "show", f"{MERGED_TOOL_COMMIT}:{LAUNCHER_PATH}").stdout
    if _blob(launcher_content) != approval["launcher_blob"]:
        raise RuntimeError("merged launcher drifted during overlay preparation")
    launcher.write_bytes(launcher_content)
    source = launcher.read_text(encoding="utf-8")
    source = _replace_once(
        source,
        'if [[ "$SCRIPT_ROOT" != "$PROJECT_ROOT" ]]; then',
        "if [[ \"$SCRIPT_ROOT\" != " + shlex.quote(str(overlay))
        + " || \"$PROJECT_ROOT\" != " + shlex.quote(str(project)) + " ]]; then",
    )
    source = _replace_once(
        source,
        'install -m 0700 "$PROJECT_ROOT/scripts/$control" "$TRUST_ROOT/scripts/$control"',
        'install -m 0700 "$SCRIPT_ROOT/scripts/$control" "$TRUST_ROOT/scripts/$control"',
    )
    launcher.write_text(source, encoding="utf-8", newline="\n")
    launcher.chmod(0o700)
    subprocess.run([_bash_executable(), "-n", str(launcher)], check=True)
    return launcher


def _add_target_worktree(tool_root, destination):
    destination = Path(destination).resolve()
    subprocess.run(
        ["git", "-C", str(tool_root), "worktree", "add", "--quiet", "--detach", str(destination), TARGET_COMMIT],
        check=True,
    )
    return destination


def _remove_target_worktree(tool_root, destination):
    result = subprocess.run(
        ["git", "-C", str(tool_root), "worktree", "remove", "--force", str(destination)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode:
        raise RuntimeError(f"failed to remove temporary target worktree: {destination}")


def _validate_node_runtime(runtime_root):
    runtime = Path(runtime_root).resolve(strict=True)
    if not runtime.is_dir():
        raise RuntimeError("node runtime directory is missing or unsafe")
    node = runtime / "bin" / "node"
    npm = runtime / "bin" / "npm"
    for executable in (node, npm):
        if not executable.is_file():
            raise RuntimeError(f"required runtime executable is missing or unsafe: {executable}")
        resolved = executable.resolve(strict=True)
        try:
            resolved.relative_to(runtime)
        except ValueError as error:
            raise RuntimeError(f"runtime executable escapes the approved runtime: {executable}") from error
    node_version = subprocess.check_output([str(node), "--version"], text=True).strip()
    npm_version = subprocess.check_output([str(npm), "--version"], text=True).strip()
    if node_version != REQUIRED_NODE_VERSION or npm_version != REQUIRED_NPM_VERSION:
        raise RuntimeError(
            f"unsupported release-check runtime: node={node_version}, npm={npm_version}; "
            f"required node={REQUIRED_NODE_VERSION}, npm={REQUIRED_NPM_VERSION}"
        )
    return runtime, node, npm


def run_check_only(*, project_root, tool_root, target_commit, deployment_key, operator_user_id, approver_user_id, approved_bootstrap_sha256, node_runtime_dir):
    approval = validate_bootstrap(project_root, tool_root, target_commit)
    if approval["bootstrap_sha256"] != approved_bootstrap_sha256:
        raise RuntimeError("bootstrap SHA256 does not match the independently approved file")
    if operator_user_id <= 0 or approver_user_id <= 0 or operator_user_id == approver_user_id:
        raise RuntimeError("operator and independent approver IDs must be distinct positive integers")
    runtime, _, npm = _validate_node_runtime(node_runtime_dir)
    print(json.dumps({
        **approval,
        "deployment_key": deployment_key,
        "operator_user_id": operator_user_id,
        "approver_user_id": approver_user_id,
        "node_runtime_dir": str(runtime),
        "node_version": REQUIRED_NODE_VERSION,
        "npm_version": REQUIRED_NPM_VERSION,
    }, ensure_ascii=False, indent=2), flush=True)
    with tempfile.TemporaryDirectory(prefix="qr-release-tool-bootstrap-") as temporary:
        overlay = Path(temporary) / "overlay"
        launcher = prepare_overlay(overlay, approval, project_root, tool_root)
        target_worktree = Path(temporary) / "target-worktree"
        _add_target_worktree(tool_root, target_worktree)
        try:
            command = [
                _bash_executable(), str(launcher),
                "--project-root", str(Path(project_root).resolve()),
                "--tool-root", str(target_worktree),
                "--expected-before", BEFORE,
                "--target-commit", TARGET_COMMIT,
                "--deployment-key", deployment_key,
                "--check-only",
            ]
            environment = os.environ.copy()
            environment["PATH"] = str(runtime / "bin") + os.pathsep + environment.get("PATH", "")
            environment["NPM_BIN"] = str(npm)
            result = subprocess.run(command, check=False, env=environment)
            if result.returncode:
                raise RuntimeError(f"real code-only --check-only failed with exit {result.returncode}")
        finally:
            _remove_target_worktree(tool_root, target_worktree)
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
    parser.add_argument("--node-runtime-dir", required=True)
    parser.add_argument("--check-only", action="store_true", required=True)
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", args.deployment_key):
        raise RuntimeError("invalid deployment key")
    run_check_only(
        project_root=args.project_root,
        tool_root=args.tool_root,
        target_commit=args.target_commit,
        deployment_key=args.deployment_key,
        operator_user_id=args.operator_user_id,
        approver_user_id=args.approver_user_id,
        approved_bootstrap_sha256=args.approved_bootstrap_sha256,
        node_runtime_dir=args.node_runtime_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
