"""
qr-system — 物料管理 Service 层

从 routes/materials.py 提取物料 + 供应商业务逻辑。
"""
from datetime import datetime
from modules.services import BaseService


class MaterialService:
    """物料管理业务逻辑。"""

    @staticmethod
    def list_materials():
        """物料列表（含供应商名称）。"""
        db = BaseService.db()
        rows = db.execute('''
            SELECT m.*, s.name as supplier_name
            FROM materials m LEFT JOIN suppliers s ON m.supplier_id = s.id
            ORDER BY m.id DESC
        ''').fetchall()
        return {'materials': [dict(r) for r in rows]}

    @staticmethod
    def create_material(data):
        """创建物料。Raises ValueError on empty name."""
        name = data.get('name', '').strip()
        if not name:
            raise ValueError('物料名称不能为空')
        with BaseService.transaction() as txn:
            txn.execute(
                'INSERT INTO materials '
                '(name, spec, unit, quantity, unit_price, safe_stock, '
                'location, supplier_id, remark) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (name,
                 data.get('spec', '').strip(),
                 data.get('unit', '件').strip(),
                 float(data.get('quantity', 0)),
                 float(data.get('unit_price', 0)),
                 float(data.get('safe_stock', 0)),
                 data.get('location', '').strip(),
                 data.get('supplier_id') or None,
                 data.get('remark', '').strip())
            )

    @staticmethod
    def update_material(mid, data):
        """更新物料。Raises ValueError on not found or no fields."""
        db = BaseService.db()
        row = db.execute(
            'SELECT id FROM materials WHERE id = ?', (mid,)
        ).fetchone()
        if not row:
            raise ValueError('物料不存在')

        fields = []
        values = []
        for k in ['name', 'spec', 'unit', 'location', 'remark']:
            if k in data:
                fields.append(f'{k} = ?')
                values.append(str(data[k]).strip())
        for k in ['quantity', 'unit_price', 'safe_stock', 'supplier_id']:
            if k in data:
                fields.append(f'{k} = ?')
                values.append(float(data[k]))
        if not fields:
            raise ValueError('no fields to update')

        fields.append("updated_at = datetime('now','localtime')")
        with BaseService.transaction() as txn:
            txn.execute(
                f'UPDATE materials SET {", ".join(fields)} WHERE id = ?',
                values + [mid]
            )

    @staticmethod
    def delete_material(mid):
        """删除物料。"""
        with BaseService.transaction() as txn:
            txn.execute('DELETE FROM materials WHERE id = ?', (mid,))

    @staticmethod
    def get_logs(mid):
        """物料库存日志。"""
        db = BaseService.db()
        rows = db.execute(
            'SELECT ml.*, u.name as operator_name_from_fk FROM material_logs ml'
            ' LEFT JOIN users u ON ml.operator_id = u.id WHERE ml.material_id = ? '
            'ORDER BY ml.created_at DESC LIMIT 100', (mid,)
        ).fetchall()
        return {'logs': [dict(r) for r in rows]}

    @staticmethod
    def stock_change(mid, change_type, quantity, remark='', operator_name=''):
        """物料入库/出库。"""
        if change_type not in ('in', 'out'):
            raise ValueError('类型必须是 in 或 out')
        if quantity <= 0:
            raise ValueError('数量必须大于0')

        db = BaseService.db()
        row = db.execute(
            'SELECT id, quantity FROM materials WHERE id = ?', (mid,)
        ).fetchone()
        if not row:
            raise ValueError('物料不存在')

        new_qty = (row['quantity'] + quantity if change_type == 'in'
                   else row['quantity'] - quantity)
        if new_qty < 0 and change_type == 'out':
            raise ValueError(f'库存不足，当前库存 {row["quantity"]}')

        with BaseService.transaction() as txn:
            txn.execute(
                'UPDATE materials SET quantity = ?, '
                'updated_at = datetime("now","localtime") WHERE id = ?',
                (new_qty, mid)
            )
            txn.execute(
                'INSERT INTO material_logs '
                '(material_id, type, quantity, remark, operator_name) '
                'VALUES (?, ?, ?, ?, ?)',
                (mid, change_type, quantity, remark, operator_name)
            )
        return new_qty

    @staticmethod
    def list_consumptions(mid):
        """物料消耗记录（含订单/工序信息）。"""
        db = BaseService.db()
        rows = db.execute('''
            SELECT mc.*, o.order_no, o.product_name, p.name as process_name,
                   u.name as operator_name_from_fk
            FROM material_consumptions mc
            LEFT JOIN orders o ON mc.order_id = o.id
            LEFT JOIN processes p ON mc.process_id = p.id
            LEFT JOIN users u ON mc.operator_id = u.id
            WHERE mc.material_id = ?
            ORDER BY mc.created_at DESC LIMIT 100
        ''', (mid,)).fetchall()
        return {'consumptions': [dict(r) for r in rows]}

    @staticmethod
    def create_consumption(mid, order_id, process_id, quantity, notes='',
                           operator_name='', user_id=None):
        """记录物料消耗（扣减库存）。"""
        if quantity <= 0:
            raise ValueError('数量必须大于0')

        db = BaseService.db()
        mat = db.execute(
            'SELECT id, quantity FROM materials WHERE id=?', (mid,)
        ).fetchone()
        if not mat:
            raise ValueError('物料不存在')
        if mat['quantity'] < quantity:
            raise ValueError(f'库存不足，当前库存 {mat["quantity"]}')

        with BaseService.transaction() as txn:
            txn.execute('''
                INSERT INTO material_consumptions
                (material_id, order_id, process_id, quantity,
                 operator_id, operator_name, notes)
                VALUES (?,?,?,?,?,?,?)
            ''', (mid, order_id or None, process_id or None, quantity,
                  user_id, operator_name, notes))
            new_qty = mat['quantity'] - quantity
            txn.execute(
                "UPDATE materials SET quantity=?, "
                "updated_at=datetime('now','localtime') WHERE id=?",
                (new_qty, mid)
            )
            txn.execute(
                'INSERT INTO material_logs '
                '(material_id, type, quantity, remark, operator_name) '
                'VALUES (?,?,?,?,?)',
                (mid, 'out', quantity,
                 f'消耗: {notes}' if notes else '消耗', operator_name)
            )
        return new_qty

    @staticmethod
    def delete_consumption(cid):
        """撤销物料消耗（归还库存）。"""
        db = BaseService.db()
        mc = db.execute(
            'SELECT * FROM material_consumptions WHERE id=?', (cid,)
        ).fetchone()
        if not mc:
            raise ValueError('记录不存在')

        with BaseService.transaction() as txn:
            txn.execute(
                'UPDATE materials SET quantity=quantity+?, '
                'updated_at=datetime("now","localtime") WHERE id=?',
                (mc['quantity'], mc['material_id'])
            )
            txn.execute('DELETE FROM material_consumptions WHERE id=?', (cid,))


class SupplierService:
    """供应商管理业务逻辑。"""

    @staticmethod
    def list_suppliers():
        """供应商列表。"""
        db = BaseService.db()
        rows = db.execute('SELECT * FROM suppliers ORDER BY name').fetchall()
        return {'suppliers': [dict(r) for r in rows]}

    @staticmethod
    def create_supplier(data):
        """创建供应商。"""
        name = data.get('name', '').strip()
        if not name:
            raise ValueError('供应商名称不能为空')
        with BaseService.transaction() as txn:
            txn.execute(
                'INSERT INTO suppliers (name, contact, phone, address, remark) '
                'VALUES (?,?,?,?,?)',
                (name, data.get('contact', '').strip(),
                 data.get('phone', '').strip(),
                 data.get('address', '').strip(),
                 data.get('remark', '').strip())
            )
            return txn.execute('SELECT last_insert_rowid()').fetchone()[0]

    @staticmethod
    def update_supplier(sid, data):
        """更新供应商。"""
        db = BaseService.db()
        row = db.execute(
            'SELECT id FROM suppliers WHERE id=?', (sid,)
        ).fetchone()
        if not row:
            raise ValueError('供应商不存在')
        with BaseService.transaction() as txn:
            txn.execute(
                'UPDATE suppliers SET name=?, contact=?, phone=?, '
                'address=?, remark=? WHERE id=?',
                (data.get('name', '').strip(),
                 data.get('contact', '').strip(),
                 data.get('phone', '').strip(),
                 data.get('address', '').strip(),
                 data.get('remark', '').strip(), sid)
            )

    @staticmethod
    def delete_supplier(sid):
        """删除供应商。"""
        with BaseService.transaction() as txn:
            txn.execute('DELETE FROM suppliers WHERE id=?', (sid,))
