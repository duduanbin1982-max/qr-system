"""
qr-system - ProductionLineService

Business logic for production lines.
"""
from modules import config
from modules.domain.errors import LegacyProcessLineWriteBlockedError
from modules.repositories.production_line_repository import ProductionLineRepository


class ProductionLineService:
    """Production line management."""

    @staticmethod
    def _assert_legacy_write_allowed():
        if config.LEGACY_PROCESS_LINE_WRITE_BLOCKED:
            raise LegacyProcessLineWriteBlockedError(
                "Legacy 产线写入已关闭，请使用生产节点接口"
            )

    @staticmethod
    def list_all():
        rows = ProductionLineRepository.find_all()
        return {"lines": [dict(r) for r in rows]}

    @staticmethod
    def create(name, capacity_per_day=10, remark=""):
        ProductionLineService._assert_legacy_write_allowed()
        name = name.strip()
        if not name:
            raise ValueError("production line name is required")
        lid = ProductionLineRepository.insert(name, capacity_per_day, remark)
        return {"id": lid, "message": "created"}

    @staticmethod
    def update(line_id, name, capacity_per_day=10, remark="", status="active"):
        ProductionLineService._assert_legacy_write_allowed()
        ProductionLineRepository.update(line_id, name, capacity_per_day, remark, status)
        return {"message": "updated"}

    @staticmethod
    def delete(line_id):
        ProductionLineService._assert_legacy_write_allowed()
        ProductionLineRepository.delete(line_id)
        return {"message": "deleted"}
