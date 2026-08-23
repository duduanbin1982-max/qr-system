import sqlite3

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
