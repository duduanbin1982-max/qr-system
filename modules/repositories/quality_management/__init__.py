"""Quality management persistence facade."""

from modules.repositories.quality_management.analytics import QualityAnalyticsRepository
from modules.repositories.quality_management.inspections import QualityInspectionRepository
from modules.repositories.quality_management.nonconformance import QualityNonconformanceRepository
from modules.repositories.quality_management.standards import QualityStandardRepository
from modules.repositories.quality_management.tasks import QualityTaskRepository


class QualityManagementRepository(
    QualityStandardRepository,
    QualityInspectionRepository,
    QualityNonconformanceRepository,
    QualityAnalyticsRepository,
):
    pass


__all__ = ["QualityManagementRepository", "QualityTaskRepository"]
