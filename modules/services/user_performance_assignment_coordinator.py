"""Public coordination boundary for user performance assignment history."""

from modules.repositories.performance_assignment_repository import (
    PerformanceAssignmentRepository,
)
from modules.services.performance_assignment_service import PerformanceAssignmentService


class UserPerformanceAssignmentCoordinator:
    """Keep assignment history updates inside the caller's transaction."""

    @staticmethod
    def record_initial(user_id, created_by=None, source_type="user_created", db=None):
        return PerformanceAssignmentService.record_initial_assignment(
            user_id,
            created_by=created_by,
            source_type=source_type,
            db=db,
        )

    @staticmethod
    def record_change(before, after, created_by=None, db=None):
        return PerformanceAssignmentService.record_user_change(
            before,
            after,
            created_by=created_by,
            db=db,
        )

    @staticmethod
    def record_snapshot_change(user_id, before, created_by=None, db=None):
        after = PerformanceAssignmentRepository.user_snapshot(user_id, db=db)
        return UserPerformanceAssignmentCoordinator.record_change(
            before,
            after,
            created_by=created_by,
            db=db,
        )

    @staticmethod
    def record_status_changes(before_rows, after_rows, created_by=None, db=None):
        changed = 0
        for user_id, before in before_rows.items():
            after = after_rows.get(user_id)
            if after and before["status"] != after["status"]:
                UserPerformanceAssignmentCoordinator.record_snapshot_change(
                    user_id,
                    before,
                    created_by=created_by,
                    db=db,
                )
                changed += 1
        return changed
    @staticmethod
    def record_deleted_users(before_rows, created_by=None, db=None):
        changed = 0
        for user_id, before in before_rows.items():
            after = PerformanceAssignmentRepository.user_snapshot(user_id, db=db)
            if after and before["status"] != after["status"]:
                UserPerformanceAssignmentCoordinator.record_change(
                    before,
                    after,
                    created_by=created_by,
                    db=db,
                )
                changed += 1
        return changed
