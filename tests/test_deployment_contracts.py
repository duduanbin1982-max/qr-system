import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_deploy_script_has_required_release_gates():
    content = (PROJECT_ROOT / "deploy.sh").read_text(encoding="utf-8")

    assert "git status --porcelain" in content
    assert "scripts/check_secrets.py" in content
    assert '"$PYTEST_BIN" -q' in content
    assert "npm run test:unit" in content
    assert "npm run test:e2e" in content
    assert "scripts/backup-db.sh" in content
    assert "load_dotenv('.env')" in content
    assert "from modules.migrations import run_migrations" in content
    assert "scripts/publish-frontend.sh" in content
    assert "systemctl --user reload" in content
    assert "health_is_ok" in content
    assert "> .deployed_commit" in content
    assert "git pull" not in content
    assert "--skip-tests" not in content

    backup_index = content.index("scripts/backup-db.sh")
    migration_index = content.index("from modules.migrations import run_migrations")
    build_index = content.rindex("scripts/publish-frontend.sh")
    assert backup_index < migration_index < build_index


def test_frontend_release_is_atomic_and_browser_tests_are_isolated():
    publisher = (PROJECT_ROOT / "scripts" / "publish-frontend.sh").read_text(encoding="utf-8")
    e2e_script = (PROJECT_ROOT / "scripts" / "test-e2e.sh").read_text(encoding="utf-8")
    app_module = (PROJECT_ROOT / "modules" / "app.py").read_text(encoding="utf-8")
    manifest = json.loads((PROJECT_ROOT / "package.json").read_text(encoding="utf-8"))

    assert '--outDir "$STAGING_DIR"' in publisher
    assert '"$STATIC_DIR/.index.html.new"' in publisher
    assert 'mv -f "$STATIC_DIR/.index.html.new" "$STATIC_DIR/index.html"' in publisher
    assert 'mtime "+$RETENTION_DAYS"' in publisher

    assert manifest["scripts"]["test:e2e"] == "bash scripts/test-e2e.sh"
    assert 'E2E_PUBLIC_DIR="$(mktemp -d' in e2e_script
    assert 'cp -a "$PROJECT_ROOT/public"/. "$E2E_PUBLIC_DIR"/' in e2e_script
    assert '--outDir "$E2E_PUBLIC_DIR/static"' in e2e_script
    assert 'export PUBLIC_DIR="$E2E_PUBLIC_DIR"' in e2e_script
    assert "os.environ.get('PUBLIC_DIR')" in app_module


def test_pytest_suite_declares_test_layers():
    config = (PROJECT_ROOT / "pytest.ini").read_text(encoding="utf-8")
    conftest = (PROJECT_ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")

    assert "unit:" in config
    assert "integration:" in config
    assert "contract:" in config
    assert "pytest_collection_modifyitems" in conftest
    assert "UNIT_TEST_FILES" in conftest
    assert "CONTRACT_TEST_FILES" in conftest


def test_user_service_has_working_reload_and_restart_policy():
    content = (PROJECT_ROOT / "deploy" / "qr-system.service").read_text(encoding="utf-8")

    assert "EnvironmentFile=/home/dubin/qr-system/.env" in content
    assert "ExecReload=/bin/kill -HUP $MAINPID" in content
    assert "Restart=always" in content
    assert "WorkingDirectory=/home/dubin/qr-system" in content


def test_build_restart_runs_migrations_before_restarting_service():
    content = (PROJECT_ROOT / "scripts" / "build.sh").read_text(encoding="utf-8")

    assert "from modules.db import init_db" in content
    assert "from dotenv import load_dotenv" in content
    assert "from modules.migrations import LATEST_VERSION" in content
    assert "systemctl --user restart qr-system.service" in content
    assert "reload-or-restart" not in content
    assert content.index("init_db") < content.index("systemctl --user restart")


def test_legacy_entrypoints_delegate_to_authoritative_tools():
    start_content = (PROJECT_ROOT / "start.sh").read_text(encoding="utf-8")
    script_deploy_content = (PROJECT_ROOT / "scripts" / "deploy.sh").read_text(encoding="utf-8")

    assert "nohup gunicorn" not in start_content
    assert 'exec "$PROJECT_ROOT/deploy.sh" "$@"' in script_deploy_content


def test_root_node_manifest_is_the_only_frontend_dependency_authority():
    manifest = json.loads((PROJECT_ROOT / "package.json").read_text(encoding="utf-8"))

    assert manifest["dependencies"]["html2canvas"] == "^1.4.1"
    assert not (PROJECT_ROOT / "frontend" / "package.json").exists()
    assert not (PROJECT_ROOT / "frontend" / "package-lock.json").exists()
    assert not (PROJECT_ROOT / "frontend" / "vite.config.js").exists()

    vite_config = (PROJECT_ROOT / "vite.config.js").read_text(encoding="utf-8")
    assert "root: frontendRoot" in vite_config
    assert "outDir: staticOutputDir" in vite_config
