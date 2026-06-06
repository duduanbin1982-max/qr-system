"""
qr-system — 客户管理 Service 层

从 routes/customers.py 提取全部业务逻辑。
"""
from modules.services import BaseService


class CustomerService:
    """客户管理业务逻辑。"""

    @staticmethod
    def list_customers(keyword=''):
        """客户列表（支持搜索）。"""
        db = BaseService.db()
        where = '1=1'
        params = []
        if keyword:
            where += ' AND (name LIKE ? OR contact LIKE ? OR phone LIKE ?)'
            params.extend([f'%{keyword}%', f'%{keyword}%', f'%{keyword}%'])
        rows = db.execute(
            f'SELECT * FROM customers WHERE {where} ORDER BY id DESC', params
        ).fetchall()
        return {'customers': [dict(r) for r in rows]}

    @staticmethod
    def create_customer(data):
        """创建客户。Raises ValueError on empty name or duplicate."""
        name = data.get('name', '').strip()
        if not name:
            raise ValueError('客户名称不能为空')
        db = BaseService.db()
        existing = db.execute(
            'SELECT id FROM customers WHERE name = ?', (name,)
        ).fetchone()
        if existing:
            raise ValueError('客户名称已存在')
        with BaseService.transaction() as txn:
            cur = txn.execute('''
                INSERT INTO customers (name, contact, phone, email, address, remark)
                VALUES (?,?,?,?,?,?)
            ''', (name, data.get('contact', ''), data.get('phone', ''),
                  data.get('email', ''), data.get('address', ''), data.get('remark', '')))
            return cur.lastrowid

    @staticmethod
    def update_customer(cid, data):
        """更新客户。Raises ValueError on empty/missing name or duplicate."""
        db = BaseService.db()
        if 'name' in data:
            name = (data.get('name') or '').strip()
            if not name:
                raise ValueError('客户名称不能为空')
            existing = db.execute(
                'SELECT id FROM customers WHERE name = ? AND id != ?', (name, cid)
            ).fetchone()
            if existing:
                raise ValueError('客户名称已存在')
            data['name'] = name

        sets = []
        params = []
        for field in ['name', 'contact', 'phone', 'email', 'address', 'remark']:
            if field in data:
                sets.append(f'{field} = ?')
                params.append(data[field])
        if not sets:
            raise ValueError('无更新内容')

        sets.append('updated_at = datetime("now","localtime")')
        with BaseService.transaction() as txn:
            txn.execute(
                f'UPDATE customers SET {", ".join(sets)} WHERE id = ?',
                params + [cid]
            )

    @staticmethod
    def delete_customer(cid):
        """删除客户。FK RESTRICT 保证有订单的客户无法删除。"""
        with BaseService.transaction() as txn:
            txn.execute('DELETE FROM customers WHERE id = ?', (cid,))

    @staticmethod
    def get_customer_orders(cid):
        """获取客户的订单历史（含工序详情和 extra_fields 解析）。"""
        import json
        db = BaseService.db()
        rows = db.execute('''
            SELECT o.*, pr.name as route_name
            FROM orders o
            LEFT JOIN process_routes pr ON o.route_id = pr.id
            WHERE o.customer_id = ? AND o.deleted_at IS NULL
            ORDER BY o.created_at DESC
        ''', (cid,)).fetchall()

        result = []
        for row in rows:
            o = dict(row)
            try:
                o['extra_fields'] = json.loads(o.get('extra_fields') or '{}')
            except Exception:
                o['extra_fields'] = {}
            procs = db.execute('''
                SELECT op.*, p.name as process_name
                FROM order_processes op JOIN processes p ON op.process_id = p.id
                WHERE op.order_id = ? ORDER BY op.seq_order
            ''', (o['id'],)).fetchall()
            o['processes'] = [dict(p) for p in procs]
            result.append(o)
        return {'orders': result}
