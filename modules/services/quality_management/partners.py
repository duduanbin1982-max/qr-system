"""QualityPartnerService quality subdomain service."""

import json
import math
from datetime import datetime, timedelta

from modules.domain.errors import ConflictError, NotFoundError, ValidationError
from modules.domain.quality_rules import QUALITY_MANAGEMENT_DEFAULT_RULES
from modules.repositories.quality_management import QualityManagementRepository
from modules.repositories.setting_repository import SettingRepository
from modules.services import BaseService
from modules.services.quality_management.base import QualityManagementBase


class QualityPartnerService(QualityManagementBase):
    @staticmethod
    def list_supplier_inspections(**filters):
        result = QualityManagementRepository.list_supplier_inspections(**filters)
        result["supplier_stats"] = [dict(row) for row in QualityManagementRepository.supplier_quality_stats()]
        return result

    @classmethod
    def create_supplier_inspection(cls, data, user_id):
        if not data.get("supplier_id"):
            raise ValidationError("供应商必填")
        checked = max(cls._positive_int(data.get("quantity_checked"), 0), 1)
        failed = min(cls._positive_int(data.get("quantity_failed"), 0), checked)
        result = cls._text(data.get("result") or ("pass" if failed == 0 else "rework"))
        if result not in {"pass", "rework", "scrap", "return"}:
            raise ValidationError("来料检验判定无效")
        normalized = {
            **data, "quantity_checked": checked, "quantity_failed": failed,
            "quantity_passed": checked - failed, "result": result,
            "score_total": min(max(cls._number(data.get("score_total"), 0), 0), 100),
            "defect_category": cls._text(data.get("defect_category")),
            "defect_level": cls._text(data.get("defect_level")), "notes": cls._text(data.get("notes")),
        }
        if result != "pass" and normalized["defect_level"] not in {"minor", "general", "severe", "critical"}:
            raise ValidationError("不合格来料必须选择缺陷等级")
        with BaseService.transaction() as db:
            inspection_id = QualityManagementRepository.insert_supplier_inspection(normalized, user_id, db)
            ncr_id = None
            if result != "pass":
                ncr_id = QualityManagementRepository.insert_ncr({
                    "ncr_no": cls._new_code("NCR", "quality_nonconformances", db),
                    "supplier_id": normalized["supplier_id"], "material_id": normalized.get("material_id"),
                    "defect_category": normalized["defect_category"], "defect_level": normalized["defect_level"],
                    "defect_quantity": failed or 1, "description": normalized["notes"],
                    "disposition": "return" if result == "return" else "pending",
                    "status": "closed" if result == "return" else "open", "source_type": "supplier_inspection",
                }, user_id, db)
                QualityManagementRepository.attach_supplier_ncr(inspection_id, ncr_id, db)
                QualityManagementRepository.add_ncr_action(
                    ncr_id, "create", "", "closed" if result == "return" else "open",
                    "来料检验不合格自动创建", user_id, db,
                )
        return {"id": inspection_id, "ncr_id": ncr_id}

    @staticmethod
    def list_gauges(**filters):
        return QualityManagementRepository.list_gauges(**filters)

    @classmethod
    def save_gauge(cls, data, user_id, gauge_id=None):
        gauge_no = cls._text(data.get("gauge_no")).upper()
        name = cls._text(data.get("name"))
        if not gauge_no or not name:
            raise ValidationError("量具编号和名称必填")
        normalized = {
            **data, "gauge_no": gauge_no, "name": name,
            "calibration_cycle_days": max(cls._positive_int(data.get("calibration_cycle_days"), 365), 1),
            "status": cls._text(data.get("status") or "active"),
        }
        with BaseService.transaction() as db:
            if gauge_id:
                if not QualityManagementRepository.gauge_by_id(gauge_id, db):
                    raise NotFoundError("量具不存在")
                QualityManagementRepository.update_gauge(gauge_id, normalized, db)
                return gauge_id
            return QualityManagementRepository.insert_gauge(normalized, user_id, db)

    @classmethod
    def calibrate_gauge(cls, gauge_id, data, user_id):
        if not QualityManagementRepository.gauge_by_id(gauge_id):
            raise NotFoundError("量具不存在")
        calibrated_at = cls._text(data.get("calibrated_at"))
        next_at = cls._text(data.get("next_calibration_at"))
        result = cls._text(data.get("result"))
        if not calibrated_at or not next_at or result not in {"pass", "fail"}:
            raise ValidationError("校准日期、下次校准日期和结果必填")
        with BaseService.transaction() as db:
            return QualityManagementRepository.insert_calibration(gauge_id, {
                **data, "calibrated_at": calibrated_at, "next_calibration_at": next_at, "result": result,
            }, user_id, db)
