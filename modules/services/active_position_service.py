"""Session-level production position context for mobile reporting."""

from modules.repositories.auth_repository import AuthRepository
from modules.repositories.position_version_repository import PositionVersionRepository
from modules.services import BaseService
from modules.services.access_policy_service import get_user_process_ids
from modules.services.position_access_service import PositionAccessService


class ActivePositionService:
    @staticmethod
    def _position_payload(row, process_ids, primary_position_id):
        return {
            "id": row["id"],
            "name": row["name"],
            "is_primary": row["id"] == primary_position_id,
            "process_ids": process_ids,
        }

    @classmethod
    def get_context(cls, user, order_id=None):
        authorized_process_ids = get_user_process_ids(user, order_id=order_id)
        authorized_set = (
            None if authorized_process_ids is None else set(authorized_process_ids)
        )
        primary_position_id = user.get("position_id")
        rows = PositionVersionRepository.roots()
        available = []
        process_map = {}
        for row in rows:
            if order_id is None:
                process_ids = PositionAccessService.new_business_process_ids(row["id"])
                root_available = (
                    row.get("status") == "active"
                    and row.get("lifecycle_status") == "active"
                )
            else:
                process_ids = PositionAccessService.historical_wip_process_ids(
                    row["id"], order_id
                )
                root_available = bool(process_ids)
            scoped_process_ids = [
                process_id
                for process_id in process_ids
                if authorized_set is None or process_id in authorized_set
            ]
            if scoped_process_ids or (
                root_available and row["id"] == primary_position_id
            ):
                available.append(row)
                process_map[row["id"]] = scoped_process_ids
        rows = available

        positions = [
            cls._position_payload(
                row,
                sorted(set(process_map.get(row["id"], []))),
                primary_position_id,
            )
            for row in rows
        ]
        positions.sort(key=lambda position: (not position["is_primary"], position["id"]))
        positions_by_id = {position["id"]: position for position in positions}

        requested_position_id = user.get("active_position_id") or primary_position_id
        active_position = positions_by_id.get(requested_position_id)
        if active_position is None:
            active_position = positions_by_id.get(primary_position_id)
        if active_position is None and positions:
            active_position = positions[0]

        primary_position = positions_by_id.get(primary_position_id)
        return {
            "primary_position": primary_position,
            "active_position": active_position,
            "active_position_id": active_position["id"] if active_position else None,
            "available_positions": positions,
        }

    @classmethod
    def set_active_position(cls, user, token, position_id):
        context = cls.get_context(user)
        available_ids = {
            position["id"] for position in context["available_positions"]
        }
        if position_id not in available_ids:
            raise ValueError("所选岗位不在您的可用岗位范围内")

        with BaseService.transaction() as transaction:
            updated = AuthRepository.update_session_active_position(
                user["id"], token, position_id, db=transaction
            )
            if not updated:
                raise ValueError("当前登录会话已失效，请重新登录")

        updated_user = dict(user)
        updated_user["active_position_id"] = position_id
        return cls.get_context(updated_user)
