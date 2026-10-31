#!/usr/bin/env python3
"""Install the four reviewed PR #132 release controls without publishing assets.

The production checkout remains on the approved baseline while a separate tool
checkout contains the reviewed Task 132 merge (and this bootstrap helper).  The
business target is fixed to ``TARGET_COMMIT``; a later tool-root commit is
allowed so the helper itself does not create a self-referential target.
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


BEFORE_COMMIT = "b9e7787f4269048bd179f3e57d745fa6ae002afa"
TARGET_COMMIT = "df7a6e398ab82eef02160d1efd143e1676d3db08"

POLICY_PATH = "scripts/code_only_release.py"
BACKUP_PATH = "scripts/backup-db.sh"
DEPLOY_CODE_ONLY_PATH = "scripts/deploy-code-only.sh"
STATIC_RELEASE_PATH = "scripts/backend_frontend_static_release.py"
STATIC_LAUNCHER_PATH = "scripts/deploy-backend-frontend-static.sh"
MANIFEST_PATH = "scripts/deployment_manifest.py"
ROLLBACK_PATH = "scripts/rollback-deployment.sh"

# Keep the old production state machine trusted until the atomic code switch.
BASELINE_CONTROLS = {
    POLICY_PATH: ("100644", "7fa3364f958b588246b865ab2cbf0da12d2c3a4a"),
    BACKUP_PATH: ("100755", "0a8af7990690f6153731a3d67123ffa230df9aa6"),
    DEPLOY_CODE_ONLY_PATH: ("100644", "98868bc7b612e59bae7b923085a1b8567a60a739"),
    MANIFEST_PATH: ("100644", "4ab0cf4e0b834426e22e10f24f11611313f0f494"),
    ROLLBACK_PATH: ("100644", "aa8591c6c3a97424c07e74fd45e8d5f1b4abed99"),
}
PRODUCTION_OVERLAY_CONTROLS = BASELINE_CONTROLS

# Exactly four reviewed control blobs may change at the atomic code switch.
RUNTIME_CONTROLS = {
    STATIC_RELEASE_PATH: ("100644", "8303fb9cd6fee5bb658fe57f92a1e0df6f203599"),
    STATIC_LAUNCHER_PATH: ("100644", "5c6817665ed341fd855343ed5e1856bd1407bc32"),
    MANIFEST_PATH: ("100644", "1141f927614232cdbaad881cd0d5d6655e4b9531"),
    ROLLBACK_PATH: ("100644", "559193c74c4cf88210eea1ef06ea5cd077b8942e"),
}

# Every business-tree change in the reviewed merge is pinned.  Support files
# are evidence only: they are never copied into the trusted overlay.
_ALL_TARGET_ENTRIES = {
    ".github/workflows/full-test.yml": ("100644", "ce4295305eaaa95ae2fff9d1d8c0a73d634483e6"),
    "docs/deployment-backend-frontend-static.md": ("100644", "0b1236898f16b4bf975766cf6d0ee6faad00f4df"),
    "frontend/tests/e2e/admin-pages.spec.js": ("100644", "888ee644a26c129d87d5d90ffe29ed50f733a2c4"),
    "frontend/tests/e2e/helpers.js": ("100644", "234c7ab405955c81c0679e34a3080788c08f3c9d"),
    "frontend/tests/e2e/wage-price-versions.spec.js": ("100644", "33ab16a88b4ac0d97ccd116b6a152ca2bf12ebee"),
    "frontend/tests/unit/GanttChartProductionNodes.spec.js": ("100644", "cdd6c1358b31b739c8dad6b2a175cbd2df308567"),
    "frontend/tests/unit/MasterDataRelease.spec.js": ("100644", "b8778e107f08ea2bd9fbce97085d7f50cde5cdd1"),
    "frontend/tests/unit/useOrderQuery.spec.js": ("100644", "5959a9a9f19ba0bd9e27faf6499d492007b38029"),
    "package.json": ("100644", "fada80315b6f8999eaa6308b6ff55b9348b31326"),
    STATIC_RELEASE_PATH: RUNTIME_CONTROLS[STATIC_RELEASE_PATH],
    "scripts/bootstrap_backend_frontend_static_check.py": ("100644", "b30f56cd57fb2c17eae09c2787f91a2351e35675"),
    "scripts/bootstrap_release_tool.py": ("100644", "97db0db34ad4d927600edcc32f10ca856aafecec"),
    "scripts/bootstrap_task7_release_check.py": ("100644", "087d24216bca13513784bdf9b20e17b99699450a"),
    "scripts/bootstrap_task8_release_control.py": ("100644", "9b8cac0670b8061f080f4a6e612f1a940e644f64"),
    STATIC_LAUNCHER_PATH: RUNTIME_CONTROLS[STATIC_LAUNCHER_PATH],
    MANIFEST_PATH: RUNTIME_CONTROLS[MANIFEST_PATH],
    ROLLBACK_PATH: RUNTIME_CONTROLS[ROLLBACK_PATH],
    "scripts/test-full.mjs": ("100644", "1c429a00b17973e06b6f7659466dee954eb684c4"),
    "tests/conftest.py": ("100644", "9cff1a0eadd9f9680d1f82840cc963c927f2e90c"),
    "tests/test_architecture_imports.py": ("100644", "5e3b01a0fa7495b3e43ae69526220b39bcc39554"),
    "tests/test_backend_frontend_static_bootstrap.py": ("100644", "c919f25ea7c70790b0b6627eb052d3ddbed4491e"),
    "tests/test_backend_frontend_static_release.py": ("100644", "5de81ef833fa3ba08c864a3d842936ab54bbab40"),
    "tests/test_bootstrap_bash_resolution.py": ("100644", "886313f97eeb04d45927b2c768eb492b5178b08a"),
    "tests/test_operations_script_boundary.py": ("100644", "1d2ab27f51ad7c8a6be7e0ab510eea1a21c2c938"),
    "tests/test_release_tool_bootstrap.py": ("100644", "52085d02dc44c5b92d0ce5cd94904dc28f0fb1a6"),
    "tests/test_task7_release_check_bootstrap.py": ("100644", "a324ecbcb77f0d58101ccfcdd6a90dd75e5c59da"),
    "tests/test_task8_release_control_bootstrap.py": ("100644", "2908c6b9c3771e0940949ea4cc58176846e225e0"),
}

# The public target map is deliberately limited to the four trusted runtime
# controls.  The remaining exact business-tree entries are evidence-only
# support changes and are never loaded into the overlay.
TARGET_ENTRIES = {path: _ALL_TARGET_ENTRIES[path] for path in RUNTIME_CONTROLS}
SUPPORT_ENTRIES = {
    path: entry for path, entry in _ALL_TARGET_ENTRIES.items()
    if path not in RUNTIME_CONTROLS
}

CONTROL_ENTRIES = BASELINE_CONTROLS

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
KEY_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _bash_executable():
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
        if executable.is_file() and not excluded.intersection(part.casefold() for part in executable.parts):
            return str(executable.resolve())
    raise RuntimeError("Git Bash is required on Windows; WSL launchers are unsupported")


def _git(root, *args, check=True):
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return result


def _entry(root, commit, path):
    result = _git(root, "ls-tree", "-z", commit, "--", path)
    entries = [value for value in result.stdout.split(b"\0") if value]
    if len(entries) != 1:
        raise RuntimeError(f"missing or ambiguous Git entry: {path}")
    metadata, raw_path = entries[0].split(b"\t", 1)
    if raw_path.decode("utf-8", errors="surrogateescape") != path:
        raise RuntimeError(f"Git entry path mismatch: {path}")
    mode, kind, blob = metadata.decode("ascii").split()
    if kind != "blob" or mode not in {"100644", "100755"}:
        raise RuntimeError(f"release control must be a regular Git file: {path}")
    return mode, kind, blob


def _blob(content):
    return hashlib.sha1(b"blob " + str(len(content)).encode("ascii") + b"\0" + content).hexdigest()


def _regular_file(root, path):
    candidate = Path(root) / path
    if not candidate.is_file() or any(part.is_symlink() for part in (candidate, *candidate.parents)):
        raise RuntimeError(f"unsafe file: {candidate}")
    return candidate.read_bytes()


def _changed_paths(repository, before_commit, target_commit):
    result = _git(repository, "diff", "--no-renames", "--name-only", "-z", before_commit, target_commit, "--")
    return sorted(os.fsdecode(value) for value in result.stdout.split(b"\0") if value)


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


def _safe_root(value):
    path = Path(value).absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise RuntimeError("worktree roots and their ancestors cannot be symlinks")
    root = path.resolve(strict=True)
    toplevel = Path(_git(root, "rev-parse", "--show-toplevel").stdout.decode().strip()).resolve(strict=True)
    if root != toplevel:
        raise RuntimeError("expected an exact Git worktree root")
    return root


def _temporary_parent(project, tool):
    parent = Path(tempfile.gettempdir()).resolve(strict=True)
    if _within(parent, project) or _within(parent, tool):
        raise RuntimeError("temporary directory must remain outside production and tool worktrees")
    return parent


def validate_transition(project_root, tool_root, target_commit=TARGET_COMMIT, tool_commit=None):
    project, tool = _safe_root(project_root), _safe_root(tool_root)
    if project == tool or _within(project, tool) or _within(tool, project):
        raise RuntimeError("production and release-tool worktrees must be separate and non-nested")
    if target_commit != TARGET_COMMIT or not SHA_RE.fullmatch(target_commit or ""):
        raise RuntimeError("target commit is not the approved Task 132 merge")
    production_head = _git(project, "rev-parse", "--verify", "HEAD").stdout.decode().strip()
    if production_head != BEFORE_COMMIT:
        raise RuntimeError("production HEAD changed from the approved baseline")
    marker = project / ".deployed_commit"
    if marker.is_symlink() or not marker.is_file() or marker.read_text(encoding="ascii").strip() != BEFORE_COMMIT:
        raise RuntimeError("production deployed marker changed")
    _assert_clean(project, "production", allow_untracked_data=True)
    for path in (project / "data", project / "data/deployments"):
        if path.is_symlink():
            raise RuntimeError("production evidence directories cannot be symlinks")
    fence = project / "data/deployments/write-fence.json"
    if fence.exists() or fence.is_symlink():
        raise RuntimeError("production write-fence file is present")

    head = _git(tool, "rev-parse", "--verify", "HEAD").stdout.decode().strip()
    if tool_commit is not None and (
        not SHA_RE.fullmatch(tool_commit) or tool_commit == TARGET_COMMIT
    ):
        raise RuntimeError("release-tool HEAD must be an independently reviewed commit after the Task 132 target")
    if tool_commit is not None and head != tool_commit:
        raise RuntimeError("release-tool worktree HEAD does not match the reviewed tool commit")
    if not SHA_RE.fullmatch(head):
        raise RuntimeError("release-tool HEAD is not a full commit SHA")
    _assert_clean(tool, "release-tool")
    if _git(tool, "cat-file", "-e", f"{TARGET_COMMIT}^{{commit}}", check=False).returncode:
        raise RuntimeError("release-tool does not contain the approved Task 132 target")
    if _git(tool, "merge-base", "--is-ancestor", BEFORE_COMMIT, TARGET_COMMIT, check=False).returncode:
        raise RuntimeError("Task 132 target is not based on the approved production baseline")
    if _git(tool, "merge-base", "--is-ancestor", TARGET_COMMIT, head, check=False).returncode:
        raise RuntimeError("release-tool HEAD does not contain the approved Task 132 target")

    changed = _changed_paths(tool, BEFORE_COMMIT, TARGET_COMMIT)
    expected_changed = sorted((*TARGET_ENTRIES, *SUPPORT_ENTRIES))
    if changed != expected_changed:
        raise RuntimeError(f"Task 132 changed paths mismatch: {changed}")
    for path, (mode, blob) in _ALL_TARGET_ENTRIES.items():
        if _entry(tool, TARGET_COMMIT, path) != (mode, "blob", blob):
            raise RuntimeError(f"Task 132 target entry mismatch: {path}")

    for path, (mode, blob) in BASELINE_CONTROLS.items():
        expected = (mode, "blob", blob)
        target_blob = TARGET_ENTRIES.get(path, (mode, blob))[1]
        if _entry(project, BEFORE_COMMIT, path) != expected or _entry(tool, TARGET_COMMIT, path) != (mode, "blob", target_blob):
            raise RuntimeError(f"baseline release control transition mismatch: {path}")
        if _blob(_regular_file(project, path)) != blob:
            raise RuntimeError(f"production release control bytes changed: {path}")
    for path, (mode, blob) in RUNTIME_CONTROLS.items():
        expected = (mode, "blob", blob)
        if _entry(tool, TARGET_COMMIT, path) != expected or _entry(tool, head, path) != expected:
            raise RuntimeError(f"reviewed runtime control mismatch: {path}")

    return {
        "before_commit": BEFORE_COMMIT,
        "target_commit": TARGET_COMMIT,
        "tool_commit": head,
        "changed_paths": changed,
        "target_entries": {path: {"mode": mode, "blob": blob} for path, (mode, blob) in TARGET_ENTRIES.items()},
        "support_entries": {path: {"mode": mode, "blob": blob} for path, (mode, blob) in SUPPORT_ENTRIES.items()},
        "ignored_changed_paths": sorted(SUPPORT_ENTRIES),
        "baseline_controls": {path: {"mode": mode, "blob": blob} for path, (mode, blob) in BASELINE_CONTROLS.items()},
        "runtime_controls": {path: {"mode": mode, "blob": blob} for path, (mode, blob) in RUNTIME_CONTROLS.items()},
        "bootstrap_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "mode": "check_only",
    }


def _replace_once(source, old, new):
    if source.count(old) != 1:
        raise RuntimeError(f"trusted launcher patch point drifted: {old[:90]}")
    return source.replace(old, new)


TASK132_POLICY_PATCH = r'''
import hashlib
TASK132_EXPECTED_TARGET_ENTRIES = {}
TASK132_EXPECTED_BEFORE = "b9e7787f4269048bd179f3e57d745fa6ae002afa"
TASK132_EXPECTED_TARGET = "df7a6e398ab82eef02160d1efd143e1676d3db08"
TASK132_APPROVED_CONTROL_TRANSITIONS = {
    "scripts/deployment_manifest.py": ("4ab0cf4e0b834426e22e10f24f11611313f0f494", "1141f927614232cdbaad881cd0d5d6655e4b9531"),
    "scripts/rollback-deployment.sh": ("aa8591c6c3a97424c07e74fd45e8d5f1b4abed99", "559193c74c4cf88210eea1ef06ea5cd077b8942e"),
    "scripts/backend_frontend_static_release.py": (None, "8303fb9cd6fee5bb658fe57f92a1e0df6f203599"),
    "scripts/deploy-backend-frontend-static.sh": (None, "5c6817665ed341fd855343ed5e1856bd1407bc32"),
}

def _assert_task132_control_blobs(repository, before_commit, target_commit):
    for path, (before_blob, target_blob) in TASK132_APPROVED_CONTROL_TRANSITIONS.items():
        before = _git(repository, "rev-parse", f"{before_commit}:{path}", check=False)
        target = _git(repository, "rev-parse", f"{target_commit}:{path}", check=False)
        actual_before = before.stdout.decode("ascii", errors="replace").strip()
        actual_target = target.stdout.decode("ascii", errors="replace").strip()
        if (before_blob is None and before.returncode == 0) or (before_blob is not None and actual_before != before_blob):
            raise RuntimeError("Task 132 release-control baseline blob mismatch: " + path)
        if target.returncode or actual_target != target_blob:
            raise RuntimeError("Task 132 release-control target blob mismatch: " + path)

def _assert_task132_bootstrap_state(repository, project_root, before_commit, target_commit):
    if before_commit != TASK132_EXPECTED_BEFORE or target_commit != TASK132_EXPECTED_TARGET:
        raise RuntimeError("Task 132 bootstrap commit mismatch")
    changed = _changed_paths(repository, before_commit, target_commit)
    if changed != sorted(TASK132_EXPECTED_TARGET_ENTRIES):
        raise RuntimeError("Task 132 bootstrap changed paths mismatch")
    for path, (mode, blob) in TASK132_EXPECTED_TARGET_ENTRIES.items():
        entry = _git(repository, "ls-tree", "-z", target_commit, "--", path).stdout
        records = [item for item in entry.split(b"\0") if item]
        if len(records) != 1:
            raise RuntimeError("Task 132 target entry mismatch: " + path)
        metadata, name = records[0].split(b"\t", 1)
        if name.decode("utf-8") != path or tuple(metadata.decode("ascii").split()) != (mode, "blob", blob):
            raise RuntimeError("Task 132 target entry mismatch: " + path)
    if _git(project_root, "rev-parse", "--verify", "HEAD").stdout.decode().strip() != before_commit:
        raise RuntimeError("production HEAD changed from the approved baseline")
    marker = project_root / ".deployed_commit"
    if marker.is_symlink() or not marker.is_file() or marker.read_text(encoding="ascii").strip() != before_commit:
        raise RuntimeError("production deployed marker changed")
    for path, (mode, blob) in {
        "scripts/code_only_release.py": ("100644", "7fa3364f958b588246b865ab2cbf0da12d2c3a4a"),
        "scripts/deploy-code-only.sh": ("100644", "98868bc7b612e59bae7b923085a1b8567a60a739"),
        "scripts/deployment_manifest.py": ("100644", "4ab0cf4e0b834426e22e10f24f11611313f0f494"),
        "scripts/rollback-deployment.sh": ("100644", "aa8591c6c3a97424c07e74fd45e8d5f1b4abed99"),
        "scripts/backup-db.sh": ("100755", "0a8af7990690f6153731a3d67123ffa230df9aa6"),
    }.items():
        candidate = project_root / path
        if not candidate.is_file() or any(part.is_symlink() for part in (candidate, *candidate.parents)):
            raise RuntimeError("unsafe production release control: " + path)
        content = candidate.read_bytes()
        oid = hashlib.sha1(b"blob " + str(len(content)).encode("ascii") + b"\0" + content).hexdigest()
        if oid != blob:
            raise RuntimeError("production release control bytes changed: " + path)

'''


def prepare_overlay(destination, approval, project_root, tool_root):
    reviewed_tool = approval.get("tool_commit")
    # Before this bootstrap is merged, the clean tool tree is exactly TARGET.
    # After merge, the caller supplies the independent post-target tool SHA.
    if reviewed_tool == TARGET_COMMIT:
        reviewed_tool = None
    current = validate_transition(
        project_root, tool_root, approval["target_commit"], reviewed_tool
    )
    if current != approval:
        raise RuntimeError("bootstrap approval drifted before overlay preparation")
    overlay = Path(destination).resolve()
    project, tool = Path(project_root).resolve(strict=True), Path(tool_root).resolve(strict=True)
    if any(_within(left, right) or _within(right, left) for left, right in ((overlay, project), (overlay, tool))):
        raise RuntimeError("temporary overlay must be outside production and release-tool worktrees")
    overlay.mkdir(mode=0o700, parents=True, exist_ok=False)
    scripts = overlay / "scripts"
    scripts.mkdir(mode=0o700)
    (scripts / "__init__.py").write_bytes(b"")
    (scripts / "__init__.py").chmod(0o700)
    for path, metadata in PRODUCTION_OVERLAY_CONTROLS.items():
        content = _regular_file(project, path)
        if _blob(content) != metadata[1]:
            raise RuntimeError(f"baseline release control drifted during overlay preparation: {path}")
        destination_path = scripts / Path(path).name
        destination_path.write_bytes(content)
        destination_path.chmod(0o700)
    policy = scripts / Path(POLICY_PATH).name
    source = policy.read_text(encoding="utf-8")
    source = _replace_once(
        source,
        '        "98868bc7b612e59bae7b923085a1b8567a60a739",\n'
        '    ),\n}\n',
        '        "98868bc7b612e59bae7b923085a1b8567a60a739",\n'
        '    ),\n'
        '    "scripts/deployment_manifest.py": ("4ab0cf4e0b834426e22e10f24f11611313f0f494", "1141f927614232cdbaad881cd0d5d6655e4b9531"),\n'
        '    "scripts/rollback-deployment.sh": ("aa8591c6c3a97424c07e74fd45e8d5f1b4abed99", "559193c74c4cf88210eea1ef06ea5cd077b8942e"),\n'
        '    "scripts/backend_frontend_static_release.py": ("", "8303fb9cd6fee5bb658fe57f92a1e0df6f203599"),\n'
        '    "scripts/deploy-backend-frontend-static.sh": ("", "5c6817665ed341fd855343ed5e1856bd1407bc32"),\n'
        '}\n',
    )
    source = _replace_once(
        source,
        "def _assert_release_controls_unchanged(repository, before_commit, target_commit):\n",
        TASK132_POLICY_PATCH + "\ndef _assert_release_controls_unchanged(repository, before_commit, target_commit):\n",
    )
    source = _replace_once(
        source,
        "TASK132_EXPECTED_TARGET_ENTRIES = {}",
        "TASK132_EXPECTED_TARGET_ENTRIES = " + repr(_ALL_TARGET_ENTRIES),
    )
    source = _replace_once(
        source,
        "    for path in PROTECTED_RELEASE_CONTROL_PATHS:\n",
        "    _assert_task132_control_blobs(repository, before_commit, target_commit)\n    for path in PROTECTED_RELEASE_CONTROL_PATHS:\n",
    )
    source = _replace_once(
        source,
        "    _assert_release_controls_unchanged(tool_root, before_commit, target_commit)\n",
        "    _assert_release_controls_unchanged(tool_root, before_commit, target_commit)\n"
        "    _assert_task132_bootstrap_state(tool_root, project_root, before_commit, target_commit)\n",
    )
    target_path_patch = (
        "TASK132_APPROVED_TARGET_PATHS = frozenset(" + repr(tuple(sorted(_ALL_TARGET_ENTRIES))) + ")\n\n"
        "def _path_is_forbidden(path):\n"
        "    normalized = PurePosixPath(path).as_posix()\n"
        "    if normalized in TASK132_APPROVED_TARGET_PATHS:\n"
        "        return False\n"
    )
    source = _replace_once(
        source,
        "def _path_is_forbidden(path):\n    normalized = PurePosixPath(path).as_posix()\n",
        target_path_patch,
    )
    policy.write_text(source, encoding="utf-8", newline="\n")
    policy.chmod(0o700)
    launcher = scripts / Path(DEPLOY_CODE_ONLY_PATH).name
    source = launcher.read_text(encoding="utf-8")
    source = _replace_once(
        source,
        'if [[ "$SCRIPT_ROOT" != "$PROJECT_ROOT" ]]; then',
        "if [[ \"$SCRIPT_ROOT\" != " + shlex.quote(str(overlay))
        + " || \"$PROJECT_ROOT\" != " + shlex.quote(str(project))
        + " ]]; then",
    )
    source = _replace_once(source, '"$PROJECT_ROOT/scripts/$control"', '"$SCRIPT_ROOT/scripts/$control"')
    launcher.write_text(source, encoding="utf-8", newline="\n")
    launcher.chmod(0o700)
    subprocess.run([_bash_executable(), "-n", str(launcher)], check=True)
    return launcher


def _remove_target_worktree(tool_root, destination):
    result = subprocess.run(
        ["git", "-C", str(tool_root), "worktree", "remove", "--force", str(destination)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    )
    if result.returncode:
        raise RuntimeError(f"failed to remove temporary target worktree: {destination}")


def _validate_identity(operator_user_id, approver_user_id):
    if operator_user_id <= 0 or approver_user_id <= 0:
        raise RuntimeError("operator and independent approver IDs must be positive")
    if operator_user_id == approver_user_id:
        raise RuntimeError("operator and independent approver IDs must differ")


def _write_receipt(path, approval, deployment_key, operator_user_id, approver_user_id):
    _validate_identity(operator_user_id, approver_user_id)
    receipt = Path(path)
    for candidate in (receipt, *receipt.parents):
        if candidate.is_symlink():
            raise RuntimeError("bootstrap receipt path cannot be a symlink")
    receipt.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _fsync_directory(receipt.parent.parent)
    payload = {
        **approval,
        "deployment_key": deployment_key,
        "operator_user_id": operator_user_id,
        "approver_user_id": approver_user_id,
        "scope": "pr132_release_control_only_execute",
        "mode": "execute",
        "database_migration": False,
        "attachment_migration": False,
        "frontend_publish": False,
        "static_publish": False,
        "frontend_migration": False,
    }
    descriptor = os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            json.dump(payload, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        _fsync_directory(receipt.parent)
    except BaseException:
        try:
            receipt.unlink()
        except FileNotFoundError:
            pass
        raise


def _fsync_directory(path):
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _invoke_launcher(*, project, tool, approval, deployment_key, mode, temporary_root):
    launcher = prepare_overlay(temporary_root / "overlay", approval, project, tool)
    target_worktree = temporary_root / "target-worktree"
    _git(tool, "worktree", "add", "--quiet", "--detach", str(target_worktree), TARGET_COMMIT)
    try:
        command = [
            _bash_executable(), str(launcher),
            "--project-root", str(project), "--tool-root", str(target_worktree),
            "--expected-before", BEFORE_COMMIT, "--target-commit", TARGET_COMMIT,
            "--deployment-key", deployment_key, mode,
        ]
        environment = os.environ.copy()
        environment["TMPDIR"] = str(temporary_root)
        result = subprocess.run(command, check=False, env=environment)
        if result.returncode:
            raise RuntimeError(f"code-only {mode} failed with exit {result.returncode}")
    finally:
        _remove_target_worktree(tool, target_worktree)


def run_check_only(*, project_root, tool_root, target_commit, deployment_key, tool_commit=None):
    if not KEY_RE.fullmatch(deployment_key or ""):
        raise RuntimeError("invalid check-only key")
    approval = validate_transition(project_root, tool_root, target_commit, tool_commit)
    print(json.dumps({**approval, "deployment_key": deployment_key}, ensure_ascii=False, indent=2), flush=True)
    project, tool = Path(project_root).resolve(strict=True), Path(tool_root).resolve(strict=True)
    initial_head, initial_marker = _git(project, "rev-parse", "HEAD").stdout.decode().strip(), (project / ".deployed_commit").read_bytes()
    temporary_parent = _temporary_parent(project, tool)
    try:
        with tempfile.TemporaryDirectory(prefix=f"qr-task132-check-{deployment_key}-", dir=temporary_parent) as temporary:
            root = Path(temporary)
            root.chmod(0o700)
            _invoke_launcher(project=project, tool=tool, approval=approval, deployment_key=deployment_key, mode="--check-only", temporary_root=root)
    finally:
        if _git(project, "rev-parse", "HEAD").stdout.decode().strip() != initial_head or (project / ".deployed_commit").read_bytes() != initial_marker:
            raise RuntimeError("production checkout changed during --check-only")
        fence = project / "data/deployments/write-fence.json"
        if fence.exists() or fence.is_symlink():
            raise RuntimeError("write-fence appeared during --check-only")
        _assert_clean(project, "production", allow_untracked_data=True)
        _assert_clean(tool, "release-tool")
    return approval


def run_execute(*, project_root, tool_root, target_commit, deployment_key, approved_bootstrap_sha256, operator_user_id, approver_user_id, tool_commit=None):
    if not KEY_RE.fullmatch(deployment_key or ""):
        raise RuntimeError("invalid deployment key")
    if not re.fullmatch(r"[0-9a-f]{64}", approved_bootstrap_sha256 or ""):
        raise RuntimeError("approved bootstrap SHA256 must be a full lowercase digest")
    _validate_identity(operator_user_id, approver_user_id)
    approval = validate_transition(project_root, tool_root, target_commit, tool_commit)
    if approval["bootstrap_sha256"] != approved_bootstrap_sha256:
        raise RuntimeError("bootstrap SHA256 does not match the independently reviewed file")
    project, tool = Path(project_root).resolve(strict=True), Path(tool_root).resolve(strict=True)
    temporary_parent = _temporary_parent(project, tool)
    receipt = project / "data" / "deployments" / f"{deployment_key}.bootstrap.json"
    _write_receipt(receipt, approval, deployment_key, operator_user_id, approver_user_id)
    with tempfile.TemporaryDirectory(prefix=f"qr-task132-execute-{deployment_key}-", dir=temporary_parent) as temporary:
        root = Path(temporary)
        root.chmod(0o700)
        _invoke_launcher(project=project, tool=tool, approval=approval, deployment_key=deployment_key, mode="--execute", temporary_root=root)
    return approval


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--tool-root", required=True)
    parser.add_argument("--target-commit", required=True)
    parser.add_argument(
        "--tool-commit",
        required=True,
        help="independent merge SHA containing this bootstrap, after the fixed target",
    )
    parser.add_argument("--deployment-key", required=True)
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
            project_root=args.project_root, tool_root=args.tool_root, target_commit=args.target_commit,
            deployment_key=args.deployment_key, approved_bootstrap_sha256=args.approved_bootstrap_sha256,
            operator_user_id=args.operator_user_id, approver_user_id=args.approver_user_id,
            tool_commit=args.tool_commit,
        )
    else:
        run_check_only(
            project_root=args.project_root, tool_root=args.tool_root, target_commit=args.target_commit,
            deployment_key=args.deployment_key, tool_commit=args.tool_commit,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
