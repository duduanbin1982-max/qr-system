"""
qr-system — 库存管理 Service 层

从 routes/inventory.py 提取全部业务逻辑。
"""
import sqlite3
from datetime import datetime
from modules.services import BaseService
from modules.repositories.inventory_repository import InventoryRepository
from modules.services.query_utils import paginate, build_sort_clause


class InventoryService:
    """库存管理业务逻辑。"""

    @staticmethod
    def list_items(keyword='', low_stock=False, location='', page=1, limit=100):
        """库存列表（搜索 + 低库存筛选 + 分页）。"""
        db = BaseService.db()
        clauses = ['1=1']
        params = []
        if keyword:
            clauses.append('(i.product_model LIKE ? OR i.product_name LIKE ? OR i.specification LIKE ? OR i.location LIKE ? OR i.unit LIKE ? OR i.remark LIKE ? OR o.order_no LIKE ? OR o.customer LIKE ?)')
            params.extend([f'%{keyword}%'] * 8)
        if low_stock:
            clauses.append('i.quantity <= i.safe_stock AND i.safe_stock > 0')
        if location:
            clauses.append('i.location = ?')
            params.append(location)
        where = ' AND '.join(clauses)
        base_sql = (
            'SELECT i.*, o.order_no, o.customer, p.price, CASE WHEN i.quantity <= i.safe_stock AND i.safe_stock > 0 '
            'THEN 1 ELSE 0 END as is_low FROM inventory i '
            'LEFT JOIN orders o ON i.order_id = o.id LEFT JOIN products p ON i.product_model = p.product_code AND p.deleted_at IS NULL WHERE ' + where
            + ' ' + build_sort_clause("updated_at", {"updated_at": "i.updated_at"}, default="i.updated_at")
        )
        total = db.execute(
            'SELECT COUNT(*) FROM inventory i LEFT JOIN orders o ON i.order_id = o.id LEFT JOIN products p ON i.product_model = p.product_code AND p.deleted_at IS NULL WHERE ' + where, params
        ).fetchone()[0]
        paginated_sql, all_params, size, offset = paginate(base_sql, params, page=page, page_size=limit)
        rows = db.execute(paginated_sql, all_params).fetchall()
        return {'items': [dict(r) for r in rows], 'total': total, 'page': page, 'limit': size}

    @staticmethod
    def create_item(data):
        """新增库存产品。Raises ValueError on duplicate model."""
        model = (data.get('product_model') or '').strip()
        if not model:
            raise ValueError('产品型号不能为空')
        with BaseService.transaction() as txn:
            try:
                txn.execute('''
                    INSERT INTO inventory (product_model, product_name, specification,
                        quantity, safe_stock, location, unit, remark, category, unit_cost, last_count_date, order_id)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ''', (
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
                    data.get('order_id') or None
                ))
            except sqlite3.IntegrityError:
                raise ValueError('产品型号已存在')
            return txn.execute('SELECT last_insert_rowid()').fetchone()[0]

    @staticmethod
    def update_item(item_id, data):
        """更新库存产品。"""
        model = (data.get('product_model') or '').strip()
        if not model:
            raise ValueError('产品型号不能为空')
        db = BaseService.db()
        with BaseService.transaction() as txn:
            dup = txn.execute(
                'SELECT id FROM inventory WHERE product_model = ? AND order_id = ? AND id != ?',
                (model, data.get('order_id'), item_id)
            ).fetchone()
            if dup:
                raise ValueError('该订单下产品型号已存在')
            txn.execute('''
                UPDATE inventory SET
                    product_model = ?, product_name = ?, specification = ?,
                    quantity = ?, safe_stock = ?, location = ?, unit = ?, remark = ?,
                    category = ?, unit_cost = ?, last_count_date = ?,
                    updated_at = datetime('now','localtime')
                WHERE id = ?
            ''', (
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
                item_id
            ))

    @staticmethod
    def delete_item(item_id):
        """删除库存产品（级联删除日志）。"""
        db = BaseService.db()
        exists = db.execute(
            'SELECT id FROM inventory WHERE id = ?', (item_id,)
        ).fetchone()
        if not exists:
            raise ValueError('库存不存在')
        with BaseService.transaction() as txn:
            txn.execute('DELETE FROM inventory_logs WHERE inventory_id = ?', (item_id,))
            txn.execute('DELETE FROM inventory WHERE id = ?', (item_id,))

    @staticmethod
    def stock_in(inv_id, qty, order_id=None, order_no='', remark='',
                 operator_id=None, operator_name=''):
        """入库操作。"""
        if qty <= 0:
            raise ValueError('参数错误')
        with BaseService.transaction() as txn:
            cur = txn.execute(
                'UPDATE inventory SET quantity = quantity + ?, '
                'updated_at = datetime("now","localtime") WHERE id = ?',
                (qty, inv_id)
            )
            if cur.rowcount == 0:
                raise ValueError('库存不存在')
            txn.execute('''INSERT INTO inventory_logs (inventory_id, type, quantity,
                order_id, order_no, remark, operator_id, operator_name)
                VALUES (?,?,?,?,?,?,?,?)''',
                (inv_id, 'in', qty, order_id, order_no, remark, operator_id, operator_name))

    @staticmethod
    def stock_out(inv_id, qty, order_id=None, order_no='', remark='',
                  operator_id=None, operator_name=''):
        """出库操作（原子扣减 + 防超卖）。"""
        if qty <= 0:
            raise ValueError('参数错误')
        with BaseService.transaction() as txn:
            txn.execute(
                'UPDATE inventory SET quantity = quantity - ?, '
                'updated_at = datetime("now","localtime") '
                'WHERE id = ? AND quantity >= ?',
                (qty, inv_id, qty)
            )
            if txn.total_changes == 0:
                inv = txn.execute(
                    'SELECT quantity FROM inventory WHERE id = ?', (inv_id,)
                ).fetchone()
                if not inv:
                    raise ValueError('库存不存在')
                raise ValueError('库存不足')
            txn.execute('''INSERT INTO inventory_logs (inventory_id, type, quantity,
                order_id, order_no, remark, operator_id, operator_name)
                VALUES (?,?,?,?,?,?,?,?)''',
                (inv_id, 'out', qty, order_id, order_no, remark, operator_id, operator_name))

    @staticmethod
    def get_logs(inv_id='', type_filter='', page=1, limit=20, date_from='', date_to=''):
        """库存流水（分页）。"""
        db = BaseService.db()
        where = '1=1'
        params = []
        if inv_id:
            where += ' AND il.inventory_id = ?'
            params.append(inv_id)
        if type_filter:
            where += ' AND il.type = ?'
            params.append(type_filter)
        if date_from:
            where += ' AND il.created_at >= ?'
            params.append(date_from)
        if date_to:
            where += ' AND il.created_at <= ?'
            params.append(date_to + ' 23:59:59')

        total = db.execute(
            'SELECT COUNT(*) FROM inventory_logs il WHERE ' + where, params
        ).fetchone()[0]
        rows = db.execute(
            'SELECT il.*, i.product_model, i.product_name '
            'FROM inventory_logs il '
            'JOIN inventory i ON il.inventory_id = i.id '
            'WHERE ' + where + ' ORDER BY il.created_at DESC LIMIT ? OFFSET ?',
            params + [limit, (page - 1) * limit]
        ).fetchall()
        return {'logs': [dict(r) for r in rows], 'total': total}

    @staticmethod
    def get_alerts():
        """库存预警列表。"""
        db = BaseService.db()
        rows = db.execute('''
            SELECT *, (safe_stock - quantity) as shortage
            FROM inventory
            WHERE quantity <= safe_stock AND safe_stock > 0
            ORDER BY shortage DESC
        ''').fetchall()
        return {'alerts': [dict(r) for r in rows]}

    @staticmethod
    def stock_adjust(inv_id, actual_qty, operator_id=None, operator_name='', remark=''):
        db = BaseService.db()
        inv = db.execute('SELECT id, quantity, product_model FROM inventory WHERE id=?', (inv_id,)).fetchone()
        if not inv:
            raise ValueError('库存记录不存在')
        current = inv['quantity'] or 0
        diff = actual_qty - current
        if diff == 0:
            return {'adjusted': False, 'message': '库存数量一致，无需调整'}

        with BaseService.transaction() as txn:
            txn.execute(
                'UPDATE inventory SET quantity = ?, updated_at = datetime("now","localtime") WHERE id = ?',
                (actual_qty, inv_id)
            )
            log_type = 'in' if diff > 0 else 'out'
            txn.execute('''INSERT INTO inventory_logs (inventory_id, type, quantity,
                order_id, order_no, remark, operator_id, operator_name)
                VALUES (?,?,?,?,?,?,?,?)''',
                (inv_id, 'adjust', abs(diff), None, '',
                 f'盘点调整: {remark or "系统调整"} (原{current}→现{actual_qty}, 差额{diff:+d})',
                 operator_id, operator_name))
        return {'adjusted': True, 'product_model': inv['product_model'],
                'old_qty': current, 'new_qty': actual_qty, 'diff': diff}


    # P2: ABC
    @staticmethod
    def classify_abc():
        db = BaseService.db()
        rows = db.execute("SELECT inv.id, inv.product_model, COALESCE(SUM(CASE WHEN il.type='out' THEN il.quantity ELSE 0 END),0) as total_out, inv.unit_cost, COALESCE(SUM(CASE WHEN il.type='out' THEN il.quantity ELSE 0 END),0) * inv.unit_cost as out_value FROM inventory inv LEFT JOIN inventory_logs il ON il.inventory_id = inv.id GROUP BY inv.id ORDER BY out_value DESC").fetchall()
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
                    txn.execute("UPDATE inventory SET category=? WHERE id=?", (cat, r["id"]))
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
                txn.execute("UPDATE inventory SET category=? WHERE id=?", (cat, r["id"]))
        if b_cut == 0: b_cut = a_cut + 1
        return {"classified": total, "a_count": a_cut, "b_count": b_cut - a_cut, "c_count": total - b_cut + 1}

    @staticmethod
    def get_turnover():
        db = BaseService.db()
        rows = db.execute("SELECT inv.id, inv.product_model, inv.product_name, inv.quantity as current_stock, COALESCE(SUM(CASE WHEN il.type='out' THEN il.quantity ELSE 0 END),0) as total_out, COALESCE(SUM(CASE WHEN il.type='in' THEN il.quantity ELSE 0 END),0) as total_in, inv.unit_cost FROM inventory inv LEFT JOIN inventory_logs il ON il.inventory_id = inv.id GROUP BY inv.id ORDER BY total_out DESC").fetchall()
        result = []
        for r in rows:
            turnover = round(r["total_out"] / max(r["current_stock"], 1), 2)
            result.append({"id": r["id"], "product_model": r["product_model"], "product_name": r["product_name"], "current_stock": r["current_stock"], "total_out": r["total_out"], "total_in": r["total_in"], "unit_cost": r["unit_cost"], "turnover_rate": turnover, "status": "高周转" if turnover > 3 else ("正常" if turnover > 1 else "低周转")})
        return result

    @staticmethod
    def suggest_safe_stock():
        db = BaseService.db()
        rows = db.execute("SELECT inv.id, inv.product_model, inv.product_name, inv.safe_stock as current_safe, inv.quantity, COALESCE(SUM(CASE WHEN il.type='out' AND il.created_at >= date('now','-30 days') THEN il.quantity ELSE 0 END),0) as month_out FROM inventory inv LEFT JOIN inventory_logs il ON il.inventory_id = inv.id GROUP BY inv.id").fetchall()
        suggestions = []
        for r in rows:
            daily_avg = round(r["month_out"] / 30, 1)
            suggested = max(1, int(daily_avg * 7))
            suggestions.append({"id": r["id"], "product_model": r["product_model"], "product_name": r["product_name"], "current_safe_stock": r["current_safe"], "suggested_safe_stock": suggested, "daily_avg_consumption": daily_avg, "current_quantity": r["quantity"], "need_adjust": abs(suggested - r["current_safe"]) > 0})
        return suggestions

    @staticmethod
    def get_batch_tracking(item_id=None, lot_no=None):
        db = BaseService.db()
        clauses = ["type='in'"]
        params = []
        if item_id:
            clauses.append("inventory_id = ?")
            params.append(item_id)
        if lot_no:
            clauses.append("lot_no = ?")
            params.append(lot_no)
        where = " AND ".join(clauses)
        batches = db.execute("SELECT * FROM inventory_logs WHERE " + where + " ORDER BY created_at DESC LIMIT 100", params).fetchall()
        result = []
        for b in batches:
            bd = dict(b)
            outs = db.execute("SELECT * FROM inventory_logs WHERE inventory_id=? AND type='out' AND created_at >= ? ORDER BY created_at", (bd["inventory_id"], bd.get("created_at", ""))).fetchall()
            bd["related_outs"] = [dict(o) for o in outs]
            bd["remaining"] = bd.get("quantity", 0) - sum(o["quantity"] for o in outs)
            result.append(bd)
        return result

    @staticmethod
    def get_locations():
        db = BaseService.db()
        rows = db.execute("SELECT location, COUNT(*) as item_count, SUM(quantity) as total_qty, GROUP_CONCAT(product_model || '(' || quantity || ')', ', ') as items FROM inventory WHERE location != '' GROUP BY location ORDER BY location").fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def update_location(item_ids, new_location):
        if not item_ids or not new_location:
            raise ValueError("请提供物料ID和目标库位")
        with BaseService.transaction() as txn:
            for iid in item_ids:
                txn.execute("UPDATE inventory SET location=?, updated_at=datetime('now','localtime') WHERE id=?", (new_location, iid))
        return {"updated": len(item_ids), "location": new_location}

    @staticmethod
    def create_count_task():
        db = BaseService.db()
        count = db.execute("SELECT COUNT(*) as cnt FROM inventory").fetchone()["cnt"]
        return {"message": "盘点任务已创建，共 %d 项待盘点" % count, "total_items": count}

    @staticmethod
    def get_count_status():
        db = BaseService.db()
        total = db.execute("SELECT COUNT(*) as cnt FROM inventory").fetchone()["cnt"]
        done = db.execute("SELECT COUNT(*) as cnt FROM inventory WHERE last_count_date >= date('now')").fetchone()["cnt"]
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
            inv = txn.execute(
                "SELECT * FROM inventory WHERE id = ?", (item_id,)
            ).fetchone()
            if not inv:
                raise ValueError("item not found")
            old_qty = inv["quantity"]
            diff = actual_qty - old_qty
            txn.execute(
                "UPDATE inventory SET quantity = ?, last_count_date = date('now'), "
                "updated_at = datetime('now','localtime') WHERE id = ?",
                (actual_qty, item_id)
            )
            log_type = "adjust" if diff != 0 else "count"
            log_remark = remark or ("count: " + str(old_qty) + " -> " + str(actual_qty))
            txn.execute(
                "INSERT INTO inventory_logs (inventory_id, type, quantity, remark, operator_id, operator_name) "
                "VALUES (?,?,?,?,?,?)",
                (item_id, log_type, diff if diff != 0 else 0, log_remark, None, "system"))
        return {"ok": True, "old_qty": old_qty, "new_qty": actual_qty, "diff": diff}

    @staticmethod
    def get_impact(item_id):
        db = BaseService.db()
        item = db.execute(
            "SELECT product_model, product_name, quantity FROM inventory WHERE id = ?",
            (item_id,)
        ).fetchone()
        if not item:
            raise ValueError("item not found")
        log_count = db.execute(
            "SELECT COUNT(*) FROM inventory_logs WHERE inventory_id = ?",
            (item_id,)
        ).fetchone()[0]
        order_count = db.execute(
            "SELECT COUNT(*) FROM orders o JOIN inventory i ON i.order_id = o.id "
            "WHERE i.id = ? AND o.deleted_at IS NULL",
            (item_id,)
        ).fetchone()[0]
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
        db = BaseService.db()
        today = datetime.now().strftime('%Y-%m-%d')
        # 合并 inventory 基础统计为1次查询
        inv_stats = db.execute(
            "SELECT COUNT(*) as total_items, COALESCE(SUM(quantity),0) as total_quantity, "
            "COALESCE(SUM(CASE WHEN quantity <= safe_stock AND safe_stock > 0 THEN 1 ELSE 0 END),0) as low_stock "
            "FROM inventory"
        ).fetchone()
        # 合并今日出入库统计为1次查询
        today_stats = db.execute(
            "SELECT COALESCE(SUM(CASE WHEN type='in' THEN quantity ELSE 0 END),0) as today_in, "
            "COALESCE(SUM(CASE WHEN type='out' THEN quantity ELSE 0 END),0) as today_out "
            "FROM inventory_logs WHERE date(created_at) = ?",
            (today,)
        ).fetchone()
        return {
            'total_items': inv_stats['total_items'] or 0,
            'total_quantity': inv_stats['total_quantity'] or 0,
            'low_stock': inv_stats['low_stock'] or 0,
            'today_in': today_stats['today_in'] or 0,
            'today_out': today_stats['today_out'] or 0,
        }
