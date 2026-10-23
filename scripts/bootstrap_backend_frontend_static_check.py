#!/usr/bin/env python3
"""Run the reviewed backend/static release check through a temporary overlay."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


SHA_RE = re.compile(r"^[0-9a-f]{40}$")
KEY_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
BASELINE_CONTROLS = (
    "scripts/code_only_release.py",
    "scripts/backup-db.sh",
)
OVERLAY_CONTROLS = (
    "scripts/backend_frontend_static_release.py",
    "scripts/deployment_manifest.py",
    "scripts/rollback-deployment.sh",
    "scripts/deploy-backend-frontend-static.sh",
)


def _git(root, *args, check=True):
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return result


def _entry(root, commit, path):
    result = _git(root, "ls-tree", "-z", commit, "--", path)
    entries = [item for item in result.stdout.split(b"\0") if item]
    if len(entries) != 1:
        raise RuntimeError(f"missing or ambiguous Git entry: {path}")
    metadata, raw_path = entries[0].split(b"\t", 1)
    mode, kind, blob = metadata.decode("ascii").split()
    if raw_path.decode("utf-8", errors="surrogateescape") != path:
        raise RuntimeError(f"Git entry path mismatch: {path}")
    if kind != "blob" or mode not in {"100644", "100755"}:
        raise RuntimeError(f"release control must be a regular Git file: {path}")
    return mode, blob


def _read_tree_file(root, commit, path):
    _entry(root, commit, path)
    return _git(root, "show", f"{commit}:{path}").stdout


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


def _within(child, parent):
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _validate_runtime(runtime_dir, tool_root, target_commit):
    runtime = Path(runtime_dir).resolve(strict=True)
    if not runtime.is_dir():
        raise RuntimeError("pinned Node runtime directory is not a directory")
    node = runtime / "bin" / "node"
    npm = runtime / "bin" / "npm"
    for executable in (node, npm):
        if not executable.is_file():
            raise RuntimeError(f"pinned executable is missing: {executable}")
        try:
            executable.resolve(strict=True).relative_to(runtime)
        except ValueError as error:
            raise RuntimeError(f"pinned executable escapes runtime directory: {executable}") from error

    package = json.loads(_read_tree_file(tool_root, target_commit, "package.json"))
    engines = package.get("engines") or {}
    required_node = engines.get("node")
    required_npm = engines.get("npm")
    if not required_node or not required_npm:
        raise RuntimeError("target package.json must pin both Node and npm")
    runtime_env = os.environ.copy()
    runtime_env["PATH"] = str(runtime / "bin") + os.pathsep + runtime_env.get("PATH", "")
    actual_node = subprocess.check_output(
        [str(node), "--version"], text=True, env=runtime_env
    ).strip().removeprefix("v")
    actual_npm = subprocess.check_output(
        [str(npm), "--version"], text=True, env=runtime_env
    ).strip()
    if actual_node != required_node or actual_npm != required_npm:
        raise RuntimeError(
            f"runtime mismatch: target requires Node {required_node}/npm {required_npm}; "
            f"found Node {actual_node}/npm {actual_npm}"
        )
    return runtime, node, npm, required_node, required_npm


def validate_bootstrap(
    project_root,
    tool_root,
    *,
    expected_before,
    target_commit,
    tool_commit,
    approved_bootstrap_sha256,
):
    if not all(SHA_RE.fullmatch(value or "") for value in (expected_before, target_commit, tool_commit)):
        raise RuntimeError("baseline, target, and tool commits must be full lowercase SHA values")
    bootstrap_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if bootstrap_sha256 != approved_bootstrap_sha256:
        raise RuntimeError("bootstrap SHA256 does not match the independently reviewed file")

    project = Path(project_root).resolve(strict=True)
    tool = Path(tool_root).resolve(strict=True)
    if project == tool or _within(project, tool) or _within(tool, project):
        raise RuntimeError("production and release-tool worktrees must be separate and non-nested")
    if _git(project, "rev-parse", "--verify", "HEAD").stdout.decode().strip() != expected_before:
        raise RuntimeError("production checkout differs from the confirmed baseline")
    marker = project / ".deployed_commit"
    if marker.is_symlink() or not marker.is_file() or marker.read_text(encoding="ascii").strip() != expected_before:
        raise RuntimeError("production deployed-commit marker differs from the confirmed baseline")
    _assert_clean(project, "production", allow_untracked_data=True)
    fence = project / "data/deployments/write-fence.json"
    if fence.exists() or fence.is_symlink():
        raise RuntimeError("production write-fence file is present; check-only is refused")

    if _git(tool, "rev-parse", "--verify", "HEAD").stdout.decode().strip() != tool_commit:
        raise RuntimeError("release-tool worktree does not match the reviewed tool commit")
    _assert_clean(tool, "release-tool")
    _git(tool, "cat-file", "-e", f"{target_commit}^{{commit}}")
    if _git(tool, "merge-base", "--is-ancestor", expected_before, target_commit, check=False).returncode:
        raise RuntimeError("target commit is not based on the confirmed production baseline")
    if _git(tool, "merge-base", "--is-ancestor", target_commit, tool_commit, check=False).returncode:
        raise RuntimeError("reviewed release-tool commit does not contain the target commit")

    baseline_controls = {}
    for path in BASELINE_CONTROLS:
        mode, blob = _entry(project, expected_before, path)
        if _entry(tool, target_commit, path) != (mode, blob):
            raise RuntimeError(f"target changes a baseline release control: {path}")
        baseline_bytes = _read_tree_file(project, expected_before, path)
        if (project / path).read_bytes() != baseline_bytes:
            raise RuntimeError(f"production release control bytes differ from baseline: {path}")
        baseline_controls[path] = {"mode": mode, "blob": blob}

    reviewed_controls = {}
    for path in OVERLAY_CONTROLS:
        mode, blob = _entry(tool, tool_commit, path)
        content = _read_tree_file(tool, tool_commit, path)
        if (tool / path).read_bytes() != content:
            raise RuntimeError(f"release-tool control bytes differ from reviewed commit: {path}")
        reviewed_controls[path] = {"mode": mode, "blob": blob, "sha256": hashlib.sha256(content).hexdigest()}

    return {
        "before_commit": expected_before,
        "target_commit": target_commit,
        "tool_commit": tool_commit,
        "baseline_controls": baseline_controls,
        "reviewed_controls": reviewed_controls,
        "bootstrap_sha256": bootstrap_sha256,
    }


def prepare_overlay(destination, project_root, tool_root, approval):
    overlay = Path(destination).resolve()
    project = Path(project_root).resolve(strict=True)
    tool = Path(tool_root).resolve(strict=True)
    if any(
        _within(left, right) or _within(right, left)
        for left, right in ((overlay, project), (overlay, tool))
    ):
        raise RuntimeError("temporary overlay must be outside production and release-tool worktrees")
    scripts = overlay / "scripts"
    scripts.mkdir(mode=0o700, parents=True)
    (scripts / "__init__.py").write_bytes(b"")
    (scripts / "__init__.py").chmod(0o700)
    for path in BASELINE_CONTROLS:
        content = (project / path).read_bytes()
        if hashlib.sha1(
            b"blob " + str(len(content)).encode("ascii") + b"\0" + content
        ).hexdigest() != approval["baseline_controls"][path]["blob"]:
            raise RuntimeError(f"baseline release control changed while preparing overlay: {path}")
        destination_path = scripts / Path(path).name
        destination_path.write_bytes(content)
        destination_path.chmod(0o700)
    for path in OVERLAY_CONTROLS:
        content = _read_tree_file(tool, approval["tool_commit"], path)
        if hashlib.sha256(content).hexdigest() != approval["reviewed_controls"][path]["sha256"]:
            raise RuntimeError(f"reviewed release control changed while preparing overlay: {path}")
        destination_path = scripts / Path(path).name
        destination_path.write_bytes(content)
        destination_path.chmod(0o700)
    return overlay / "scripts/deploy-backend-frontend-static.sh"


def _add_target_worktree(tool_root, destination, target_commit):
    subprocess.run(
        ["git", "-C", str(tool_root), "worktree", "add", "--quiet", "--detach", str(destination), target_commit],
        check=True,
    )


def _remove_target_worktree(tool_root, destination):
    subprocess.run(
        ["git", "-C", str(tool_root), "worktree", "remove", "--force", str(destination)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def run_check_only(
    *,
    project_root,
    tool_root,
    expected_before,
    target_commit,
    tool_commit,
    deployment_key,
    approved_bootstrap_sha256,
    node_runtime_dir,
):
    if not KEY_RE.fullmatch(deployment_key or ""):
        raise RuntimeError("invalid preflight-only key")
    approval = validate_bootstrap(
        project_root,
        tool_root,
        expected_before=expected_before,
        target_commit=target_commit,
        tool_commit=tool_commit,
        approved_bootstrap_sha256=approved_bootstrap_sha256,
    )
    runtime, node, npm, required_node, required_npm = _validate_runtime(
        node_runtime_dir, tool_root, target_commit
    )
    print(json.dumps({
        **approval,
        "deployment_key": deployment_key,
        "node_runtime": str(runtime),
        "node_version": required_node,
        "npm_version": required_npm,
        "operations": {
            "database_migration": False,
            "attachment_migration": False,
            "frontend_publish": False,
            "service_change": False,
        },
    }, ensure_ascii=False, indent=2), flush=True)

    temporary_parent = Path(tempfile.gettempdir()).resolve(strict=True)
    project = Path(project_root).resolve(strict=True)
    tool = Path(tool_root).resolve(strict=True)
    if any(
        _within(left, right) or _within(right, left)
        for left, right in ((temporary_parent, project), (temporary_parent, tool))
    ):
        raise RuntimeError("system temp directory must be outside production and release-tool worktrees")
    before_head = _git(project, "rev-parse", "HEAD").stdout.decode().strip()
    before_marker = (project / ".deployed_commit").read_bytes()
    target_worktree = None
    with tempfile.TemporaryDirectory(prefix=f"qr-static-check-{deployment_key}-", dir=temporary_parent) as temporary:
        root = Path(temporary)
        overlay = prepare_overlay(root / "overlay", project, tool, approval)
        target_worktree = root / "target-worktree"
        _add_target_worktree(tool, target_worktree, target_commit)
        try:
            command = [
                "bash", str(overlay),
                "--project-root", str(project),
                "--launcher-root", str(overlay.parent.parent),
                "--tool-root", str(target_worktree),
                "--expected-before", expected_before,
                "--target-commit", target_commit,
                "--deployment-key", deployment_key,
                "--check-only",
            ]
            environment = os.environ.copy()
            environment["PATH"] = str(runtime / "bin") + os.pathsep + environment.get("PATH", "")
            environment["NODE_BIN"] = str(node)
            environment["NPM_BIN"] = str(npm)
            result = subprocess.run(command, check=False, env=environment)
            if result.returncode:
                raise RuntimeError(f"real production backend/static --check-only failed with exit {result.returncode}")
        finally:
            _remove_target_worktree(tool, target_worktree)

    if _git(project, "rev-parse", "HEAD").stdout.decode().strip() != before_head:
        raise RuntimeError("production checkout changed during --check-only")
    if (project / ".deployed_commit").read_bytes() != before_marker:
        raise RuntimeError("production deployed marker changed during --check-only")
    subprocess.run(["systemctl", "--user", "is-active", "--quiet", "qr-system.service"], check=True)
    fence = project / "data/deployments/write-fence.json"
    if fence.exists() or fence.is_symlink():
        raise RuntimeError("production write-fence file appeared during --check-only")
    return approval


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--tool-root", required=True)
    parser.add_argument("--expected-before", required=True)
    parser.add_argument("--target-commit", required=True)
    parser.add_argument("--tool-commit", required=True)
    parser.add_argument("--deployment-key", required=True)
    parser.add_argument("--approved-bootstrap-sha256", required=True)
    parser.add_argument("--node-runtime-dir", required=True)
    parser.add_argument("--check-only", action="store_true", required=True)
    args = parser.parse_args(argv)
    run_check_only(
        project_root=args.project_root,
        tool_root=args.tool_root,
        expected_before=args.expected_before,
        target_commit=args.target_commit,
        tool_commit=args.tool_commit,
        deployment_key=args.deployment_key,
        approved_bootstrap_sha256=args.approved_bootstrap_sha256,
        node_runtime_dir=args.node_runtime_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
