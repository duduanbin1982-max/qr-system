"""Position-version snapshots for performance assignment history."""

from modules.domain.errors import ConflictError, ValidationError
from modules.repositories.performance_assignment_repository import (
    PerformanceAssignmentRepository,
)
from modules.repositories.position_version_repository import PositionVersionRepository


class PositionSnapshotService:
    @staticmethod
    def apply_published_name(
        position_id, position_version_id, name, published_at, db
    ):
        snapshot_name = str(name or "").strip()
        effective_at = str(published_at or "").strip()
        if not snapshot_name:
            raise ValidationError("岗位名称不能为空")
        if not effective_at:
            raise ValidationError("岗位发布时间不能为空")
        current = PerformanceAssignmentRepository.open_assignments_for_position(
            position_id, db=db
        )
        changed = 0
        for assignment in current:
            if assignment["position_name_snapshot"] == snapshot_name:
                continue
            if effective_at < assignment["valid_from"]:
                raise ConflictError("岗位发布时间早于当前任职区间")
            closed = PerformanceAssignmentRepository.close_assignment(
                assignment["id"], effective_at, db=db
            )
            if closed != 1:
                raise ConflictError("当前任职区间已变化，请重试")
            PerformanceAssignmentRepository.create_assignment(
                {
                    "user_id": assignment["user_id"],
                    "employee_name_snapshot": assignment[
                        "employee_name_snapshot"
                    ],
                    "employee_no_snapshot": assignment["employee_no_snapshot"],
                    "position_id": int(position_id),
                    "position_version_id": int(position_version_id),
                    "position_name_snapshot": snapshot_name,
                    "department_id": assignment["department_id"],
                    "department_name_snapshot": assignment[
                        "department_name_snapshot"
                    ],
                    "valid_from": effective_at,
                    "valid_to": "",
                    "source_type": "position_version_published",
                    "source_key": (
                        f"position_version:{assignment['id']}:{position_version_id}"
                    ),
                    "created_by": assignment.get("created_by"),
                },
                db=db,
            )
            changed += 1
        return changed

    @staticmethod
    def version_at(position_id, occurred_at, db=None):
        timestamp = str(occurred_at or "").strip()
        if not timestamp:
            raise ValidationError("业务时间不能为空")
        return PositionVersionRepository.version_at(position_id, timestamp, db=db)
