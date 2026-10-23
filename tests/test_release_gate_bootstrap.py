"""Behavior tests for the exact-content, one-time release-control upgrade."""

import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import bootstrap_release_gate as bootstrap
from scripts import code_only_release


ROOT = Path(__file__).resolve().parents[1]


def git(root, *arguments, content=None):
    return subprocess.check_output(["git", "-C", str(root), *arguments], input=content)


def write(root, name, content):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))


def stage(root, name, mode="100644"):
    # Feed plaintext through stdin: endpoint file encryption can otherwise make
    # Git read encrypted on-disk bytes from a Python-created temporary fixture.
    oid = git(root, "hash-object", "-w", "--stdin", content=(root / name).read_bytes()).decode().strip()
    git(root, "update-index", "--add", "--cacheinfo", mode, oid, name)
    git(root, "checkout-index", "--force", "--", name)


@pytest.fixture
def transition(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    repository.mkdir()
    git(repository, "init", "--quiet", "--initial-branch=master")
    git(repository, "config", "user.name", "Bootstrap Test")
    git(repository, "config", "user.email", "bootstrap@example.invalid")
    git(repository, "config", "core.autocrlf", "false")
    write(repository, ".gitignore", ".deployed_commit\n__pycache__/\n")
    stage(repository, ".gitignore")
    for name in bootstrap.CONTROL_ENTRIES:
        content = git(ROOT, "show", f"{bootstrap.BEFORE}:{name}")
        write(repository, name, content)
        stage(repository, name, bootstrap.CONTROL_ENTRIES[name][0])
    for name in code_only_release.PROTECTED_RUNTIME_PATHS:
        write(repository, name, git(ROOT, "show", f"{bootstrap.BEFORE}:{name}"))
        stage(repository, name)
    write(repository, "scripts/check_secrets.py", (ROOT / "scripts/check_secrets.py").read_bytes())
    stage(repository, "scripts/check_secrets.py")
    write(repository, "package.json", '{"name":"bootstrap-fixture","version":"1.0.0"}\n')
    write(repository, "package-lock.json", '{"name":"bootstrap-fixture","version":"1.0.0","lockfileVersion":3,"packages":{"":{"name":"bootstrap-fixture","version":"1.0.0"}}}\n')
    stage(repository, "package.json")
    stage(repository, "package-lock.json")
    write(repository, "public/static/app.js", "// preserved frontend\n")
    stage(repository, "public/static/app.js")
    write(repository, "modules/migrations.py", "LATEST_VERSION = 96\n")
    stage(repository, "modules/migrations.py")
    write(repository, "tests/test_code_only_deployment.py", "# baseline tests\n")
    stage(repository, "tests/test_code_only_deployment.py")
    for name in (
        "modules/repositories/performance_history_migration_repository.py",
        "modules/repositories/performance_ledger_repository.py",
        "tests/test_architecture_imports.py",
    ):
        write(repository, name, git(ROOT, "show", f"{bootstrap.BEFORE}:{name}"))
        stage(repository, name)
    git(repository, "commit", "--quiet", "-m", "approved production")
    before = git(repository, "rev-parse", "HEAD").decode().strip()
    for name in bootstrap.ALLOWED_CHANGES:
        # The fixture represents the independently approved Task 5 target.
        # Read its exact bytes from that commit instead of the current checkout,
        # which may already contain a later release-control revision.
        write(
            repository,
            name,
            git(ROOT, "show", f"{bootstrap.APPROVED_TARGET_COMMIT}:{name}"),
        )
        stage(repository, name)
    git(repository, "commit", "--quiet", "-m", "approved gate upgrade")
    target = git(repository, "rev-parse", "HEAD").decode().strip()
    project = tmp_path / "production"
    tool = tmp_path / "target"
    git(repository, "worktree", "add", "--quiet", "--detach", str(project), before)
    git(repository, "worktree", "add", "--quiet", "--detach", str(tool), target)
    write(project, ".deployed_commit", before + "\n")
    database = project / "data/production.db"
    database.parent.mkdir()
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE facts (quantity INTEGER)")
        connection.execute("INSERT INTO facts VALUES (12)")
        connection.execute("PRAGMA user_version=96")
    monkeypatch.setattr(bootstrap, "BEFORE", before)
    monkeypatch.setattr(bootstrap, "APPROVED_TARGET_COMMIT", target)
    monkeypatch.setattr(
        bootstrap,
        "APPROVED_TARGET_ENTRIES",
        {
            path: tuple(bootstrap._entry(repository, target, path))
            for path in bootstrap.ALLOWED_CHANGES
        },
    )
    return SimpleNamespace(repository=repository, project=project, tool=tool, before=before, target=target, database=database)


def approve(transition):
    return bootstrap.validate_transition(transition.project, transition.tool, transition.target)


def amend(transition, path, content):
    write(transition.tool, path, content)
    stage(transition.tool, path)
    git(transition.tool, "commit", "--quiet", "-m", "unapproved change")
    transition.target = git(transition.tool, "rev-parse", "HEAD").decode().strip()


def load_overlay(tmp_path, approval):
    overlay = tmp_path / "overlay"
    overlay.mkdir()
    launcher = bootstrap.prepare_overlay(overlay, approval)
    policy = launcher.parent / "code_only_release.py"
    specification = importlib.util.spec_from_file_location("scripts.bootstrap_policy_test", policy)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module, launcher


def preflight(policy, transition):
    return policy.validate_code_only_release(
        transition.tool, transition.project, transition.database, transition.before, transition.target,
    )


def test_ordinary_gate_rejects_self_upgrade_but_exact_bootstrap_accepts_without_writes(transition, tmp_path):
    with pytest.raises(RuntimeError, match="cannot change trusted release control"):
        preflight(code_only_release, transition)
    baseline = transition.database.read_bytes()
    production_status = git(transition.project, "status", "--porcelain")
    approval = approve(transition)
    policy, launcher = load_overlay(tmp_path, approval)

    result = preflight(policy, transition)

    assert result["target_commit"] == transition.target
    assert result["database"]["user_version"] == 96
    assert transition.database.read_bytes() == baseline
    assert git(transition.project, "status", "--porcelain") == production_status
    assert git(transition.project, "rev-parse", "HEAD").decode().strip() == transition.before
    assert not (transition.project / "data/deployments").exists()
    assert launcher.exists()


@pytest.mark.parametrize("path", [
    "modules/services/new_rule.py", "modules/migrations.py", "data/tracked.db",
    "frontend/src/views/Inventory.vue", "public/static/app.js", "package.json",
    "scripts/deploy-code-only.sh", "scripts/deployment_manifest.py",
    "scripts/backup-db.sh", "scripts/rollback-deployment.sh",
])
def test_bootstrap_rejects_business_migration_frontend_data_and_control_changes(transition, path):
    amend(transition, path, "UNAPPROVED = True\n")
    with pytest.raises(RuntimeError, match="changed paths mismatch"):
        approve(transition)


def test_bootstrap_rejects_any_unreviewed_validator_byte(transition):
    amend(transition, bootstrap.POLICY_PATH, (ROOT / bootstrap.POLICY_PATH).read_bytes() + b"# drift\n")
    with pytest.raises(RuntimeError, match="regular, retained"):
        approve(transition)


def test_bootstrap_rejects_modified_production_controls(transition):
    write(transition.project, "scripts/deployment_manifest.py", "# locally modified\n")
    with pytest.raises(RuntimeError, match="production release control modified"):
        approve(transition)


def test_bootstrap_rejects_target_bootstrap_change(transition):
    amend(transition, bootstrap.BOOTSTRAP_PATH, "raise RuntimeError('target authorized itself')\n")
    with pytest.raises(RuntimeError, match="changed paths mismatch"):
        approve(transition)


@pytest.mark.parametrize("path", [bootstrap.POLICY_PATH])
def test_bootstrap_rejects_executable_mode_changes(transition, path):
    git(transition.tool, "update-index", "--chmod=+x", path)
    git(transition.tool, "commit", "--quiet", "-m", "mode change")
    transition.target = git(transition.tool, "rev-parse", "HEAD").decode().strip()
    with pytest.raises(RuntimeError, match="regular, retained"):
        approve(transition)


def test_bootstrap_rejects_deleted_tests(transition):
    # A test path is allowed to change, but a missing target entry is not allowed.
    git(transition.tool, "rm", "tests/test_code_only_deployment.py")
    git(transition.tool, "commit", "--quiet", "-m", "deleted tests")
    transition.target = git(transition.tool, "rev-parse", "HEAD").decode().strip()
    with pytest.raises(RuntimeError, match="missing or ambiguous"):
        approve(transition)


def test_bootstrap_rejects_git_symlink_in_allowed_path(transition):
    path = "tests/test_code_only_deployment.py"
    oid = git(transition.tool, "hash-object", "-w", "--stdin", content=b"../scripts/bootstrap_release_gate.py").decode().strip()
    git(transition.tool, "update-index", "--cacheinfo", "120000", oid, path)
    git(transition.tool, "commit", "--quiet", "-m", "symlink tests")
    transition.target = git(transition.tool, "rev-parse", "HEAD").decode().strip()
    with pytest.raises(RuntimeError, match="regular, retained"):
        approve(transition)


def test_overlay_rechecks_drift_after_initial_approval(transition, tmp_path):
    policy, _ = load_overlay(tmp_path, approve(transition))
    amend(transition, "modules/services/surprise.py", "VALUE = 1\n")
    with pytest.raises(RuntimeError, match="bootstrap approval commit or root mismatch"):
        preflight(policy, transition)


def test_overlay_uses_old_backup_fence_and_rollback_controls(transition, tmp_path):
    approval = approve(transition)
    _, launcher = load_overlay(tmp_path, approval)
    for path in bootstrap.CONTROL_ENTRIES:
        if path not in {bootstrap.POLICY_PATH, "scripts/deploy-code-only.sh"}:
            assert (launcher.parent / Path(path).name).read_bytes() == git(
                transition.project, "show", f"{transition.before}:{path}",
            ), path
    source = launcher.read_text(encoding="utf-8")
    previous = git(transition.project, "show", f"{transition.before}:scripts/deploy-code-only.sh").decode()
    # The complete execution/rollback state machine remains byte-for-byte intact.
    assert source[source.index("fence_owned=false\n"):] == previous[previous.index("fence_owned=false\n"):]
    assert 'install -m 0700 "$SCRIPT_ROOT/scripts/$control"' in source


def test_bootstrap_patch_point_drift_fails_closed():
    with pytest.raises(RuntimeError, match="patch point drifted"):
        bootstrap._replace_once("different source", "expected source", "replacement")


@pytest.mark.skipif(not hasattr(os, "O_DIRECTORY"), reason="Linux production durability contract")
def test_bootstrap_receipt_is_exclusive_and_preserves_approval(tmp_path):
    path = tmp_path / "deployments/key.bootstrap.json"
    args = SimpleNamespace(operator_user_id=1000, approver_user_id=1004, deployment_key="key")
    approval = {"before_commit": "a" * 40, "target_commit": "b" * 40}
    bootstrap.write_receipt(path, approval, args)
    persisted = json.loads(path.read_text())
    assert persisted["scope"] == "release_gate_bootstrap_code_only"
    assert persisted["operator_user_id"] == 1000
    assert persisted["approver_user_id"] == 1004
    assert persisted["migrations"] is False
    baseline = path.read_bytes()
    with pytest.raises(FileExistsError):
        bootstrap.write_receipt(path, approval, args)
    assert path.read_bytes() == baseline


@pytest.mark.skipif(os.name == "nt", reason="Linux production filesystem contract")
def test_bootstrap_rejects_symlinked_production_control(transition):
    path = transition.project / "scripts/deployment_manifest.py"
    original = path.read_bytes()
    path.unlink()
    replacement = transition.project / "data/manifest-copy.py"
    replacement.write_bytes(original)
    path.symlink_to(replacement)
    with pytest.raises(RuntimeError, match="unsafe file"):
        approve(transition)


@pytest.mark.skipif(not hasattr(os, "O_DIRECTORY"), reason="Linux production durability contract")
def test_receipt_persistence_failure_prevents_release_and_preserves_production(transition, monkeypatch):
    database_before = transition.database.read_bytes()
    approval = approve(transition)

    def fail_sync(_descriptor):
        raise OSError("injected durability failure")

    def refuse_execution(_arguments):
        pytest.fail("release must not start before bootstrap evidence is durable")

    monkeypatch.setattr(bootstrap.os, "fsync", fail_sync)
    monkeypatch.setattr(bootstrap.subprocess, "call", refuse_execution)
    monkeypatch.setattr(bootstrap, "prepare_test_runner", lambda *_: Path("/unused-before-receipt"))
    with pytest.raises(OSError, match="injected durability failure"):
        bootstrap.main([
            "--project-root", str(transition.project), "--tool-root", str(transition.tool),
            "--target-commit", transition.target, "--deployment-key", "durability-failure",
            "--approved-bootstrap-sha256", approval["bootstrap_sha256"],
            "--operator-user-id", "1000", "--approver-user-id", "1004", "--execute",
        ])
    assert transition.database.read_bytes() == database_before
    assert git(transition.project, "rev-parse", "HEAD").decode().strip() == transition.before
    assert (transition.project / "data/deployments/durability-failure.bootstrap.json").exists()
    assert not (transition.project / "data/deployments/write-fence.json").exists()


@pytest.mark.skipif(os.name == "nt", reason="Linux executable test runner")
def test_locked_test_dependencies_are_only_linked_into_temporary_test_checkout(transition, tmp_path, monkeypatch):
    probe = tmp_path / "pytest-probe"
    probe.write_text(f"#!{sys.executable}\nfrom pathlib import Path\nimport sys\n"
        "assert sys.argv[1:] == ['-q']\n"
        "assert (Path.cwd() / 'node_modules').is_symlink()\n", encoding="utf-8")
    probe.chmod(0o700)
    monkeypatch.setenv("PYTEST_BIN", str(probe))
    runner = bootstrap.prepare_test_runner(tmp_path, approve(transition))
    for protected in (transition.project, transition.tool):
        result = subprocess.run([str(runner), "-q"], cwd=protected, capture_output=True)
        assert result.returncode != 0
        assert not (protected / "node_modules").is_symlink()
    temporary = tmp_path / "temporary-test-checkout"
    git(transition.tool, "worktree", "add", "--quiet", "--detach", str(temporary), transition.target)
    subprocess.run([str(runner), "-q"], cwd=temporary, check=True)
    assert (temporary / "node_modules").resolve() == tmp_path / "test-dependencies/node_modules"


@pytest.mark.skipif(os.name == "nt" or not Path("/usr/bin/sqlite3").is_file(), reason="Linux release rehearsal")
@pytest.mark.parametrize("reject_target_health", [False, True], ids=["accepted", "rollback"])
def test_real_launcher_preserves_facts_and_evidence_on_acceptance_and_rollback(
    transition, tmp_path, monkeypatch, reject_target_health,
):
    # Only service/HTTP/test-runner process boundaries are faked. The real old
    # launcher, validator, backups, manifest, fence and rollback execute on a
    # disposable repository/database, never the host's service or live data.
    with sqlite3.connect(transition.database) as connection:
        connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO users VALUES (1000)")
        for index in range(8):
            connection.execute(f"CREATE TABLE fixture_{index} (id INTEGER)")
        # Match the independently read production baseline (V096, schema cookie
        # 1); SQLite backup resets this internal cookie on a new destination.
        connection.execute("PRAGMA schema_version=1")
    attachment = transition.project / "data/attachments/fact.txt"
    write(transition.project, "data/attachments/fact.txt", "preserved attachment\n")
    database_before = transition.database.read_bytes()
    tools = tmp_path / "fake-process-boundaries"
    tools.mkdir()
    driver = tools / "driver"
    driver.write_text(f"#!{sys.executable}\n" + '''import json, os, sys
from pathlib import Path
root = Path(os.environ["REHEARSAL_PROJECT"])
state = Path(os.environ["REHEARSAL_STATE"])
name = Path(sys.argv[0]).name
if name == "systemctl":
    action = sys.argv[2]
    if action == "is-active":
        raise SystemExit(0 if state.read_text() == "active" else 3)
    if action not in {"start", "stop"}:
        raise SystemExit("unsupported fake service action")
    state.write_text("active" if action == "start" else "stopped")
elif name == "curl":
    if state.read_text() != "active":
        raise SystemExit(7)
    commit = (root / ".deployed_commit").read_text().strip()
    fence = root / "data/deployments/write-fence.json"
    if os.environ["REHEARSAL_REJECT_TARGET"] == "1" and commit == os.environ["REHEARSAL_TARGET"]:
        raise SystemExit(22)
    print(json.dumps({"status": "ok", "db": "connected", "commit": commit,
        "write_fenced": fence.exists(),
        "deployment_key": json.loads(fence.read_text())["deployment_key"] if fence.exists() else None}))
else:
    raise SystemExit("unsupported fake process")
''', encoding="utf-8")
    driver.chmod(0o700)
    for name in ("systemctl", "curl"):
        (tools / name).symlink_to(driver)
    (tools / "sleep").symlink_to(shutil.which("true"))
    state = tmp_path / "service-state"
    state.write_text("active")
    for name, value in {
        "PATH": str(tools) + os.pathsep + os.environ["PATH"],
        "REHEARSAL_PROJECT": str(transition.project), "REHEARSAL_STATE": str(state),
        "REHEARSAL_TARGET": transition.target,
        "REHEARSAL_REJECT_TARGET": "1" if reject_target_health else "0",
        "PYTEST_BIN": shutil.which("true"), "GUNICORN_BIN": shutil.which("true"),
    }.items():
        monkeypatch.setenv(name, value)
    approval = approve(transition)

    result = bootstrap.main([
        "--project-root", str(transition.project), "--tool-root", str(transition.tool),
        "--target-commit", transition.target, "--deployment-key", "rehearsal",
        "--approved-bootstrap-sha256", approval["bootstrap_sha256"],
        "--operator-user-id", "1000", "--approver-user-id", "1004", "--execute",
    ])

    expected_commit = transition.before if reject_target_health else transition.target
    assert (result != 0) is reject_target_health
    assert git(transition.project, "rev-parse", "HEAD").decode().strip() == expected_commit
    assert (transition.project / ".deployed_commit").read_text().strip() == expected_commit
    assert transition.database.read_bytes() == database_before
    assert attachment.read_text() == "preserved attachment\n"
    assert (transition.project / "public/static/app.js").read_text() == "// preserved frontend\n"
    assert state.read_text() == "active"
    assert not (transition.project / "data/deployments/write-fence.json").exists()
    manifest = json.loads((transition.project / "data/deployments/rehearsal.json").read_text())
    assert manifest["status"] == ("rollback_code_only" if reject_target_health else "succeeded")
    assert (transition.project / "data/deployments/rehearsal.bootstrap.json").is_file()
    for name in ("production_rehearsal.db", "attachments_rehearsal.tar.gz", "release_rehearsal.tar.gz"):
        assert (transition.project / "data/backups" / name).is_file(), name
