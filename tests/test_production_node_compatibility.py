import json
import sqlite3

import pytest

from modules import config
from modules.db import get_db
from modules.repositories.production_node_repository import ProductionNodeRepository
from modules.services.production_node_compatibility_service import (
    ProductionNodeCompatibilityService,
    normalize_legacy_resources,
    normalize_node_resources,
)


def test_normalization_compares_operational_resource_facts_not_display_names():
    legacy = [
        {
            "id": 41,
            "process_id": 7,
            "line_code": "WELD-01",
            "line_name": "旧显示名",
            "status": "active",
            "calendar_id": 3,
            "daily_minutes": 540,
            "scheduled_operations": 2,
            "occupied_minutes": 125.5,
            "downtime_count": 1,
            "conflict_count": 0,
        }
    ]
    nodes = [
        {
            "id": 91,
            "legacy_process_line_id": 41,
            "process_id": 7,
            "node_code": "WELD-NODE-01",
            "node_name": "新显示名",
            "capacity_mode": "exclusive",
            "status": "active",
            "calendar_id": 3,
            "capacity_minutes": 540,
            "scheduled_operations": 2,
            "occupied_minutes": 125.5,
            "downtime_count": 1,
            "conflict_count": 0,
        }
    ]

    legacy_normalized = normalize_legacy_resources(legacy)
    node_normalized = normalize_node_resources(nodes)

    assert legacy_normalized == node_normalized
    assert legacy_normalized == [
        {
            "stable_mapping_id": 41,
            "process_id": 7,
            "status": "active",
            "calendar_id": 3,
            "capacity_mode": "exclusive",
            "capacity_minutes": 540.0,
            "scheduled_operations": 2,
            "occupied_minutes": 125.5,
            "downtime_count": 1,
            "conflict_count": 0,
        }
    ]

    nodes[0]["conflict_count"] = 1
    assert normalize_legacy_resources(legacy) != normalize_node_resources(nodes)


def test_audit_disabled_preserves_legacy_response_and_writes_no_evidence(
    client, monkeypatch
):
    monkeypatch.setattr(config, "PRODUCTION_NODE_QUERY_ENABLED", False)
    monkeypatch.setattr(config, "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED", False)
    with client.application.app_context():
        db = get_db()
        result = ProductionNodeCompatibilityService.list_resources(limit=50, db=db)

        assert result
        assert "line_code" in result[0]
        assert "node_code" not in result[0]
        assert db.execute(
            "SELECT COUNT(*) FROM production_node_compatibility_observations"
        ).fetchone()[0] == 0


def test_query_enabled_without_audit_writes_no_evidence(client, monkeypatch):
    monkeypatch.setattr(config, "PRODUCTION_NODE_QUERY_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED", False)
    with client.application.app_context():
        db = get_db()
        result = ProductionNodeCompatibilityService.list_resources(limit=50, db=db)

        assert result
        assert "node_code" in result[0]
        assert db.execute(
            "SELECT COUNT(*) FROM production_node_compatibility_observations"
        ).fetchone()[0] == 0


def test_audit_is_idempotent_and_query_flag_switches_to_nodes(client, monkeypatch):
    monkeypatch.setattr(config, "PRODUCTION_NODE_QUERY_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED", True)
    with client.application.app_context():
        db = get_db()
        first = ProductionNodeCompatibilityService.list_resources(limit=50, db=db)
        second = ProductionNodeCompatibilityService.list_resources(limit=50, db=db)

        assert first == second
        assert first
        assert "node_code" in first[0]
        assert "line_code" not in first[0]
        observations = db.execute(
            "SELECT mismatch,difference_json FROM "
            "production_node_compatibility_observations"
        ).fetchall()
        assert len(observations) == 1
        assert observations[0]["mismatch"] == 0
        assert json.loads(observations[0]["difference_json"])["changes"] == []


def test_audit_records_operational_mismatch_as_new_immutable_observation(
    client, monkeypatch
):
    monkeypatch.setattr(config, "PRODUCTION_NODE_QUERY_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED", True)
    with client.application.app_context():
        db = get_db()
        ProductionNodeCompatibilityService.list_resources(limit=50, db=db)
        node = db.execute(
            "SELECT id FROM production_nodes ORDER BY id LIMIT 1"
        ).fetchone()
        db.execute(
            "UPDATE production_nodes SET status='maintenance' WHERE id=?",
            (node["id"],),
        )

        ProductionNodeCompatibilityService.list_resources(limit=50, db=db)

        observations = db.execute(
            "SELECT id,mismatch,difference_json FROM "
            "production_node_compatibility_observations ORDER BY id"
        ).fetchall()
        assert len(observations) == 2
        assert [row["mismatch"] for row in observations] == [0, 1]
        changes = json.loads(observations[-1]["difference_json"])["changes"]
        assert any(change["field"] == "status" for change in changes)
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(
                "UPDATE production_node_compatibility_observations "
                "SET mismatch=0 WHERE id=?",
                (observations[-1]["id"],),
            )
        db.rollback()


def test_repository_bounds_limit_and_supports_process_scope(client):
    with client.application.app_context():
        db = get_db()
        process_id = db.execute(
            "SELECT process_id FROM production_nodes ORDER BY id LIMIT 1"
        ).fetchone()[0]
        legacy = ProductionNodeRepository.list_legacy_resources(
            process_id=process_id, limit=100000, db=db
        )
        nodes = ProductionNodeRepository.list_nodes(
            process_id=process_id, limit=100000, db=db
        )
        assert legacy
        assert nodes
        assert {row["process_id"] for row in legacy} == {process_id}
        assert {row["process_id"] for row in nodes} == {process_id}
