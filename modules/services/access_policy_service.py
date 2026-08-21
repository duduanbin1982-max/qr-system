"""Application service for resolving user access policies."""
import logging
from typing import List, Optional

from modules.access_policy import (
    collect_permission_codes,
    has_global_data_scope,
    has_permission_code,
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
    def has_global_scope(user: Optional[dict]) -> bool:
        return has_global_data_scope(
            AccessPolicyService.get_user_permissions(user),
            set(GLOBAL_DATA_SCOPE_PERMS),
        )

    @staticmethod
    def get_user_process_ids(
        user: Optional[dict], order_id=None, db=None
    ) -> Optional[List[int]]:
        from modules.services.position_access_service import PositionAccessService

        return PositionAccessService.effective_user_process_ids(
            user, order_id=order_id, db=db
        )


def get_user_permissions(user: Optional[dict]) -> List[str]:
    return AccessPolicyService.get_user_permissions(user)


def has_permission(user: Optional[dict], perm: str) -> bool:
    return AccessPolicyService.has_permission(user, perm)


def get_user_process_ids(
    user: Optional[dict], order_id=None, db=None
) -> Optional[List[int]]:
    return AccessPolicyService.get_user_process_ids(user, order_id=order_id, db=db)
