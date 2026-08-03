"""Shipment lifecycle, inventory posting, and receivables service."""

import json
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO
from uuid import uuid4

from modules.domain.errors import ConflictError, NotFoundError, ValidationError
from modules.export_utils import CELL_ALIGN, THIN_BORDER, auto_width, style_header
from modules.repositories.inventory_repository import InventoryRepository
from modules.repositories.order_repository import OrderRepository
from modules.repositories.shipment_repository import ShipmentRepository
from modules.services import BaseService
from modules.services.inventory_posting_service import InventoryPostingService
from modules.setting_reader import get_setting
from modules.shipment_config import (
    DEFAULT_SHIPMENT_NO_PREFIX,
    SHIPMENT_NO_PREFIX_KEY,
    normalize_shipment_no_prefix,
)


MONEY_QUANTUM = Decimal("0.01")
ACTIVE_SHIPMENT_STATUSES = ("completed", "received")


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _generate_shipment_no(db, prefix=None):
    if prefix is None:
        prefix = get_setting(SHIPMENT_NO_PREFIX_KEY, DEFAULT_SHIPMENT_NO_PREFIX)
    prefix = normalize_shipment_no_prefix(prefix)
    today = datetime.now().strftime("%Y%m%d")
    prefix_len = len(prefix) + 10
    row = ShipmentRepository.max_seq_for_date(prefix, today, prefix_len, db=db)
    seq = (row["max_seq"] if row and row["max_seq"] else 0) + 1
    return prefix + today + "-" + str(seq).zfill(3)


def _operator(current_user):
    if isinstance(current_user, dict):
        return current_user.get("id"), (current_user.get("name") or "").strip()
    return None, str(current_user or "").strip()


def _decimal(value, label, *, positive=False, nonnegative=False):
    try:
        result = Decimal(str(value)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError(label + "必须为数字")
    if not result.is_finite():
        raise ValidationError(label + "必须为有限数字")
    if positive and result <= 0:
        raise ValidationError(label + "必须大于零")
    if nonnegative and result < 0:
        raise ValidationError(label + "不能小于零")
    return result


def _payment_date(value):
    text = (value or datetime.now().strftime("%Y-%m-%d")).strip()
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        raise ValidationError("收付款日期格式必须为 YYYY-MM-DD")
    return text


class ShipmentService:
    @staticmethod
    def _event(
        txn, shipment_id, event_type, from_status, to_status, current_user,
        payload=None, idempotency_key="",
    ):
        operator_id, operator_name = _operator(current_user)
        return ShipmentRepository.insert_event_txn(
            "SE-" + uuid4().hex.upper(), shipment_id, event_type,
            from_status or "", to_status or "",
            json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":")),
            operator_id, operator_name, idempotency_key, db=txn,
        )

    @staticmethod
    def generate_no():
        return _generate_shipment_no(BaseService.db())

    @staticmethod
    def list_shipments(
        keyword="", status="", page=1, limit=20,
        sort_by="created_at", sort_dir="desc",
    ):
        rows, total, size = ShipmentRepository.list_shipments(
            keyword=keyword, status=status, page=page, limit=limit,
            sort_by=sort_by, sort_dir=sort_dir,
        )
        summary = dict(ShipmentRepository.fetch_list_summary(keyword, status))
        summary["unpaid_total"] = round(
            float(summary["receivable_total"] or 0) - float(summary["paid_total"] or 0), 2
        )
        return {
            "shipments": [dict(row) for row in rows],
            "total": total,
            "page": page,
            "limit": size,
            "summary": summary,
            **summary,
        }

    @staticmethod
    def create_shipment(data, created_by, allow_unlinked=False):
        items = data.get("items", [])
        if not items:
            raise ValidationError("请添加出库产品")
        operator_id, operator_name = _operator(created_by)
        deduction_mode = data.get("deduction_mode") or "on_complete"
        if deduction_mode not in ("on_complete", "on_create"):
            raise ValidationError("库存扣减方式无效")
        receivable = _decimal(
            data.get("receivable_amount", 0), "应收金额", nonnegative=True
        )

        with BaseService.transaction() as txn:
            shipment_no = (data.get("shipment_no") or "").strip() or _generate_shipment_no(txn)
            canonical_items = []
            required_by_inventory = {}
            inventory_cache = {}
            order_cache = {}
            total_qty = Decimal("0")

            for raw_item in items:
                try:
                    inventory_id = int(raw_item.get("inventory_id"))
                except (TypeError, ValueError):
                    raise ValidationError("请选择有效库存记录")
                quantity = _decimal(raw_item.get("quantity", 0), "出库数量", positive=True)
                inventory = inventory_cache.get(inventory_id)
                if inventory is None:
                    inventory = InventoryRepository.find_item_by_id(inventory_id, db=txn)
                    if not inventory:
                        raise NotFoundError("库存记录不存在 (ID:" + str(inventory_id) + ")")
                    inventory_cache[inventory_id] = inventory
                quality_status = (
                    inventory["quality_status"] if "quality_status" in inventory.keys() else "released"
                ) or "released"
                if quality_status != "released":
                    raise ConflictError(
                        inventory["product_model"] + " " + inventory["product_name"]
                        + ": 库存处于质量隔离状态，不能创建出库单"
                    )

                order_id = inventory["order_id"] if "order_id" in inventory.keys() else None
                order = None
                if order_id:
                    if order_id not in order_cache:
                        order_cache[order_id] = OrderRepository.find_by_id(order_id, db=txn)
                    order = order_cache[order_id]
                if (not order_id or not order) and not allow_unlinked:
                    raise ConflictError(
                        inventory["product_model"] + " " + inventory["product_name"]
                        + ": 库存未关联有效订单，需要“无订单发货”权限"
                    )

                required_by_inventory[inventory_id] = (
                    required_by_inventory.get(inventory_id, Decimal("0")) + quantity
                )
                total_qty += quantity
                canonical_items.append({
                    "inventory": inventory,
                    "inventory_id": inventory_id,
                    "quantity": quantity,
                    "order_id": order_id if order else None,
                    "order_no": order["order_no"] if order else "",
                    "remark": (raw_item.get("remark") or "").strip(),
                })

            for inventory_id, required in required_by_inventory.items():
                inventory = inventory_cache[inventory_id]
                available = Decimal(str(inventory["quantity"] or 0)) - Decimal(
                    str(inventory["reserved"] or 0)
                )
                if available < required:
                    raise ConflictError(
                        inventory["product_model"] + " " + inventory["product_name"]
                        + ": 可用库存不足 (当前" + str(available)
                        + "，需要" + str(required) + ")"
                    )

            try:
                shipment_id = ShipmentRepository.insert_shipment_txn(
                    shipment_no, data.get("customer", ""), data.get("contact_person", ""),
                    data.get("contact_phone", ""), data.get("address", ""), float(total_qty),
                    data.get("remark", ""), operator_id, operator_name, deduction_mode,
                    data.get("material_bill_no", ""), float(receivable), db=txn,
                )
            except Exception as exc:
                if "UNIQUE" in str(exc).upper():
                    raise ConflictError("出库单号已存在，请重新生成")
                raise

            inserted_items = []
            for item in canonical_items:
                inventory = item["inventory"]
                shipment_item_id = ShipmentRepository.insert_shipment_item_txn(
                    shipment_id, item["inventory_id"], inventory["product_model"],
                    inventory["product_name"], float(item["quantity"]), inventory["unit"] or "件",
                    item["remark"], item["order_id"], inventory["product_model"],
                    item["order_no"], db=txn,
                )
                inserted_items.append((shipment_item_id, item))

            if deduction_mode == "on_create":
                for shipment_item_id, item in inserted_items:
                    InventoryPostingService.reserve(
                        item["inventory_id"], float(item["quantity"]),
                        operator_id=operator_id, operator_name=operator_name,
                        source_type="shipment", source_id=shipment_item_id,
                        idempotency_key=f"shipment:{shipment_id}:item:{shipment_item_id}:reserve",
                        remark="出库单 %s 预留库存" % shipment_no, db=txn,
                    )
                ShipmentRepository.mark_reserved_txn(shipment_id, db=txn)

            ShipmentService._event(
                txn, shipment_id, "created", "", "pending", created_by,
                {
                    "shipment_no": shipment_no,
                    "item_count": len(inserted_items),
                    "total_quantity": str(total_qty),
                    "deduction_mode": deduction_mode,
                },
                f"shipment:{shipment_id}:created",
            )
            from modules.services.quality_management_service import QualityManagementService
            QualityManagementService.generate_for_shipment(shipment_id, operator_name, txn)
            return shipment_id, shipment_no

    @staticmethod
    def get_shipment(shipment_id):
        row = ShipmentRepository.find_shipment_by_id(shipment_id)
        if not row:
            return None
        shipment = dict(row)
        shipment["items"] = [
            dict(item) for item in ShipmentRepository.find_shipment_items(shipment_id)
        ]
        shipment["events"] = ShipmentService.get_events(shipment_id)
        shipment["payments"] = ShipmentService.get_payments(shipment_id)
        return shipment

    @staticmethod
    def get_events(shipment_id):
        if not ShipmentRepository.shipment_exists(shipment_id):
            raise NotFoundError("出库单不存在")
        events = []
        for row in ShipmentRepository.find_events(shipment_id):
            item = dict(row)
            try:
                item["payload"] = json.loads(item.get("payload") or "{}")
            except (TypeError, json.JSONDecodeError):
                item["payload"] = {}
            events.append(item)
        return events

    @staticmethod
    def get_payments(shipment_id):
        if not ShipmentRepository.shipment_exists(shipment_id):
            raise NotFoundError("出库单不存在")
        return [dict(row) for row in ShipmentRepository.find_payments(shipment_id)]

    @staticmethod
    def update_shipment(shipment_id, data, current_user=None):
        forbidden = {"status", "paid_amount", "payment_status", "payment_date", "payment_method"}
        if forbidden.intersection(data):
            raise ValidationError("状态和收付款信息必须使用专用操作")
        allowed = {
            "customer", "contact_person", "contact_phone", "address", "remark",
            "receivable_amount",
        }
        changes = {field: data[field] for field in allowed if field in data}
        if "receivable_amount" in changes:
            changes["receivable_amount"] = float(
                _decimal(changes["receivable_amount"], "应收金额", nonnegative=True)
            )
        if not changes:
            raise ValidationError("没有需要更新的字段")
        with BaseService.transaction() as txn:
            row = ShipmentRepository.find_shipment_by_id(shipment_id, db=txn)
            if not row:
                raise NotFoundError("出库单不存在")
            if row["status"] != "pending":
                raise ConflictError("只有待出库单可编辑")
            if float(changes.get("receivable_amount", row["receivable_amount"] or 0)) < float(
                row["paid_amount"] or 0
            ):
                raise ConflictError("应收金额不能小于已收金额")
            if ShipmentRepository.update_shipment_fields_txn(
                shipment_id, changes, row["version"], db=txn
            ) != 1:
                raise ConflictError("出库单已被其他操作更新，请刷新后重试")
            ShipmentService._event(
                txn, shipment_id, "updated", "pending", "pending", current_user,
                {"changes": changes},
            )

    @staticmethod
    def complete_shipment(shipment_id, current_user):
        operator_id, operator_name = _operator(current_user)
        with BaseService.transaction() as txn:
            row = ShipmentRepository.find_shipment_by_id(shipment_id, db=txn)
            if not row:
                raise NotFoundError("出库单不存在")
            if row["status"] != "pending":
                raise ConflictError("只有待出库单可完成出库")
            items = ShipmentRepository.find_shipment_items(shipment_id, db=txn)
            if not items:
                raise ConflictError("出库单无明细")

            from modules.services.quality_management_service import QualityManagementService
            QualityManagementService.assert_shipment_allowed(shipment_id, db=txn)
            for item in items:
                item_order_no = item["order_no"] or row["shipment_no"]
                InventoryPostingService.post(
                    item["inventory_id"], -float(item["quantity"]), "out",
                    order_id=item["order_id"], order_no=item_order_no,
                    remark="出库单 %s 出库 %s %s" % (
                        row["shipment_no"], item["quantity"], item["unit"] or "件"
                    ),
                    operator_id=operator_id, operator_name=operator_name,
                    source_type="shipment", source_id=item["id"],
                    idempotency_key=f"shipment:{shipment_id}:item:{item['id']}:out",
                    consume_reserved=bool(row["reserved_at"]), db=txn,
                )
            completed_at = _now()
            if ShipmentRepository.transition_status_txn(
                shipment_id, ("pending",), "completed", row["version"],
                {
                    "completed_at": completed_at,
                    "completed_by_id": operator_id,
                    "completed_by_name": operator_name,
                }, db=txn,
            ) != 1:
                raise ConflictError("出库单已被其他操作更新，请刷新后重试")
            ShipmentService._event(
                txn, shipment_id, "completed", "pending", "completed", current_user,
                {"completed_at": completed_at}, f"shipment:{shipment_id}:completed",
            )
            ShipmentService._update_order_delivery_status(txn, shipment_id)
            return row["shipment_no"]

    @staticmethod
    def batch_complete(ids, current_user):
        if not ids:
            raise ValidationError("请选择出库单")
        results = {"success": [], "failed": []}
        for shipment_id in ids:
            try:
                shipment_no = ShipmentService.complete_shipment(shipment_id, current_user)
                results["success"].append({"id": shipment_id, "shipment_no": shipment_no})
            except ValueError as exc:
                results["failed"].append({"id": shipment_id, "error": str(exc)})
        return results

    @staticmethod
    def update_logistics(shipment_id, data, current_user=None):
        logistics_company = (data.get("logistics_company") or "").strip()
        tracking_no = (data.get("tracking_no") or "").strip()
        with BaseService.transaction() as txn:
            row = ShipmentRepository.find_shipment_by_id(shipment_id, db=txn)
            if not row:
                raise NotFoundError("出库单不存在")
            if row["status"] not in ("pending", "completed"):
                raise ConflictError("当前状态不可修改物流信息")
            if ShipmentRepository.update_logistics_txn(
                shipment_id, logistics_company, tracking_no, row["version"], db=txn
            ) != 1:
                raise ConflictError("出库单已被其他操作更新，请刷新后重试")
            ShipmentService._event(
                txn, shipment_id, "logistics_updated", row["status"], row["status"],
                current_user,
                {
                    "before": {
                        "logistics_company": row["logistics_company"],
                        "tracking_no": row["tracking_no"],
                    },
                    "after": {
                        "logistics_company": logistics_company,
                        "tracking_no": tracking_no,
                    },
                },
            )

    @staticmethod
    def receive_shipment(shipment_id, current_user, receiver="", receive_date=""):
        operator_id, operator_name = _operator(current_user)
        receive_date = _payment_date(receive_date)
        receiver = (receiver or "").strip()
        with BaseService.transaction() as txn:
            row = ShipmentRepository.find_shipment_by_id(shipment_id, db=txn)
            if not row:
                raise NotFoundError("出库单不存在")
            if row["status"] != "completed":
                raise ConflictError("只有已出库单可签收")
            received_at = _now()
            if ShipmentRepository.transition_status_txn(
                shipment_id, ("completed",), "received", row["version"],
                {
                    "received_at": received_at,
                    "received_by_id": operator_id,
                    "received_by_name": operator_name,
                    "receiver_name": receiver,
                    "receive_date": receive_date,
                }, db=txn,
            ) != 1:
                raise ConflictError("出库单已被其他操作更新，请刷新后重试")
            ShipmentService._event(
                txn, shipment_id, "received", "completed", "received", current_user,
                {"receiver": receiver, "receive_date": receive_date},
                f"shipment:{shipment_id}:received",
            )
            return row["shipment_no"]

    @staticmethod
    def _post_payment(
        shipment_id, current_user, payment_type, amount, method, remark,
        payment_date, idempotency_key,
    ):
        amount = _decimal(amount, "收付款金额", positive=True)
        payment_date = _payment_date(payment_date)
        method = (method or "").strip()
        remark = (remark or "").strip()
        idempotency_key = (idempotency_key or "").strip()
        if not idempotency_key:
            raise ValidationError("缺少收付款幂等键")
        operator_id, operator_name = _operator(current_user)

        with BaseService.transaction() as txn:
            row = ShipmentRepository.find_shipment_by_id(shipment_id, db=txn)
            if not row:
                raise NotFoundError("出库单不存在")
            if row["status"] not in ACTIVE_SHIPMENT_STATUSES:
                raise ConflictError("只有已出库或已签收单可收退款")
            existing = ShipmentRepository.find_payment_by_idempotency_key(
                idempotency_key, db=txn
            )
            if existing:
                if (
                    existing["shipment_id"] != shipment_id
                    or existing["type"] != payment_type
                    or _decimal(existing["amount"], "收付款金额") != amount
                ):
                    raise ConflictError("幂等键已用于其他收付款")
                return row["shipment_no"]

            paid = _decimal(row["paid_amount"] or 0, "已收金额")
            receivable = _decimal(row["receivable_amount"] or 0, "应收金额")
            if payment_type == "receipt" and paid + amount > receivable:
                raise ConflictError("收款金额超出应收(" + str(receivable) + ")")
            if payment_type == "refund" and amount > paid:
                raise ConflictError("退款金额超出已收(" + str(paid) + ")")

            payment_no = "PAY-" + uuid4().hex.upper()
            payment_id = ShipmentRepository.insert_payment_txn(
                payment_no, shipment_id, payment_type, float(amount), payment_date,
                method, remark, operator_id, operator_name, idempotency_key, None, db=txn,
            )
            event_type = "payment_received" if payment_type == "receipt" else "payment_refunded"
            ShipmentService._event(
                txn, shipment_id, event_type, row["status"], row["status"], current_user,
                {
                    "payment_id": payment_id,
                    "payment_no": payment_no,
                    "amount": str(amount),
                    "payment_date": payment_date,
                    "method": method,
                    "remark": remark,
                },
                idempotency_key + ":event",
            )
            return row["shipment_no"]

    @staticmethod
    def record_payment(
        shipment_id, current_user, amount, method="", remark="", payment_date="",
        idempotency_key="",
    ):
        return ShipmentService._post_payment(
            shipment_id, current_user, "receipt", amount, method, remark,
            payment_date, idempotency_key,
        )

    @staticmethod
    def refund_payment(
        shipment_id, current_user, amount, method="", remark="", payment_date="",
        idempotency_key="",
    ):
        return ShipmentService._post_payment(
            shipment_id, current_user, "refund", amount, method, remark,
            payment_date, idempotency_key,
        )

    @staticmethod
    def reverse_payment(shipment_id, payment_id, current_user, idempotency_key=""):
        idempotency_key = (idempotency_key or "").strip()
        if not idempotency_key:
            raise ValidationError("缺少收付款幂等键")
        operator_id, operator_name = _operator(current_user)
        with BaseService.transaction() as txn:
            shipment = ShipmentRepository.find_shipment_by_id(shipment_id, db=txn)
            if not shipment:
                raise NotFoundError("出库单不存在")
            existing = ShipmentRepository.find_payment_by_idempotency_key(
                idempotency_key, db=txn
            )
            if existing:
                if existing["shipment_id"] != shipment_id or existing["type"] != "reversal":
                    raise ConflictError("幂等键已用于其他收付款")
                return shipment["shipment_no"]
            payment = ShipmentRepository.find_payment_by_id(payment_id, db=txn)
            if not payment or payment["shipment_id"] != shipment_id:
                raise NotFoundError("收付款流水不存在")
            if payment["type"] == "reversal":
                raise ConflictError("不能再次冲销冲销流水")
            amount = _decimal(payment["amount"], "冲销金额", positive=True)
            paid = _decimal(shipment["paid_amount"] or 0, "已收金额")
            receivable = _decimal(shipment["receivable_amount"] or 0, "应收金额")
            projected = paid - amount if payment["type"] == "receipt" else paid + amount
            if projected < 0 or projected > receivable:
                raise ConflictError("冲销后收款余额超出有效范围")
            payment_no = "PAY-" + uuid4().hex.upper()
            reversal_id = ShipmentRepository.insert_payment_txn(
                payment_no, shipment_id, "reversal", float(amount),
                datetime.now().strftime("%Y-%m-%d"), payment["method"],
                "冲销 " + payment["payment_no"], operator_id, operator_name,
                idempotency_key, payment_id, db=txn,
            )
            ShipmentService._event(
                txn, shipment_id, "payment_reversed", shipment["status"],
                shipment["status"], current_user,
                {
                    "payment_id": reversal_id,
                    "payment_no": payment_no,
                    "reversal_of_id": payment_id,
                    "amount": str(amount),
                }, idempotency_key + ":event",
            )
            return shipment["shipment_no"]

    @staticmethod
    def cancel_shipment(shipment_id, current_user, reason=""):
        reason = (reason or "").strip()
        if not reason:
            raise ValidationError("请填写取消或冲销原因")
        operator_id, operator_name = _operator(current_user)
        with BaseService.transaction() as txn:
            row = ShipmentRepository.find_shipment_by_id(shipment_id, db=txn)
            if not row:
                raise NotFoundError("出库单不存在")
            if row["status"] in ("cancelled", "reversed"):
                raise ConflictError("出库单已处于终态")
            if row["status"] not in ("pending", "completed", "received"):
                raise ConflictError("当前状态不可取消或冲销")
            if row["status"] in ACTIVE_SHIPMENT_STATUSES and float(row["paid_amount"] or 0) > 0:
                raise ConflictError("出库单仍有已收款，请先退款或冲销收款")

            items = ShipmentRepository.find_shipment_items(shipment_id, db=txn)
            from_status = row["status"]
            if from_status == "pending":
                if row["reserved_at"]:
                    for item in items:
                        InventoryPostingService.release(
                            item["inventory_id"], item["quantity"],
                            operator_id=operator_id, operator_name=operator_name,
                            source_type="shipment_cancel", source_id=item["id"],
                            idempotency_key=f"shipment:{shipment_id}:item:{item['id']}:cancel-release",
                            remark="取消出库单 %s 释放预留" % row["shipment_no"], db=txn,
                        )
                to_status = "cancelled"
                fields = {
                    "cancelled_at": _now(),
                    "cancelled_by_id": operator_id,
                    "cancelled_by_name": operator_name,
                    "cancel_reason": reason,
                }
                event_type = "cancelled"
            else:
                for item in items:
                    outbound = InventoryRepository.find_log_by_idempotency_key(
                        f"shipment:{shipment_id}:item:{item['id']}:out", db=txn
                    )
                    InventoryPostingService.post(
                        item["inventory_id"], float(item["quantity"]), "return",
                        order_id=item["order_id"], order_no=item["order_no"] or row["shipment_no"],
                        remark="冲销出库单 " + row["shipment_no"] + " - 归还库存",
                        operator_id=operator_id, operator_name=operator_name,
                        source_type="shipment_reverse", source_id=item["id"],
                        idempotency_key=f"shipment:{shipment_id}:item:{item['id']}:reverse-return",
                        reversal_of_id=outbound["id"] if outbound else None, db=txn,
                    )
                to_status = "reversed"
                fields = {
                    "reversed_at": _now(),
                    "reversed_by_id": operator_id,
                    "reversed_by_name": operator_name,
                    "reverse_reason": reason,
                }
                event_type = "reversed"

            if ShipmentRepository.transition_status_txn(
                shipment_id, (from_status,), to_status, row["version"], fields, db=txn
            ) != 1:
                raise ConflictError("出库单已被其他操作更新，请刷新后重试")
            ShipmentService._event(
                txn, shipment_id, event_type, from_status, to_status, current_user,
                {"reason": reason}, f"shipment:{shipment_id}:{event_type}",
            )
            ShipmentService._update_order_delivery_status(txn, shipment_id)
            return row["shipment_no"]

    @staticmethod
    def delete_shipment(shipment_id, current_user):
        return ShipmentService.cancel_shipment(
            shipment_id, current_user, reason="通过删除兼容入口取消或冲销"
        )

    @staticmethod
    def batch_delete(ids, current_user):
        if not ids:
            raise ValidationError("请选择出库单")
        results = {"success": [], "failed": []}
        for shipment_id in ids:
            try:
                shipment_no = ShipmentService.delete_shipment(shipment_id, current_user)
                results["success"].append({"id": shipment_id, "shipment_no": shipment_no})
            except ValueError as exc:
                results["failed"].append({"id": shipment_id, "error": str(exc)})
        return results

    @staticmethod
    def get_order_stock(order_id):
        order = OrderRepository.find_by_id(order_id)
        if not order:
            raise NotFoundError("订单不存在")
        items = InventoryRepository.list_available_by_order(order_id)
        return {"order": dict(order), "items": [dict(item) for item in items]}

    @staticmethod
    def get_stats():
        today = datetime.now().strftime("%Y-%m-%d")
        month_start = datetime.now().strftime("%Y-%m-01")
        return dict(ShipmentRepository.fetch_shipment_stats(today, month_start))

    @staticmethod
    def get_impact(shipment_id):
        shipment = ShipmentRepository.find_shipment_for_impact(shipment_id)
        if not shipment:
            raise NotFoundError("出库单不存在")
        item_count = ShipmentRepository.count_shipment_items_impact(shipment_id)
        return {
            "shipment": dict(shipment),
            "items": item_count["cnt"] or 0,
            "total_qty": item_count["qty"] or 0,
            "inventory_refs": ShipmentRepository.count_distinct_inventory(shipment_id) or 0,
            "action": "cancel" if shipment["status"] == "pending" else "reverse",
        }

    @staticmethod
    def get_customer_history(customer, limit=50):
        rows = ShipmentRepository.find_shipments_by_customer(customer, limit)
        return [dict(row) for row in rows]

    @staticmethod
    def export_shipments(keyword="", status=""):
        items = [
            dict(row) for row in ShipmentRepository.list_all_shipments(
                keyword=keyword, status=status
            )
        ]
        from openpyxl import Workbook

        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "发货清单"
        headers = [
            "出库单号", "客户", "联系人", "电话", "地址", "状态", "总数量",
            "物流公司", "运单号", "应收金额", "已收金额", "收款状态", "备注",
            "创建时间", "完成时间",
        ]
        style_header(worksheet, headers)
        status_map = {
            "pending": "待出库", "completed": "已出库", "received": "已签收",
            "cancelled": "已取消", "reversed": "已冲销",
        }
        payment_status_map = {"unpaid": "未收款", "partial": "部分收", "paid": "已收清"}
        for row_index, item in enumerate(items, 2):
            values = [
                item.get("shipment_no", ""), item.get("customer", ""),
                item.get("contact_person", ""), item.get("contact_phone", ""),
                item.get("address", ""), status_map.get(item.get("status"), item.get("status", "")),
                item.get("total_quantity", 0), item.get("logistics_company", ""),
                item.get("tracking_no", ""), item.get("receivable_amount", 0),
                item.get("paid_amount", 0), payment_status_map.get(
                    item.get("payment_status"), item.get("payment_status") or "未收款"
                ), item.get("remark", ""), (item.get("created_at") or "")[:19],
                (item.get("completed_at") or "")[:19],
            ]
            for column_index, value in enumerate(values, 1):
                cell = worksheet.cell(row=row_index, column=column_index, value=value)
                cell.border = THIN_BORDER
                cell.alignment = CELL_ALIGN
        auto_width(worksheet)
        output = BytesIO()
        workbook.save(output)
        output.seek(0)
        return output

    @staticmethod
    def _update_order_delivery_status(txn, shipment_id):
        for item in ShipmentRepository.find_order_ids_for_shipment_txn(shipment_id, db=txn):
            order_id = item["order_id"]
            if not order_id:
                continue
            shipped_qty = ShipmentRepository.sum_shipped_qty_txn(order_id, db=txn)
            order = OrderRepository.find_by_id(order_id, db=txn)
            total_qty = order["quantity"] if order else 0
            if not total_qty:
                continue
            if shipped_qty >= total_qty:
                status = "全部发货"
            elif shipped_qty > 0:
                status = "部分发货"
            else:
                status = "pending"
            OrderRepository.update_delivery_status(order_id, status, db=txn)
