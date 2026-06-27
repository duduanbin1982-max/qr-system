"""
qr-system — 库存管理 Service 层

从 routes/inventory.py 提取全部业务逻辑。
"""
from datetime import datetime
from modules.services import BaseService
from modules.repositories.inventory_repository import InventoryRepository


class InventoryService:
    """库存管理业务逻辑。"""

    @staticmethod
    def list_items(keyword='', low_stock=False, location='', page=1, limit=100):
        """库存列表（搜索 + 低库存筛选 + 分页）。"""
        where, params = InventoryRepository.build_item_filters(keyword, low_stock, location)
        total = InventoryRepository.count_items(where, params)
        rows, size = InventoryRepository.list_items_paginated(where, params, page, limit)
        return {'items': [dict(r) for r in rows], 'total': total, 'page': page, 'limit': size}

    @staticmethod
    def create_item(data):
        """新增库存产品。Raises ValueError on duplicate model."""
        model = (data.get('product_model') or '').strip()
        if not model:
            raise ValueError('产品型号不能为空')
        with BaseService.transaction() as txn:
            if InventoryRepository.find_duplicate_model_txn(model, data.get('order_id'), 0, txn):
                raise ValueError('产品型号已存在')
            return InventoryRepository.insert_txn(
                model,
                data.get('product_name', ''),
                data.get('specification', ''),
                data.get('quantity', 0),
                data.get('safe_stock', 0),
                data.get('location', ''),
                data.get('unit', '件'),
                data.get('remark', ''),
                data.get('category', ''),
                data.get('unit_cost', 0),
                data.get('last_count_date', ''),
                data.get('order_id') or None,
                txn,
            )

    @staticmethod
    def update_item(item_id, data):
        """更新库存产品。"""
        model = (data.get('product_model') or '').strip()
        if not model:
            raise ValueError('产品型号不能为空')
        with BaseService.transaction() as txn:
            if InventoryRepository.find_duplicate_model_txn(model, data.get('order_id'), item_id, txn):
                raise ValueError('该订单下产品型号已存在')
            InventoryRepository.update_item_txn(
                item_id,
                data.get('product_model', ''),
                data.get('product_name', ''),
                data.get('specification', ''),
                data.get('quantity', 0),
                data.get('safe_stock', 0),
                data.get('location', ''),
                data.get('unit', '件'),
                data.get('remark', ''),
                data.get('category', ''),
                data.get('unit_cost', 0),
                data.get('last_count_date', ''),
                txn,
            )

    @staticmethod
    def delete_item(item_id):
        """删除库存产品（级联删除日志）。"""
        if not InventoryRepository.find_item_by_id(item_id):
            raise ValueError('库存不存在')
        with BaseService.transaction() as txn:
            InventoryRepository.delete_logs_for_item_txn(item_id, txn)
            InventoryRepository.delete_item_txn(item_id, txn)

    @staticmethod
    def stock_in(inv_id, qty, order_id=None, order_no='', remark='',
                 operator_id=None, operator_name=''):
        """入库操作。"""
        if qty <= 0:
            raise ValueError('参数错误')
        with BaseService.transaction() as txn:
            cur = InventoryRepository.increase_stock_txn(inv_id, qty, txn)
            if cur.rowcount == 0:
                raise ValueError('库存不存在')
            InventoryRepository.insert_movement_log_txn(
                inv_id,
                'in',
                qty,
                order_id,
                order_no,
                remark,
                operator_id,
                operator_name,
                txn,
            )

    @staticmethod
    def stock_out(inv_id, qty, order_id=None, order_no='', remark='',
                  operator_id=None, operator_name=''):
        """出库操作（原子扣减 + 防超卖）。"""
        if qty <= 0:
            raise ValueError('参数错误')
        with BaseService.transaction() as txn:
            cur = InventoryRepository.decrease_stock_if_available_txn(inv_id, qty, txn)
            if cur.rowcount == 0:
                inv = InventoryRepository.get_item_quantity(inv_id, txn)
                if not inv:
                    raise ValueError('库存不存在')
                raise ValueError('库存不足')
            InventoryRepository.insert_movement_log_txn(
                inv_id,
                'out',
                qty,
                order_id,
                order_no,
                remark,
                operator_id,
                operator_name,
                txn,
            )

    @staticmethod
    def get_logs(inv_id='', type_filter='', page=1, limit=20, date_from='', date_to=''):
        """库存流水（分页）。"""
        total = InventoryRepository.count_logs(inv_id, type_filter, date_from, date_to)
        rows = InventoryRepository.list_logs(inv_id, type_filter, date_from, date_to, page, limit)
        return {'logs': [dict(r) for r in rows], 'total': total}

    @staticmethod
    def get_alerts():
        """库存预警列表。"""
        rows = InventoryRepository.list_alerts()
        return {'alerts': [dict(r) for r in rows]}

    @staticmethod
    def stock_adjust(inv_id, actual_qty, operator_id=None, operator_name='', remark=''):
        inv = InventoryRepository.find_adjustment_item(inv_id)
        if not inv:
            raise ValueError('库存记录不存在')
        current = inv['quantity'] or 0
        diff = actual_qty - current
        if diff == 0:
            return {'adjusted': False, 'message': '库存数量一致，无需调整'}

        with BaseService.transaction() as txn:
            InventoryRepository.update_quantity_txn(inv_id, actual_qty, txn)
            InventoryRepository.insert_movement_log_txn(
                inv_id,
                'adjust',
                abs(diff),
                None,
                '',
                f'盘点调整: {remark or "系统调整"} (原{current}→现{actual_qty}, 差额{diff:+d})',
                operator_id,
                operator_name,
                txn,
            )
        return {'adjusted': True, 'product_model': inv['product_model'],
                'old_qty': current, 'new_qty': actual_qty, 'diff': diff}


    # P2: ABC
    @staticmethod
    def classify_abc():
        rows = InventoryRepository.list_abc_rows()
        if not rows:
            return {"message": "无库存数据"}
        total_value = sum(r["out_value"] for r in rows)
        total = len(rows)
        if total_value == 0:
            a_cut = max(1, int(total * 0.2))
            b_cut = max(a_cut + 1, int(total * 0.5))
            with BaseService.transaction() as txn:
                for i, r in enumerate(rows):
                    cat = "A" if i < a_cut else ("B" if i < b_cut else "C")
                    InventoryRepository.update_category_txn(r["id"], cat, txn)
            return {"classified": total, "a_count": a_cut, "b_count": b_cut - a_cut, "c_count": total - b_cut}
        cum = 0
        a_cut = b_cut = 0
        with BaseService.transaction() as txn:
            for i, r in enumerate(rows):
                cum += r["out_value"]
                pct = cum / total_value
                cat = "A" if pct <= 0.8 else ("B" if pct <= 0.95 else "C")
                if cat == "A" and a_cut == 0: a_cut = i + 1
                if cat == "B" and b_cut == 0: b_cut = i + 1
                InventoryRepository.update_category_txn(r["id"], cat, txn)
        if b_cut == 0: b_cut = a_cut + 1
        return {"classified": total, "a_count": a_cut, "b_count": b_cut - a_cut, "c_count": total - b_cut + 1}

    @staticmethod
    def get_turnover():
        rows = InventoryRepository.list_turnover_rows()
        result = []
        for r in rows:
            turnover = round(r["total_out"] / max(r["current_stock"], 1), 2)
            result.append({"id": r["id"], "product_model": r["product_model"], "product_name": r["product_name"], "current_stock": r["current_stock"], "total_out": r["total_out"], "total_in": r["total_in"], "unit_cost": r["unit_cost"], "turnover_rate": turnover, "status": "高周转" if turnover > 3 else ("正常" if turnover > 1 else "低周转")})
        return result

    @staticmethod
    def suggest_safe_stock():
        rows = InventoryRepository.list_safe_stock_suggestion_rows()
        suggestions = []
        for r in rows:
            daily_avg = round(r["month_out"] / 30, 1)
            suggested = max(1, int(daily_avg * 7))
            suggestions.append({"id": r["id"], "product_model": r["product_model"], "product_name": r["product_name"], "current_safe_stock": r["current_safe"], "suggested_safe_stock": suggested, "daily_avg_consumption": daily_avg, "current_quantity": r["quantity"], "need_adjust": abs(suggested - r["current_safe"]) > 0})
        return suggestions

    @staticmethod
    def get_batch_tracking(item_id=None, lot_no=None):
        batches = InventoryRepository.list_inbound_batches(item_id=item_id, lot_no=lot_no)
        result = []
        for b in batches:
            bd = dict(b)
            outs = InventoryRepository.list_batch_outbound_after(
                bd["inventory_id"],
                bd.get("created_at", ""),
            )
            bd["related_outs"] = [dict(o) for o in outs]
            bd["remaining"] = bd.get("quantity", 0) - sum(o["quantity"] for o in outs)
            result.append(bd)
        return result

    @staticmethod
    def get_locations():
        rows = InventoryRepository.list_locations()
        return [dict(r) for r in rows]

    @staticmethod
    def update_location(item_ids, new_location):
        if not item_ids or not new_location:
            raise ValueError("请提供物料ID和目标库位")
        with BaseService.transaction() as txn:
            for iid in item_ids:
                InventoryRepository.update_location_txn(iid, new_location, txn)
        return {"updated": len(item_ids), "location": new_location}

    @staticmethod
    def create_count_task():
        count = InventoryRepository.count_inventory_items()
        return {"message": "盘点任务已创建，共 %d 项待盘点" % count, "total_items": count}

    @staticmethod
    def get_count_status():
        total = InventoryRepository.count_inventory_items()
        done = InventoryRepository.count_inventory_items_counted_today()
        return {"total": total, "done": done, "pending": total - done, "progress_pct": round(done / max(total, 1) * 100, 1)}

    @staticmethod
    def export_inventory(keyword='', low_stock=False):
        from modules.export_utils import style_header, auto_width, THIN_BORDER, CELL_ALIGN
        from openpyxl import Workbook
        from openpyxl.styles import Font
        from io import BytesIO

        result = InventoryService.list_items(keyword=keyword, low_stock=low_stock, page=1, limit=99999)
        items = result.get('items', [])

        wb = Workbook()
        ws = wb.active
        ws.title = '库存清单'

        headers = ['产品名称', '订单号', '客户', '产品型号', '规格', '当前库存', '安全库存', '状态', '存放位置', '单位', '备注', '更新时间']
        style_header(ws, headers)

        for row_idx, item in enumerate(items, 2):
            status = '⚠低库存' if item.get('is_low') else '正常'
            vals = [
                item.get('product_name', ''), item.get('order_no', ''),
                item.get('customer', ''), item.get('product_model', ''),
                item.get('specification', ''), item.get('quantity', 0),
                item.get('safe_stock', 0), status,
                item.get('location', ''), item.get('unit', ''),
                item.get('remark', ''), (item.get('updated_at') or '')[:19]
            ]
            for col_idx, val in enumerate(vals, 1):
                cell = ws.cell(row=row_idx, column=col_idx, value=val)
                cell.border = THIN_BORDER
                cell.alignment = CELL_ALIGN
                if status == '⚠低库存':
                    cell.font = Font(name='Microsoft YaHei', color='FF0000')

        auto_width(ws)
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        return output

    @staticmethod
    def export_logs(inv_id='', type_filter='', date_from='', date_to=''):
        from modules.export_utils import style_header, auto_width, THIN_BORDER, CELL_ALIGN
        from openpyxl import Workbook
        from openpyxl.styles import Font
        from io import BytesIO

        result = InventoryService.get_logs(inv_id=inv_id, type_filter=type_filter,
                                           date_from=date_from, date_to=date_to, page=1, limit=99999)
        items = result.get('logs', [])

        wb = Workbook()
        ws = wb.active
        ws.title = '库存流水'

        headers = ['时间', '类型', '产品型号', '产品名称', '数量', '订单号', '操作人', '备注']
        style_header(ws, headers)

        type_map = {'in': '入库', 'out': '出库', 'adjust': '盘点调整'}
        for row_idx, item in enumerate(items, 2):
            vals = [
                (item.get('created_at') or '')[:19],
                type_map.get(item.get('type', ''), item.get('type', '')),
                item.get('product_model', ''), item.get('product_name', ''),
                item.get('quantity', 0), item.get('order_no', ''),
                item.get('operator_name', ''), item.get('remark', '')
            ]
            for col_idx, val in enumerate(vals, 1):
                cell = ws.cell(row=row_idx, column=col_idx, value=val)
                cell.border = THIN_BORDER
                cell.alignment = CELL_ALIGN

        auto_width(ws)
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        return output

    @staticmethod
    def submit_count(item_id, actual_qty, remark=""):
        if actual_qty < 0:
            raise ValueError("count quantity cannot be negative")
        with BaseService.transaction() as txn:
            inv = InventoryRepository.get_count_item(item_id, txn)
            if not inv:
                raise ValueError("item not found")
            old_qty = inv["quantity"]
            diff = actual_qty - old_qty
            log_type = "adjust" if diff != 0 else "count"
            log_remark = remark or ("count: " + str(old_qty) + " -> " + str(actual_qty))
            InventoryRepository.submit_count_txn(
                item_id,
                actual_qty,
                diff if diff != 0 else 0,
                log_type,
                log_remark,
                txn,
            )
        return {"ok": True, "old_qty": old_qty, "new_qty": actual_qty, "diff": diff}

    @staticmethod
    def get_impact(item_id):
        item = InventoryRepository.find_item_for_delete(item_id)
        if not item:
            raise ValueError("item not found")
        log_count = InventoryRepository.count_item_logs(item_id)
        order_count = InventoryRepository.count_linked_orders(item_id)
        warnings = []
        if log_count > 0:
            warnings.append("will delete " + str(log_count) + " log records")
        if order_count > 0:
            warnings.append("linked to " + str(order_count) + " orders")
        return {
            "item": dict(item),
            "log_count": log_count,
            "order_count": order_count,
            "can_delete": True,
            "warnings": [w for w in warnings if w]
        }

    @staticmethod
    def get_stats():
        """库存统计（2次查询替代4次）。"""
        today = datetime.now().strftime('%Y-%m-%d')
        inv_stats = InventoryRepository.get_inventory_stats()
        today_stats = InventoryRepository.get_today_stats(today)
        return {
            'total_items': inv_stats['total_items'] or 0,
            'total_quantity': inv_stats['total_quantity'] or 0,
            'low_stock': inv_stats['low_stock'] or 0,
            'today_in': today_stats['today_in'] or 0,
            'today_out': today_stats['today_out'] or 0,
        }
