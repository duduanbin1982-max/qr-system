"""Read-only audit-log query service."""
from modules.repositories.audit_log_repository import AuditLogRepository


class AuditLogService:

    @staticmethod
    def list_logs(page=1, limit=50, action='', keyword='', user_id=None, category='', date_from='', date_to=''):
        return AuditLogRepository.list_logs(
            page=page, limit=limit, action=action, keyword=keyword,
            user_id=user_id, category=category, date_from=date_from, date_to=date_to
        )
