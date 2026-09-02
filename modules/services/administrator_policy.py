"""Administrator authorization and role-permission invariants."""
import json

from modules.domain.errors import AuthorizationError, ConflictError, ValidationError
from modules.permission_catalog import ALL_PERMISSION_CODES, infer_page_permissions
from modules.repositories.user_repository import UserRepository


class AdministratorPolicy:
    """Security rules that must hold for every administrator mutation."""

    @staticmethod
    def require_actual_admin(actor_id, db, message="仅系统管理员可以修改角色和权限"):
        if not actor_id or not UserRepository.check_admin_role(actor_id, db=db):
            raise AuthorizationError(message)

    @staticmethod
    def protect_admin_accounts(actor_id, target_user_ids, db):
        target_ids = [int(user_id) for user_id in target_user_ids if user_id]
        if not UserRepository.admin_assignment_ids(target_ids, db=db):
            return
        AdministratorPolicy.require_actual_admin(
            actor_id,
            db,
            message="仅系统管理员可以修改管理员账号",
        )

    @staticmethod
    def normalize_status(value):
        status = str(value or "").strip().lower()
        if status not in {"active", "inactive"}:
            raise ValidationError("状态只能是 active 或 inactive")
        return status

    @staticmethod
    def normalize_permissions(value, *, allow_wildcard=False):
        if value in (None, ""):
            permissions = []
        elif isinstance(value, str):
            try:
                permissions = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValidationError("权限必须是有效的 JSON 数组") from exc
        elif isinstance(value, list):
            permissions = value
        else:
            raise ValidationError("权限必须是数组")

        if not isinstance(permissions, list) or any(
            not isinstance(item, str) or not item.strip() for item in permissions
        ):
            raise ValidationError("权限数组只能包含非空字符串")

        normalized = list(dict.fromkeys(item.strip() for item in permissions))
        if "*" in normalized:
            if not allow_wildcard or normalized != ["*"]:
                raise ConflictError("通配权限仅限内置系统管理员角色")
            return normalized

        catalog = set(ALL_PERMISSION_CODES)
        invalid = sorted(set(normalized) - catalog)
        if invalid:
            raise ValidationError("未知权限编码：" + "、".join(invalid))
        # Persist the same page chain used by the server and frontend. This
        # keeps newly-created roles from relying on a client-side inference.
        normalized.extend(
            code for code in infer_page_permissions(normalized)
            if code not in normalized
        )
        return normalized

    @staticmethod
    def normalize_group_permissions(value):
        permissions = AdministratorPolicy.normalize_permissions(value)
        if permissions:
            raise ConflictError("角色组仅用于分类，不能直接授予权限")
        return []
