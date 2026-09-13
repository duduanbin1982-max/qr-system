"""V084 order priority and scheduling change-history coverage."""

import sqlite3

import pytest

from modules.migrations import run_migrations
from modules.services.order_service import OrderService


def test_v084_migration_adds_fields_and_immutable_baseline():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        run_migrations(db)
        columns = {row["name"] for row in db.execute("PRAGMA table_info(orders)")}
        assert {
            "priority_level", "is_expedited", "priority_reason",
            "priority_changed_by", "priority_changed_by_name", "priority_changed_at",
            "priority_effective_at", "schedule_policy", "priority_version",
        }.issubset(columns)
        assert db.execute("SELECT COUNT(*) FROM order_priority_history").fetchone()[0] == 0
        db.execute(
            "INSERT INTO orders (order_no,product_name,quantity,status) VALUES ('V084-IMMUTABLE-001','P',1,'pending')"
        )
        order_id = db.execute("SELECT id FROM orders WHERE order_no='V084-IMMUTABLE-001'").fetchone()[0]
        db.execute(
            "INSERT INTO order_priority_history "
            "(order_id,order_no_snapshot,event_type,new_priority_level,new_is_expedited,"
            "new_schedule_policy,changed_at,priority_version,snapshot_digest) "
            "VALUES (?,?,'updated',3,0,'auto','2026-01-01 00:00:00',1,?)",
            (order_id, "V084-IMMUTABLE-001", "a" * 64),
        )
        history_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE order_priority_history SET new_priority_level=2 WHERE id=?", (history_id,))
        with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
            db.execute("DELETE FROM order_priority_history WHERE id=?", (history_id,))
    finally:
        db.close()


def test_create_order_writes_priority_baseline(client):
    with client.application.app_context():
        order_id, _ = OrderService.create_order(
            {
                "order_no": "V084-CREATE-001",
                "product_name": "V084 Product",
                "quantity": 2,
                "priority_level": 2,
                "is_expedited": True,
                "priority_reason": "客户急单",
                "schedule_policy": "allow_split",
            },
            user_id=1,
            user_name="Test Runner",
        )
        from modules.db import get_db

        row = get_db().execute(
            "SELECT priority_level,is_expedited,schedule_policy,priority_version "
            "FROM orders WHERE id=?", (order_id,)
        ).fetchone()
        history = get_db().execute(
            "SELECT event_type,new_priority_level,new_is_expedited,new_schedule_policy "
            "FROM order_priority_history WHERE order_id=?", (order_id,)
        ).fetchall()
        assert tuple(row) == (2, 1, "allow_split", 1)
        assert [tuple(item) for item in history] == [("created", 2, 1, "allow_split")]


def test_update_priority_requires_reason_and_records_version(client):
    with client.application.app_context():
        order_id, _ = OrderService.create_order({
            "order_no": "V084-UPDATE-001", "product_name": "V084 Product", "quantity": 1,
        })
        with pytest.raises(ValueError, match="必须填写变更原因"):
            OrderService.update_order(order_id, {"priority_level": 1}, user_id=1, user_name="Test Runner")
        OrderService.update_order(
            order_id,
            {"priority_level": 1, "deadline": "2026-10-01", "schedule_change_reason": "客户交期提前"},
            user_id=1,
            user_name="Test Runner",
        )
        from modules.db import get_db

        row = get_db().execute(
            "SELECT priority_level,deadline,priority_version,priority_changed_by_name "
            "FROM orders WHERE id=?", (order_id,)
        ).fetchone()
        history = get_db().execute(
            "SELECT old_priority_level,new_priority_level,old_deadline,new_deadline,"
            "change_reason,priority_version FROM order_priority_history "
            "WHERE order_id=? ORDER BY id", (order_id,)
        ).fetchall()
        assert tuple(row) == (1, "2026-10-01", 2, "Test Runner")
        assert tuple(history[0])[0:2] == (None, 3)
        assert tuple(history[1]) == (3, 1, "", "2026-10-01", "客户交期提前", 2)


def test_priority_history_can_detach_order_but_cannot_be_changed(client):
    with client.application.app_context():
        order_id, _ = OrderService.create_order({
            "order_no": "V084-DELETE-001", "product_name": "V084 Product", "quantity": 1,
        })
        from modules.db import get_db

        history_id = get_db().execute(
            "SELECT id FROM order_priority_history WHERE order_id=?", (order_id,)
        ).fetchone()[0]
        get_db().execute("DELETE FROM orders WHERE id=?", (order_id,))
        row = get_db().execute(
            "SELECT order_id FROM order_priority_history WHERE id=?", (history_id,)
        ).fetchone()
        assert row[0] is None
        with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
            get_db().execute("DELETE FROM order_priority_history WHERE id=?", (history_id,))
