import sqlite3

import pytest

from modules.db import get_db
from modules.domain.errors import ConflictError
from modules.services.inventory_posting_service import InventoryPostingService
from modules.services.inventory_service import InventoryService
from modules.services.scan_helper_service import ScanHelperService
from factories import create_order, ensure_process


def _create_item(quantity=0, model="LEDGER-001"):
    return InventoryService.create_item({
        "product_model": model,
        "product_name": "Ledger product",
        "quantity": quantity,
        "safe_stock": 1,
        "unit": "件",
    })


def test_opening_balance_and_all_movements_have_balance_snapshots(client):
    with client.application.app_context():
        db = get_db()
        item_id = _create_item(quantity=5)
        InventoryService.stock_out(item_id, 2, idempotency_key="manual-out-1")
        InventoryService.stock_in(item_id, 1, idempotency_key="manual-in-1")

        item = db.execute("SELECT * FROM inventory WHERE id=?", (item_id,)).fetchone()
        logs = db.execute(
            "SELECT type, qty_delta, balance_before, balance_after, movement_no "
            "FROM inventory_logs WHERE inventory_id=? ORDER BY id",
            (item_id,),
        ).fetchall()

        assert item["quantity"] == 4
        assert [(row["type"], row["qty_delta"]) for row in logs] == [
            ("opening_balance", 5), ("out", -2), ("in", 1),
        ]
        assert [(row["balance_before"], row["balance_after"]) for row in logs] == [
            (0, 5), (5, 3), (3, 4),
        ]
        assert all(row["movement_no"] for row in logs)
        assert sum(row["qty_delta"] for row in logs) == item["quantity"]


def test_idempotency_prevents_duplicate_balance_changes(client):
    with client.application.app_context():
        db = get_db()
        item_id = _create_item(model="LEDGER-IDEMPOTENT")

        first = InventoryPostingService.post(
            item_id, 3, "in", idempotency_key="stable-request-key"
        )
        second = InventoryPostingService.post(
            item_id, 3, "in", idempotency_key="stable-request-key"
        )

        assert second["id"] == first["id"]
        assert db.execute(
            "SELECT quantity FROM inventory WHERE id=?", (item_id,)
        ).fetchone()[0] == 3
        assert db.execute(
            "SELECT COUNT(*) FROM inventory_logs WHERE idempotency_key='stable-request-key'"
        ).fetchone()[0] == 1


def test_ledger_is_immutable_and_inventory_is_archived(client):
    with client.application.app_context():
        db = get_db()
        item_id = _create_item(quantity=2, model="LEDGER-ARCHIVE")
        log_id = db.execute(
            "SELECT id FROM inventory_logs WHERE inventory_id=?", (item_id,)
        ).fetchone()[0]

        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE inventory_logs SET remark='changed' WHERE id=?", (log_id,))
        db.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("DELETE FROM inventory_logs WHERE id=?", (log_id,))
        db.rollback()
        with pytest.raises(ConflictError, match="库存不为零"):
            InventoryService.delete_item(item_id)

        InventoryService.stock_out(item_id, 2)
        InventoryService.delete_item(item_id)
        archived = db.execute(
            "SELECT deleted_at FROM inventory WHERE id=?", (item_id,)
        ).fetchone()
        assert archived["deleted_at"]
        assert db.execute(
            "SELECT COUNT(*) FROM inventory_logs WHERE inventory_id=?", (item_id,)
        ).fetchone()[0] == 2
        with pytest.raises(sqlite3.IntegrityError, match="archive"):
            db.execute("DELETE FROM inventory WHERE id=?", (item_id,))


def test_reservation_and_reserved_consumption_are_atomic(client):
    with client.application.app_context():
        db = get_db()
        item_id = _create_item(quantity=5, model="LEDGER-RESERVE")

        InventoryPostingService.reserve(
            item_id, 4, idempotency_key="reserve-1", remark="shipment reserve"
        )
        with pytest.raises(ConflictError, match="可用库存"):
            InventoryService.stock_out(item_id, 2)
        InventoryPostingService.post(
            item_id, -4, "out", consume_reserved=True,
            idempotency_key="consume-1",
        )

        item = db.execute(
            "SELECT quantity, reserved FROM inventory WHERE id=?", (item_id,)
        ).fetchone()
        assert tuple(item) == (1, 0)


def test_lot_and_serial_balances_are_enforced(client):
    with client.application.app_context():
        item_id = _create_item(model="LEDGER-BATCH")
        InventoryService.stock_in(item_id, 2, lot_no="LOT-1")
        with pytest.raises(ConflictError, match="批次库存不足"):
            InventoryService.stock_out(item_id, 3, lot_no="LOT-1")
        InventoryService.stock_out(item_id, 1, lot_no="LOT-1")

        InventoryService.stock_in(item_id, 1, serial_no="SN-001")
        with pytest.raises(ConflictError, match="序列号已入库"):
            InventoryService.stock_in(item_id, 1, serial_no="SN-001")
        InventoryService.stock_out(item_id, 1, serial_no="SN-001")
        with pytest.raises(ConflictError, match="已出库"):
            InventoryService.stock_out(item_id, 1, serial_no="SN-001")


def test_count_task_posts_difference_only_after_approval(client):
    with client.application.app_context():
        db = get_db()
        item_id = _create_item(quantity=5, model="LEDGER-COUNT")
        task = InventoryService.create_count_task(user_id=1, user_name="counter")
        task_id = task["task"]["id"]

        InventoryService.submit_count(
            task_id, item_id, 3, user_id=1, user_name="counter"
        )
        assert db.execute(
            "SELECT quantity FROM inventory WHERE id=?", (item_id,)
        ).fetchone()[0] == 5

        approved = InventoryService.approve_count_task(
            task_id, user_id=1, user_name="approver"
        )
        assert approved["task"]["status"] == "posted"
        assert db.execute(
            "SELECT quantity FROM inventory WHERE id=?", (item_id,)
        ).fetchone()[0] == 3
        movement = db.execute(
            "SELECT type, qty_delta, source_type FROM inventory_logs "
            "WHERE idempotency_key=?",
            ("count:%s:item:%s:post" % (task_id, task["items"][0]["id"]),),
        ).fetchone()
        assert tuple(movement) == ("count_loss", -2, "count_task")


def test_count_approval_rejects_stock_changed_after_snapshot(client):
    with client.application.app_context():
        item_id = _create_item(quantity=5, model="LEDGER-COUNT-RACE")
        task = InventoryService.create_count_task(user_id=1, user_name="counter")
        task_id = task["task"]["id"]
        InventoryService.submit_count(task_id, item_id, 5)
        InventoryService.stock_in(item_id, 1)

        with pytest.raises(ConflictError, match="盘点期间"):
            InventoryService.approve_count_task(task_id, user_id=1, user_name="approver")


def test_inventory_api_rejects_direct_quantity_edit(client, auth_headers):
    response = client.post(
        "/api/inventory",
        json={"product_model": "API-LEDGER", "quantity": 2, "order_id": None},
        headers=auth_headers,
    )
    assert response.status_code == 200
    item_id = response.get_json()["id"]

    response = client.put(
        "/api/inventory/%s" % item_id,
        json={"product_model": "API-LEDGER", "quantity": 99},
        headers=auth_headers,
    )
    assert response.status_code == 400


def test_auto_inbound_can_create_separate_inventory_for_same_model_by_order(client):
    with client.application.app_context():
        db = get_db()
        process_id = ensure_process(db, "inventory-ledger-process")
        first_order = create_order(db, [process_id], product_code="SHARED-MODEL")
        second_order = create_order(db, [process_id], product_code="SHARED-MODEL")

        first = ScanHelperService.find_or_create_inventory(
            "SHARED-MODEL", "Product", first_order, db=db
        )
        second = ScanHelperService.find_or_create_inventory(
            "SHARED-MODEL", "Product", second_order, db=db
        )

        assert first != second
        assert db.execute(
            "SELECT COUNT(*) FROM inventory WHERE product_model='SHARED-MODEL'"
        ).fetchone()[0] == 2
