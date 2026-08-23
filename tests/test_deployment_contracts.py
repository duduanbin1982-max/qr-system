import io
import json
import shutil
import sqlite3
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.runtime_version import get_application_version
from scripts import deployment_manifest


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
    assert "from modules.bootstrap import load_environment" in content
    assert "from modules.migrations import run_migrations" in content
    assert "scripts/publish-frontend.sh" in content
    assert "systemctl --user stop qr-system.service" in content
    assert "systemctl --user start qr-system.service" in content
    assert "scripts/rollback-deployment.sh" in content
    assert "deployment_manifest.py" in content
    assert "health_is_ok" in content
    assert "atomic_write_deployed_commit" in content
    assert "git pull" not in content
    assert "systemctl --user reload" not in content
    assert "--skip-tests" not in content
    assert 'git -C "$PROJECT_ROOT" switch --detach "$before_commit"' in content
    assert content.index('"${1:-}" == "--check-only"') < content.index(
        "if [[ ! -f .deployed_commit ]]"
    )

    stop_index = content.index("systemctl --user stop qr-system.service")
    backup_index = content.index("scripts/backup-db.sh")
    attachment_migration_index = content.index("scripts/migrate-employee-documents.sh")
    migration_index = content.index("from modules.migrations import run_migrations")
    build_index = content.rindex("scripts/publish-frontend.sh")
    marker_index = content.rindex('atomic_write_deployed_commit "$commit"')
    start_index = content.rindex("systemctl --user start qr-system.service")
    assert (
        stop_index
        < backup_index
        < attachment_migration_index
        < migration_index
        < build_index
        < marker_index
        < start_index
    )


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
    assert 'ATTACH_DIR="$QR_PROJECT_ROOT/data/attachments"' in backup
    assert 'LEGACY_ATTACH_DIR="$QR_PROJECT_ROOT/uploads/employee_docs"' in backup
    assert 'attachment_paths+=("data/attachments")' in backup
    assert 'attachment_paths+=("uploads/employee_docs")' in backup
    assert 'tar -tzf "$ATTACH_BACKUP"' in backup
    assert 'sha256sum "$ATTACH_BACKUP"' in backup
    assert 'secure_chmod 0600 "$partial_file"' in migration
    assert 'mv "$partial_file" "$target_file"' in migration
    assert 'cmp -s "$source_file" "$target_file"' in migration


def _create_database(path, version):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    try:
        db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
        db.execute("INSERT INTO users (username) VALUES ('operator')")
        db.execute(f"PRAGMA user_version={version}")
        db.commit()
    finally:
        db.close()


def _archive_tree(path, project_root, relative_root):
    with tarfile.open(path, "w:gz") as archive:
        source = project_root / relative_root
        if source.exists():
            archive.add(source, arcname=relative_root.as_posix())


def test_deployment_manifest_restores_database_attachments_and_release(tmp_path):
    project_root = tmp_path / "project"
    backup_root = tmp_path / "backups"
    source_database = project_root / "data" / "production.db"
    _create_database(source_database, 72)

    attachment = project_root / "data" / "attachments" / "employee_docs" / "old.pdf"
    attachment.parent.mkdir(parents=True)
    attachment.write_bytes(b"verified attachment")
    static_asset = project_root / "public" / "static" / "app.js"
    static_asset.parent.mkdir(parents=True)
    static_asset.write_text("old release", encoding="utf-8")

    backup_root.mkdir()
    database_backup = backup_root / "production.db"
    shutil.copy2(source_database, database_backup)
    attachment_backup = backup_root / "attachments.tar.gz"
    release_backup = backup_root / "release.tar.gz"
    _archive_tree(
        attachment_backup, project_root, Path("data") / "attachments"
    )
    _archive_tree(release_backup, project_root, Path("public") / "static")

    backup_metadata = backup_root / "backup.json"
    deployment_manifest.create_backup_metadata(
        SimpleNamespace(
            database=str(database_backup),
            attachments=str(attachment_backup),
            attachment_root=["data/attachments"],
            output=str(backup_metadata),
        )
    )
    manifest_path = backup_root / "deployment.json"
    deployment_manifest.prepare_deployment_manifest(
        SimpleNamespace(
            backup_metadata=str(backup_metadata),
            release_backup=str(release_backup),
            deployment_key="test-deployment",
            before_commit="a" * 40,
            target_commit="b" * 40,
            target_database_version=73,
            output=str(manifest_path),
        )
    )

    source_database.unlink()
    _create_database(source_database, 73)
    attachment.write_bytes(b"changed attachment")
    (attachment.parent / "new.pdf").write_bytes(b"new attachment")
    static_asset.write_text("new release", encoding="utf-8")

    deployment_manifest.restore_deployment(
        SimpleNamespace(
            manifest=str(manifest_path),
            database=str(source_database),
            project_root=str(project_root),
        )
    )

    with sqlite3.connect(source_database) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 72
        assert db.execute("SELECT username FROM users").fetchone()[0] == "operator"
    assert attachment.read_bytes() == b"verified attachment"
    assert not (attachment.parent / "new.pdf").exists()
    assert static_asset.read_text(encoding="utf-8") == "old release"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "data_restored"


def test_backup_verification_rejects_attachment_path_traversal(tmp_path):
    database = tmp_path / "production.db"
    _create_database(database, 73)
    archive_path = tmp_path / "attachments.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        payload = b"unsafe"
        member = tarfile.TarInfo("../outside.txt")
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))

    metadata_path = tmp_path / "backup.json"
    deployment_manifest.create_backup_metadata(
        SimpleNamespace(
            database=str(database),
            attachments=str(archive_path),
            attachment_root=[],
            output=str(metadata_path),
        )
    )

    with pytest.raises(RuntimeError, match="unsafe attachment archive path"):
        deployment_manifest.verify_backup_metadata(metadata_path)


def test_deployment_manifest_refuses_to_overwrite_existing_evidence(tmp_path):
    manifest_path = tmp_path / "deployment.json"
    manifest_path.write_text("{}", encoding="utf-8")

    with pytest.raises(RuntimeError, match="already exists"):
        deployment_manifest.prepare_deployment_manifest(
            SimpleNamespace(output=str(manifest_path))
        )


def test_rollback_script_records_failures_and_restores_all_release_state():
    content = (PROJECT_ROOT / "scripts" / "rollback-deployment.sh").read_text(
        encoding="utf-8"
    )

    assert "trap record_rollback_failure ERR" in content
    assert 'systemctl --user stop qr-system.service || true' in content
    assert 'deployment_manifest.py" restore' in content
    assert 'git -C "$PROJECT_ROOT" switch --detach "$before_commit"' in content
    assert '.deployed_commit.tmp.$$' in content
    assert "systemctl --user start qr-system.service" in content
    assert "--status rolled_back" in content
    assert "--status rollback_failed" in content


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


def test_gunicorn_startup_only_verifies_schema_and_never_runs_migrations():
    content = (PROJECT_ROOT / "gunicorn.conf.py").read_text(encoding="utf-8")

    assert "from modules.db import verify_schema" in content
    assert "verify_schema()" in content
    assert "init_db" not in content
    assert "run_migrations" not in content


def test_all_application_entrypoints_load_environment_before_config_or_app():
    app_content = (PROJECT_ROOT / "modules" / "app.py").read_text(encoding="utf-8")
    server_content = (PROJECT_ROOT / "server.py").read_text(encoding="utf-8")
    gunicorn_content = (PROJECT_ROOT / "gunicorn.conf.py").read_text(encoding="utf-8")

    assert app_content.index("load_environment()") < app_content.index("from modules.config")
    assert server_content.index("load_environment()") < server_content.index("from modules.app")
    assert gunicorn_content.index("load_environment(base_dir)") < gunicorn_content.index(
        "import gunicorn"
    )


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
