"""Quality management application subdomains."""

from modules.services.quality_management.gates import QualityGateService
from modules.services.quality_management.inspections import QualityInspectionService
from modules.services.quality_management.nonconformance import QualityNonconformanceService
from modules.services.quality_management.partners import QualityPartnerService
from modules.services.quality_management.standards import QualityStandardService
from modules.services.quality_management.tasks import QualityTaskService

__all__ = [
    "QualityGateService",
    "QualityInspectionService",
    "QualityNonconformanceService",
    "QualityPartnerService",
    "QualityStandardService",
    "QualityTaskService",
]
