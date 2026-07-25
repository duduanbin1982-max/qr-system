"""QualityStandardService quality subdomain service."""

import json
import math
from datetime import datetime, timedelta

from modules.domain.errors import ConflictError, NotFoundError, ValidationError
from modules.domain.quality_rules import QUALITY_MANAGEMENT_DEFAULT_RULES
from modules.repositories.quality_management import QualityManagementRepository
from modules.repositories.setting_repository import SettingRepository
from modules.services import BaseService
from modules.services.quality_management.base import QualityManagementBase


class QualityStandardService(QualityManagementBase):
    @classmethod
    def _normalize_standard(cls, data):
        standard_no = cls._text(data.get("standard_no")).upper()
        name = cls._text(data.get("name"))
        inspection_type = cls._text(data.get("inspection_type"))
        if not standard_no or not name:
            raise ValidationError("标准编码和名称必填")
        if inspection_type not in cls.INSPECTION_TYPES:
            raise ValidationError("检验类型无效")
        gate_mode = cls._text(data.get("gate_mode") or "soft")
        sampling_mode = cls._text(data.get("sampling_mode") or "fixed")
        if gate_mode not in cls.GATE_MODES or sampling_mode not in cls.SAMPLING_MODES:
            raise ValidationError("门禁或抽样方式无效")
        items = data.get("items") or []
        if not isinstance(items, list) or not items:
            raise ValidationError("质量标准至少需要一个检验项目")
        normalized_items = []
        seen = set()
        for index, item in enumerate(items):
            code = cls._text(item.get("item_code")).upper()
            item_name = cls._text(item.get("item_name"))
            item_type = cls._text(item.get("item_type") or "boolean")
            if not code or not item_name:
                raise ValidationError(f"第 {index + 1} 个检验项目缺少编码或名称")
            if code in seen:
                raise ValidationError(f"检验项目编码重复：{code}")
            if item_type not in {"numeric", "boolean", "score", "text"}:
                raise ValidationError(f"检验项目类型无效：{item_type}")
            seen.add(code)
            normalized_items.append({
                **item,
                "item_code": code,
                "item_name": item_name,
                "item_type": item_type,
                "weight": max(cls._number(item.get("weight"), 0), 0),
                "sort_order": cls._positive_int(item.get("sort_order"), (index + 1) * 10),
            })
        return {
            **data,
            "standard_no": standard_no,
            "name": name,
            "inspection_type": inspection_type,
            "product_code": cls._text(data.get("product_code")),
            "route_id": data.get("route_id") or None,
            "process_id": data.get("process_id") or None,
            "version": max(cls._positive_int(data.get("version"), 1), 1),
            "status": cls._text(data.get("status") or "active"),
            "gate_mode": gate_mode,
            "sampling_mode": sampling_mode,
            "sample_value": max(cls._number(data.get("sample_value"), 1), 0.01),
            "min_score": min(max(cls._number(data.get("min_score"), 85), 0), 100),
            "acceptance_rule": cls._text(data.get("acceptance_rule") or "all_required_pass"),
            "notes": cls._text(data.get("notes")),
            "items": normalized_items,
        }

    @classmethod
    def list_standards(cls, **filters):
        return QualityManagementRepository.list_standards(**filters)

    @classmethod
    def get_standard(cls, standard_id):
        standard = QualityManagementRepository.standard_by_id(standard_id)
        if not standard:
            raise NotFoundError("质量标准不存在")
        return standard

    @classmethod
    def create_standard(cls, data, user_id):
        normalized = cls._normalize_standard(data)
        with BaseService.transaction() as db:
            if QualityManagementRepository.standard_no_exists(normalized["standard_no"], db=db):
                raise ConflictError("质量标准编码已存在")
            standard_id = QualityManagementRepository.insert_standard(normalized, user_id, db)
            QualityManagementRepository.replace_standard_items(standard_id, normalized["items"], db)
        return standard_id

    @classmethod
    def update_standard(cls, standard_id, data):
        current = cls.get_standard(standard_id)
        merged = {**current, **data, "items": data.get("items", current.get("items", []))}
        normalized = cls._normalize_standard(merged)
        with BaseService.transaction() as db:
            if QualityManagementRepository.standard_no_exists(normalized["standard_no"], standard_id, db):
                raise ConflictError("质量标准编码已存在")
            QualityManagementRepository.update_standard(standard_id, normalized, db)
            QualityManagementRepository.replace_standard_items(standard_id, normalized["items"], db)

    @staticmethod
    def archive_standard(standard_id):
        if not QualityManagementRepository.standard_by_id(standard_id):
            raise NotFoundError("质量标准不存在")
        with BaseService.transaction() as db:
            QualityManagementRepository.archive_standard(standard_id, db)

    @classmethod
    def _normalize_plan(cls, data):
        name = cls._text(data.get("name"))
        trigger_type = cls._text(data.get("trigger_type"))
        inspection_type = cls._text(data.get("inspection_type"))
        if not name:
            raise ValidationError("检验方案名称必填")
        if trigger_type not in cls.TRIGGER_TYPES or inspection_type not in cls.INSPECTION_TYPES:
            raise ValidationError("触发方式或检验类型无效")
        gate_mode = cls._text(data.get("gate_mode") or "soft")
        sampling_mode = cls._text(data.get("sampling_mode") or "fixed")
        if gate_mode not in cls.GATE_MODES or sampling_mode not in cls.SAMPLING_MODES:
            raise ValidationError("门禁或抽样方式无效")
        return {
            **data,
            "name": name,
            "standard_id": data.get("standard_id") or None,
            "product_code": cls._text(data.get("product_code")),
            "route_id": data.get("route_id") or None,
            "process_id": data.get("process_id") or None,
            "trigger_type": trigger_type,
            "inspection_type": inspection_type,
            "gate_mode": gate_mode,
            "sampling_mode": sampling_mode,
            "sample_value": max(cls._number(data.get("sample_value"), 1), 0.01),
            "frequency_qty": cls._positive_int(data.get("frequency_qty"), 0),
            "due_minutes": max(cls._positive_int(data.get("due_minutes"), 120), 1),
            "status": cls._text(data.get("status") or "active"),
        }

    @staticmethod
    def list_plans(**filters):
        return QualityManagementRepository.list_plans(**filters)

    @classmethod
    def create_plan(cls, data, user_id):
        normalized = cls._normalize_plan(data)
        if normalized.get("standard_id") and not QualityManagementRepository.standard_by_id(normalized["standard_id"]):
            raise ValidationError("关联质量标准不存在")
        with BaseService.transaction() as db:
            return QualityManagementRepository.insert_plan(normalized, user_id, db)

    @classmethod
    def update_plan(cls, plan_id, data):
        current = QualityManagementRepository.plan_by_id(plan_id)
        if not current:
            raise NotFoundError("检验方案不存在")
        normalized = cls._normalize_plan({**dict(current), **data})
        with BaseService.transaction() as db:
            QualityManagementRepository.update_plan(plan_id, normalized, db)

    @staticmethod
    def archive_plan(plan_id):
        if not QualityManagementRepository.plan_by_id(plan_id):
            raise NotFoundError("检验方案不存在")
        with BaseService.transaction() as db:
            QualityManagementRepository.archive_plan(plan_id, db)
