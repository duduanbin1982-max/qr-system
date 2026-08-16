"""Business-facing impact summaries for versioned process master data."""

from modules.domain.errors import NotFoundError
from modules.master_data_references import IMPACT_INTERNAL
from modules.repositories.process_repository import ProcessRepository
from modules.repositories.route_repository import RouteRepository


class MasterDataImpactService:
    @staticmethod
    def _structured_references(reference_counts):
        return [
            {
                "key": reference.business_key,
                "label": reference.business_label,
                "count": count,
                "impact_level": reference.impact_level,
                "suggested_action": reference.suggested_action,
            }
            for reference, count in reference_counts
            if count and reference.impact_level != IMPACT_INTERNAL
        ]

    @staticmethod
    def process_impact(process_id, db=None):
        process = ProcessRepository.find_by_id(process_id, db=db)
        if not process:
            raise NotFoundError("Process not found")
        counts = ProcessRepository.reference_counts(process_id, db=db)
        references = MasterDataImpactService._structured_references(counts)
        impact = {
            reference.table: count
            for reference, count in counts
            if count and reference.impact_level != IMPACT_INTERNAL
        }
        return {
            "process_id": process_id,
            "name": process["name"],
            "impact": impact,
            "references": references,
            "total_references": sum(item["count"] for item in references),
            "is_locked": bool(references),
        }

    @staticmethod
    def route_impact(route_id, db=None):
        route = RouteRepository.find_route_name(route_id, db=db)
        if not route:
            raise NotFoundError("Route not found")
        usage = RouteRepository.get_route_usage(route_id, db=db)
        references = MasterDataImpactService._structured_references(
            usage["reference_counts"]
        )
        return {
            "route_id": route_id,
            "name": route["name"],
            "used_orders": usage["used_orders"],
            "used_products": usage["used_products"],
            "is_locked": bool(references),
            "references": references,
            "total_references": sum(item["count"] for item in references),
        }
