"""Atomic inventory posting and reservation operations."""
from contextlib import nullcontext
from uuid import uuid4

from modules.domain.errors import ConflictError, NotFoundError
from modules.repositories.inventory_repository import InventoryRepository
from modules.services import BaseService


class InventoryPostingService:
    """The only service allowed to change finished-goods stock balances."""

    @staticmethod
    def _scope(db):
        return nullcontext(db) if db is not None else BaseService.transaction()

    @staticmethod
    def _movement_no():
        return "IM-" + uuid4().hex.upper()

    @staticmethod
    def _existing(idempotency_key, db):
        if not idempotency_key:
            return None
        row = InventoryRepository.find_log_by_idempotency_key(idempotency_key, db=db)
        return dict(row) if row else None

    @classmethod
    def post(
        cls,
        inventory_id,
        qty_delta,
        movement_type,
        *,
        order_id=None,
        order_no="",
        remark="",
        operator_id=None,
        operator_name="",
        lot_no="",
        serial_no="",
        source_type="manual",
        source_id=None,
        idempotency_key="",
        reversal_of_id=None,
        consume_reserved=False,
        db=None,
    ):
        """Post one signed stock movement and its balance snapshot atomically."""
        try:
            qty_delta = float(qty_delta)
        except (TypeError, ValueError):
            raise ValueError("库存变动数量必须为数字")
        if qty_delta == 0:
            raise ValueError("库存变动数量不能为零")
        lot_no = (lot_no or "").strip()
        serial_no = (serial_no or "").strip()
        if serial_no and abs(qty_delta) != 1:
            raise ValueError("序列号库存每次只能变动 1 件")

        with cls._scope(db) as txn:
            existing = cls._existing(idempotency_key, txn)
            if existing:
                if (
                    existing["inventory_id"] != inventory_id
                    or float(existing["qty_delta"] or 0) != qty_delta
                    or existing["type"] != movement_type
                ):
                    raise ConflictError("幂等键已用于其他库存变动")
                return existing

            item = InventoryRepository.find_item_by_id(inventory_id, db=txn)
            if not item:
                raise NotFoundError("库存不存在")
            before = float(item["quantity"] or 0)
            quantity = abs(qty_delta)

            if qty_delta > 0 and serial_no:
                inbound = InventoryRepository.find_serial_inbound(serial_no, db=txn)
                if inbound:
                    raise ConflictError("序列号已入库")
            if qty_delta < 0 and serial_no:
                inbound = InventoryRepository.find_serial_inbound(serial_no, db=txn)
                serial_balance = InventoryRepository.get_serial_balance(
                    inventory_id, serial_no, db=txn
                )
                if not inbound or inbound["inventory_id"] != inventory_id or serial_balance < quantity:
                    raise ConflictError("序列号不在库或已出库")
                inbound_lot = inbound["lot_no"] or ""
                if lot_no and inbound_lot and lot_no != inbound_lot:
                    raise ConflictError("序列号与批次不匹配")
                if not lot_no:
                    lot_no = inbound_lot
            if qty_delta < 0 and lot_no:
                lot_balance = InventoryRepository.get_lot_balance(
                    inventory_id, lot_no, db=txn
                )
                if lot_balance < quantity:
                    raise ConflictError("批次库存不足（当前 %s）" % lot_balance)

            if qty_delta > 0:
                cursor = InventoryRepository.increase_stock_txn(inventory_id, quantity, txn)
            elif consume_reserved:
                cursor = InventoryRepository.consume_stock_txn(
                    inventory_id, quantity, quantity, txn
                )
            else:
                cursor = InventoryRepository.decrease_stock_if_available_txn(
                    inventory_id, quantity, txn
                )

            if cursor.rowcount != 1:
                latest = InventoryRepository.find_item_by_id(inventory_id, db=txn)
                if not latest:
                    raise NotFoundError("库存不存在")
                available = float(latest["quantity"] or 0) - float(latest["reserved"] or 0)
                if consume_reserved:
                    raise ConflictError("库存或预留数量不足")
                raise ConflictError("可用库存不足（当前可用 %s）" % available)

            after_row = InventoryRepository.get_item_quantity(inventory_id, db=txn)
            after = float(after_row["quantity"])
            movement_no = cls._movement_no()
            movement_id = InventoryRepository.insert_movement_log_txn(
                inventory_id=inventory_id,
                log_type=movement_type,
                quantity=quantity,
                order_id=order_id,
                order_no=order_no,
                remark=remark,
                operator_id=operator_id,
                operator_name=operator_name,
                qty_delta=qty_delta,
                balance_before=before,
                balance_after=after,
                lot_no=lot_no,
                serial_no=serial_no,
                source_type=source_type,
                source_id=source_id,
                idempotency_key=(idempotency_key or "").strip(),
                movement_no=movement_no,
                reversal_of_id=reversal_of_id,
                db=txn,
            )
            return {
                "id": movement_id,
                "movement_no": movement_no,
                "inventory_id": inventory_id,
                "qty_delta": qty_delta,
                "balance_before": before,
                "balance_after": after,
            }

    @classmethod
    def reserve(
        cls,
        inventory_id,
        quantity,
        *,
        operator_id=None,
        operator_name="",
        source_type="shipment",
        source_id=None,
        idempotency_key="",
        remark="",
        db=None,
    ):
        return cls._change_reservation(
            inventory_id,
            quantity,
            release=False,
            operator_id=operator_id,
            operator_name=operator_name,
            source_type=source_type,
            source_id=source_id,
            idempotency_key=idempotency_key,
            remark=remark,
            db=db,
        )

    @classmethod
    def release(
        cls,
        inventory_id,
        quantity,
        *,
        operator_id=None,
        operator_name="",
        source_type="shipment",
        source_id=None,
        idempotency_key="",
        remark="",
        db=None,
    ):
        return cls._change_reservation(
            inventory_id,
            quantity,
            release=True,
            operator_id=operator_id,
            operator_name=operator_name,
            source_type=source_type,
            source_id=source_id,
            idempotency_key=idempotency_key,
            remark=remark,
            db=db,
        )

    @classmethod
    def _change_reservation(
        cls,
        inventory_id,
        quantity,
        *,
        release,
        operator_id,
        operator_name,
        source_type,
        source_id,
        idempotency_key,
        remark,
        db,
    ):
        try:
            quantity = float(quantity)
        except (TypeError, ValueError):
            raise ValueError("预留数量必须为数字")
        if quantity <= 0:
            raise ValueError("预留数量必须大于零")

        with cls._scope(db) as txn:
            existing = cls._existing(idempotency_key, txn)
            if existing:
                expected_type = "release" if release else "reserve"
                if (
                    existing["inventory_id"] != inventory_id
                    or float(existing["quantity"] or 0) != quantity
                    or existing["type"] != expected_type
                ):
                    raise ConflictError("幂等键已用于其他预留操作")
                return existing
            item = InventoryRepository.find_item_by_id(inventory_id, db=txn)
            if not item:
                raise NotFoundError("库存不存在")
            before = float(item["quantity"] or 0)
            if release:
                cursor = InventoryRepository.release_reserved_stock_txn(
                    inventory_id, quantity, txn
                )
                movement_type = "release"
                failure = "预留库存不足"
            else:
                cursor = InventoryRepository.reserve_stock_txn(inventory_id, quantity, txn)
                movement_type = "reserve"
                failure = "可用库存不足"
            if cursor.rowcount != 1:
                raise ConflictError(failure)

            movement_id = InventoryRepository.insert_movement_log_txn(
                inventory_id=inventory_id,
                log_type=movement_type,
                quantity=quantity,
                remark=remark,
                operator_id=operator_id,
                operator_name=operator_name,
                qty_delta=0,
                balance_before=before,
                balance_after=before,
                source_type=source_type,
                source_id=source_id,
                idempotency_key=(idempotency_key or "").strip(),
                movement_no=cls._movement_no(),
                db=txn,
            )
            return {
                "id": movement_id,
                "inventory_id": inventory_id,
                "quantity": quantity,
                "type": movement_type,
                "balance_before": before,
                "balance_after": before,
            }
