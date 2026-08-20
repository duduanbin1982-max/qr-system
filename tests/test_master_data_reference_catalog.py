import sqlite3
import uuid

import pytest

from factories import ensure_route_version
from modules.db import get_db
from modules.master_data_references import (
    POSITION_REFERENCES,
    PROCESS_REFERENCES,
    ROUTE_REFERENCES,
    cataloged_reference_columns,
    discover_position_reference_columns,
    find_unregistered_reference_columns,
    registered_position_reference_columns,
)
from modules.migration_process_management import rebuild_master_data_reference_guards
from modules.services.master_data_impact_service import MasterDataImpactService


def _insert_process(db, name):
    return db.execute(
        "INSERT INTO processes (name, description, category, seq_order, status, updated_at) "
        "VALUES (?, '', '结构件', 1, 'active', datetime('now','localtime'))",
        (name,),
    ).lastrowid


def _insert_route(db, process_id):
    route_id = db.execute(
        "INSERT INTO process_routes (name, description, category, status) "
        "VALUES (?, '', '结构件', 'active')",
        (f"引用目录路线-{uuid.uuid4().hex[:8]}",),
    ).lastrowid
    db.execute(
        "INSERT INTO process_route_items "
        "(route_id, process_id, seq_order, required_audit) VALUES (?, ?, 1, 0)",
        (route_id, process_id),
    )
    return route_id


def test_reference_catalog_covers_current_schema(client):
    with client.application.app_context():
        assert find_unregistered_reference_columns(get_db()) == []


def test_reference_catalog_reports_new_unregistered_columns(client):
    with client.application.app_context():
        db = get_db()
        db.execute(
            "CREATE TABLE simulated_master_data_reference ("
            "id INTEGER PRIMARY KEY, process_id INTEGER, route_id INTEGER)"
        )

        assert find_unregistered_reference_columns(db) == [
            ("simulated_master_data_reference", "process_id"),
            ("simulated_master_data_reference", "route_id"),
        ]


def test_reference_catalog_includes_payroll_performance_price_time_and_quality():
    columns = cataloged_reference_columns()
    expected = {
        ("payroll_detail_lines", "process_id"),
        ("payroll_detail_lines", "route_id"),
        ("performance_quality_events", "process_id"),
        ("performance_source_facts", "process_id"),
        ("route_price_versions", "process_id"),
        ("route_price_versions", "route_id"),
        ("route_price_history", "route_id"),
        ("work_time_standards", "route_id"),
        ("quality_standards", "route_id"),
        ("quality_inspection_plans", "route_id"),
    }
    assert expected.issubset(columns)
    assert all(reference.business_label for reference in PROCESS_REFERENCES)
    assert all(reference.suggested_action for reference in ROUTE_REFERENCES)


def test_position_reference_catalog_covers_all_live_columns(client):
    with client.application.app_context():
        db = get_db()
        discovered = discover_position_reference_columns(db)

    assert discovered - registered_position_reference_columns() == set()
    assert {
        ("users", "position_id"),
        ("user_sessions", "active_position_id"),
        ("performance_assignment_history", "position_version_id"),
        ("performance_source_facts", "position_id_snapshot"),
        ("performance_score_revisions", "position_version_id_snapshot"),
        ("performance_position_target_versions", "position_id"),
        ("work_records", "submit_position_version_id"),
    }.issubset(registered_position_reference_columns())
    assert all(reference.business_label for reference in POSITION_REFERENCES)
    assert all(reference.suggested_action for reference in POSITION_REFERENCES)


def test_route_impact_returns_business_labels_and_ignores_owned_nodes(client):
    with client.application.app_context():
        db = get_db()
        process_id = _insert_process(db, "路线影响目录工序")
        route_id = _insert_route(db, process_id)
        route_version_id = ensure_route_version(db, route_id)
        process_version_id = db.execute(
            "SELECT process_version_id FROM process_route_version_items "
            "WHERE route_version_id=? AND process_id=?",
            (route_version_id, process_id),
        ).fetchone()["process_version_id"]
        db.execute(
            "INSERT INTO route_price_versions ("
            "route_id, route_version_id, process_id, process_version_id, "
            "normal_unit_price_micros, valid_from, status) "
            "VALUES (?, ?, ?, ?, 10000, '2026-08-01 07:00:00', 'draft')",
            (route_id, route_version_id, process_id, process_version_id),
        )
        db.execute(
            "INSERT INTO quality_standards ("
            "standard_no, name, route_id, process_id, inspection_type) "
            "VALUES (?, '路线质量标准', ?, ?, 'in_process')",
            (f"STD-{uuid.uuid4().hex[:8]}", route_id, process_id),
        )
        db.commit()

        impact = MasterDataImpactService.route_impact(route_id, db=db)

    assert impact["used_orders"] == 0
    assert impact["used_products"] == 0
    assert impact["is_locked"] is True
    assert impact["total_references"] == 2
    references = {item["key"]: item for item in impact["references"]}
    assert references["price_versions"] == {
        "key": "price_versions",
        "label": "工价版本",
        "count": 1,
        "impact_level": "blocking",
        "suggested_action": "保留原路线并创建修订版",
    }
    assert references["quality_standards"]["label"] == "质量标准"
    assert "route_items" not in references


def test_reference_guards_block_root_and_referenced_draft_version_deletes(client):
    with client.application.app_context():
        db = get_db()
        process_id = _insert_process(db, "删除保护目录工序")
        route_id = _insert_route(db, process_id)
        process_version_id = db.execute(
            "INSERT INTO process_versions ("
            "process_id, version, process_code_snapshot, name, category, status) "
            "VALUES (?, 1, ?, '删除保护目录工序', '结构件', 'draft')",
            (process_id, f"PROC-{process_id:04d}"),
        ).lastrowid
        route_version_id = db.execute(
            "INSERT INTO process_route_versions ("
            "process_route_id, version, route_code_snapshot, name, category, status) "
            "VALUES (?, 1, ?, '删除保护目录路线', '结构件', 'draft')",
            (route_id, f"ROUTE-{route_id:04d}"),
        ).lastrowid
        db.execute(
            "INSERT INTO process_route_version_items "
            "(route_version_id, process_id, process_version_id, seq_order) "
            "VALUES (?, ?, ?, 1)",
            (route_version_id, process_id, process_version_id),
        )
        rebuild_master_data_reference_guards(db)
        db.commit()

        with pytest.raises(sqlite3.IntegrityError, match="process is referenced"):
            db.execute("DELETE FROM processes WHERE id=?", (process_id,))
        db.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="route is referenced"):
            db.execute("DELETE FROM process_routes WHERE id=?", (route_id,))
        db.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="process version is referenced"):
            db.execute("DELETE FROM process_versions WHERE id=?", (process_version_id,))
        db.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="route version is referenced"):
            db.execute("DELETE FROM process_route_versions WHERE id=?", (route_version_id,))
        db.rollback()
