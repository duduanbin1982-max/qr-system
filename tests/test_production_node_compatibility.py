import json
import sqlite3

import pytest

from factories import create_order
from modules import config
from modules.db import get_db
from modules.repositories.production_node_repository import ProductionNodeRepository
from modules.services.production_node_compatibility_service import (
    ProductionNodeCompatibilityService,
    normalize_legacy_resources,
    normalize_node_resources,
)


def _mapped_resources(db, count=1):
    rows = db.execute(
        "SELECT n.id AS node_id,n.legacy_process_line_id AS line_id,n.process_id "
        "FROM production_nodes n "
        "WHERE n.process_id=("
        "  SELECT process_id FROM production_nodes "
        "  GROUP BY process_id HAVING COUNT(*)>=? ORDER BY process_id LIMIT 1"
        ") ORDER BY n.id LIMIT ?",
        (count, count),
    ).fetchall()
    assert len(rows) == count
    return rows


def _seed_schedule_fact(
    db,
    *,
    suffix,
    resource,
    occupied_minutes,
    start_at,
    end_at,
    status="planned",
    with_segment=False,
    soft_deleted=False,
):
    order_id = create_order(
        db,
        [resource["process_id"]],
        quantity=1,
        product_code=f"NODE-COMPAT-{suffix}",
    )
    operation = db.execute(
        "SELECT id,process_version_id FROM order_processes WHERE order_id=?",
        (order_id,),
    ).fetchone()
    run_id = db.execute(
        "INSERT INTO schedule_runs "
        "(schedule_run_key,order_id,status,requested_start_date,result_json) "
        "VALUES (?,?,'completed','2026-09-18','[]')",
        (f"node-compat-{suffix}", order_id),
    ).lastrowid
    schedule_id = db.execute(
        "INSERT INTO order_process_schedules "
        "(order_id,order_process_id,process_id,process_line_id,production_node_id,"
        "seq_order,quantity,plan_start,plan_end,status,planned_start_at,"
        "planned_end_at,occupied_minutes,process_version_id,schedule_run_id) "
        "VALUES (?,?,?,?,?,1,1,'2026-09-18','2026-09-18',?,?,?,?,?,?)",
        (
            order_id,
            operation["id"],
            resource["process_id"],
            resource["line_id"],
            resource["node_id"],
            status,
            start_at,
            end_at,
            occupied_minutes,
            operation["process_version_id"],
            run_id,
        ),
    ).lastrowid
    segment_id = None
    if with_segment:
        segment_id = db.execute(
            "INSERT INTO order_process_schedule_segments "
            "(schedule_id,process_line_id,production_node_id,segment_start_at,"
            "segment_end_at,occupied_minutes,quantity) VALUES (?,?,?,?,?,?,1)",
            (
                schedule_id,
                resource["line_id"],
                resource["node_id"],
                start_at,
                end_at,
                occupied_minutes,
            ),
        ).lastrowid
    if soft_deleted:
        db.execute(
            "UPDATE orders SET deleted_at='2026-09-18 12:00:00' WHERE id=?",
            (order_id,),
        )
    return {
        "order_id": order_id,
        "schedule_id": schedule_id,
        "segment_id": segment_id,
    }


def _resource_row(rows, resource_id):
    return next(row for row in rows if row["id"] == resource_id)


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
            "occupancy_digest": "same-occupancy",
            "downtime_count": 1,
            "downtime_digest": "same-downtime",
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
            "occupancy_digest": "same-occupancy",
            "downtime_count": 1,
            "downtime_digest": "same-downtime",
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
            "occupancy_digest": "same-occupancy",
            "downtime_count": 1,
            "downtime_digest": "same-downtime",
            "conflict_count": 0,
        }
    ]

    nodes[0]["conflict_count"] = 1
    assert normalize_legacy_resources(legacy) != normalize_node_resources(nodes)

    nodes[0]["conflict_count"] = 0
    nodes[0]["downtime_digest"] = "different-window"
    assert normalize_legacy_resources(legacy) != normalize_node_resources(nodes)

    nodes[0]["downtime_digest"] = "same-downtime"
    nodes[0]["occupancy_digest"] = "different-fact"
    assert normalize_legacy_resources(legacy) != normalize_node_resources(nodes)


def test_repository_fact_projection_filters_non_capacity_facts_and_uses_segment_fallback(
    client,
):
    with client.application.app_context():
        db = get_db()
        resource = _mapped_resources(db)[0]
        _seed_schedule_fact(
            db,
            suffix="segment",
            resource=resource,
            occupied_minutes=30,
            start_at="2026-09-18 08:00:00",
            end_at="2026-09-18 08:30:00",
            with_segment=True,
        )
        _seed_schedule_fact(
            db,
            suffix="fallback",
            resource=resource,
            occupied_minutes=40,
            start_at="2026-09-18 09:00:00",
            end_at="2026-09-18 09:40:00",
        )
        _seed_schedule_fact(
            db,
            suffix="blocked",
            resource=resource,
            occupied_minutes=50,
            start_at="2026-09-18 10:00:00",
            end_at="2026-09-18 10:50:00",
            status="blocked",
            with_segment=True,
        )
        _seed_schedule_fact(
            db,
            suffix="deleted",
            resource=resource,
            occupied_minutes=60,
            start_at="2026-09-18 11:00:00",
            end_at="2026-09-18 12:00:00",
            with_segment=True,
            soft_deleted=True,
        )
        db.execute(
            "INSERT INTO schedule_downtime_events "
            "(process_line_id,production_node_id,start_at,end_at,reason,status) "
            "VALUES (?,?,?,?,?,'active')",
            (
                resource["line_id"],
                resource["node_id"],
                "2026-09-18 13:00:00",
                "2026-09-18 13:30:00",
                "active-window",
            ),
        )
        db.execute(
            "INSERT INTO schedule_downtime_events "
            "(process_line_id,production_node_id,start_at,end_at,reason,status) "
            "VALUES (?,?,?,?,?,'completed')",
            (
                resource["line_id"],
                resource["node_id"],
                "2026-09-18 14:00:00",
                "2026-09-18 14:30:00",
                "completed-window",
            ),
        )

        legacy = _resource_row(
            ProductionNodeRepository.list_legacy_resources(
                process_id=resource["process_id"], db=db
            ),
            resource["line_id"],
        )
        node = _resource_row(
            ProductionNodeRepository.list_nodes(
                process_id=resource["process_id"], db=db
            ),
            resource["node_id"],
        )

        assert legacy["scheduled_operations"] == node["scheduled_operations"] == 2
        assert legacy["occupied_minutes"] == node["occupied_minutes"] == 70
        assert legacy["downtime_count"] == node["downtime_count"] == 1
        assert legacy["occupancy_digest"] == node["occupancy_digest"]
        assert legacy["downtime_digest"] == node["downtime_digest"]


def test_conflicts_use_segment_first_fallback_facts_and_exclude_non_capacity_rows(
    client,
):
    with client.application.app_context():
        db = get_db()
        resource = _mapped_resources(db)[0]
        _seed_schedule_fact(
            db,
            suffix="conflict-segment",
            resource=resource,
            occupied_minutes=60,
            start_at="2026-09-18 08:00:00",
            end_at="2026-09-18 09:00:00",
            with_segment=True,
        )
        _seed_schedule_fact(
            db,
            suffix="conflict-fallback-a",
            resource=resource,
            occupied_minutes=60,
            start_at="2026-09-18 08:30:00",
            end_at="2026-09-18 09:30:00",
        )
        _seed_schedule_fact(
            db,
            suffix="conflict-fallback-b",
            resource=resource,
            occupied_minutes=60,
            start_at="2026-09-18 09:00:00",
            end_at="2026-09-18 10:00:00",
        )
        _seed_schedule_fact(
            db,
            suffix="conflict-blocked",
            resource=resource,
            occupied_minutes=60,
            start_at="2026-09-18 08:15:00",
            end_at="2026-09-18 09:15:00",
            status="blocked",
        )
        _seed_schedule_fact(
            db,
            suffix="conflict-deleted",
            resource=resource,
            occupied_minutes=60,
            start_at="2026-09-18 08:20:00",
            end_at="2026-09-18 09:20:00",
            with_segment=True,
            soft_deleted=True,
        )

        legacy = _resource_row(
            ProductionNodeRepository.list_legacy_resources(
                process_id=resource["process_id"], db=db
            ),
            resource["line_id"],
        )
        node = _resource_row(
            ProductionNodeRepository.list_nodes(
                process_id=resource["process_id"], db=db
            ),
            resource["node_id"],
        )

        # segment/fallback-a and fallback-a/fallback-b overlap.  The exact
        # boundary between segment and fallback-b is not a conflict.
        assert legacy["conflict_count"] == node["conflict_count"] == 2


def test_equal_occupancy_totals_with_different_fact_identity_record_mismatch(
    client, monkeypatch
):
    monkeypatch.setattr(config, "PRODUCTION_NODE_QUERY_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED", True)
    with client.application.app_context():
        db = get_db()
        first_resource, second_resource = _mapped_resources(db, count=2)
        first = _seed_schedule_fact(
            db,
            suffix="occupancy-a",
            resource=first_resource,
            occupied_minutes=30,
            start_at="2026-09-18 08:00:00",
            end_at="2026-09-18 08:30:00",
            with_segment=True,
        )
        second = _seed_schedule_fact(
            db,
            suffix="occupancy-b",
            resource=second_resource,
            occupied_minutes=30,
            start_at="2026-09-18 09:00:00",
            end_at="2026-09-18 09:30:00",
            with_segment=True,
        )
        ProductionNodeCompatibilityService.list_resources(
            process_id=first_resource["process_id"], db=db
        )

        db.execute(
            "UPDATE order_process_schedules SET production_node_id=? WHERE id=?",
            (second_resource["node_id"], first["schedule_id"]),
        )
        db.execute(
            "UPDATE order_process_schedules SET production_node_id=? WHERE id=?",
            (first_resource["node_id"], second["schedule_id"]),
        )
        db.execute(
            "UPDATE order_process_schedule_segments SET production_node_id=? WHERE id=?",
            (second_resource["node_id"], first["segment_id"]),
        )
        db.execute(
            "UPDATE order_process_schedule_segments SET production_node_id=? WHERE id=?",
            (first_resource["node_id"], second["segment_id"]),
        )

        ProductionNodeCompatibilityService.list_resources(
            process_id=first_resource["process_id"], db=db
        )
        observation = db.execute(
            "SELECT mismatch,difference_json FROM "
            "production_node_compatibility_observations ORDER BY id DESC LIMIT 1"
        ).fetchone()
        difference = json.loads(observation["difference_json"])
        changed_fields = {change["field"] for change in difference["changes"]}

        assert observation["mismatch"] == 1
        assert "occupancy_digest" in changed_fields
        assert "occupied_minutes" not in changed_fields
        assert "scheduled_operations" not in changed_fields


def test_equal_active_downtime_counts_with_different_windows_record_mismatch(
    client, monkeypatch
):
    monkeypatch.setattr(config, "PRODUCTION_NODE_QUERY_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED", True)
    with client.application.app_context():
        db = get_db()
        first_resource, second_resource = _mapped_resources(db, count=2)
        downtime_ids = []
        for resource, start_at, end_at, source_id in (
            (
                first_resource,
                "2026-09-18 08:00:00",
                "2026-09-18 08:30:00",
                101,
            ),
            (
                second_resource,
                "2026-09-18 10:00:00",
                "2026-09-18 10:30:00",
                202,
            ),
        ):
            downtime_ids.append(
                db.execute(
                    "INSERT INTO schedule_downtime_events "
                    "(process_line_id,production_node_id,start_at,end_at,reason,status,"
                    "source_type,source_id) VALUES (?,?,?,?,?,'active','manual',?)",
                    (
                        resource["line_id"],
                        resource["node_id"],
                        start_at,
                        end_at,
                        "compat-window",
                        source_id,
                    ),
                ).lastrowid
            )
        ProductionNodeCompatibilityService.list_resources(
            process_id=first_resource["process_id"], db=db
        )

        db.execute(
            "UPDATE schedule_downtime_events SET production_node_id=? WHERE id=?",
            (second_resource["node_id"], downtime_ids[0]),
        )
        db.execute(
            "UPDATE schedule_downtime_events SET production_node_id=? WHERE id=?",
            (first_resource["node_id"], downtime_ids[1]),
        )

        ProductionNodeCompatibilityService.list_resources(
            process_id=first_resource["process_id"], db=db
        )
        observation = db.execute(
            "SELECT mismatch,difference_json FROM "
            "production_node_compatibility_observations ORDER BY id DESC LIMIT 1"
        ).fetchone()
        difference = json.loads(observation["difference_json"])
        changed_fields = {change["field"] for change in difference["changes"]}

        assert observation["mismatch"] == 1
        assert "downtime_digest" in changed_fields
        assert "downtime_count" not in changed_fields


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
        difference = json.loads(observations[0]["difference_json"])
        assert difference["changes"] == []
        assert difference["coverage"] == {
            "legacy_count": 21,
            "node_count": 21,
            "truncated": False,
        }


def test_audit_uses_complete_scope_even_when_response_limit_is_one(
    client, monkeypatch
):
    monkeypatch.setattr(config, "PRODUCTION_NODE_QUERY_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED", True)
    with client.application.app_context():
        db = get_db()
        mapped = _mapped_resources(db)[0]
        calendar_id = db.execute(
            "SELECT calendar_id FROM production_nodes WHERE id=?",
            (mapped["node_id"],),
        ).fetchone()[0]
        unmapped_node_id = db.execute(
            "INSERT INTO production_nodes "
            "(process_id,node_code,node_name,capacity_mode,status,calendar_id) "
            "VALUES (?,?,?,'exclusive','active',?)",
            (
                mapped["process_id"],
                "AUDIT-UNMAPPED-LIMIT",
                "审计全量未映射节点",
                calendar_id,
            ),
        ).lastrowid

        response = ProductionNodeCompatibilityService.list_resources(
            process_id=mapped["process_id"], limit=1, db=db
        )
        observation = db.execute(
            "SELECT mismatch,difference_json FROM "
            "production_node_compatibility_observations ORDER BY id DESC LIMIT 1"
        ).fetchone()
        difference = json.loads(observation["difference_json"])

        assert len(response) == 1
        assert observation["mismatch"] == 1
        assert difference["missing_from_legacy"] == [
            f"unmapped-node:{unmapped_node_id}"
        ]
        assert difference["coverage"] == {
            "legacy_count": 1,
            "node_count": 2,
            "truncated": False,
        }


def test_db_none_commits_observation_before_app_context_closes(client, monkeypatch):
    monkeypatch.setattr(config, "PRODUCTION_NODE_QUERY_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED", True)

    with client.application.app_context():
        ProductionNodeCompatibilityService.list_resources(limit=1)
        assert get_db().in_transaction is False

    with client.application.app_context():
        observation = get_db().execute(
            "SELECT mismatch,difference_json FROM "
            "production_node_compatibility_observations"
        ).fetchone()
        assert observation is not None
        assert observation["mismatch"] == 0
        assert json.loads(observation["difference_json"])["coverage"][
            "truncated"
        ] is False


def test_db_none_rolls_back_owned_observation_transaction_on_error(
    client, monkeypatch
):
    monkeypatch.setattr(config, "PRODUCTION_NODE_QUERY_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED", True)

    def insert_then_fail(*, db, **_kwargs):
        db.execute(
            "INSERT INTO production_node_compatibility_observations "
            "(observation_key,scope,legacy_digest,node_digest,mismatch,difference_json) "
            "VALUES ('forced-rollback','resource_list','a','b',1,'{}')"
        )
        raise RuntimeError("forced compatibility audit failure")

    monkeypatch.setattr(
        ProductionNodeRepository,
        "record_compatibility_observation",
        staticmethod(insert_then_fail),
    )
    with client.application.app_context():
        db = get_db()
        with pytest.raises(RuntimeError, match="forced compatibility audit failure"):
            ProductionNodeCompatibilityService.list_resources(limit=1)
        assert db.in_transaction is False
        assert db.execute(
            "SELECT COUNT(*) FROM production_node_compatibility_observations"
        ).fetchone()[0] == 0


def test_explicit_db_keeps_caller_transaction_open_and_uncommitted(
    client, monkeypatch
):
    monkeypatch.setattr(config, "PRODUCTION_NODE_QUERY_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED", True)
    with client.application.app_context():
        db = get_db()
        db.execute("BEGIN")

        ProductionNodeCompatibilityService.list_resources(limit=1, db=db)

        assert db.in_transaction is True
        assert db.execute(
            "SELECT COUNT(*) FROM production_node_compatibility_observations"
        ).fetchone()[0] == 1
        db.rollback()
        assert db.execute(
            "SELECT COUNT(*) FROM production_node_compatibility_observations"
        ).fetchone()[0] == 0


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
        assert ProductionNodeRepository._bounded_limit(None) == 500
        assert ProductionNodeRepository._bounded_limit("") == 500
        assert ProductionNodeRepository._bounded_limit("invalid") == 500
        assert ProductionNodeRepository._bounded_limit(0) == 1
        assert ProductionNodeRepository._bounded_limit(-100) == 1
        assert ProductionNodeRepository._bounded_limit(100000) == 1000
