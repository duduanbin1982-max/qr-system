"""Read-only user-role and permission-matrix queries."""

from modules.repositories.audit_log_repository import AuditLogRepository


class PermissionQueryService:
    @staticmethod
    def get_user_roles(uid):
        return AuditLogRepository.get_user_roles(uid)

    @staticmethod
    def get_permission_matrix():
        users = AuditLogRepository.get_active_users()
        mappings = AuditLogRepository.get_user_role_mappings()
        roles = AuditLogRepository.get_all_roles()
        return {
            "users": [dict(user) for user in users],
            "all_rows": [dict(row) for row in mappings],
            "all_roles": [dict(role) for role in roles],
        }
