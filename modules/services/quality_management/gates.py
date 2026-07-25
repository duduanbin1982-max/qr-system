"""QualityGateService quality subdomain service."""

import json
import math
from datetime import datetime, timedelta

from modules.domain.errors import ConflictError, NotFoundError, ValidationError
from modules.domain.quality_rules import QUALITY_MANAGEMENT_DEFAULT_RULES
from modules.repositories.quality_management import QualityManagementRepository
from modules.repositories.setting_repository import SettingRepository
from modules.services import BaseService
from modules.services.quality_management.base import QualityManagementBase


class QualityGateService(QualityManagementBase):
    @staticmethod
    def dashboard():
        return QualityManagementRepository.dashboard()

    @staticmethod
    def analytics(date_from="", date_to=""):
        return QualityManagementRepository.analytics(date_from=date_from, date_to=date_to)

    @staticmethod
    def cancel_tasks_for_evaluation(evaluation_id, reason, db):
        return QualityManagementRepository.cancel_tasks_for_evaluation(
            evaluation_id, reason, db
        )

    @staticmethod
    def assert_report_allowed(order_id, process_id, db=None):
        gate = QualityManagementRepository.hard_report_gate(order_id, process_id, db)
        if gate:
            task_name = (
                "首件检验"
                if gate["inspection_type"] == "first_article"
                else "工序质量核验"
            )
            raise ConflictError(
                f"{task_name}任务 {gate['task_no']} 尚未放行，当前工序不能继续报工"
            )

    @staticmethod
    def assert_completion_allowed(order_id, db=None):
        gate = QualityManagementRepository.hard_completion_gate(order_id, db)
        if gate:
            raise ConflictError(f"完工检验任务 {gate['task_no']} 尚未放行，订单不能完成归档")

    @staticmethod
    def assert_shipment_allowed(shipment_id, db=None):
        gate = QualityManagementRepository.hard_shipment_gate(shipment_id, db)
        if gate:
            raise ConflictError(f"出库检验任务 {gate['task_no']} 尚未放行，不能完成出库")
