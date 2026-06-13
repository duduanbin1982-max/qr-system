"""
qr-system — 库存管理 Service 层

从 routes/inventory.py 提取全部业务逻辑。
"""
import sqlite3
from datetime import datetime
from modules.services import BaseService


class InventoryService:
    """库存管理业务逻辑。"""

    @staticmethod
    def list_items(keyword='', low_stock=False, page=1, limit=100):
        """库存列表（搜索 + 低库存筛选 + 分页）。"""
        db = BaseService.db()
        clauses = ['1=1']
        params = []
        if keyword:
            clauses.append('(product_model LIKE ? OR product_name LIKE ?)')
            params.extend([f'%{keyword}%', f'%{keyword}%'])
        if low_stock:
            clauses.append('quantity <= safe_stock AND safe_stock > 0')
        where = ' AND '.join(clauses)
        total = db.execute(
            'SELECT COUNT(*) FROM inventory WHERE ' + where, params
        ).fetchone()[0]
        offset = (page - 1) * limit
        rows = db.execute(
            'SELECT *, CASE WHEN quantity <= safe_stock AND safe_stock > 0 '
            'THEN 1 ELSE 0 END as is_low FROM inventory WHERE ' + where
            + ' ORDER BY updated_at DESC LIMIT ? OFFSET ?',
            params + [limit, offset]
        ).fetchall()
        return {'items': [dict(r) for r in rows], 'total': total, 'page': page, 'limit': limit}

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
                        quantity, safe_stock, location, unit, remark)
                    VALUES (?,?,?,?,?,?,?,?)
                ''', (
                    model,
                    data.get('product_name', ''),
                    data.get('specification', ''),
                    data.get('quantity', 0),
                    data.get('safe_stock', 0),
                    data.get('location', ''),
                    data.get('unit', '件'),
                    data.get('remark', '')
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
                'SELECT id FROM inventory WHERE product_model = ? AND id != ?',
                (model, item_id)
            ).fetchone()
            if dup:
                raise ValueError('产品型号已存在')
            txn.execute('''
                UPDATE inventory SET
                    product_model = ?, product_name = ?, specification = ?,
                    quantity = ?, safe_stock = ?, location = ?, unit = ?, remark = ?,
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
    def get_logs(inv_id='', type_filter='', page=1, limit=20):
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
