"""qr-system - AuditLogService"""
from modules.services import BaseService
from modules.repositories.audit_log_repository import AuditLogRepository


class AuditLogService:

    @staticmethod
    def list_logs(page=1, limit=50, action='', keyword='', user_id=None, category='', date_from='', date_to=''):
        return AuditLogRepository.list_logs(
            page=page, limit=limit, action=action, keyword=keyword,
            user_id=user_id, category=category, date_from=date_from, date_to=date_to
        )

    @staticmethod
    def get_user_roles(uid):
        return AuditLogRepository.get_user_roles(uid)

    @staticmethod
    def set_user_roles(uid, role_ids):
        with BaseService.transaction() as txn:
            AuditLogRepository.set_user_roles_txn(uid, role_ids, db=txn)

    @staticmethod
    def batch_set_roles(user_ids, role_ids, action='set'):
        valid, invalid = AuditLogRepository.validate_role_ids(role_ids)
        if invalid:
            raise ValueError('Invalid role IDs: ' + ', '.join(invalid))
        with BaseService.transaction() as txn:
            AuditLogRepository.batch_set_roles_txn(user_ids, role_ids, action, db=txn)

    @staticmethod
    def get_permission_matrix():
        users = AuditLogRepository.get_active_users()
        all_rows = AuditLogRepository.get_user_role_mappings()
        all_roles = AuditLogRepository.get_all_roles()
        return {
            'users': [dict(u) for u in users],
            'all_rows': [dict(r) for r in all_rows],
            'all_roles': [dict(r) for r in all_roles],
        }

    @staticmethod
    def list_menu_permissions():
        return AuditLogRepository.list_menu_permissions()

    @staticmethod
    def create_menu_permission(data):
        page = data.get('page', '').strip()
        if not page:
            raise ValueError('Page required')
        existing = AuditLogRepository.find_menu_by_page(page)
        if existing:
            raise ValueError('Menu page exists: ' + page)
        with BaseService.transaction() as txn:
            AuditLogRepository.insert_menu_permission_txn(
                page, data.get('permission', ''), data.get('label', ''),
                data.get('icon', ''), data.get('sort_order', 0), db=txn
            )

    @staticmethod
    def update_menu_permission(page, data):
        row = AuditLogRepository.find_menu_by_page(page)
        if not row:
            raise ValueError('Menu not found')
        updates = {}
        for field in ['permission', 'label', 'icon', 'sort_order']:
            if field in data:
                updates[field] = data[field]
        if not updates:
            raise ValueError('no fields to update')
        set_clause = ', '.join(k + ' = ?' for k in updates)
        values = list(updates.values()) + [page]
        with BaseService.transaction() as txn:
            AuditLogRepository.update_menu_permission_txn(page, set_clause, values, db=txn)

    @staticmethod
    def delete_menu_permission(page):
        row = AuditLogRepository.find_menu_by_page(page)
        if not row:
            raise ValueError('Menu not found')
        with BaseService.transaction() as txn:
            AuditLogRepository.delete_menu_permission_txn(page, db=txn)

    @staticmethod
    def batch_update_menu_permissions(items):
        with BaseService.transaction() as txn:
            AuditLogRepository.batch_update_menu_permissions_txn(items, db=txn)

    @staticmethod
    def clear_logs(before_days=90):
        with BaseService.transaction() as txn:
            return AuditLogRepository.clear_logs_txn(before_days, db=txn)
