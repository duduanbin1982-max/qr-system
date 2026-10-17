#!/usr/bin/env python3
"""One-time, independently approved upgrade of the current release validator.

Run an externally verified copy, never the target's validator. Only the exact
Task 5 validator transition is permitted; the current launcher, fence, backup
and rollback controls remain the authority throughout the release.
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


BEFORE = "787319edbdfa6ce2c17c23eeeb5e2fdeaa68598d"
APPROVED_TARGET_COMMIT = "8f928c2e6040346b986dac97d10fd50eb659140e"
POLICY_PATH = "scripts/code_only_release.py"
BOOTSTRAP_PATH = "scripts/bootstrap_release_gate.py"
CONTROL_ENTRIES = {
    POLICY_PATH: ("100644", "2451adc20d00fc4841638961111f8815b1eabadd"),
    "scripts/deploy-code-only.sh": ("100644", "f916286b10611284f279ce1a722b0c2874d10258"),
    "scripts/deployment_manifest.py": ("100644", "4ab0cf4e0b834426e22e10f24f11611313f0f494"),
    "scripts/backup-db.sh": ("100755", "0a8af7990690f6153731a3d67123ffa230df9aa6"),
    "scripts/rollback-deployment.sh": ("100644", "aa8591c6c3a97424c07e74fd45e8d5f1b4abed99"),
}
APPROVED_POLICY_BLOB = "f619adedac535e03735f98f40adaa049b6eb9c1b"
APPROVED_TARGET_ENTRIES = {
    POLICY_PATH: ("100644", "blob", APPROVED_POLICY_BLOB),
    "tests/test_code_only_deployment.py": (
        "100644",
        "blob",
        "bf64ed5ec08b5a77a9ce81c678562016c2875630",
    ),
}
ALLOWED_CHANGES = frozenset(APPROVED_TARGET_ENTRIES)


def _git(root, *arguments):
    result = subprocess.run(
        ["git", "-C", str(root), *arguments], capture_output=True, check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout


def _entry(root, commit, path):
    result = _git(root, "ls-tree", commit, "--", path)
    if not result or b"\n" in result.rstrip(b"\n"):
        raise RuntimeError(f"missing or ambiguous Git entry: {path}")
    metadata, name = result.rstrip(b"\n").split(b"\t", 1)
    if name.decode("utf-8") != path:
        raise RuntimeError(f"Git entry path mismatch: {path}")
    return metadata.decode("ascii").split()


def _regular_file(root, path):
    candidate = root / path
    if not candidate.is_file() or any(part.is_symlink() for part in (candidate, *candidate.parents)):
        raise RuntimeError(f"unsafe file: {candidate}")
    return candidate.read_bytes()


def _blob(content):
    return hashlib.sha1(b"blob " + str(len(content)).encode("ascii") + b"\0" + content).hexdigest()


def validate_transition(project_root, tool_root, target_commit):
    """Validate the approved upgrade without importing any target Python code."""
    project_root = Path(project_root).resolve(strict=True)
    tool_root = Path(tool_root).resolve(strict=True)
    if project_root == tool_root:
        raise RuntimeError("target worktree must be separate from production")
    if not re.fullmatch(r"[0-9a-f]{40}", target_commit) or target_commit == BEFORE:
        raise RuntimeError("target must be a new full lowercase commit SHA")
    if _git(project_root, "rev-parse", "HEAD").decode().strip() != BEFORE:
        raise RuntimeError("production HEAD changed from the approved bootstrap baseline")
    if _regular_file(project_root, ".deployed_commit").decode("ascii").strip() != BEFORE:
        raise RuntimeError("production deployed marker changed")
    if _git(tool_root, "rev-parse", "HEAD").decode().strip() != target_commit:
        raise RuntimeError("target worktree HEAD mismatch")
    _git(tool_root, "merge-base", "--is-ancestor", BEFORE, target_commit)
    changed = sorted(filter(None, _git(
        tool_root, "diff", "--no-renames", "--name-only", "-z", BEFORE, target_commit, "--",
    ).decode("utf-8").split("\0")))
    if changed != sorted(ALLOWED_CHANGES):
        raise RuntimeError(f"bootstrap changed paths mismatch: {changed}")
    for path in changed:
        if _entry(tool_root, target_commit, path) != list(APPROVED_TARGET_ENTRIES[path]):
            raise RuntimeError(f"bootstrap requires regular, retained text files: {path}")
    if target_commit != APPROVED_TARGET_COMMIT:
        raise RuntimeError("target commit is not the independently approved Task 5 release")
    controls = {}
    for path, (mode, before_oid) in CONTROL_ENTRIES.items():
        before_entry = [mode, "blob", before_oid]
        target_entry = [mode, "blob", APPROVED_POLICY_BLOB if path == POLICY_PATH else before_oid]
        if _entry(tool_root, BEFORE, path) != before_entry or _entry(tool_root, target_commit, path) != target_entry:
            raise RuntimeError(f"unapproved release control content or mode: {path}")
        if _blob(_regular_file(project_root, path)) != before_oid:
            raise RuntimeError(f"production release control modified: {path}")
        controls[path] = [before_entry, target_entry]
    return {
        "before_commit": BEFORE,
        "target_commit": target_commit,
        "project_root": str(project_root),
        "tool_root": str(tool_root),
        "changed_paths": changed,
        "target_entries": {
            path: list(entry) for path, entry in APPROVED_TARGET_ENTRIES.items()
        },
        "controls": controls,
        "bootstrap_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }


# Executed by the CURRENT production validator, both before tests and immediately
# before acquiring the fence. It rechecks the complete, exact approval each time.
OVERLAY_GUARD = r'''
def _assert_bootstrap_approval(tool_root, project_root, before_commit, target_commit):
    import hashlib
    approval = BOOTSTRAP_APPROVAL
    if (str(project_root), str(tool_root), before_commit, target_commit) != (
        approval["project_root"], approval["tool_root"],
        approval["before_commit"], approval["target_commit"],
    ):
        raise RuntimeError("bootstrap approval commit or root mismatch")
    if _changed_paths(tool_root, before_commit, target_commit) != approval["changed_paths"]:
        raise RuntimeError("bootstrap approval changed paths mismatch")
    if target_commit != approval["target_commit"]:
        raise RuntimeError("bootstrap approval commit or root mismatch")
    for path, expected in approval["target_entries"].items():
        actual = _git(tool_root, "ls-tree", target_commit, "--", path).stdout
        metadata, name = actual.rstrip(b"\n").split(b"\t", 1)
        if metadata.decode("ascii").split() != expected or name.decode("utf-8") != path:
            raise RuntimeError("bootstrap target entry mismatch: " + path)
    for path, entries in approval["controls"].items():
        for commit, expected in zip((before_commit, target_commit), entries):
            actual = _git(tool_root, "ls-tree", commit, "--", path).stdout
            if actual.split(b"\t", 1)[0].decode("ascii").split() != expected:
                raise RuntimeError("bootstrap release control Git entry mismatch: " + path)
        candidate = project_root / path
        if not candidate.is_file() or any(part.is_symlink() for part in (candidate, *candidate.parents)):
            raise RuntimeError("unsafe bootstrap release control: " + path)
        content = candidate.read_bytes()
        oid = hashlib.sha1(b"blob " + str(len(content)).encode("ascii") + b"\0" + content).hexdigest()
        if oid != entries[0][2]:
            raise RuntimeError("bootstrap production release control modified: " + path)

'''


def _replace_once(source, old, new):
    if source.count(old) != 1:
        raise RuntimeError("trusted source patch point drifted: " + old[:70])
    return source.replace(old, new)


def prepare_overlay(overlay_root, approval):
    """Copy current controls, changing only a pinned validator exception and origin."""
    production = Path(approval["project_root"])
    scripts = Path(overlay_root) / "scripts"
    scripts.mkdir(mode=0o700)
    for path in CONTROL_ENTRIES:
        content = _git(production, "show", f"{BEFORE}:{path}")
        (scripts / Path(path).name).write_bytes(content)
    policy = scripts / "code_only_release.py"
    source = policy.read_text(encoding="utf-8")
    source = _replace_once(source, "def validate_code_only_release(",
        "BOOTSTRAP_APPROVAL = " + repr(approval) + "\n" + OVERLAY_GUARD + "def validate_code_only_release(")
    source = _replace_once(source,
        "    _assert_release_controls_unchanged(tool_root, before_commit, target_commit)\n",
        "    _assert_bootstrap_approval(tool_root, project_root, before_commit, target_commit)\n")
    source = _replace_once(source,
        "        if _path_is_forbidden(path) and path not in documentation_only\n",
        "        if path != " + repr(POLICY_PATH) + " and _path_is_forbidden(path) and path not in documentation_only\n")
    policy.write_text(source, encoding="utf-8", newline="\n")
    launcher = scripts / "deploy-code-only.sh"
    source = launcher.read_text(encoding="utf-8")
    source = _replace_once(source,
        'if [[ "$SCRIPT_ROOT" != "$PROJECT_ROOT" ]]; then',
        'if [[ "$SCRIPT_ROOT" != ' + shlex.quote(str(Path(overlay_root).resolve()))
        + ' || "$PROJECT_ROOT" != ' + shlex.quote(str(production)) + ' ]]; then')
    source = _replace_once(source,
        'install -m 0700 "$PROJECT_ROOT/scripts/$control" "$TRUST_ROOT/scripts/$control"',
        'install -m 0700 "$SCRIPT_ROOT/scripts/$control" "$TRUST_ROOT/scripts/$control"')
    launcher.write_text(source, encoding="utf-8", newline="\n")
    return launcher


def prepare_test_runner(temporary, approval):
    """Install locked test dependencies outside production and the target tree."""
    dependencies = Path(temporary) / "test-dependencies"
    dependencies.mkdir(mode=0o700)
    for name in ("package.json", "package-lock.json"):
        before = _git(approval["tool_root"], "show", f"{BEFORE}:{name}")
        if _git(approval["tool_root"], "show", f'{approval["target_commit"]}:{name}') != before:
            raise RuntimeError("bootstrap cannot change test dependency manifests")
        (dependencies / name).write_bytes(before)
    subprocess.run([
        "npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund", "--prefer-offline",
    ], cwd=dependencies, check=True)
    pytest = shutil.which(os.environ.get("PYTEST_BIN", str(Path.home() / ".local/bin/pytest")))
    if not pytest:
        raise RuntimeError("pytest executable is unavailable")
    runner = Path(temporary) / "run-backend-tests.py"
    runner.write_text(
        f"#!{sys.executable}\nimport os, subprocess, sys\nfrom pathlib import Path\n"
        f"production = Path({approval['project_root']!r})\n"
        f"tool = Path({approval['tool_root']!r})\n"
        f"target = {approval['target_commit']!r}\n"
        "root = Path.cwd().resolve()\n"
        "if root in (production, tool):\n    raise SystemExit('test checkout must be temporary')\n"
        "head = subprocess.check_output(['git', 'rev-parse', 'HEAD']).decode().strip()\n"
        "if head != target:\n    raise SystemExit('temporary test checkout HEAD mismatch')\n"
        f"(root / 'node_modules').symlink_to({str(dependencies / 'node_modules')!r}, target_is_directory=True)\n"
        f"os.execv({pytest!r}, [{pytest!r}, *sys.argv[1:]])\n",
        encoding="utf-8", newline="\n",
    )
    runner.chmod(0o700)
    return runner


def write_receipt(path, approval, args):
    """Reserve the bootstrap key exclusively and durably before invoking release."""
    if args.operator_user_id == args.approver_user_id:
        raise RuntimeError("operator and independent approver must differ")
    for candidate in (path, *path.parents):
        if candidate.is_symlink():
            raise RuntimeError("bootstrap evidence path cannot be a symlink")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = {
        **approval, "deployment_key": args.deployment_key,
        "operator_user_id": args.operator_user_id, "approver_user_id": args.approver_user_id,
        "scope": "release_gate_bootstrap_code_only", "migrations": False,
    }
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
        json.dump(payload, output, ensure_ascii=False, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    # This entry point executes on the Linux production host.
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--tool-root", required=True)
    parser.add_argument("--target-commit", required=True)
    parser.add_argument("--deployment-key", required=True)
    parser.add_argument("--approved-bootstrap-sha256", required=True)
    parser.add_argument("--operator-user-id", required=True, type=int)
    parser.add_argument("--approver-user-id", required=True, type=int)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check-only", action="store_true")
    mode.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", args.deployment_key):
        raise RuntimeError("invalid deployment key")
    approval = validate_transition(args.project_root, args.tool_root, args.target_commit)
    if approval["bootstrap_sha256"] != args.approved_bootstrap_sha256:
        raise RuntimeError("bootstrap SHA256 does not match independent approval")
    if args.operator_user_id <= 0 or args.approver_user_id <= 0 or args.operator_user_id == args.approver_user_id:
        raise RuntimeError("distinct operator and independent approver IDs are required")
    print(json.dumps(approval, ensure_ascii=False, indent=2), flush=True)
    with tempfile.TemporaryDirectory(prefix="qr-release-gate-bootstrap-") as temporary:
        Path(temporary).chmod(0o700)
        launcher = prepare_overlay(temporary, approval)
        subprocess.run(["bash", "-n", str(launcher)], check=True)
        test_runner = prepare_test_runner(temporary, approval)
        if args.execute:
            receipt = Path(approval["project_root"]) / "data/deployments" / (args.deployment_key + ".bootstrap.json")
            write_receipt(receipt, approval, args)
        return subprocess.call([
            "bash", str(launcher), "--project-root", approval["project_root"],
            "--tool-root", approval["tool_root"], "--expected-before", BEFORE,
            "--target-commit", args.target_commit, "--deployment-key", args.deployment_key,
            "--execute" if args.execute else "--check-only",
        ], env={**os.environ, "PYTEST_BIN": str(test_runner)})


if __name__ == "__main__":
    raise SystemExit(main())
