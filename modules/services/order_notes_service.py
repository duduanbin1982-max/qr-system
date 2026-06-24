"""qr-system - OrderNotesService"""
from modules.services import BaseService
from modules.repositories.order_notes_repository import OrderNotesRepository


class OrderNotesService:
    @staticmethod
    def get_remarks(oid, page=1, limit=20):
        order = OrderNotesRepository.find_order(oid)
        if not order:
            raise ValueError('Order not found')

        total = OrderNotesRepository.count_history(oid)
        offset = (page - 1) * limit
        rows = OrderNotesRepository.list_history(oid, limit, offset)

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
