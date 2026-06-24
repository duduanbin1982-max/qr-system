"""qr-system - ExportService (Repository-refactored)"""
from modules.services import BaseService
from modules.repositories.export_repository import ExportRepository


class ExportService:

    @staticmethod
    def get_orders_export():
        rows = ExportRepository.get_orders_export()
        return [{
            "id": r[0], "order_no": r[1], "customer": r[2], "product_name": r[3],
            "quantity": r[4], "status": r[5], "plan_start": r[6], "plan_end": r[7],
            "deadline": r[8], "created_at": r[9],
        } for r in rows]

    @staticmethod
    def get_work_records_export(order_id=None, date_from=None, date_to=None):
        rows = ExportRepository.get_work_records_export(order_id, date_from, date_to)
        return [{
            "id": r[0], "order_no": r[1], "process_name": r[2], "worker_name": r[3],
            "serial_no": r[4], "quantity": r[5], "type": r[6], "remark": r[7], "created_at": r[8],
        } for r in rows]
