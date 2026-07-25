"""Backward-compatible facade for quality management application services."""

from modules.services.quality_management import (
    QualityGateService,
    QualityInspectionService,
    QualityNonconformanceService,
    QualityPartnerService,
    QualityStandardService,
)


class QualityManagementService(
    QualityStandardService,
    QualityInspectionService,
    QualityNonconformanceService,
    QualityPartnerService,
    QualityGateService,
):
    pass
