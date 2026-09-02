"""Menu-permission lifecycle service."""

from modules.domain.errors import ConflictError, NotFoundError
from modules.repositories.audit_log_repository import AuditLogRepository
from modules.services import BaseService


class MenuPermissionService:
    @staticmethod
    def list_items():
        return AuditLogRepository.list_menu_permissions()

    @staticmethod
    def create(data):
        page = data.get("page", "").strip()
        if not page:
            raise ValueError("Page required")
        if AuditLogRepository.find_menu_by_page(page):
            raise ConflictError("Menu page exists: " + page)
        with BaseService.transaction() as txn:
            AuditLogRepository.insert_menu_permission_txn(
                page,
                data.get("permission", ""),
                data.get("label", ""),
                data.get("icon", ""),
                data.get("sort_order", 0),
                db=txn,
            )

    @staticmethod
    def update(page, data):
        if not AuditLogRepository.find_menu_by_page(page):
            raise NotFoundError("Menu not found")
        updates = {
            field: data[field]
            for field in ("permission", "label", "icon", "sort_order")
            if field in data
        }
        if not updates:
            raise ValueError("no fields to update")
        set_clause = ", ".join(field + " = ?" for field in updates)
        values = list(updates.values()) + [page]
        with BaseService.transaction() as txn:
            AuditLogRepository.update_menu_permission_txn(
                page, set_clause, values, db=txn
            )

    @staticmethod
    def delete(page):
        if not AuditLogRepository.find_menu_by_page(page):
            raise NotFoundError("Menu not found")
        with BaseService.transaction() as txn:
            AuditLogRepository.delete_menu_permission_txn(page, db=txn)

    @staticmethod
    def batch_update(items):
        with BaseService.transaction() as txn:
            AuditLogRepository.batch_update_menu_permissions_txn(items, db=txn)
