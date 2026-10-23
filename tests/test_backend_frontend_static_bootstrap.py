import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts import bootstrap_backend_frontend_static_check as bootstrap
from scripts import code_only_release
from tests.test_code_only_deployment import _create_database, _write


def _commit_fixture(repository, files, message):
    """Store exact fixture bytes through Git, independent of filesystem filters."""
    entries = []
    for path, content in files.items():
        blob = subprocess.run(
            ["git", "-C", str(repository), "hash-object", "-w", "--stdin"],
            input=content.encode("utf-8"),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout.strip()
        entries.append(b"100644 " + blob + b"\t" + path.encode("utf-8") + b"\0")
    subprocess.run(
        ["git", "-C", str(repository), "update-index", "-z", "--index-info"],
        input=b"".join(entries),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    code_only_release._git(repository, "commit", "--quiet", "-m", message)
    return code_only_release._git(repository, "rev-parse", "HEAD").stdout.decode().strip()


def _bootstrap_repositories(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    code_only_release._git(repository, "init", "--quiet", "--initial-branch=master")
    code_only_release._git(repository, "config", "user.name", "Codex Test")
    code_only_release._git(repository, "config", "user.email", "codex-test@example.invalid")
    code_only_release._git(repository, "config", "core.autocrlf", "false")

    files = {path: f"# reviewed fixture: {path}\n" for path in (
        *bootstrap.BASELINE_CONTROLS,
        *bootstrap.OVERLAY_CONTROLS,
    )}
    files.update({
        ".gitattributes": "* -filter -text\n",
        ".gitignore": ".deployed_commit\n",
        "modules/migrations.py": "LATEST_VERSION = 96\n",
        "modules/migration_catalog.py": "MIGRATION_VERSION_CHAIN = (96,)\n",
        "modules/services/schedule.py": "VALUE = 1\n",
        "frontend/src/App.vue": "<template>before</template>\n",
        "package.json": json.dumps({"engines": {"node": "24.22.0", "npm": "11.19.1"}}),
        "package-lock.json": "{\"lockfileVersion\": 3}\n",
        ".nvmrc": "24.22.0\n",
        ".node-version": "24.22.0\n",
        ".npmrc": "engine-strict=true\n",
        "vite.config.js": "export default {}\n",
        "public/static/index.html": "<html>before</html>\n",
    })
    before = _commit_fixture(repository, files, "baseline")

    target = _commit_fixture(repository, {
        "modules/services/schedule.py": "VALUE = 2\n",
        "frontend/src/App.vue": "<template>target</template>\n",
    }, "target")

    production = tmp_path / "production"
    tool = tmp_path / "tool"
    code_only_release._git(repository, "worktree", "add", "--quiet", "--detach", str(production), before)
    code_only_release._git(repository, "worktree", "add", "--quiet", "--detach", str(tool), target)
    _create_database(production / "data/production.db", version=96)
    _write(production / ".deployed_commit", before + "\n")
    return production, tool, before, target


def test_bootstrap_uses_reviewed_controls_in_a_temporary_overlay(tmp_path):
    production, tool, before, target = _bootstrap_repositories(tmp_path)
    approved_sha256 = hashlib.sha256(Path(bootstrap.__file__).read_bytes()).hexdigest()

    approval = bootstrap.validate_bootstrap(
        production,
        tool,
        expected_before=before,
        target_commit=target,
        tool_commit=target,
        approved_bootstrap_sha256=approved_sha256,
    )
    launcher = bootstrap.prepare_overlay(tmp_path / "overlay", production, tool, approval)

    assert launcher.is_file()
    assert (launcher.parent / "__init__.py").read_bytes() == b""
    assert (launcher.parent / "deployment_manifest.py").read_bytes() == (
        tool / "scripts/deployment_manifest.py"
    ).read_bytes()
    assert (launcher.parent / "code_only_release.py").read_bytes() == (
        production / "scripts/code_only_release.py"
    ).read_bytes()


def test_bootstrap_refuses_unapproved_digest(tmp_path):
    production, tool, before, target = _bootstrap_repositories(tmp_path)

    with pytest.raises(RuntimeError, match="SHA256"):
        bootstrap.validate_bootstrap(
            production,
            tool,
            expected_before=before,
            target_commit=target,
            tool_commit=target,
            approved_bootstrap_sha256="0" * 64,
        )


def test_bootstrap_is_check_only_and_has_no_execute_option():
    source = Path(bootstrap.__file__).read_text(encoding="utf-8")

    assert 'parser.add_argument("--check-only", action="store_true", required=True)' in source
    assert 'parser.add_argument("--execute"' not in source
    assert '"--check-only",' in source
    assert '"--execute",' not in source
