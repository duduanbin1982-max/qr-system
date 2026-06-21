"""qr-system - InventoryService (Repository-refactored)"""
import sqlite3
from datetime import datetime
from modules.services import BaseService
from modules.repositories.inventory_repository import InventoryRepository


class InventoryService:

    @staticmethod
    def list_items(keyword='', low_stock=False, location='', page=1, limit=100):
        clauses = ['1=1']
        params = []
        if keyword:
            clauses.append('(i.product_model LIKE ? OR i.product_name LIKE ? OR i.specification LIKE ? OR i.location LIKE ? OR i.unit LIKE ? OR i.remark LIKE ? OR o.order_no LIKE ? OR o.customer LIKE ?)')
            params.extend(['%' + keyword + '%'] * 8)
        if low_stock:
            clauses.append('i.quantity <= i.safe_stock AND i.safe_stock > 0')
        if location:
            clauses.append('i.location = ?')
            params.append(location)
        where = ' AND '.join(clauses)
        total = InventoryRepository.count_items(where, params)
        rows, size = InventoryRepository.list_items_paginated(where, params, page, limit)
        return {'items': [dict(r) for r in rows], 'total': total, 'page': page, 'limit': size}

    @staticmethod
    def create_item(data):
        model = (data.get('product_model') or '').strip()
        if not model:
            raise ValueError('Product model required')
        with BaseService.transaction() as txn:
            try:
                inv_id = InventoryRepository.insert_txn(
                    model, data.get('product_name', ''), data.get('specification', ''),
                    data.get('quantity', 0), data.get('safe_stock', 0),
                    data.get('location', ''), data.get('unit', 'pcs'),
                    data.get('remark', ''), data.get('category', ''),
                    data.get('unit_cost', 0), data.get('last_count_date', ''),
                    data.get('order_id') or None, db=txn
                )
            except sqlite3.IntegrityError:
                raise ValueError('Product model already exists')
            return inv_id

    @staticmethod
    def update_item(item_id, data):
        model = (data.get('product_model') or '').strip()
        if not model:
            raise ValueError('Product model required')
        with BaseService.transaction() as txn:
            dup = InventoryRepository.find_duplicate_model_txn(
                model, data.get('order_id'), item_id, db=txn
            )
            if dup:
                raise ValueError('Product model already exists under this order')
            InventoryRepository.update_item_txn(
                item_id, data.get('product_model', ''), data.get('product_name', ''),
                data.get('specification', ''), data.get('quantity', 0),
                data.get('safe_stock', 0), data.get('location', ''),
                data.get('unit', 'pcs'), data.get('remark', ''),
                data.get('category', ''), data.get('unit_cost', 0),
                data.get('last_count_date', ''), db=txn
            )

    @staticmethod
    def delete_item(item_id):
        """Delete inventory item and related logs."""
        item = InventoryRepository.find_item_for_delete(item_id)
        if not item:
            raise ValueError('Item not found')
        with BaseService.transaction() as txn:
            InventoryRepository.delete_logs_for_item_txn(item_id, db=txn)
            InventoryRepository.delete_item_txn(item_id, db=txn)

    @staticmethod
    def stock_in(item_id, quantity, remark, operator_id, operator_name):
        if quantity <= 0:
            raise ValueError('Quantity must be positive')
        inv = InventoryRepository.find_item_by_id(item_id)
        if not inv:
            raise ValueError('Item not found')
        new_qty = inv['quantity'] + quantity
        with BaseService.transaction() as txn:
            InventoryRepository.update_quantity_txn(item_id, new_qty, db=txn)
            InventoryRepository.insert_log_txn(item_id, 'in', quantity, remark, operator_id, operator_name, db=txn)

    @staticmethod
    def stock_out(item_id, quantity, remark, operator_id, operator_name):
        if quantity <= 0:
            raise ValueError('Quantity must be positive')
        inv = InventoryRepository.find_item_by_id(item_id)
        if not inv:
            raise ValueError('Item not found')
        if inv['quantity'] < quantity:
            raise ValueError('Insufficient stock')
        new_qty = inv['quantity'] - quantity
        with BaseService.transaction() as txn:
            InventoryRepository.update_quantity_txn(item_id, new_qty, db=txn)
            InventoryRepository.insert_log_txn(item_id, 'out', quantity, remark, operator_id, operator_name, db=txn)

    @staticmethod
    def adjust_inventory(item_id, new_quantity, remark, operator_id, operator_name):
        inv = InventoryRepository.find_item_by_id(item_id)
        if not inv:
            raise ValueError('Item not found')
        diff = new_quantity - inv['quantity']
        with BaseService.transaction() as txn:
            if diff != 0:
                InventoryRepository.update_quantity_txn(item_id, new_quantity, db=txn)
            InventoryRepository.insert_log_txn(item_id, 'adjust' if diff != 0 else 'count', diff, remark, operator_id, operator_name, db=txn)

    @staticmethod
    def get_logs(inv_id=None, type_filter='', date_from='', date_to='', page=1, limit=20):
        total = InventoryRepository.count_logs(inv_id, type_filter, date_from, date_to)
        rows = InventoryRepository.list_logs(inv_id, type_filter, date_from, date_to, page, limit)
        return {
            'logs': [dict(r) for r in rows],
            'total': total, 'page': page, 'limit': limit
        }

    @staticmethod
    def export_logs(inv_id=None, type_filter='', date_from='', date_to=''):
        from openpyxl import Workbook
        from openpyxl.styles import Font
        from io import BytesIO
        result = InventoryService.get_logs(inv_id=inv_id, type_filter=type_filter,
                                           date_from=date_from, date_to=date_to, page=1, limit=99999)
        items = result.get('logs', [])
        wb = Workbook()
        ws = wb.active
        ws.title = 'Inventory Logs'
        headers = ['Time', 'Type', 'Model', 'Name', 'Qty', 'Order No', 'Operator', 'Remark']
        for col_idx, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_idx, value=h)
            cell.font = Font(bold=True)
        type_map = {'in': 'In', 'out': 'Out', 'adjust': 'Adjust'}
        for row_idx, item in enumerate(items, 2):
            vals = [
                (item.get('created_at') or '')[:19],
                type_map.get(item.get('type', ''), item.get('type', '')),
                item.get('product_model', ''), item.get('product_name', ''),
                item.get('quantity', 0), item.get('order_no', ''),
                item.get('operator_name', ''), item.get('remark', '')
            ]
            for col_idx, val in enumerate(vals, 1):
                ws.cell(row=row_idx, column=col_idx, value=val)
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        return output

    @staticmethod
    def submit_count(item_id, actual_qty, remark=""):
        if actual_qty < 0:
            raise ValueError("Count quantity cannot be negative")
        with BaseService.transaction() as txn:
            inv = InventoryRepository.find_item_by_id(item_id)
            if not inv:
                raise ValueError("Item not found")
            old_qty = inv["quantity"]
            diff = actual_qty - old_qty
            log_type = "adjust" if diff != 0 else "count"
            log_remark = remark or ("count: " + str(old_qty) + " -> " + str(actual_qty))
            InventoryRepository.submit_count_txn(item_id, actual_qty, diff if diff != 0 else 0, log_type, log_remark, db=txn)
        return {"ok": True, "old_qty": old_qty, "new_qty": actual_qty, "diff": diff}

    @staticmethod
    def get_impact(item_id):
        item = InventoryRepository.find_item_for_delete(item_id)
        if not item:
            raise ValueError("Item not found")
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
        inv_stats = InventoryRepository.get_inventory_stats()
        today = datetime.now().strftime('%Y-%m-%d')
        today_stats = InventoryRepository.get_today_stats(today)
        return {
            'total_items': inv_stats['total_items'] or 0,
            'total_quantity': inv_stats['total_quantity'] or 0,
            'low_stock': inv_stats['low_stock'] or 0,
            'today_in': today_stats['today_in'] or 0,
            'today_out': today_stats['today_out'] or 0,
        }
