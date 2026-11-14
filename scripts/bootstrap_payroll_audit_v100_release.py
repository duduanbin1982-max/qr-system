#!/usr/bin/env python3
"""Hash-verify and invoke the independently reviewed payroll V100 release tool."""

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path


SHA_RE = re.compile(r"^[0-9a-f]{40}$")
KEY_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
CONTROL_PATHS = (
    "scripts/payroll_audit_v100_release.py",
    "scripts/deploy-payroll-audit-v100.sh",
    "scripts/backend_frontend_static_release.py",
    "scripts/code_only_release.py",
    "scripts/deployment_manifest.py",
    "scripts/rollback-deployment.sh",
    "scripts/backup-db.sh",
)


def _git(root, *args, check=True):
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if check and result.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def _git_bytes(root, *args):
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        raise RuntimeError(
            f"git {' '.join(args)} failed: "
            + result.stderr.decode("utf-8", errors="replace").strip()
        )
    return result.stdout


def _assert_clean(root, *, allow_data=False):
    output = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout
    unexpected = []
    for entry in output.split("\0"):
        if not entry:
            continue
        path = entry[3:]
        if allow_data and entry[:2] == "??" and (path == "data" or path.startswith("data/")):
            continue
        unexpected.append(entry)
    if unexpected:
        raise RuntimeError("worktree is not clean: " + "; ".join(unexpected[:10]))


def _tree_bytes(root, commit, path):
    entry = _git(root, "ls-tree", commit, "--", path).stdout.strip()
    if not entry:
        raise RuntimeError(f"reviewed control is missing: {path}")
    mode, kind, _ = entry.split("\t", 1)[0].split()
    if kind != "blob" or mode not in {"100644", "100755"}:
        raise RuntimeError(f"reviewed control is not a regular file: {path}")
    return _git_bytes(root, "show", f"{commit}:{path}")


def validate(args):
    for value in (args.expected_before, args.target_commit, args.tool_commit):
        if not SHA_RE.fullmatch(value or ""):
            raise RuntimeError("all commit identities must be full lowercase SHA values")
    if not KEY_RE.fullmatch(args.deployment_key or ""):
        raise RuntimeError("invalid deployment key")
    bootstrap_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if bootstrap_sha256 != args.approved_bootstrap_sha256:
        raise RuntimeError("bootstrap SHA256 does not match the reviewed file")

    project = Path(args.project_root).resolve(strict=True)
    tool = Path(args.tool_root).resolve(strict=True)
    if project == tool or project in tool.parents or tool in project.parents:
        raise RuntimeError("production and release-tool roots must be separate")
    if _git(project, "rev-parse", "HEAD").stdout.strip() != args.expected_before:
        raise RuntimeError("production checkout differs from the confirmed baseline")
    marker = project / ".deployed_commit"
    if marker.is_symlink() or not marker.is_file() or marker.read_text(encoding="ascii").strip() != args.expected_before:
        raise RuntimeError("production marker differs from the confirmed baseline")
    _assert_clean(project, allow_data=True)
    if _git(tool, "rev-parse", "HEAD").stdout.strip() != args.tool_commit:
        raise RuntimeError("release-tool checkout differs from the reviewed merge SHA")
    _assert_clean(tool)
    _git(tool, "cat-file", "-e", f"{args.target_commit}^{{commit}}")
    if _git(tool, "merge-base", "--is-ancestor", args.target_commit, args.tool_commit, check=False).returncode:
        raise RuntimeError("reviewed tool commit does not contain the business target")

    controls = {}
    for path in CONTROL_PATHS:
        reviewed = _tree_bytes(tool, args.tool_commit, path)
        installed = (tool / path).read_bytes()
        if installed != reviewed:
            raise RuntimeError(f"installed release control differs from reviewed bytes: {path}")
        controls[path] = hashlib.sha256(reviewed).hexdigest()

    runtime = Path(args.node_runtime_dir).resolve(strict=True)
    node = runtime / "bin/node"
    npm = runtime / "bin/npm"
    package = json.loads(_git(tool, "show", f"{args.target_commit}:package.json").stdout)
    required = package["engines"]
    environment = {**os.environ, "PATH": str(runtime / "bin") + os.pathsep + os.environ.get("PATH", "")}
    actual_node = subprocess.check_output([str(node), "--version"], text=True, env=environment).strip().removeprefix("v")
    actual_npm = subprocess.check_output([str(npm), "--version"], text=True, env=environment).strip()
    if (actual_node, actual_npm) != (required["node"], required["npm"]):
        raise RuntimeError("pinned Node/npm runtime does not match the business target")
    return project, tool, node, npm, environment, {
        "bootstrap_sha256": bootstrap_sha256,
        "tool_commit": args.tool_commit,
        "target_commit": args.target_commit,
        "expected_before": args.expected_before,
        "deployment_key": args.deployment_key,
        "controls": controls,
        "node": actual_node,
        "npm": actual_npm,
        "mode": args.mode,
    }


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
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check-only", dest="mode", action="store_const", const="--check-only")
    modes.add_argument("--execute", dest="mode", action="store_const", const="--execute")
    args = parser.parse_args(argv)
    project, tool, node, npm, environment, approval = validate(args)
    print(json.dumps(approval, ensure_ascii=False, indent=2), flush=True)
    command = [
        "bash", str(tool / "scripts/deploy-payroll-audit-v100.sh"),
        "--project-root", str(project),
        "--tool-root", str(tool),
        "--launcher-root", str(tool),
        "--expected-before", args.expected_before,
        "--target-commit", args.target_commit,
        "--deployment-key", args.deployment_key,
        args.mode,
    ]
    environment["NODE_BIN"] = str(node)
    environment["NPM_BIN"] = str(npm)
    return subprocess.run(command, env=environment, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
