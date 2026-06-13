"""qr-system — 出库管理 Service 层"""
from datetime import datetime
from modules.services import BaseService


def _generate_shipment_no(db):
    today = datetime.now().strftime('%Y%m%d')
    row = db.execute(
        "SELECT MAX(CAST(SUBSTR(shipment_no, 11) AS INTEGER)) as max_seq "
        "FROM shipments WHERE shipment_no LIKE ?", (f'SH{today}-%',)
    ).fetchone()
    seq = (row['max_seq'] if row and row['max_seq'] else 0) + 1
    return f'SH{today}-{seq:03d}'


class ShipmentService:

    @staticmethod
    def generate_no():
        db = BaseService.db()
        return _generate_shipment_no(db)

    @staticmethod
    def list_shipments(keyword='', status='', page=1, limit=20):
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
        rows = db.execute(f'''
            SELECT s.*, COALESCE(si.item_count, 0) as item_count
            FROM shipments s
            LEFT JOIN (
                SELECT shipment_id, COUNT(*) as item_count
                FROM shipment_items GROUP BY shipment_id
            ) si ON si.shipment_id = s.id
            WHERE {where}
            ORDER BY s.created_at DESC LIMIT ? OFFSET ?
        ''', params + [limit, (page - 1) * limit]).fetchall()
        return {'shipments': [dict(r) for r in rows], 'total': total, 'page': page, 'limit': limit}

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
                        contact_phone, address, status, total_quantity, remark, created_by)
                    VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                ''', (shipment_no, data.get('customer', ''), data.get('contact_person', ''),
                      data.get('contact_phone', ''), data.get('address', ''),
                      total_qty, data.get('remark', ''), created_by))
            except Exception as e:
                if 'UNIQUE' in str(e):
                    raise ValueError('出库单号已存在，请稍后重试')
                raise
            shipment_id = cur.lastrowid
            for item in items:
                txn.execute('''
                    INSERT INTO shipment_items (shipment_id, inventory_id, product_model,
                        product_name, quantity, unit, remark)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (shipment_id, item.get('inventory_id', 0),
                      item.get('product_model', ''), item.get('product_name', ''),
                      item.get('quantity', 0), item.get('unit', '件'), item.get('remark', '')))
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
        fields = ['customer', 'contact_person', 'contact_phone', 'address', 'remark', 'status']
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
                remark = f'出库单 {sn} 出库 {item["quantity"]} {item["unit"] or "件"}'
                txn.execute('''
                    INSERT INTO inventory_logs (inventory_id, type, quantity, order_no,
                        remark, operator_id, operator_name)
                    VALUES (?, 'out', ?, ?, ?, ?, ?)
                ''', (item['inventory_id'], item['quantity'], sn, remark,
                      current_user['id'], current_user['name']))
            txn.execute(
                "UPDATE shipments SET status = 'completed', completed_at = ? WHERE id = ?",
                (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), shipment_id))
        return sn
