import json
from pathlib import Path

from modules.runtime_version import get_application_version


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_deploy_script_has_required_release_gates():
    content = (PROJECT_ROOT / "deploy.sh").read_text(encoding="utf-8")

    assert "git status --porcelain" in content
    assert "scripts/check_secrets.py" in content
    assert '"$PYTEST_BIN" -q' in content
    assert "npm ci --ignore-scripts --no-audit --no-fund" in content
    assert "bash scripts/install-playwright-runtime.sh" in content
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
    attachment_migration_index = content.index("scripts/migrate-employee-documents.sh")
    migration_index = content.index("from modules.migrations import run_migrations")
    build_index = content.rindex("scripts/publish-frontend.sh")
    assert backup_index < attachment_migration_index < migration_index < build_index


def test_employee_documents_share_verified_attachment_backup_boundary():
    config = (PROJECT_ROOT / "modules" / "config.py").read_text(encoding="utf-8")
    users_route = (PROJECT_ROOT / "modules" / "routes" / "users.py").read_text(
        encoding="utf-8"
    )
    backup = (PROJECT_ROOT / "scripts" / "backup-db.sh").read_text(encoding="utf-8")
    migration = (
        PROJECT_ROOT / "scripts" / "migrate-employee-documents.sh"
    ).read_text(encoding="utf-8")

    assert 'EMPLOYEE_DOCUMENT_DIR = os.path.join(DATA_DIR, "attachments", "employee_docs")' in config
    assert 'LEGACY_EMPLOYEE_DOCUMENT_DIR = os.path.join(BASE_DIR, "uploads", "employee_docs")' in config
    assert "EMPLOYEE_DOCUMENT_DIR" in users_route
    assert 'ATTACH_DIR="/home/dubin/qr-system/data/attachments"' in backup
    assert 'LEGACY_ATTACH_DIR="/home/dubin/qr-system/uploads/employee_docs"' in backup
    assert 'attachment_paths+=("data/attachments")' in backup
    assert 'attachment_paths+=("uploads/employee_docs")' in backup
    assert 'tar -tzf "$ATTACH_BACKUP"' in backup
    assert 'sha256sum "$ATTACH_BACKUP"' in backup
    assert 'secure_chmod 0600 "$partial_file"' in migration
    assert 'mv "$partial_file" "$target_file"' in migration
    assert 'cmp -s "$source_file" "$target_file"' in migration


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


def test_playwright_runtime_installer_prepares_browser_and_user_libraries():
    installer = (
        PROJECT_ROOT / "scripts" / "install-playwright-runtime.sh"
    ).read_text(encoding="utf-8")
    runner = (PROJECT_ROOT / "scripts" / "run-playwright.sh").read_text(
        encoding="utf-8"
    )

    assert "npx playwright install chromium" in installer
    assert "apt-get download" in installer
    assert "dpkg-deb -x" in installer
    assert "playwright-debs/root" in installer
    assert "playwright-debs/root" in runner
    assert "LD_LIBRARY_PATH" in runner


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


def test_build_restart_atomically_syncs_deployed_commit_before_restart():
    content = (PROJECT_ROOT / "scripts" / "build.sh").read_text(encoding="utf-8")

    assert 'git rev-parse --verify HEAD' in content
    assert '[[ ! "$commit" =~ ^[0-9a-f]{40}$ ]]' in content
    assert '.deployed_commit.tmp.' in content
    assert 'mv -f "$deployed_commit_tmp" .deployed_commit' in content
    sync_index = content.index('mv -f "$deployed_commit_tmp" .deployed_commit')
    restart_index = content.index("systemctl --user restart qr-system.service")
    assert sync_index < restart_index


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


def test_package_manifest_is_the_application_version_authority():
    manifest = json.loads((PROJECT_ROOT / "package.json").read_text(encoding="utf-8"))
    lockfile = json.loads((PROJECT_ROOT / "package-lock.json").read_text(encoding="utf-8"))
    app_module = (PROJECT_ROOT / "modules" / "app.py").read_text(encoding="utf-8")
    system_routes = (
        PROJECT_ROOT / "modules" / "routes" / "system.py"
    ).read_text(encoding="utf-8")
    vite_config = (PROJECT_ROOT / "vite.config.js").read_text(encoding="utf-8")
    frontend_index = (
        PROJECT_ROOT / "frontend" / "index.html"
    ).read_text(encoding="utf-8")
    login_page = (
        PROJECT_ROOT / "frontend" / "src" / "views" / "LoginPage.vue"
    ).read_text(encoding="utf-8")
    legacy_index = (PROJECT_ROOT / "public" / "index.html").read_text(encoding="utf-8")
    service_worker = (PROJECT_ROOT / "public" / "sw.js").read_text(encoding="utf-8")

    assert get_application_version() == manifest["version"]
    assert lockfile["version"] == manifest["version"]
    assert lockfile["packages"][""]["version"] == manifest["version"]
    assert "get_application_version" in app_module
    assert "get_application_version" in system_routes
    assert "'version': '2.0'" not in app_module
    assert "'version': '2.0'" not in system_routes
    assert "package.json" in vite_config
    assert "__APP_VERSION__" in vite_config
    assert "%APP_VERSION%" in frontend_index
    assert "__APP_VERSION__" in login_page
    assert "生产管理系统 v3" not in legacy_index
    assert manifest["version"] not in service_worker
    assert "CACHE_REVISION" in service_worker
