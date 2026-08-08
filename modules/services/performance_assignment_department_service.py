"""Prepare and approve immutable department supplements for assignments."""

from modules.domain.errors import ConflictError, NotFoundError
from modules.domain.performance_policy import require_row_version
from modules.repositories.performance_assignment_department_repository import (
    PerformanceAssignmentDepartmentRepository,
)
from modules.services import BaseService
from modules.services.performance_authorization_service import (
    PerformanceAuthorizationService,
)


class PerformanceAssignmentDepartmentService:
    @staticmethod
    def _actor(actor, action):
        if not PerformanceAuthorizationService.can_perform(actor, action):
            raise PermissionError("performance:" + action + " permission is required")
        actor_id = (actor or {}).get("id")
        if actor_id is None:
            raise PermissionError("绩效部门补充操作人不存在")
        return int(actor_id), str(
            (actor or {}).get("name") or (actor or {}).get("username") or ""
        )

    @classmethod
    def create_revision(cls, data, actor, db=None):
        actor_id, actor_name = cls._actor(actor, "prepare")
        if not isinstance(data, dict):
            raise ValueError("绩效任职部门补充参数无效")
        try:
            assignment_id = int(data.get("assignment_id"))
            department_id = int(data.get("department_id"))
        except (TypeError, ValueError) as exc:
            raise ValueError("任职记录和部门必须有效") from exc
        reason = str(data.get("reason") or "").strip()
        source_type = str(data.get("source_type") or "manual_confirmation").strip()
        source_key = str(data.get("source_key") or "").strip()
        if not reason:
            raise ValueError("部门补充原因不能为空")
        if not source_key:
            raise ValueError("部门补充来源键不能为空")

        def execute(txn):
            existing = PerformanceAssignmentDepartmentRepository.revision_by_source_key(
                source_key, db=txn
            )
            if existing:
                raise ConflictError("部门补充来源键已存在")
            assignment = PerformanceAssignmentDepartmentRepository.assignment(
                assignment_id, db=txn
            )
            if not assignment:
                raise NotFoundError("绩效任职记录不存在")
            department = PerformanceAssignmentDepartmentRepository.department(
                department_id, db=txn
            )
            if not department or department.get("status") != "active":
                raise NotFoundError("绩效部门不存在或未启用")
            revision_id = PerformanceAssignmentDepartmentRepository.insert_revision(
                {
                    "assignment_id": assignment_id,
                    "revision": PerformanceAssignmentDepartmentRepository.next_revision(
                        assignment_id, db=txn
                    ),
                    "user_id": assignment["user_id"],
                    "department_id": department_id,
                    "department_name_snapshot": department["name"],
                    "valid_from_snapshot": assignment["valid_from"],
                    "valid_to_snapshot": assignment.get("valid_to") or "",
                    "reason": reason,
                    "source_type": source_type,
                    "source_key": source_key,
                    "created_by": actor_id,
                    "created_by_name": actor_name,
                },
                txn,
            )
            return PerformanceAssignmentDepartmentRepository.revision(
                revision_id, db=txn
            )

        if db is not None:
            return execute(db)
        with BaseService.transaction() as txn:
            return execute(txn)

    @classmethod
    def approve_revision(cls, revision_id, actor, expected_row_version, db=None):
        actor_id, actor_name = cls._actor(actor, "approve")
        expected = require_row_version(expected_row_version)

        def execute(txn):
            current = PerformanceAssignmentDepartmentRepository.revision(
                revision_id, db=txn
            )
            if not current:
                raise NotFoundError("绩效任职部门补充版本不存在")
            if current["status"] != "draft":
                raise ConflictError("只有草稿部门补充版本可以批准")
            PerformanceAuthorizationService.require_distinct_actors(
                current.get("created_by"), actor_id
            )
            previous = PerformanceAssignmentDepartmentRepository.current_approved(
                current["assignment_id"], db=txn
            )
            previous_id = previous["id"] if previous else None
            if previous and not PerformanceAssignmentDepartmentRepository.supersede(
                previous["id"], current["id"], previous["row_version"], txn
            ):
                raise ConflictError("原部门补充版本已变化，请刷新后重试")
            if not PerformanceAssignmentDepartmentRepository.approve(
                current["id"],
                expected,
                actor_id,
                actor_name,
                previous_id,
                txn,
            ):
                raise ConflictError("部门补充版本已变化，请刷新后重试")
            return PerformanceAssignmentDepartmentRepository.revision(
                current["id"], db=txn
            )

        if db is not None:
            return execute(db)
        with BaseService.transaction() as txn:
            return execute(txn)

    @staticmethod
    def list_revisions(assignment_id, db=None):
        return PerformanceAssignmentDepartmentRepository.list_for_assignment(
            assignment_id, db=db
        )
