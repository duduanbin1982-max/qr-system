"""
qr-system - ProductionLineService

Business logic for production lines.
"""
from modules.repositories.production_line_repository import ProductionLineRepository


class ProductionLineService:
    """Production line management."""

    @staticmethod
    def list_all():
        rows = ProductionLineRepository.find_all()
        return {"lines": [dict(r) for r in rows]}

    @staticmethod
    def create(name, capacity_per_day=10, remark=""):
        name = name.strip()
        if not name:
            raise ValueError("production line name is required")
        lid = ProductionLineRepository.insert(name, capacity_per_day, remark)
        return {"id": lid, "message": "created"}

    @staticmethod
    def update(line_id, name, capacity_per_day=10, remark="", status="active"):
        ProductionLineRepository.update(line_id, name, capacity_per_day, remark, status)
        return {"message": "updated"}

    @staticmethod
    def delete(line_id):
        ProductionLineRepository.delete(line_id)
        return {"message": "deleted"}
