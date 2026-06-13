"""
qr-system — OrderNotesService
"""
from modules.services import BaseService


class OrderNotesService:
    @staticmethod
    def get_remarks(oid, page=1, limit=20):
        db = BaseService.db()
        order = db.execute(
            'SELECT id, order_no, remark FROM orders WHERE id = ? AND deleted_at IS NULL',
            (oid,)
        ).fetchone()
        if not order:
            raise ValueError('Order not found')

        total = db.execute(
            'SELECT COUNT(*) FROM order_remark_history WHERE order_id = ?', (oid,)
        ).fetchone()[0]
        offset = (page - 1) * limit
        rows = db.execute('''
            SELECT id, old_remark, new_remark, user_id, user_name, created_at
            FROM order_remark_history WHERE order_id = ?
            ORDER BY id DESC LIMIT ? OFFSET ?
        ''', (oid, limit, offset)).fetchall()

        history = [{
            'id': r['id'], 'old_remark': r['old_remark'],
            'new_remark': r['new_remark'], 'user_id': r['user_id'],
            'user_name': r['user_name'], 'created_at': r['created_at'],
        } for r in rows]

        return {
            'order_id': oid, 'order_no': order['order_no'],
            'current_remark': order['remark'] or '',
            'total': total, 'page': page, 'limit': limit, 'history': history,
        }
