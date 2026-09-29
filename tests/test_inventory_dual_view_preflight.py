import os

from scripts.preflight_inventory_dual_view import run


def test_inventory_dual_view_preflight_is_read_only_and_passes_schema():
    report = run(os.environ["DB_PATH"], limit=1000)
    assert report["connection_mode"] == "read-only"
    assert report["required_version"] == 96
    assert report["required_tables_missing"] == []
    assert report["required_triggers_missing"] == []
    assert report["foreign_key_violations"] == 0
    assert report["integrity_check"] == "ok"
    assert report["ok"] is True
