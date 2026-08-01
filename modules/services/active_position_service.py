"""Session-level production position context for mobile reporting."""

from modules.repositories.auth_repository import AuthRepository
from modules.repositories.position_repository import PositionRepository
from modules.services import BaseService
from modules.services.access_policy_service import get_user_process_ids


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
    def get_context(cls, user):
        authorized_process_ids = get_user_process_ids(user)
        authorized_set = (
            None if authorized_process_ids is None else set(authorized_process_ids)
        )
        primary_position_id = user.get("position_id")
        rows = list(
            PositionRepository.find_active_positions_for_process_ids(
                authorized_process_ids
            )
        )
        rows_by_id = {row["id"]: row for row in rows}

        if primary_position_id and primary_position_id not in rows_by_id:
            primary_row = PositionRepository.find_position_by_id(primary_position_id)
            if primary_row and primary_row["status"] == "active":
                rows.append(primary_row)
                rows_by_id[primary_position_id] = primary_row

        position_ids = [row["id"] for row in rows]
        process_map = {position_id: [] for position_id in position_ids}
        for process in PositionRepository.find_position_processes(position_ids):
            process_id = process["process_id"]
            if authorized_set is None or process_id in authorized_set:
                process_map[process["position_id"]].append(process_id)

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
