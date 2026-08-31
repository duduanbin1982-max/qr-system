"""Stable business impact summaries for versioned position master data."""

from modules.domain.position_versioning import (
    PositionActiveEmployeesError,
    PositionActiveSessionsError,
    PositionNotFoundError,
    PositionReferenceConflictError,
    impact_digest,
)
from modules.master_data_references import IMPACT_INTERNAL
from modules.repositories.position_repository import PositionRepository


class PositionImpactService:
    _INDIRECT_CATEGORIES = (
        {
            "key": "open_orders",
            "label": "相关在制订单",
            "blocking_level": "high",
            "suggested_action": "保留历史在制订单授权",
            "block_operations": (),
        },
        {
            "key": "current_routes",
            "label": "相关当前工艺路线",
            "blocking_level": "warning",
            "suggested_action": "确认路线岗位覆盖影响",
            "block_operations": (),
        },
    )

    @staticmethod
    def _reference_counts(position_id, db=None):
        position = PositionRepository.find_position_by_id(position_id, db=db)
        if not position:
            raise PositionNotFoundError(
                "岗位不存在", details={"position_id": position_id}
            )
        return PositionRepository.position_reference_counts(position_id, db=db)

    @staticmethod
    def summarize(position_id, db=None):
        counts = PositionImpactService._reference_counts(position_id, db=db)
        categories = []
        blockers = []
        for reference, count in counts:
            if reference.impact_level == IMPACT_INTERNAL:
                continue
            item = {
                "key": reference.business_key,
                "label": reference.business_label,
                "count": count,
                "blocking_level": reference.impact_level,
                "suggested_action": reference.suggested_action,
            }
            categories.append(item)
            if count and reference.block_operations:
                blockers.append(
                    {
                        "key": reference.business_key,
                        "count": count,
                        "operations": list(reference.block_operations),
                    }
                )

        indirect = PositionRepository.position_indirect_counts(position_id, db=db)
        for definition in PositionImpactService._INDIRECT_CATEGORIES:
            count = indirect[definition["key"]]
            categories.append(
                {
                    "key": definition["key"],
                    "label": definition["label"],
                    "count": count,
                    "blocking_level": definition["blocking_level"],
                    "suggested_action": definition["suggested_action"],
                }
            )

        digest_items = [
            {
                "key": item["key"],
                "count": item["count"],
                "blocking_level": item["blocking_level"],
            }
            for item in categories
        ]
        return {
            "position_id": int(position_id),
            "categories": categories,
            "total": sum(item["count"] for item in categories),
            "blockers": blockers,
            "impact_digest": impact_digest(digest_items),
        }

    @staticmethod
    def assert_deletable(position_id, db=None):
        counts = PositionImpactService._reference_counts(position_id, db=db)
        blocking = [
            (reference, count)
            for reference, count in counts
            if count and "delete" in reference.block_operations
        ]
        if blocking:
            raise PositionReferenceConflictError(
                "岗位已有业务或版本引用，不能物理删除",
                details={
                    "position_id": int(position_id),
                    "references": [
                        {"key": reference.business_key, "count": count}
                        for reference, count in blocking
                    ],
                },
            )
        return True

    @staticmethod
    def assert_retirable(position_id, db=None):
        result = PositionImpactService.summarize(position_id, db=db)
        counts = {item["key"]: item["count"] for item in result["categories"]}
        if counts.get("active_employees", 0):
            raise PositionActiveEmployeesError(
                "岗位仍有启用员工，请先完成调岗",
                details={
                    "position_id": int(position_id),
                    "count": counts["active_employees"],
                },
            )
        if counts.get("active_sessions", 0):
            raise PositionActiveSessionsError(
                "岗位仍有活跃会话，请先失效会话",
                details={
                    "position_id": int(position_id),
                    "count": counts["active_sessions"],
                },
            )
        return result
