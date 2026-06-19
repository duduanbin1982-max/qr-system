"""qr-system — 出库管理 Service 层"""
from datetime import datetime
from modules.services import BaseService
from modules.services.query_utils import paginate, build_sort_clause


def _generate_shipment_no(db, prefix=None):
    if not prefix:
        setting = None  # Settings lookup
        prefix = setting['value'] if setting else 'SH'
    today = datetime.now().strftime('%Y%m%d')
    prefix_len = len(prefix) + 10
    row = db.execute(
        'SELECT MAX(CAST(SUBSTR(shipment_no, ?) AS INTEGER)) as max_seq FROM shipments WHERE shipment_no LIKE ?',
        (prefix_len, prefix + today + '-%')
    ).fetchone()
    seq = (row['max_seq'] if row and row['max_seq'] else 0) + 1
    return prefix + today + '-' + str(seq).zfill(3)

class ShipmentService:

    @staticmethod
    def generate_no():
        db = BaseService.db()
        return _generate_shipment_no(db)

    @staticmethod
    def list_shipments(keyword='', status='', page=1, limit=20, sort_by='created_at', sort_dir='desc'):
        db = BaseService.db()
        where = '1=1'
        params = []
        if keyword:
            where += ' AND (shipment_no LIKE ? OR customer LIKE ?)'
            params.extend([f'%{keyword}%', f'%{keyword}%'])
        if status:
            where += ' AND status = ?'
            params.append(status)

        total = db.execute(f'SELECT COUNT(*) FROM shipments WHERE {where}', params).fetchone()[0]
        sort_clause = build_sort_clause(
            sort_by,
            {'created_at': 's.created_at', 'customer': 's.customer', 'status': 's.status', 'total_quantity': 's.total_quantity'},
            default='s.created_at'
        )
        base_sql = f'''
            SELECT s.*, COALESCE(si.item_count, 0) as item_count
            FROM shipments s
            LEFT JOIN (
                SELECT shipment_id, COUNT(*) as item_count
                FROM shipment_items GROUP BY shipment_id
            ) si ON si.shipment_id = s.id
            WHERE {where}
            {sort_clause}
        '''
        paginated_sql, all_params, size, offset = paginate(base_sql, params, page=page, page_size=limit)
        rows = db.execute(paginated_sql, all_params).fetchall()
        return {'shipments': [dict(r) for r in rows], 'total': total, 'page': page, 'limit': size}

    @staticmethod
    def create_shipment(data, created_by):
        shipment_no = data.get('shipment_no', '')
        if not shipment_no:
            db = BaseService.db()
            shipment_no = _generate_shipment_no(db)

        items = data.get('items', [])
        if not items:
            raise ValueError('请添加出库产品')

        total_qty = sum(item.get('quantity', 0) for item in items)

        # 库存校验
        db = BaseService.db()
        for item in items:
            inv = db.execute(
                'SELECT quantity, product_model, product_name FROM inventory WHERE id = ?',
                (item.get('inventory_id', 0),)
            ).fetchone()
            if not inv:
                raise ValueError(f'库存记录不存在 (ID:{item.get("inventory_id")})')
            if inv['quantity'] < item.get('quantity', 0):
                raise ValueError(f'{inv["product_model"]} {inv["product_name"]}: 库存不足 (当前{inv["quantity"]}，需要{item["quantity"]})')

        with BaseService.transaction() as txn:
            try:
                cur = txn.execute('''
                    INSERT INTO shipments (shipment_no, customer, contact_person,
                        contact_phone, address, status, total_quantity, remark, created_by, deduction_mode, material_bill_no, receivable_amount)
                    VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)
                ''', (shipment_no, data.get('customer', ''), data.get('contact_person', ''),
                      data.get('contact_phone', ''), data.get('address', ''),
                      total_qty, data.get('remark', ''), created_by,
                      data.get('deduction_mode', 'on_complete'),
                      data.get('material_bill_no', ''), data.get('receivable_amount', 0)))
            except Exception as e:
                if 'UNIQUE' in str(e):
                    raise ValueError('出库单号已存在，请稍后重试')
                raise
            shipment_id = cur.lastrowid
            # Resolve order_id from first item (shipment-level order association)
            order_id = data.get('order_id') or (items[0].get('order_id') if items else None)
            order_no_val = data.get('order_no', '')
            if order_id and not order_no_val:
                ord_row = txn.execute("SELECT order_no FROM orders WHERE id = ?", (order_id,)).fetchone()
                order_no_val = ord_row["order_no"] if ord_row else ""

            for item in items:
                item_order_id = item.get('order_id') or order_id
                item_order_no = item.get('order_no') or order_no_val
                if item_order_id and not item_order_no:
                    ord_row = txn.execute("SELECT order_no FROM orders WHERE id = ?", (item_order_id,)).fetchone()
                    item_order_no = ord_row["order_no"] if ord_row else ""
                # Resolve product_code from inventory or products
                product_code = item.get('product_code', '')
                if not product_code:
                    inv_row = txn.execute("SELECT product_model FROM inventory WHERE id = ?", (item.get("inventory_id", 0),)).fetchone()
                    if inv_row:
                        prod_row = txn.execute("SELECT product_code FROM products WHERE product_code = ? AND deleted_at IS NULL ORDER BY id DESC LIMIT 1", (inv_row["product_model"],)).fetchone()
                        product_code = prod_row["product_code"] if prod_row else inv_row["product_model"]
                    else:
                        product_code = item.get('product_model', '')
                txn.execute('''
                    INSERT INTO shipment_items (shipment_id, inventory_id, product_model,
                        product_name, quantity, unit, remark, order_id, product_code, order_no)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (shipment_id, item.get('inventory_id', 0),
                      item.get('product_model', ''), item.get('product_name', ''),
                      item.get('quantity', 0), item.get('unit', '件'), item.get('remark', ''),
                      item_order_id, product_code, item_order_no))
            # P3: reserve stock for on_create mode
            if data.get('deduction_mode') == 'on_create':
                for item in items:
                    txn.execute('UPDATE inventory SET reserved = reserved + ? WHERE id = ?',
                               (item.get('quantity', 0), item.get('inventory_id', 0)))
                txn.execute("UPDATE shipments SET reserved_at = datetime('now','localtime') WHERE id = ?",
                           (shipment_id,))
            return shipment_id, shipment_no

    @staticmethod
    def get_shipment(shipment_id):
        db = BaseService.db()
        row = db.execute('SELECT * FROM shipments WHERE id = ?', (shipment_id,)).fetchone()
        if not row:
            return None
        items = db.execute('''
            SELECT si.*, COALESCE(i.product_model, si.product_model) as product_model,
                   COALESCE(i.product_name, si.product_name) as product_name
            FROM shipment_items si LEFT JOIN inventory i ON si.inventory_id = i.id
            WHERE si.shipment_id = ?
        ''', (shipment_id,)).fetchall()
        shipment = dict(row)
        shipment['items'] = [dict(r) for r in items]
        return shipment

    @staticmethod
    def update_shipment(shipment_id, data):
        db = BaseService.db()
        row = db.execute('SELECT * FROM shipments WHERE id = ?', (shipment_id,)).fetchone()
        if not row:
            raise ValueError('出库单不存在')
        fields = ['customer', 'contact_person', 'contact_phone', 'address', 'remark', 'status', 'receivable_amount', 'payment_status']
        updates = []
        params = []
        for f in fields:
            if f in data:
                if f == 'status' and data[f] == 'completed' and row['status'] != 'completed':
                    raise ValueError('请使用「完成出库」按钮完成出库')
                updates.append(f'{f} = ?')
                params.append(data[f])
        if not updates:
            raise ValueError('没有需要更新的字段')
        with BaseService.transaction() as txn:
            txn.execute(f'UPDATE shipments SET {", ".join(updates)} WHERE id = ?', params + [shipment_id])

    @staticmethod
    def delete_shipment(shipment_id, current_user):
        db = BaseService.db()
        row = db.execute('SELECT * FROM shipments WHERE id = ?', (shipment_id,)).fetchone()
        if not row:
            raise ValueError('出库单不存在')
        with BaseService.transaction() as txn:
            if row['status'] == 'completed':
                items = txn.execute('SELECT * FROM shipment_items WHERE shipment_id = ?', (shipment_id,)).fetchall()
                for item in items:
                    txn.execute('UPDATE inventory SET quantity = quantity + ? WHERE id = ?',
                               (item['quantity'], item['inventory_id']))
                    remark = f'删除出库单 {row["shipment_no"]} - 归还库存'
                    txn.execute('''
                        INSERT INTO inventory_logs (inventory_id, type, quantity, order_no,
                            remark, operator_id, operator_name)
                        VALUES (?, 'in', ?, ?, ?, ?, ?)
                    ''', (item['inventory_id'], item['quantity'], row['shipment_no'], remark,
                          current_user['id'], current_user['name']))
            txn.execute('DELETE FROM shipment_items WHERE shipment_id = ?', (shipment_id,))
            txn.execute('DELETE FROM shipments WHERE id = ?', (shipment_id,))
        return row['shipment_no']
    @staticmethod
    def complete_shipment(shipment_id, current_user):
        db = BaseService.db()
        row = db.execute('SELECT * FROM shipments WHERE id = ?', (shipment_id,)).fetchone()
        if not row:
            raise ValueError('出库单不存在')
        if row['status'] == 'completed':
            raise ValueError('出库单已完成')
        items = db.execute('SELECT * FROM shipment_items WHERE shipment_id = ?', (shipment_id,)).fetchall()
        if not items:
            raise ValueError('出库单无明细')

        sn = row['shipment_no']
        with BaseService.transaction() as txn:
            if row['reserved_at']:
                for item in items:
                    txn.execute('UPDATE inventory SET reserved = MAX(0, reserved - ?) WHERE id = ?',
                               (item['quantity'], item['inventory_id']))
            for item in items:
                cur = txn.execute(
                    'UPDATE inventory SET quantity = quantity - ? WHERE id = ? AND quantity >= ?',
                    (item['quantity'], item['inventory_id'], item['quantity']))
                if cur.rowcount == 0:
                    inv = txn.execute(
                        'SELECT quantity, product_model, product_name FROM inventory WHERE id = ?',
                        (item['inventory_id'],)).fetchone()
                    current = inv['quantity'] if inv else 0
                    model = inv['product_model'] if inv else item['product_model'] or '?'
                    raise ValueError(f'{model} {item["product_name"] or ""}: 库存不足 (库存{current}，需{item["quantity"]})')
                item_order_no = item['order_no'] if item['order_no'] else sn
                remark = f'出库单 {sn} 出库 {item["quantity"]} {item["unit"] or "件"}'
                txn.execute('''
                    INSERT INTO inventory_logs (inventory_id, type, quantity, order_no,
                        remark, operator_id, operator_name)
                    VALUES (?, 'out', ?, ?, ?, ?, ?)
                ''', (item['inventory_id'], item['quantity'], item_order_no, remark,
                      current_user['id'], current_user['name']))
            txn.execute(
                "UPDATE shipments SET status = 'completed', completed_at = ? WHERE id = ?",
                (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), shipment_id))
            ShipmentService._update_order_delivery_status(txn, shipment_id)
        return sn

    @staticmethod
    def batch_complete(ids, current_user):
        """批量完成出库单。"""
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
        """批量删除出库单。"""
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
        """更新物流信息。"""
        db = BaseService.db()
        row = db.execute("SELECT id FROM shipments WHERE id = ?", (shipment_id,)).fetchone()
        if not row:
            raise ValueError("出库单不存在")
        with BaseService.transaction() as txn:
            txn.execute(
                "UPDATE shipments SET logistics_company=?, tracking_no=? WHERE id=?",
                (data.get("logistics_company", ""), data.get("tracking_no", ""), shipment_id)
            )

    @staticmethod
    def receive_shipment(shipment_id, current_user, receiver="", receive_date=""):
        db = BaseService.db()
        row = db.execute("SELECT * FROM shipments WHERE id = ?", (shipment_id,)).fetchone()
        if not row:
            raise ValueError("出库单不存在")
        if row["status"] == "received":
            raise ValueError("已签收")
        if row["status"] != "completed":
            raise ValueError("仅已出库可签收")
        with BaseService.transaction() as txn:
            txn.execute(
                "UPDATE shipments SET status='received', remark = remark || ? WHERE id=?",
                ((" 签收人: " + receiver + " 签收日期: " + receive_date) if receiver else "", shipment_id)
            )
        return row["shipment_no"]

    @staticmethod
    def record_payment(shipment_id, current_user, amount, method="", remark=""):
        """记录收款。"""
        db = BaseService.db()
        row = db.execute("SELECT * FROM shipments WHERE id = ?", (shipment_id,)).fetchone()
        if not row:
            raise ValueError("出库单不存在")
        if row["status"] not in ("completed", "received"):
            raise ValueError("仅已出库或已签收可收款")
        new_paid = (row["paid_amount"] or 0) + amount
        receivable = row["receivable_amount"] or 0
        if new_paid > receivable:
            raise ValueError(f"收款金额超出应收({receivable})")
        payment_status = "paid" if new_paid >= receivable else "partial"
        with BaseService.transaction() as txn:
            txn.execute(
                "UPDATE shipments SET paid_amount = ?, payment_status = ?, payment_date = ?, payment_method = ?, payment_remark = ? WHERE id = ?",
                (new_paid, payment_status, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), method, remark, shipment_id)
            )
        return row["shipment_no"]

    @staticmethod
    def cancel_shipment(shipment_id, current_user):
        """取消出库单。已完成单需归还库存。"""
        db = BaseService.db()
        row = db.execute("SELECT * FROM shipments WHERE id = ?", (shipment_id,)).fetchone()
        if not row:
            raise ValueError("出库单不存在")
        if row["status"] == "cancelled":
            raise ValueError("出库单已取消")
        with BaseService.transaction() as txn:
            if row['reserved_at']:
                items_rel = txn.execute('SELECT * FROM shipment_items WHERE shipment_id = ?', (shipment_id,)).fetchall()
                for item in items_rel:
                    txn.execute('UPDATE inventory SET reserved = MAX(0, reserved - ?) WHERE id = ?',
                               (item['quantity'], item['inventory_id']))
            if row['status'] == 'completed':
                # 归还库存
                items = txn.execute("SELECT * FROM shipment_items WHERE shipment_id = ?", (shipment_id,)).fetchall()
                for item in items:
                    txn.execute("UPDATE inventory SET quantity = quantity + ? WHERE id = ?",
                               (item["quantity"], item["inventory_id"]))
                    txn.execute('''
                        INSERT INTO inventory_logs (inventory_id, type, quantity, order_no,
                            remark, operator_id, operator_name)
                        VALUES (?, 'in', ?, ?, ?, ?, ?)
                    ''', (item["inventory_id"], item["quantity"], row["shipment_no"],
                          f"取消出库单 {row['shipment_no']} - 归还库存",
                          current_user["id"], current_user["name"]))
            txn.execute(
                "UPDATE shipments SET status='cancelled', cancelled_at=datetime('now','localtime') WHERE id=?",
                (shipment_id,)
            )
        return row["shipment_no"]

    # P0: 按订单获取可出库库存
    @staticmethod
    def get_order_stock(order_id):
        db = BaseService.db()
        order = db.execute(
            "SELECT id, order_no, customer, product_name, product_code FROM orders WHERE id = ?",
            (order_id,)
        ).fetchone()
        if not order:
            raise ValueError("订单不存在")
        items = db.execute(
            "SELECT i.id as inventory_id, i.product_model, i.product_name, i.specification, "
            "i.quantity, i.unit, i.order_id FROM inventory i "
            "WHERE i.order_id = ? AND i.quantity > 0",
            (order_id,)
        ).fetchall()
        return { "order": dict(order), "items": [dict(it) for it in items] }

    # P2: stats
    @staticmethod
    def get_stats():
        db = BaseService.db()
        today = datetime.now().strftime("%Y-%m-%d")
        month_start = datetime.now().strftime("%Y-%m-01")
        stats = db.execute("SELECT COUNT(*) as total, COALESCE(SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END),0) as pending, COALESCE(SUM(CASE WHEN status='received' THEN 1 ELSE 0 END),0) as received, COALESCE(SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END),0) as completed, COALESCE(SUM(CASE WHEN status='cancelled' THEN 1 ELSE 0 END),0) as cancelled, COALESCE(SUM(CASE WHEN date(created_at)=? THEN 1 ELSE 0 END),0) as today_count, COALESCE(SUM(CASE WHEN date(created_at)>=? THEN 1 ELSE 0 END),0) as month_count, COALESCE(SUM(CASE WHEN date(completed_at)=? THEN 1 ELSE 0 END),0) as today_completed, COALESCE(SUM(CASE WHEN status='completed' THEN total_quantity ELSE 0 END),0) as total_shipped_qty, COALESCE(SUM(receivable_amount),0) as total_receivable, COALESCE(SUM(paid_amount),0) as total_paid, COALESCE(SUM(CASE WHEN payment_status='paid' THEN 1 ELSE 0 END),0) as paid_count, COALESCE(SUM(CASE WHEN payment_status='partial' THEN 1 ELSE 0 END),0) as partial_paid FROM shipments", (today, month_start, today)).fetchone()
        return dict(stats)

    @staticmethod
    def get_customer_history(customer, limit=50):
        db = BaseService.db()
        rows = db.execute("SELECT s.*, COALESCE(si.item_count,0) as item_count FROM shipments s LEFT JOIN (SELECT shipment_id, COUNT(*) as item_count FROM shipment_items GROUP BY shipment_id) si ON si.shipment_id = s.id WHERE s.customer = ? ORDER BY s.created_at DESC LIMIT ?", (customer, limit)).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _update_order_delivery_status(txn, shipment_id):
        items = txn.execute("SELECT DISTINCT order_id FROM shipment_items WHERE shipment_id = ? AND order_id IS NOT NULL", (shipment_id,)).fetchall()
        for item in items:
            if item["order_id"]:
                total_shipped = txn.execute("SELECT COALESCE(SUM(si.quantity),0) as shipped_qty FROM shipment_items si JOIN shipments s ON s.id = si.shipment_id WHERE si.order_id = ? AND s.status = 'completed'", (item["order_id"],)).fetchone()
                shipped_qty = total_shipped["shipped_qty"] if total_shipped else 0
                order_row = txn.execute("SELECT quantity FROM orders WHERE id = ?", (item["order_id"],)).fetchone()
                if order_row:
                    total_qty = order_row["quantity"]
                    status = "全部发货" if shipped_qty >= total_qty else ("部分发货" if shipped_qty > 0 else None)
                    if status:
                        txn.execute("UPDATE orders SET delivery_status = ?, updated_at = datetime('now','localtime') WHERE id = ?", (status, item["order_id"]))
