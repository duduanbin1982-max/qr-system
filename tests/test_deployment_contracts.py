from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_deploy_script_has_required_release_gates():
    content = (PROJECT_ROOT / "deploy.sh").read_text(encoding="utf-8")

    assert "git status --porcelain" in content
    assert "scripts/check_secrets.py" in content
    assert '"$PYTEST_BIN" -q' in content
    assert "scripts/backup-db.sh" in content
    assert "npm run build" in content
    assert "systemctl --user reload" in content
    assert "health_is_ok" in content
    assert "> .deployed_commit" in content
    assert "git pull" not in content
    assert "--skip-tests" not in content


def test_user_service_has_working_reload_and_restart_policy():
    content = (PROJECT_ROOT / "deploy" / "qr-system.service").read_text(encoding="utf-8")

    assert "EnvironmentFile=/home/dubin/qr-system/.env" in content
    assert "ExecReload=/bin/kill -HUP $MAINPID" in content
    assert "Restart=always" in content
    assert "WorkingDirectory=/home/dubin/qr-system" in content


def test_legacy_entrypoints_delegate_to_authoritative_tools():
    start_content = (PROJECT_ROOT / "start.sh").read_text(encoding="utf-8")
    script_deploy_content = (PROJECT_ROOT / "scripts" / "deploy.sh").read_text(encoding="utf-8")

    assert "nohup gunicorn" not in start_content
    assert 'exec "$PROJECT_ROOT/deploy.sh" "$@"' in script_deploy_content
