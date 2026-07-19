"""Application service for resolving user access policies."""
import logging
from typing import List, Optional

from modules.access_policy import (
    collect_permission_codes,
    has_permission_code,
    parse_process_ids,
    resolve_process_scope,
)
from modules.config import GLOBAL_DATA_SCOPE_PERMS
from modules.repositories.access_policy_repository import AccessPolicyRepository


class AccessPolicyService:
    @staticmethod
    def get_user_permissions(user: Optional[dict]) -> List[str]:
        if not user:
            return []
        cached = user.get("_permissions")
        if cached is not None:
            return sorted(cached)
        rows = AccessPolicyRepository.get_permission_rows(user["id"])
        return collect_permission_codes(
            rows,
            user_id=user.get("id"),
            logger=logging.getLogger("qr"),
        )

    @staticmethod
    def has_permission(user: Optional[dict], perm: str) -> bool:
        if not user:
            return False
        return has_permission_code(AccessPolicyService.get_user_permissions(user), perm)

    @staticmethod
    def get_user_process_ids(user: Optional[dict]) -> Optional[List[int]]:
        if not user:
            return None

        position_id = user.get("position_id")
        position_rows = []
        if position_id:
            position_rows = AccessPolicyRepository.list_position_process_ids(position_id)

        process_ids_text = (user.get("process_ids") or "").strip()
        explicit_rows = []
        if process_ids_text:
            try:
                process_ids = parse_process_ids(process_ids_text)
            except (ValueError, TypeError):
                process_ids = []
            if process_ids:
                explicit_rows = AccessPolicyRepository.list_existing_process_ids(process_ids)
        user_process_rows = AccessPolicyRepository.list_user_process_ids(user["id"])
        explicit_rows = list(explicit_rows) + list(user_process_rows)

        return resolve_process_scope(
            position_rows,
            explicit_rows,
            has_position_scope=bool(position_id),
            has_explicit_process_scope=bool(process_ids_text or user_process_rows),
            permissions=AccessPolicyService.get_user_permissions(user),
            global_data_scope_permissions=set(GLOBAL_DATA_SCOPE_PERMS),
        )


def get_user_permissions(user: Optional[dict]) -> List[str]:
    return AccessPolicyService.get_user_permissions(user)


def has_permission(user: Optional[dict], perm: str) -> bool:
    return AccessPolicyService.has_permission(user, perm)


def get_user_process_ids(user: Optional[dict]) -> Optional[List[int]]:
    return AccessPolicyService.get_user_process_ids(user)
