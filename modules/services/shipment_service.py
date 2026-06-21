"""qr-system — 出库管理 Service 层（Repository-refactored）"""
from datetime import datetime
from modules.services import BaseService
from modules.services.query_utils import paginate, build_sort_clause
from modules.repositories.shipment_repository import ShipmentRepository


def _generate_shipment_no(db, prefix=None):
    if not prefix:
        setting = None  # Settings lookup
        prefix = setting["value"] if setting else "SH"
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
        where = "1=1"
        params = []
        if keyword:
            where += " AND (shipment_no LIKE ? OR customer LIKE ?)"
            params.extend(["%" + keyword + "%", "%" + keyword + "%"])
        if status:
            where += " AND status = ?"
            params.append(status)

        total = ShipmentRepository.count_shipments(where, params)

        sort_clause = build_sort_clause(
            sort_by,
            {"created_at": "s.created_at", "customer": "s.customer", "status": "s.status", "total_quantity": "s.total_quantity"},
            default="s.created_at"
        )
        base_sql = (
            "SELECT s.*, COALESCE(si.item_count, 0) as item_count "
            "FROM shipments s "
            "LEFT JOIN (SELECT shipment_id, COUNT(*) as item_count FROM shipment_items GROUP BY shipment_id) si "
            "ON si.shipment_id = s.id "
            "WHERE " + where + " " + sort_clause
        )
        paginated_sql, all_params, size, offset = paginate(base_sql, params, page=page, page_size=limit)
        rows = ShipmentRepository.list_shipments_paginated(paginated_sql, all_params)
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
        db = BaseService.db()
        for item in items:
            inv = ShipmentRepository.find_inventory_for_validation(item.get("inventory_id", 0))
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
                order_no_val = ShipmentRepository.find_order_no_txn(order_id, db=txn)

            for item in items:
                item_order_id = item.get("order_id") or order_id
                item_order_no = item.get("order_no") or order_no_val
                if item_order_id and not item_order_no:
                    item_order_no = ShipmentRepository.find_order_no_txn(item_order_id, db=txn)
                product_code = item.get("product_code", "")
                if not product_code:
                    inv_row = ShipmentRepository.find_inventory_model_txn(item.get("inventory_id", 0), db=txn)
                    if inv_row:
                        prod_code = ShipmentRepository.find_product_code_by_model_txn(inv_row["product_model"], db=txn)
                        product_code = prod_code if prod_code else inv_row["product_model"]
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
                    ShipmentRepository.reserve_inventory_txn(item.get("inventory_id", 0), item.get("quantity", 0), db=txn)
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
        fields = ["customer", "contact_person", "contact_phone", "address", "remark", "status", "receivable_amount", "payment_status"]
        updates = []
        params = []
        for f in fields:
            if f in data:
                if f == "status" and data[f] == "completed" and row["status"] != "completed":
                    raise ValueError("请使用「完成出库」按钮完成出库")
                updates.append(f + " = ?")
                params.append(data[f])
        if not updates:
            raise ValueError("没有需要更新的字段")
        with BaseService.transaction() as txn:
            ShipmentRepository.update_shipment_fields_txn(", ".join(updates), params, shipment_id, db=txn)

    @staticmethod
    def delete_shipment(shipment_id, current_user):
        row = ShipmentRepository.find_shipment_by_id(shipment_id)
        if not row:
            raise ValueError("出库单不存在")
        with BaseService.transaction() as txn:
            if row["status"] == "completed":
                items = ShipmentRepository.find_shipment_items_for_delete_txn(shipment_id, db=txn)
                for item in items:
                    ShipmentRepository.return_inventory_txn(item["inventory_id"], item["quantity"], db=txn)
                    remark = "删除出库单 " + row["shipment_no"] + " - 归还库存"
                    ShipmentRepository.insert_inventory_log_txn(
                        item["inventory_id"], "in", item["quantity"], row["shipment_no"],
                        remark, current_user["id"], current_user["name"], db=txn
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
                    ShipmentRepository.release_reserved_txn(item["inventory_id"], item["quantity"], db=txn)
            for item in items:
                cur = ShipmentRepository.deduct_inventory_txn(item["inventory_id"], item["quantity"], db=txn)
                if cur.rowcount == 0:
                    inv = ShipmentRepository.find_inventory_for_deduct_txn(item["inventory_id"], db=txn)
                    current = inv["quantity"] if inv else 0
                    model = inv["product_model"] if inv else (item["product_model"] or "?")
                    raise ValueError(model + " " + (item["product_name"] or "") + ": 库存不足 (库存" + str(current) + "，需" + str(item["quantity"]) + ")")
                item_order_no = item["order_no"] if item["order_no"] else sn
                remark = "出库单 " + sn + " 出库 " + str(item["quantity"]) + " " + (item["unit"] or "件")
                ShipmentRepository.insert_inventory_log_txn(
                    item["inventory_id"], "out", item["quantity"], item_order_no,
                    remark, current_user["id"], current_user["name"], db=txn
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
                    ShipmentRepository.release_reserved_txn(item["inventory_id"], item["quantity"], db=txn)
            if row["status"] == "completed":
                items = ShipmentRepository.find_shipment_items_for_delete_txn(shipment_id, db=txn)
                for item in items:
                    ShipmentRepository.return_inventory_txn(item["inventory_id"], item["quantity"], db=txn)
                    ShipmentRepository.insert_inventory_log_txn(
                        item["inventory_id"], "in", item["quantity"], row["shipment_no"],
                        "取消出库单 " + row["shipment_no"] + " - 归还库存",
                        current_user["id"], current_user["name"], db=txn
                    )
            ShipmentRepository.cancel_shipment_txn(shipment_id, db=txn)
        return row["shipment_no"]

    @staticmethod
    def get_order_stock(order_id):
        order = ShipmentRepository.find_order_for_stock(order_id)
        if not order:
            raise ValueError("订单不存在")
        items = ShipmentRepository.find_inventory_by_order(order_id)
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
    def _update_order_delivery_status(txn, shipment_id):
        items = ShipmentRepository.find_order_ids_for_shipment_txn(shipment_id, db=txn)
        for item in items:
            if item["order_id"]:
                shipped_qty = ShipmentRepository.sum_shipped_qty_txn(item["order_id"], db=txn)
                total_qty = ShipmentRepository.find_order_quantity_txn(item["order_id"], db=txn)
                if total_qty:
                    status = "全部发货" if shipped_qty >= total_qty else ("部分发货" if shipped_qty > 0 else None)
                    if status:
                        ShipmentRepository.update_order_delivery_status_txn(item["order_id"], status, db=txn)
