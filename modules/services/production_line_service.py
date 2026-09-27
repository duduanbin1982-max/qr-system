"""
qr-system - Legacy ProductionLineService

Read-only compatibility projection for retired production-line master data.
"""
from modules.domain.errors import LegacyProcessLineWriteBlockedError
from modules.repositories.production_line_repository import ProductionLineRepository


class ProductionLineService:
    """Expose Legacy lines for reads and reject every business write."""

    @staticmethod
    def _reject_legacy_write():
        raise LegacyProcessLineWriteBlockedError(
            "Legacy 产线已转为只读兼容数据，请使用生产节点接口"
        )

    @staticmethod
    def list_all():
        rows = ProductionLineRepository.find_all()
        return {"lines": [dict(r) for r in rows]}

    @staticmethod
    def create(name, capacity_per_day=10, remark=""):
        ProductionLineService._reject_legacy_write()
        name = name.strip()
        if not name:
            raise ValueError("production line name is required")
        lid = ProductionLineRepository.insert(name, capacity_per_day, remark)
        return {"id": lid, "message": "created"}

    @staticmethod
    def update(line_id, name, capacity_per_day=10, remark="", status="active"):
        ProductionLineService._reject_legacy_write()
        ProductionLineRepository.update(line_id, name, capacity_per_day, remark, status)
        return {"message": "updated"}

    @staticmethod
    def delete(line_id):
        ProductionLineService._reject_legacy_write()
        ProductionLineRepository.delete(line_id)
        return {"message": "deleted"}
