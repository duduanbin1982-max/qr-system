"""qr-system — 返工管理 Service 层"""
from datetime import datetime
from modules.services import BaseService


class ReworkService:

    @staticmethod
    def list_rework(status='', search='', date_from='', date_to='', page=1, per_page=50):
        db = BaseService.db()
        where = ['1=1']
        params = []
        if status:
            where.append('rw.status = ?'); params.append(status)
        if search:
            where.append('(o.order_no LIKE ? OR p.name LIKE ? OR u.name LIKE ?)')
            params.extend([f'%{search}%'] * 3)
        if date_from:
            where.append('rw.created_at >= ?'); params.append(date_from)
        if date_to:
            where.append('rw.created_at <= ?'); params.append(date_to + ' 23:59:59')

        where_clause = ' AND '.join(where)
        total = db.execute(f'''SELECT COUNT(*) FROM rework_records rw
            JOIN orders o ON rw.order_id=o.id
            JOIN processes p ON rw.process_id=p.id
            LEFT JOIN users u ON rw.user_id=u.id
            WHERE {where_clause}''', params).fetchone()[0]

        offset = (page - 1) * per_page
        rows = db.execute(f'''
            SELECT rw.*, o.order_no, o.product_name,
                   COALESCE(c.name, o.customer) as customer_name,
                   p.name as process_name, u.name as worker_name,
                   cu.name as completed_by_name
            FROM rework_records rw
            JOIN orders o ON rw.order_id = o.id
            LEFT JOIN customers c ON o.customer_id = c.id
            JOIN processes p ON rw.process_id = p.id
            LEFT JOIN users u ON rw.user_id = u.id
            LEFT JOIN users cu ON rw.completed_by = cu.id
            WHERE {where_clause}
            ORDER BY rw.created_at DESC LIMIT ? OFFSET ?
        ''', params + [per_page, offset]).fetchall()
        return {'ok': True, 'items': [dict(r) for r in rows],
                'total': total, 'page': page, 'per_page': per_page}

    @staticmethod
    def get_stats():
        db = BaseService.db()
        today = datetime.now().strftime('%Y-%m-%d')
        pending = db.execute(
            "SELECT COUNT(*), COALESCE(SUM(quantity),0) FROM rework_records WHERE status='pending'").fetchone()
        today_total = db.execute(
            "SELECT COUNT(*), COALESCE(SUM(quantity),0) FROM rework_records WHERE DATE(created_at)=?", (today,)).fetchone()
        today_done = db.execute(
            "SELECT COUNT(*), COALESCE(SUM(quantity),0) FROM rework_records WHERE DATE(completed_at)=?", (today,)).fetchone()
        return {'ok': True,
                'pending_count': pending[0], 'pending_qty': pending[1] or 0,
                'today_count': today_total[0], 'today_qty': today_total[1] or 0,
                'today_done': today_done[0], 'today_done_qty': today_done[1] or 0}

    @staticmethod
    def update_rework(rework_id, reason):
        db = BaseService.db()
        rw = db.execute('SELECT * FROM rework_records WHERE id = ?', (rework_id,)).fetchone()
        if not rw:
            raise ValueError('记录不存在')
        with BaseService.transaction() as txn:
            txn.execute('UPDATE rework_records SET reason = ? WHERE id = ?', (reason, rework_id))

    @staticmethod
    def complete_rework(rework_id, reason, user_id):
        db = BaseService.db()
        rw = db.execute('SELECT * FROM rework_records WHERE id = ?', (rework_id,)).fetchone()
        if not rw:
            raise ValueError('返工记录不存在')
        if rw['status'] == 'completed':
            raise ValueError('该记录已完成')

        with BaseService.transaction() as txn:
            reason_final = reason or rw['reason']
            txn.execute('''UPDATE rework_records SET status = 'completed', reason = ?,
                          completed_at = datetime("now","localtime"),
                          completed_by = ? WHERE id = ?''', (reason_final, user_id, rework_id))
            txn.execute(
                'UPDATE order_processes SET rework = MAX(rework - ?, 0) '
                'WHERE order_id = ? AND process_id = ?',
                (rw['quantity'], rw['order_id'], rw['process_id']))
            txn.execute(
                'UPDATE orders SET rework = (SELECT COALESCE(SUM(rework),0) '
                'FROM order_processes WHERE order_id = ?), '
                'updated_at = datetime("now","localtime") WHERE id = ?',
                (rw['order_id'], rw['order_id']))
