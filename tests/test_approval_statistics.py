"""List and dashboard visibility must describe the same approval population."""
import sqlite3

import pytest

from modules.repositories.approval_repository import ApprovalRepository


@pytest.fixture
def approval_db():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE orders(id INTEGER PRIMARY KEY, order_no TEXT, deleted_at TEXT);
        CREATE TABLE work_records(id INTEGER PRIMARY KEY,order_id INTEGER,process_id INTEGER,
          process_version_id INTEGER,process_name_snapshot TEXT,user_id INTEGER,quantity INTEGER,
          serial_no TEXT,report_source TEXT,actual_completed_at TEXT,backfill_reason TEXT,
          submit_position_id INTEGER,submit_position_name TEXT,remark TEXT);
        CREATE TABLE approval_records(id INTEGER PRIMARY KEY,work_record_id INTEGER,status TEXT,
          created_at TEXT,processed_at TEXT);
        CREATE TABLE processes(id INTEGER PRIMARY KEY,name TEXT);
        CREATE TABLE process_versions(id INTEGER PRIMARY KEY,name TEXT);
        CREATE TABLE users(id INTEGER PRIMARY KEY,name TEXT);
        INSERT INTO orders VALUES(1,'ACTIVE',NULL),(2,'DELETED','2026-01-01');
        INSERT INTO work_records(id,order_id,quantity) VALUES(1,1,1),(2,2,1),(3,999,1);
    """)
    yield db
    db.close()


def add_record(db, work_id, status, age=25, duration=2):
    return db.execute("INSERT INTO approval_records(work_record_id,status,created_at,processed_at) "
                      "VALUES (?,?,datetime('now','localtime',?),CASE WHEN ?='pending' THEN NULL "
                      "ELSE datetime('now','localtime',?) END)",
                      (work_id, status, f"-{age} hours", status, f"-{age - duration} hours")).lastrowid


@pytest.mark.parametrize("status", ["pending", "approved", "rejected"])
@pytest.mark.parametrize("work_id,visible", [(1, True), (2, False), (3, True), (999, True)])
def test_statistics_and_lists_share_visibility(approval_db, status, work_id, visible):
    db = approval_db
    record_id = add_record(db, work_id, status)
    scope = "pending" if status == "pending" else "history"
    expected = int(visible)
    assert ApprovalRepository.count_by_status(scope, db=db) == expected
    rows = ApprovalRepository.find_by_status(scope, 20, 0, db=db)
    assert [row["id"] for row in rows] == ([record_id] if visible else [])
    stats = ApprovalRepository.get_approval_stats(db=db)
    assert stats["total"] == expected
    assert stats["pending"] == (expected if status == "pending" else 0)
    assert stats["pending_over_24h"] == (expected if status == "pending" else 0)
    assert stats["avg_hours"] == (2 if visible and status != "pending" else 0)


def test_average_and_overdue_exclude_deleted_orders(approval_db):
    db = approval_db
    add_record(db, 1, "approved", duration=2)
    add_record(db, 3, "rejected", duration=4)
    add_record(db, 2, "approved", age=125, duration=100)
    add_record(db, 1, "pending", age=25)
    add_record(db, 3, "pending", age=23)
    add_record(db, 2, "pending", age=50)
    assert ApprovalRepository.get_approval_stats(db=db) == {
        "pending": 2, "pending_over_24h": 1, "total": 4, "avg_hours": 3,
    }


def test_empty_statistics_are_zero(approval_db):
    assert ApprovalRepository.get_approval_stats(db=approval_db) == {
        "pending": 0, "pending_over_24h": 0, "total": 0, "avg_hours": 0,
    }


def test_unprocessed_history_is_not_in_average(approval_db):
    db = approval_db
    add_record(db, 1, "approved", duration=2)
    record_id = add_record(db, 1, "rejected", duration=15)
    db.execute("UPDATE approval_records SET processed_at=NULL WHERE id=?", (record_id,))
    assert ApprovalRepository.get_approval_stats(db=db)["avg_hours"] == 2
