"""qr-system - ProgressService"""
from modules.services import BaseService
from modules.repositories.progress_repository import ProgressRepository


class ProgressService:
    @staticmethod
    def get_order_progress(order_id):
        order = ProgressRepository.find_order(order_id)
        if not order:
            raise ValueError("Order not found")
        processes = ProgressRepository.list_processes(order_id)
        return {"order": dict(order), "processes": [dict(p) for p in processes]}

    @staticmethod
    def get_delivery_alerts():
        overdue = ProgressRepository.count_overdue()
        near_due = ProgressRepository.count_near_due()
        return {"overdue": overdue, "near_due": near_due}
