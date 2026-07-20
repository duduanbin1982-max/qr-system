import pytest

from factories import create_inventory_item, create_order, ensure_process
from modules.db import get_db
from modules.services.shipment_service import ShipmentService


CURRENT_USER = {"id": 1, "name": "测试管理员"}


def _shipment_context(db, quantity=10):
    process_id = ensure_process(db, "发货测试工序")
    order_id = create_order(db, [process_id], quantity=quantity, product_code="SHIP-001")
    order = db.execute("SELECT order_no FROM orders WHERE id = ?", (order_id,)).fetchone()
    inventory_id = create_inventory_item(
        db,
        quantity=quantity,
        order_id=order_id,
        product_model="SHIP-001",
        product_name="发货测试产品",
    )
    return order_id, order["order_no"], inventory_id


def _shipment_payload(order_id, order_no, inventory_id, quantity=4, **overrides):
    payload = {
        "customer": "测试客户",
        "order_id": order_id,
        "order_no": order_no,
        "receivable_amount": 100,
        "items": [{
            "inventory_id": inventory_id,
            "product_model": "SHIP-001",
            "product_name": "发货测试产品",
            "quantity": quantity,
            "unit": "件",
            "order_id": order_id,
            "order_no": order_no,
        }],
    }
    payload.update(overrides)
    return payload


def test_create_and_get_shipment_preserves_product_and_order_identity(client):
    with client.application.app_context():
        db = get_db()
        order_id, order_no, inventory_id = _shipment_context(db)
        shipment_id, shipment_no = ShipmentService.create_shipment(
            _shipment_payload(order_id, order_no, inventory_id), created_by="测试管理员"
        )

        shipment = ShipmentService.get_shipment(shipment_id)
        assert shipment["shipment_no"] == shipment_no
        assert shipment["status"] == "pending"
        assert shipment["items"][0]["product_code"] == "SHIP-001"
        assert shipment["items"][0]["order_no"] == order_no
        assert db.execute(
            "SELECT quantity FROM inventory WHERE id = ?", (inventory_id,)
        ).fetchone()["quantity"] == 10


def test_create_shipment_rejects_empty_items_and_insufficient_stock(client):
    with client.application.app_context():
        db = get_db()
        order_id, order_no, inventory_id = _shipment_context(db, quantity=2)
        with pytest.raises(ValueError, match="请添加出库产品"):
            ShipmentService.create_shipment({"items": []}, created_by="测试管理员")
        with pytest.raises(ValueError, match="库存不足"):
            ShipmentService.create_shipment(
                _shipment_payload(order_id, order_no, inventory_id, quantity=3),
                created_by="测试管理员",
            )


def test_complete_shipment_deducts_stock_and_updates_delivery_status(client):
    with client.application.app_context():
        db = get_db()
        order_id, order_no, inventory_id = _shipment_context(db, quantity=4)
        shipment_id, shipment_no = ShipmentService.create_shipment(
            _shipment_payload(order_id, order_no, inventory_id, quantity=4),
            created_by="测试管理员",
        )

        assert ShipmentService.complete_shipment(shipment_id, CURRENT_USER) == shipment_no
        shipment = ShipmentService.get_shipment(shipment_id)
        inventory = db.execute(
            "SELECT quantity FROM inventory WHERE id = ?", (inventory_id,)
        ).fetchone()
        order = db.execute(
            "SELECT delivery_status FROM orders WHERE id = ?", (order_id,)
        ).fetchone()
        assert shipment["status"] == "completed"
        assert inventory["quantity"] == 0
        assert order["delivery_status"] == "全部发货"
        with pytest.raises(ValueError, match="已完成"):
            ShipmentService.complete_shipment(shipment_id, CURRENT_USER)


def test_logistics_receive_and_payment_follow_status_rules(client):
    with client.application.app_context():
        db = get_db()
        order_id, order_no, inventory_id = _shipment_context(db)
        shipment_id, _ = ShipmentService.create_shipment(
            _shipment_payload(order_id, order_no, inventory_id), created_by="测试管理员"
        )
        with pytest.raises(ValueError, match="仅已出库"):
            ShipmentService.receive_shipment(shipment_id, CURRENT_USER)
        with pytest.raises(ValueError, match="仅已出库或已签收"):
            ShipmentService.record_payment(shipment_id, CURRENT_USER, 10)

        ShipmentService.update_logistics(
            shipment_id, {"logistics_company": "顺丰", "tracking_no": "SF001"}
        )
        ShipmentService.complete_shipment(shipment_id, CURRENT_USER)
        ShipmentService.record_payment(shipment_id, CURRENT_USER, 40, "bank", "首款")
        ShipmentService.receive_shipment(shipment_id, CURRENT_USER, "张三", "2026-07-20")
        ShipmentService.record_payment(shipment_id, CURRENT_USER, 60, "bank", "尾款")

        shipment = ShipmentService.get_shipment(shipment_id)
        assert shipment["status"] == "received"
        assert shipment["tracking_no"] == "SF001"
        assert shipment["paid_amount"] == 100
        assert shipment["payment_status"] == "paid"
        with pytest.raises(ValueError, match="超出应收"):
            ShipmentService.record_payment(shipment_id, CURRENT_USER, 1)


@pytest.mark.parametrize("action", ["cancel", "delete"])
def test_cancel_or_delete_completed_shipment_restores_stock(client, action):
    with client.application.app_context():
        db = get_db()
        order_id, order_no, inventory_id = _shipment_context(db, quantity=5)
        shipment_id, _ = ShipmentService.create_shipment(
            _shipment_payload(order_id, order_no, inventory_id, quantity=5),
            created_by="测试管理员",
        )
        ShipmentService.complete_shipment(shipment_id, CURRENT_USER)

        if action == "cancel":
            ShipmentService.cancel_shipment(shipment_id, CURRENT_USER)
            assert ShipmentService.get_shipment(shipment_id)["status"] == "cancelled"
        else:
            ShipmentService.delete_shipment(shipment_id, CURRENT_USER)
            assert ShipmentService.get_shipment(shipment_id) is None
        stock = db.execute(
            "SELECT quantity FROM inventory WHERE id = ?", (inventory_id,)
        ).fetchone()["quantity"]
        assert stock == 5
