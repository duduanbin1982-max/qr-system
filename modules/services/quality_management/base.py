"""QualityManagementBase quality subdomain service."""

import json
import math
from datetime import datetime, timedelta

from modules.domain.errors import ConflictError, NotFoundError, ValidationError
from modules.domain.quality_rules import QUALITY_MANAGEMENT_DEFAULT_RULES
from modules.repositories.quality_management import QualityManagementRepository
from modules.repositories.setting_repository import SettingRepository
from modules.services import BaseService


class QualityManagementBase:
    INSPECTION_TYPES = {"first_article", "in_process", "final", "outgoing", "rework_check", "quality_verification", "manual"}

    GATE_MODES = {"off", "soft", "hard"}

    SAMPLING_MODES = {"fixed", "ratio", "full"}

    TRIGGER_TYPES = {"first_report", "quantity_interval", "final_process", "shipment", "rework_complete", "low_evaluation", "manual"}

    TASK_STATUSES = {"pending", "in_progress", "passed", "failed", "cancelled"}

    DISPOSITIONS = {"pending", "rework", "scrap", "concession", "isolate", "return"}

    @staticmethod
    def _text(value):
        return str(value or "").strip()

    @staticmethod
    def _positive_int(value, default=0):
        try:
            result = int(value)
        except (TypeError, ValueError):
            result = default
        return max(result, 0)

    @staticmethod
    def _number(value, default=0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @staticmethod
    def _foreign_id(value):
        try:
            result = int(value)
        except (TypeError, ValueError):
            return None
        return result if result > 0 else None

    @classmethod
    def rules(cls, db=None):
        raw = SettingRepository.get_value("quality_management_rules", "", db=db)
        try:
            stored = json.loads(raw or "{}")
        except (TypeError, json.JSONDecodeError):
            stored = {}
        result = dict(QUALITY_MANAGEMENT_DEFAULT_RULES)
        if isinstance(stored, dict):
            result.update(stored)
        return result

    @classmethod
    def save_rules(cls, data):
        rules = cls.rules()
        for key in QUALITY_MANAGEMENT_DEFAULT_RULES:
            if key in data:
                rules[key] = data[key]
        for key in ("first_article_gate", "in_process_gate", "final_gate", "shipment_gate"):
            if rules[key] not in cls.GATE_MODES:
                raise ValidationError(f"{key} 配置无效")
        rules["in_process_frequency"] = max(cls._positive_int(rules.get("in_process_frequency"), 20), 1)
        rules["capa_repeat_threshold"] = max(cls._positive_int(rules.get("capa_repeat_threshold"), 3), 1)
        rules["gauge_due_warning_days"] = max(cls._positive_int(rules.get("gauge_due_warning_days"), 30), 0)
        with BaseService.transaction() as db:
            SettingRepository.upsert_txn("quality_management_rules", json.dumps(rules, ensure_ascii=False), db)
        return rules

    @staticmethod
    def reference_data():
        return QualityManagementRepository.reference_data()
