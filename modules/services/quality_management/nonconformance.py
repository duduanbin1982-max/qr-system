"""QualityNonconformanceService quality subdomain service."""

import json
import math
from datetime import datetime, timedelta

from modules.domain.errors import ConflictError, NotFoundError, ValidationError
from modules.domain.quality_rules import QUALITY_MANAGEMENT_DEFAULT_RULES
from modules.repositories.quality_management import QualityManagementRepository
from modules.repositories.setting_repository import SettingRepository
from modules.services import BaseService
from modules.services.quality_management.base import QualityManagementBase


class QualityNonconformanceService(QualityManagementBase):
    @classmethod
    def create_ncr(cls, data, user_id):
        description = cls._text(data.get("description"))
        defect_level = cls._text(data.get("defect_level"))
        if not description:
            raise ValidationError("质量异常必须填写问题描述")
        if defect_level not in {"minor", "general", "severe", "critical"}:
            raise ValidationError("质量异常必须选择缺陷等级")
        quantity = max(cls._positive_int(data.get("defect_quantity"), 1), 1)
        with BaseService.transaction() as db:
            ncr_id = QualityManagementRepository.insert_ncr({
                **data,
                "ncr_no": cls._new_code("NCR", "quality_nonconformances", db),
                "defect_level": defect_level,
                "defect_quantity": quantity,
                "description": description,
                "disposition": "pending",
                "status": "open",
                "source_type": "manual",
            }, user_id, db)
            QualityManagementRepository.add_ncr_action(
                ncr_id, "create", "", "open", "手工创建质量异常", user_id, db
            )
            if data.get("order_id"):
                QualityManagementRepository.set_inventory_quality(
                    int(data["order_id"]), "quarantined", f"质量异常单 #{ncr_id} 待处置", db
                )
            return ncr_id

    @staticmethod
    def get_ncr(ncr_id):
        ncr = QualityManagementRepository.ncr_detail(ncr_id)
        if not ncr:
            raise NotFoundError("质量异常单不存在")
        return ncr

    @staticmethod
    def list_ncr(**filters):
        return QualityManagementRepository.list_ncr(**filters)

    @classmethod
    def dispose_ncr(cls, ncr_id, data, user_id):
        row = QualityManagementRepository.ncr_by_id(ncr_id)
        if not row:
            raise NotFoundError("不合格单不存在")
        ncr = dict(row)
        if ncr["status"] in {"closed", "cancelled"}:
            raise ConflictError("不合格单已经关闭")
        disposition = cls._text(data.get("disposition"))
        if disposition not in cls.DISPOSITIONS - {"pending"}:
            raise ValidationError("处置方式无效")
        old_status = ncr["status"]
        status = "processing"
        closed_at = ""
        if disposition in {"scrap", "concession", "return"}:
            status = "closed"
            closed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ncr.update({
            **data,
            "disposition": disposition, "status": status,
            "responsible_user_id": data.get("responsible_user_id") or ncr.get("responsible_user_id"),
            "responsible_process_id": data.get("responsible_process_id") or ncr.get("responsible_process_id"),
            "owner_id": data.get("owner_id") or ncr.get("owner_id"),
            "due_at": cls._text(data.get("due_at") or ncr.get("due_at")),
            "root_cause": cls._text(data.get("root_cause") or ncr.get("root_cause")),
            "corrective_action": cls._text(data.get("corrective_action") or ncr.get("corrective_action")),
            "verification_result": cls._text(data.get("verification_result") or ncr.get("verification_result")),
            "closed_by": user_id if status == "closed" else None, "closed_at": closed_at,
        })
        with BaseService.transaction() as db:
            QualityManagementRepository.update_ncr(ncr_id, ncr, db)
            QualityManagementRepository.add_ncr_action(
                ncr_id, f"disposition_{disposition}", old_status, status,
                cls._text(data.get("note") or data.get("corrective_action")), user_id, db,
            )
            rework_id = None
            if disposition == "rework":
                if not ncr.get("order_id") or not ncr.get("process_id"):
                    raise ValidationError("返修处置必须关联订单和工序")
                rework_id = QualityManagementRepository.insert_rework_for_ncr(ncr, user_id, db)
            if disposition in {"rework", "isolate", "scrap"} and ncr.get("order_id"):
                quality_status = "quarantined" if disposition in {"rework", "isolate"} else "nonconforming"
                QualityManagementRepository.set_inventory_quality(
                    ncr["order_id"], quality_status, f"质量异常单 {ncr['ncr_no']} 待质量放行", db
                )
            if disposition == "concession" and ncr.get("task_id"):
                QualityManagementRepository.release_task(ncr["task_id"], db)
                task = QualityManagementRepository.task_by_id(ncr["task_id"], db)
                if task and task.get("inspection_type") == "final" and task.get("order_id"):
                    QualityManagementRepository.set_inventory_quality(task["order_id"], "released", "让步接收", db)
                    from modules.services.order_completion_service import OrderCompletionService
                    OrderCompletionService.reconcile(
                        task["order_id"], trigger="quality_concession_release", actor_id=user_id, db=db
                    )
        return {"status": status, "disposition": disposition, "rework_id": rework_id}

    @staticmethod
    def list_capa(**filters):
        return QualityManagementRepository.list_capa(**filters)

    @classmethod
    def save_capa(cls, data, user_id, capa_id=None):
        title = cls._text(data.get("title"))
        if not title:
            raise ValidationError("CAPA 标题必填")
        normalized = {
            **data, "title": title, "problem_description": cls._text(data.get("problem_description")),
            "root_cause": cls._text(data.get("root_cause")), "corrective_action": cls._text(data.get("corrective_action")),
            "preventive_action": cls._text(data.get("preventive_action")), "due_at": cls._text(data.get("due_at")),
            "status": cls._text(data.get("status") or "open"),
            "effectiveness_result": cls._text(data.get("effectiveness_result")),
        }
        with BaseService.transaction() as db:
            if capa_id:
                if not QualityManagementRepository.capa_by_id(capa_id, db):
                    raise NotFoundError("CAPA 记录不存在")
                QualityManagementRepository.update_capa(capa_id, normalized, user_id, db)
                return capa_id
            normalized["capa_no"] = cls._new_code("CAPA", "quality_capa_records", db)
            return QualityManagementRepository.insert_capa(normalized, user_id, db)
