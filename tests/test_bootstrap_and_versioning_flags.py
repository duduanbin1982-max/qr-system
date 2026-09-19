import os
import sqlite3
import subprocess
import sys

import pytest

from modules.bootstrap import load_environment
from modules.versioning_flags import get_versioning_flags, validate_versioning_flags


FLAG_NAMES = ("QUERY", "AUDIT", "WRITE", "LEGACY_BLOCKED")


def _validate(flags):
    return validate_versioning_flags(
        flags,
        label="测试版本化",
        query_key="QUERY",
        audit_key="AUDIT",
        write_key="WRITE",
        legacy_blocked_key="LEGACY_BLOCKED",
    )


def test_load_environment_reads_project_env_without_overwriting_explicit_values(
    tmp_path, monkeypatch
):
    (tmp_path / ".env").write_text(
        "BOOTSTRAP_FROM_FILE=loaded\nBOOTSTRAP_EXPLICIT=file-value\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("BOOTSTRAP_FROM_FILE", raising=False)
    monkeypatch.setenv("BOOTSTRAP_EXPLICIT", "environment-value")

    environment = load_environment(tmp_path)

    assert environment["BOOTSTRAP_FROM_FILE"] == "loaded"
    assert environment["BOOTSTRAP_EXPLICIT"] == "environment-value"


def test_shared_versioning_flags_parse_values_and_enforce_cutover_order():
    assert get_versioning_flags(
        FLAG_NAMES,
        {"QUERY": "yes", "AUDIT": "1", "WRITE": "true", "LEGACY_BLOCKED": "on"},
    ) == {name: True for name in FLAG_NAMES}

    with pytest.raises(RuntimeError, match="测试版本化功能开关组合无效"):
        _validate(
            {"QUERY": False, "AUDIT": False, "WRITE": True, "LEGACY_BLOCKED": False}
        )


def test_production_node_flags_default_to_disabled():
    from modules import config

    assert config.get_production_node_flags({}) == {
        "PRODUCTION_NODE_QUERY_ENABLED": False,
        "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED": False,
        "PRODUCTION_NODE_WRITE_ENABLED": False,
        "PRODUCTION_NODE_ENGINE_ENABLED": False,
        "LEGACY_PROCESS_LINE_WRITE_BLOCKED": False,
    }


@pytest.mark.parametrize(
    "overrides,expected_message",
    [
        (
            {"PRODUCTION_NODE_COMPAT_AUDIT_ENABLED": True},
            "兼容双读审计要求先开启版本化查询",
        ),
        (
            {"PRODUCTION_NODE_WRITE_ENABLED": True},
            "版本化写入要求先开启版本化查询",
        ),
        (
            {
                "PRODUCTION_NODE_QUERY_ENABLED": True,
                "PRODUCTION_NODE_WRITE_ENABLED": True,
            },
            "生产节点写入要求先开启查询和兼容审计",
        ),
        (
            {
                "PRODUCTION_NODE_QUERY_ENABLED": True,
                "PRODUCTION_NODE_ENGINE_ENABLED": True,
            },
            "节点排程引擎要求先开启查询、兼容审计和节点写入",
        ),
        (
            {
                "PRODUCTION_NODE_QUERY_ENABLED": True,
                "PRODUCTION_NODE_WRITE_ENABLED": True,
                "LEGACY_PROCESS_LINE_WRITE_BLOCKED": True,
            },
            "阻断 Legacy 产线写入要求先开启节点排程引擎",
        ),
    ],
)
def test_production_node_flags_enforce_cutover_order(overrides, expected_message):
    from modules import config

    flags = config.get_production_node_flags({})
    flags.update(overrides)
    with pytest.raises(RuntimeError, match="生产节点功能开关组合无效") as error:
        config.validate_production_node_flags(flags)
    assert expected_message in str(error.value)


def test_production_node_flags_accept_complete_cutover_order():
    from modules import config

    flags = {
        "PRODUCTION_NODE_QUERY_ENABLED": True,
        "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED": True,
        "PRODUCTION_NODE_WRITE_ENABLED": True,
        "PRODUCTION_NODE_ENGINE_ENABLED": True,
        "LEGACY_PROCESS_LINE_WRITE_BLOCKED": True,
    }
    assert config.validate_production_node_flags(flags) == flags


def test_invalid_production_node_environment_fails_during_startup():
    environment = dict(os.environ)
    environment.update(
        {
            "SECRET_KEY": "startup-validation-test",
            "PRODUCTION_NODE_QUERY_ENABLED": "false",
            "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED": "false",
            "PRODUCTION_NODE_WRITE_ENABLED": "false",
            "PRODUCTION_NODE_ENGINE_ENABLED": "true",
            "LEGACY_PROCESS_LINE_WRITE_BLOCKED": "false",
        }
    )

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys\n"
                "try:\n"
                " import modules.config\n"
                "except RuntimeError as exc:\n"
                " assert '\\u751f\\u4ea7\\u8282\\u70b9\\u529f\\u80fd\\u5f00\\u5173\\u7ec4\\u5408\\u65e0\\u6548' in str(exc)\n"
                " print('PRODUCTION_NODE_FLAGS_REJECTED')\n"
                " sys.exit(7)\n"
            ),
        ],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=environment,
        capture_output=True,
    )

    assert result.returncode == 7
    assert b"PRODUCTION_NODE_FLAGS_REJECTED" in result.stdout


def test_production_node_write_without_audit_fails_during_startup():
    environment = dict(os.environ)
    environment.update(
        {
            "SECRET_KEY": "startup-validation-test",
            "PRODUCTION_NODE_QUERY_ENABLED": "true",
            "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED": "false",
            "PRODUCTION_NODE_WRITE_ENABLED": "true",
            "PRODUCTION_NODE_ENGINE_ENABLED": "false",
            "LEGACY_PROCESS_LINE_WRITE_BLOCKED": "false",
        }
    )

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys\n"
                "try:\n"
                " import modules.config\n"
                "except RuntimeError as exc:\n"
                " assert '\\u751f\\u4ea7\\u8282\\u70b9\\u5199\\u5165\\u8981\\u6c42\\u5148\\u5f00\\u542f\\u67e5\\u8be2\\u548c\\u517c\\u5bb9\\u5ba1\\u8ba1' in str(exc)\n"
                " print('PRODUCTION_NODE_WRITE_WITHOUT_AUDIT_REJECTED')\n"
                " sys.exit(7)\n"
            ),
        ],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=environment,
        capture_output=True,
    )

    assert result.returncode == 7
    assert b"PRODUCTION_NODE_WRITE_WITHOUT_AUDIT_REJECTED" in result.stdout


def test_verify_schema_is_read_only_and_rejects_stale_database(tmp_path, monkeypatch):
    from modules import db as db_module

    database = tmp_path / "stale.db"
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA user_version=1")
    connection.close()
    monkeypatch.setattr(db_module, "DB_PATH", str(database))

    with pytest.raises(RuntimeError, match="数据库版本不匹配"):
        db_module.verify_schema()

    assert sqlite3.connect(database).execute("PRAGMA user_version").fetchone()[0] == 1
