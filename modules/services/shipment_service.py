"""qr-system — 出库管理 Service 层（Repository-refactored）"""
from datetime import datetime
from io import BytesIO

from modules.export_utils import auto_width, style_header, CELL_ALIGN, THIN_BORDER
from modules.services import BaseService
from modules.repositories.inventory_repository import InventoryRepository
from modules.repositories.order_repository import OrderRepository
from modules.repositories.shipment_repository import ShipmentRepository
from modules.setting_reader import get_setting
from modules.shipment_config import (
    DEFAULT_SHIPMENT_NO_PREFIX,
    SHIPMENT_NO_PREFIX_KEY,
    normalize_shipment_no_prefix,
)


def _generate_shipment_no(db, prefix=None):
    if prefix is None:
        prefix = get_setting(SHIPMENT_NO_PREFIX_KEY, DEFAULT_SHIPMENT_NO_PREFIX)
    prefix = normalize_shipment_no_prefix(prefix)
    today = datetime.now().strftime("%Y%m%d")
    prefix_len = len(prefix) + 10
    row = ShipmentRepository.max_seq_for_date(prefix, today, prefix_len, db=db)
    seq = (row["max_seq"] if row and row["max_seq"] else 0) + 1
    return prefix + today + "-" + str(seq).zfill(3)


class ShipmentService:

    @staticmethod
    def generate_no():
        db = BaseService.db()
        return _generate_shipment_no(db)

    @staticmethod
    def list_shipments(keyword="", status="", page=1, limit=20, sort_by="created_at", sort_dir="desc"):
        rows, total, size = ShipmentRepository.list_shipments(
            keyword=keyword,
            status=status,
            page=page,
            limit=limit,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
        return {"shipments": [dict(r) for r in rows], "total": total, "page": page, "limit": size}

    @staticmethod
    def create_shipment(data, created_by):
        shipment_no = data.get("shipment_no", "")
        if not shipment_no:
            db = BaseService.db()
            shipment_no = _generate_shipment_no(db)

        items = data.get("items", [])
        if not items:
            raise ValueError("请添加出库产品")

        total_qty = sum(item.get("quantity", 0) for item in items)

        # 库存校验
        for item in items:
            inv = InventoryRepository.find_item_by_id(item.get("inventory_id", 0))
            if not inv:
                raise ValueError("库存记录不存在 (ID:" + str(item.get("inventory_id")) + ")")
            if inv["quantity"] < item.get("quantity", 0):
                raise ValueError(inv["product_model"] + " " + inv["product_name"] + ": 库存不足 (当前" + str(inv["quantity"]) + "，需要" + str(item["quantity"]) + ")")

        with BaseService.transaction() as txn:
            try:
                shipment_id = ShipmentRepository.insert_shipment_txn(
                    shipment_no, data.get("customer", ""), data.get("contact_person", ""),
                    data.get("contact_phone", ""), data.get("address", ""),
                    total_qty, data.get("remark", ""), created_by,
                    data.get("deduction_mode", "on_complete"),
                    data.get("material_bill_no", ""), data.get("receivable_amount", 0),
                    db=txn
                )
            except Exception as e:
                if "UNIQUE" in str(e):
                    raise ValueError("出库单号已存在，请稍后重试")
                raise

            order_id = data.get("order_id") or (items[0].get("order_id") if items else None)
            order_no_val = data.get("order_no", "")
            if order_id and not order_no_val:
                order = OrderRepository.find_by_id(order_id, db=txn)
                order_no_val = order["order_no"] if order else ""

            for item in items:
                item_order_id = item.get("order_id") or order_id
                item_order_no = item.get("order_no") or order_no_val
                if item_order_id and not item_order_no:
                    item_order = OrderRepository.find_by_id(item_order_id, db=txn)
                    item_order_no = item_order["order_no"] if item_order else ""
                product_code = item.get("product_code", "")
                if not product_code:
                    inv_row = InventoryRepository.find_item_by_id(item.get("inventory_id", 0), db=txn)
                    if inv_row:
                        product_code = inv_row["product_model"]
                    else:
                        product_code = item.get("product_model", "")
                ShipmentRepository.insert_shipment_item_txn(
                    shipment_id, item.get("inventory_id", 0),
                    item.get("product_model", ""), item.get("product_name", ""),
                    item.get("quantity", 0), item.get("unit", "件"), item.get("remark", ""),
                    item_order_id, product_code, item_order_no,
                    db=txn
                )

            if data.get("deduction_mode") == "on_create":
                for item in items:
                    InventoryRepository.reserve_stock_txn(
                        item.get("inventory_id", 0), item.get("quantity", 0), db=txn
                    )
                ShipmentRepository.mark_reserved_txn(shipment_id, db=txn)

            return shipment_id, shipment_no

    @staticmethod
    def get_shipment(shipment_id):
        row = ShipmentRepository.find_shipment_by_id(shipment_id)
        if not row:
            return None
        items = ShipmentRepository.find_shipment_items(shipment_id)
        shipment = dict(row)
        shipment["items"] = [dict(r) for r in items]
        return shipment

    @staticmethod
    def update_shipment(shipment_id, data):
        row = ShipmentRepository.find_shipment_by_id(shipment_id)
        if not row:
            raise ValueError("出库单不存在")
        fields = {
            "customer", "contact_person", "contact_phone", "address", "remark",
            "status", "receivable_amount", "payment_status",
        }
        changes = {}
        for field in fields:
            if field in data:
                if field == "status" and data[field] == "completed" and row["status"] != "completed":
                    raise ValueError("请使用「完成出库」按钮完成出库")
                changes[field] = data[field]
        if not changes:
            raise ValueError("没有需要更新的字段")
        with BaseService.transaction() as txn:
            ShipmentRepository.update_shipment_fields_txn(shipment_id, changes, db=txn)

    @staticmethod
    def delete_shipment(shipment_id, current_user):
        row = ShipmentRepository.find_shipment_by_id(shipment_id)
        if not row:
            raise ValueError("出库单不存在")
        with BaseService.transaction() as txn:
            if row["status"] == "completed":
                items = ShipmentRepository.find_shipment_items_for_delete_txn(shipment_id, db=txn)
                for item in items:
                    InventoryRepository.increase_stock_txn(item["inventory_id"], item["quantity"], db=txn)
                    remark = "删除出库单 " + row["shipment_no"] + " - 归还库存"
                    InventoryRepository.insert_movement_log_txn(
                        item["inventory_id"], "in", item["quantity"],
                        order_id=item["order_id"], order_no=row["shipment_no"], remark=remark,
                        operator_id=current_user["id"], operator_name=current_user["name"], db=txn,
                    )
            ShipmentRepository.delete_shipment_items_txn(shipment_id, db=txn)
            ShipmentRepository.delete_shipment_txn(shipment_id, db=txn)
        return row["shipment_no"]

    @staticmethod
    def complete_shipment(shipment_id, current_user):
        row = ShipmentRepository.find_shipment_by_id(shipment_id)
        if not row:
            raise ValueError("出库单不存在")
        if row["status"] == "completed":
            raise ValueError("出库单已完成")
        items = ShipmentRepository.shipment_items_exist(shipment_id)
        if not items:
            raise ValueError("出库单无明细")

        sn = row["shipment_no"]
        with BaseService.transaction() as txn:
            if row["reserved_at"]:
                for item in items:
                    InventoryRepository.release_reserved_stock_txn(
                        item["inventory_id"], item["quantity"], db=txn
                    )
            for item in items:
                cur = InventoryRepository.decrease_stock_if_available_txn(
                    item["inventory_id"], item["quantity"], db=txn
                )
                if cur.rowcount == 0:
                    inv = InventoryRepository.find_item_by_id(item["inventory_id"], db=txn)
                    current = inv["quantity"] if inv else 0
                    model = inv["product_model"] if inv else (item["product_model"] or "?")
                    raise ValueError(model + " " + (item["product_name"] or "") + ": 库存不足 (库存" + str(current) + "，需" + str(item["quantity"]) + ")")
                item_order_no = item["order_no"] if item["order_no"] else sn
                remark = "出库单 " + sn + " 出库 " + str(item["quantity"]) + " " + (item["unit"] or "件")
                InventoryRepository.insert_movement_log_txn(
                    item["inventory_id"], "out", item["quantity"],
                    order_id=item["order_id"], order_no=item_order_no, remark=remark,
                    operator_id=current_user["id"], operator_name=current_user["name"], db=txn,
                )
            ShipmentRepository.complete_shipment_txn(shipment_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), db=txn)
            ShipmentService._update_order_delivery_status(txn, shipment_id)
        return sn

    @staticmethod
    def batch_complete(ids, current_user):
        if not ids:
            raise ValueError("请选择出库单")
        results = {"success": [], "failed": []}
        for sid in ids:
            try:
                sn = ShipmentService.complete_shipment(sid, current_user)
                results["success"].append({"id": sid, "shipment_no": sn})
            except ValueError as e:
                results["failed"].append({"id": sid, "error": str(e)})
        return results

    @staticmethod
    def batch_delete(ids, current_user):
        if not ids:
            raise ValueError("请选择出库单")
        results = {"success": [], "failed": []}
        for sid in ids:
            try:
                sn = ShipmentService.delete_shipment(sid, current_user)
                results["success"].append({"id": sid, "shipment_no": sn})
            except ValueError as e:
                results["failed"].append({"id": sid, "error": str(e)})
        return results

    @staticmethod
    def update_logistics(shipment_id, data):
        row = ShipmentRepository.shipment_exists(shipment_id)
        if not row:
            raise ValueError("出库单不存在")
        with BaseService.transaction() as txn:
            ShipmentRepository.update_logistics_txn(
                shipment_id, data.get("logistics_company", ""), data.get("tracking_no", ""), db=txn
            )

    @staticmethod
    def receive_shipment(shipment_id, current_user, receiver="", receive_date=""):
        row = ShipmentRepository.find_shipment_by_id(shipment_id)
        if not row:
            raise ValueError("出库单不存在")
        if row["status"] == "received":
            raise ValueError("已签收")
        if row["status"] != "completed":
            raise ValueError("仅已出库可签收")
        remark_append = (" 签收人: " + receiver + " 签收日期: " + receive_date) if receiver else ""
        with BaseService.transaction() as txn:
            ShipmentRepository.receive_shipment_txn(shipment_id, remark_append, db=txn)
        return row["shipment_no"]

    @staticmethod
    def record_payment(shipment_id, current_user, amount, method="", remark=""):
        row = ShipmentRepository.find_shipment_by_id(shipment_id)
        if not row:
            raise ValueError("出库单不存在")
        if row["status"] not in ("completed", "received"):
            raise ValueError("仅已出库或已签收可收款")
        new_paid = (row["paid_amount"] or 0) + amount
        receivable = row["receivable_amount"] or 0
        if new_paid > receivable:
            raise ValueError("收款金额超出应收(" + str(receivable) + ")")
        payment_status = "paid" if new_paid >= receivable else "partial"
        with BaseService.transaction() as txn:
            ShipmentRepository.record_payment_txn(
                shipment_id, new_paid, payment_status,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"), method, remark, db=txn
            )
        return row["shipment_no"]

    @staticmethod
    def cancel_shipment(shipment_id, current_user):
        row = ShipmentRepository.find_shipment_by_id(shipment_id)
        if not row:
            raise ValueError("出库单不存在")
        if row["status"] == "cancelled":
            raise ValueError("出库单已取消")
        with BaseService.transaction() as txn:
            if row["reserved_at"]:
                items_rel = ShipmentRepository.release_reserved_for_shipment_txn(shipment_id, db=txn)
                for item in items_rel:
                    InventoryRepository.release_reserved_stock_txn(
                        item["inventory_id"], item["quantity"], db=txn
                    )
            if row["status"] == "completed":
                items = ShipmentRepository.find_shipment_items_for_delete_txn(shipment_id, db=txn)
                for item in items:
                    InventoryRepository.increase_stock_txn(item["inventory_id"], item["quantity"], db=txn)
                    InventoryRepository.insert_movement_log_txn(
                        item["inventory_id"], "in", item["quantity"],
                        order_id=item["order_id"], order_no=row["shipment_no"],
                        remark="取消出库单 " + row["shipment_no"] + " - 归还库存",
                        operator_id=current_user["id"], operator_name=current_user["name"], db=txn,
                    )
            ShipmentRepository.cancel_shipment_txn(shipment_id, db=txn)
        return row["shipment_no"]

    @staticmethod
    def get_order_stock(order_id):
        order = OrderRepository.find_by_id(order_id)
        if not order:
            raise ValueError("订单不存在")
        items = InventoryRepository.list_available_by_order(order_id)
        return {"order": dict(order), "items": [dict(it) for it in items]}

    @staticmethod
    def get_stats():
        today = datetime.now().strftime("%Y-%m-%d")
        month_start = datetime.now().strftime("%Y-%m-01")
        stats = ShipmentRepository.fetch_shipment_stats(today, month_start)
        return dict(stats)

    @staticmethod
    def get_impact(shipment_id):
        s = ShipmentRepository.find_shipment_for_impact(shipment_id)
        if not s:
            raise ValueError("shipment not found")
        item_count = ShipmentRepository.count_shipment_items_impact(shipment_id)
        inv_count = ShipmentRepository.count_distinct_inventory(shipment_id)
        return {
            "shipment": dict(s),
            "items": item_count["cnt"] or 0,
            "total_qty": item_count["qty"] or 0,
            "inventory_refs": inv_count or 0
        }

    @staticmethod
    def get_customer_history(customer, limit=50):
        rows = ShipmentRepository.find_shipments_by_customer(customer, limit)
        return [dict(r) for r in rows]

    @staticmethod
    def export_shipments(keyword="", status=""):
        result = ShipmentService.list_shipments(keyword=keyword, status=status, page=1, limit=99999)
        items = result.get("shipments", [])
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "发货清单"
        headers = [
            "出库单号", "客户", "联系人", "电话", "地址", "状态", "总数量",
            "物流公司", "运单号", "应收金额", "已收金额", "收款状态", "备注", "创建时间", "完成时间"
        ]
        style_header(ws, headers)
        status_map = {"pending": "待出库", "partial": "部分出库", "completed": "已出库", "cancelled": "已取消"}
        payment_status_map = {"unpaid": "未收款", "partial": "部分收", "paid": "已收清"}
        for row_idx, item in enumerate(items, 2):
            values = [
                item.get("shipment_no", ""),
                item.get("customer", ""),
                item.get("contact_person", ""),
                item.get("contact_phone", ""),
                item.get("address", ""),
                status_map.get(item.get("status", ""), item.get("status", "")),
                item.get("total_quantity", 0),
                item.get("logistics_company", ""),
                item.get("tracking_no", ""),
                item.get("receivable_amount", 0),
                item.get("paid_amount", 0),
                payment_status_map.get(item.get("payment_status", ""), item.get("payment_status", "") or "未收款"),
                item.get("remark", ""),
                (item.get("created_at") or "")[:19],
                (item.get("completed_at") or "")[:19],
            ]
            for col_idx, value in enumerate(values, 1):
                cell = ws.cell(row=row_idx, column=col_idx, value=value)
                cell.border = THIN_BORDER
                cell.alignment = CELL_ALIGN
        auto_width(ws)
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        return output

    @staticmethod
    def _update_order_delivery_status(txn, shipment_id):
        items = ShipmentRepository.find_order_ids_for_shipment_txn(shipment_id, db=txn)
        for item in items:
            if item["order_id"]:
                shipped_qty = ShipmentRepository.sum_shipped_qty_txn(item["order_id"], db=txn)
                order = OrderRepository.find_by_id(item["order_id"], db=txn)
                total_qty = order["quantity"] if order else 0
                if total_qty:
                    status = "全部发货" if shipped_qty >= total_qty else ("部分发货" if shipped_qty > 0 else None)
                    if status:
                        OrderRepository.update_delivery_status(item["order_id"], status, db=txn)
