"""Transaction-aware lifecycle rules for performance assignments."""

from datetime import datetime
import uuid

from modules.repositories.performance_assignment_repository import (
    PerformanceAssignmentRepository,
)


class PerformanceAssignmentService:
    ACTIVE_STATUS = "active"
    ASSIGNMENT_FIELDS = ("position_id", "department_id")
    IDENTITY_FIELDS = ("name", "employee_no")

    @staticmethod
    def _current_timestamp():
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

    @staticmethod
    def _source_key(user_id, source_type, effective_at):
        return (
            f"{source_type}:{user_id}:{effective_at}:"
            f"{uuid.uuid4().hex}"
        )

    @staticmethod
    def _append_snapshot(snapshot, source_type, created_by, effective_at, db):
        payload = dict(snapshot)
        payload.update(
            {
                "valid_from": effective_at,
                "valid_to": "",
                "source_type": source_type,
                "source_key": PerformanceAssignmentService._source_key(
                    snapshot["user_id"], source_type, effective_at
                ),
                "created_by": created_by,
            }
        )
        return PerformanceAssignmentRepository.insert_assignment(payload, db=db)

    @staticmethod
    def record_initial_assignment(
        user_id, created_by=None, source_type="user_created", effective_at=None, db=None
    ):
        snapshot = PerformanceAssignmentRepository.user_snapshot(user_id, db=db)
        if not snapshot or snapshot["status"] != PerformanceAssignmentService.ACTIVE_STATUS:
            return None
        effective_at = effective_at or PerformanceAssignmentService._current_timestamp()
        return PerformanceAssignmentService._append_snapshot(
            snapshot, source_type, created_by, effective_at, db
        )

    @staticmethod
    def record_user_change(before, after, created_by=None, effective_at=None, db=None):
        before = dict(before)
        after = dict(after)
        effective_at = effective_at or PerformanceAssignmentService._current_timestamp()
        was_active = before.get("status") == PerformanceAssignmentService.ACTIVE_STATUS
        is_active = after.get("status") == PerformanceAssignmentService.ACTIVE_STATUS

        if was_active and not is_active:
            PerformanceAssignmentRepository.close_open_assignment(
                after["user_id"], effective_at, db=db
            )
            return None
        if not was_active and is_active:
            # V56 seeded a current baseline for every existing user, including
            # inactive users. End that baseline before recording reactivation.
            PerformanceAssignmentRepository.close_open_assignment(
                after["user_id"], effective_at, db=db
            )
            return PerformanceAssignmentService._append_snapshot(
                after, "user_reactivated", created_by, effective_at, db
            )
        if not is_active:
            return None

        assignment_changed = any(
            before.get(field) != after.get(field)
            for field in PerformanceAssignmentService.ASSIGNMENT_FIELDS
        )
        identity_changed = any(
            before.get(field) != after.get(field)
            for field in PerformanceAssignmentService.IDENTITY_FIELDS
        )
        if not assignment_changed and not identity_changed:
            return None

        PerformanceAssignmentRepository.close_open_assignment(
            after["user_id"], effective_at, db=db
        )
        source_type = (
            "assignment_changed" if assignment_changed else "identity_snapshot_changed"
        )
        return PerformanceAssignmentService._append_snapshot(
            after, source_type, created_by, effective_at, db
        )

    @staticmethod
    def assignments_for_period(user_id, period_start, period_end, db=None):
        return PerformanceAssignmentRepository.list_for_period(
            user_id, period_start, period_end, db=db
        )

    @staticmethod
    def candidate_user_ids(period_start, period_end, db=None):
        return PerformanceAssignmentRepository.candidate_user_ids(
            period_start, period_end, db=db
        )
