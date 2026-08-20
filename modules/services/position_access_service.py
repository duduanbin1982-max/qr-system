"""Authoritative position and explicit-user process scope resolution."""

import logging

from modules.access_policy import (
    collect_permission_codes,
    has_global_data_scope,
    parse_process_ids,
)
from modules.config import GLOBAL_DATA_SCOPE_PERMS
from modules.repositories.access_policy_repository import AccessPolicyRepository
from modules.repositories.position_repository import PositionRepository
from modules.repositories.position_version_repository import PositionVersionRepository


class PositionAccessService:
    @staticmethod
    def _row_ids(rows):
        values = set()
        for row in rows or []:
            if hasattr(row, "keys"):
                key = "id" if "id" in row.keys() else "process_id"
                value = row[key]
            else:
                value = row[0]
            if value is not None:
                values.add(int(value))
        return sorted(values)

    @staticmethod
    def _active_process_ids(process_ids, db=None):
        rows = AccessPolicyRepository.list_active_existing_process_ids(
            process_ids, db=db
        )
        return PositionAccessService._row_ids(rows)

    @staticmethod
    def new_business_process_ids(position_id, db=None):
        if not position_id:
            return []
        root = PositionVersionRepository.root(position_id, db=db)
        if not root:
            return []
        if root.get("status") != "active" or root.get("lifecycle_status") != "active":
            return []

        current = PositionVersionRepository.current_version(position_id, db=db)
        if current is not None:
            if current.get("status") != "published":
                return []
            return PositionAccessService._active_process_ids(
                current.get("process_ids") or [], db=db
            )

        # During the staged cutover, roots created by the Legacy endpoint have
        # no revision. V2 draft roots are inactive, so this fallback cannot
        # accidentally authorize an unpublished V2 position.
        return PositionAccessService._active_process_ids(
            PositionRepository.find_process_ids_by_position(position_id, db=db),
            db=db,
        )

    @staticmethod
    def historical_wip_process_ids(position_id, order_id, db=None):
        if not position_id or not order_id:
            return []
        root = PositionVersionRepository.root(position_id, db=db)
        if not root:
            return []
        rows = AccessPolicyRepository.list_historical_position_order_process_ids(
            int(position_id), int(order_id), db=db
        )
        return PositionAccessService._row_ids(rows)

    @staticmethod
    def _explicit_user_process_ids(user, db=None):
        explicit_ids = set()
        process_ids_text = str(user.get("process_ids") or "").strip()
        if process_ids_text:
            try:
                parsed = parse_process_ids(process_ids_text)
            except (TypeError, ValueError):
                parsed = []
            explicit_ids.update(
                PositionAccessService._row_ids(
                    AccessPolicyRepository.list_active_existing_process_ids(
                        parsed, db=db
                    )
                )
            )
        junction_rows = AccessPolicyRepository.list_user_process_ids(
            user["id"], db=db
        )
        junction_ids = PositionAccessService._row_ids(junction_rows)
        if junction_ids:
            explicit_ids.update(
                PositionAccessService._active_process_ids(junction_ids, db=db)
            )
        return explicit_ids, bool(process_ids_text or junction_rows)

    @staticmethod
    def _has_global_scope(user, db=None):
        cached = user.get("_permissions")
        if cached is None:
            permissions = collect_permission_codes(
                AccessPolicyRepository.get_permission_rows(user["id"], db=db),
                user_id=user.get("id"),
                logger=logging.getLogger("qr"),
            )
        else:
            permissions = cached
        return has_global_data_scope(permissions, set(GLOBAL_DATA_SCOPE_PERMS))

    @staticmethod
    def effective_user_process_ids(user, order_id=None, db=None):
        if not user:
            return None
        explicit, explicit_configured = (
            PositionAccessService._explicit_user_process_ids(user, db=db)
        )
        position_id = user.get("position_id")
        if order_id is None:
            position = PositionAccessService.new_business_process_ids(
                position_id, db=db
            )
        else:
            position = PositionAccessService.historical_wip_process_ids(
                position_id, order_id, db=db
            )
        resolved = sorted(explicit | set(position))
        if resolved or position_id or explicit_configured:
            return resolved
        if PositionAccessService._has_global_scope(user, db=db):
            return None
        return []
