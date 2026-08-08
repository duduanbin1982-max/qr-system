"""Versioned performance rule and position-target configuration workflow."""

from copy import deepcopy
import json
import math

from modules.domain.errors import NotFoundError
from modules.domain.performance_policy import (
    PerformanceConflictError,
    require_row_version,
    validate_production_month,
)
from modules.repositories.performance_configuration_repository import (
    PerformanceConfigurationRepository,
)
from modules.services import BaseService
from modules.services.performance_authorization_service import (
    PerformanceAuthorizationService,
)
from modules.services.performance_scoring_policy import PerformanceScoringPolicy


class PerformanceConfigurationService:
    WEIGHT_FIELDS = ("output", "quality", "delivery", "discipline", "improvement")

    @staticmethod
    def _require(actor, action):
        if not PerformanceAuthorizationService.can_perform(actor, action):
            raise PermissionError("performance:" + action + " permission is required")
        actor_id = (actor or {}).get("id")
        if actor_id is None:
            raise PermissionError("绩效配置操作人不存在")
        return int(actor_id), str(
            (actor or {}).get("name") or (actor or {}).get("username") or ""
        )

    @staticmethod
    def _canonical(value):
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    @staticmethod
    def _finite_number(value, field):
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(field + "必须为数字") from exc
        if not math.isfinite(number):
            raise ValueError(field + "必须为有限数字")
        return number

    @staticmethod
    def _month_range(data, require_from=False):
        effective_from = str(data.get("effective_from_month") or "").strip()
        effective_to = str(data.get("effective_to_month") or "").strip()
        if require_from and not effective_from:
            raise ValueError("生效月份不能为空")
        if effective_from:
            validate_production_month(effective_from)
        if effective_to:
            validate_production_month(effective_to)
        if effective_from and effective_to and effective_to <= effective_from:
            raise ValueError("生效结束月份必须晚于开始月份")
        return effective_from, effective_to

    @classmethod
    def _rule_payload(cls, data, require_effective_from=False):
        version_code = str(data.get("version_code") or "").strip()
        if not version_code:
            raise ValueError("规则版本编码不能为空")
        if len(version_code) > 80:
            raise ValueError("规则版本编码过长")
        defaults = PerformanceScoringPolicy.rules()
        weights = deepcopy(data.get("weights") or defaults["weights"])
        if not isinstance(weights, dict):
            raise ValueError("绩效权重格式无效")
        if set(weights) != set(cls.WEIGHT_FIELDS):
            raise ValueError("绩效权重必须包含五个维度")
        normalized_weights = {
            name: cls._finite_number(weights[name], name + "评分权重")
            for name in cls.WEIGHT_FIELDS
        }
        if any(value < 0 for value in normalized_weights.values()):
            raise ValueError("绩效权重不能为负数")
        if round(sum(normalized_weights.values()), 6) != 100:
            raise ValueError("绩效五维权重必须为非负数且合计 100")
        warning_levels = deepcopy(
            data.get("warning_levels")
            if data.get("warning_levels") is not None
            else defaults["warning_levels"]
        )
        if not isinstance(warning_levels, list) or not warning_levels:
            raise ValueError("绩效等级阈值不能为空")
        normalized_levels = []
        for item in warning_levels:
            if not isinstance(item, dict) or not str(item.get("level") or "").strip():
                raise ValueError("绩效等级阈值格式无效")
            normalized_levels.append(
                {
                    "level": str(item["level"]).strip(),
                    "min_score": cls._finite_number(item.get("min_score"), "绩效等级阈值"),
                    "reason": str(item.get("reason") or "").strip(),
                }
            )
        parameters = {
            "work_days_target": defaults["work_days_target"],
            "handoff": deepcopy(defaults["handoff"]),
            "improvement": deepcopy(defaults["improvement"]),
        }
        provided_parameters = data.get("scoring_parameters")
        if provided_parameters is not None:
            if not isinstance(provided_parameters, dict):
                raise ValueError("绩效评分参数格式无效")
            for key, value in provided_parameters.items():
                if key in ("handoff", "improvement"):
                    if not isinstance(value, dict):
                        raise ValueError("绩效评分参数格式无效")
                    parameters[key].update(value)
                else:
                    parameters[key] = value
        if "work_days_target" in data:
            parameters["work_days_target"] = data["work_days_target"]
        parameters["work_days_target"] = cls._finite_number(
            parameters["work_days_target"], "交付目标工作日"
        )
        if parameters["work_days_target"] <= 0:
            raise ValueError("交付目标工作日必须大于 0")
        effective_from, effective_to = cls._month_range(
            data, require_from=require_effective_from
        )
        return {
            "version_code": version_code,
            "name": str(data.get("name") or "").strip(),
            "weights_json": cls._canonical(
                {
                    key: int(value) if value.is_integer() else value
                    for key, value in normalized_weights.items()
                }
            ),
            "warning_levels_json": cls._canonical(normalized_levels),
            "scoring_parameters_json": cls._canonical(parameters),
            "effective_from_month": effective_from,
            "effective_to_month": effective_to,
        }

    @staticmethod
    def _rule_data(row):
        """Convert a persisted rule row to the editable service payload shape."""
        try:
            weights = json.loads(row.get("weights_json") or "{}")
            warning_levels = json.loads(row.get("warning_levels_json") or "[]")
            scoring_parameters = json.loads(
                row.get("scoring_parameters_json") or "{}"
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("绩效规则版本数据损坏") from exc
        return {
            "version_code": row.get("version_code", ""),
            "name": row.get("name", ""),
            "weights": weights,
            "warning_levels": warning_levels,
            "scoring_parameters": scoring_parameters,
            "effective_from_month": row.get("effective_from_month", ""),
            "effective_to_month": row.get("effective_to_month", ""),
        }

    @staticmethod
    def _target_payload(data, db, require_effective_from=True):
        try:
            position_id = int(data.get("position_id"))
        except (TypeError, ValueError) as exc:
            raise ValueError("岗位必须有效") from exc
        position = PerformanceConfigurationRepository.position(position_id, db=db)
        if not position:
            raise ValueError("岗位不存在")
        try:
            target_output = PerformanceConfigurationService._finite_number(
                data.get("target_output_qty"), "岗位目标产量"
            )
            minimum_days_value = PerformanceConfigurationService._finite_number(
                data.get("minimum_effective_work_days"), "最低有效报工日"
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("岗位目标产量和最低有效报工日必须有效") from exc
        if not minimum_days_value.is_integer():
            raise ValueError("最低有效报工日必须为整数")
        minimum_days = int(minimum_days_value)
        if target_output <= 0 or minimum_days <= 0:
            raise ValueError("岗位目标产量和最低有效报工日必须大于 0")
        effective_from, effective_to = PerformanceConfigurationService._month_range(
            data, require_from=require_effective_from
        )
        return {
            "position_id": position_id,
            "position_name_snapshot": position["name"],
            "target_output_qty": target_output,
            "minimum_effective_work_days": minimum_days,
            "effective_from_month": effective_from,
            "effective_to_month": effective_to,
        }

    @staticmethod
    def create_rule_version(data, actor, db=None):
        actor_id, actor_name = PerformanceConfigurationService._require(actor, "prepare")
        payload = PerformanceConfigurationService._rule_payload(data or {})
        with BaseService.transaction() as txn:
            if PerformanceConfigurationRepository.rule_by_code(
                payload["version_code"], db=txn
            ):
                raise ValueError("规则版本编码已存在")
            payload.update({"created_by": actor_id, "created_by_name": actor_name})
            rule_id = PerformanceConfigurationRepository.insert_rule(payload, db=txn)
            return PerformanceConfigurationRepository.rule(rule_id, db=txn)

    @staticmethod
    def list_rule_versions(status="", db=None):
        return PerformanceConfigurationRepository.list_rules(status=status, db=db)

    @staticmethod
    def get_rule_version(rule_id, db=None):
        row = PerformanceConfigurationRepository.rule(rule_id, db=db)
        if not row:
            raise ValueError("绩效规则版本不存在")
        return row

    @staticmethod
    def update_rule_version(rule_id, data, actor, expected_row_version, db=None):
        PerformanceConfigurationService._require(actor, "prepare")
        expected = require_row_version(expected_row_version)
        with BaseService.transaction() as txn:
            current = PerformanceConfigurationRepository.rule(rule_id, db=txn)
            if not current:
                raise ValueError("绩效规则版本不存在")
            merged = PerformanceConfigurationService._rule_data(current)
            merged.update(data or {})
            payload = PerformanceConfigurationService._rule_payload(merged)
            fields = {
                key: payload[key]
                for key in (
                    "name",
                    "weights_json",
                    "warning_levels_json",
                    "scoring_parameters_json",
                    "effective_from_month",
                    "effective_to_month",
                )
            }
            PerformanceConfigurationRepository.update_rule_draft(
                rule_id, expected, fields, db=txn
            )
            return PerformanceConfigurationRepository.rule(rule_id, db=txn)

    @staticmethod
    def publish_rule_version(rule_id, actor, expected_row_version, db=None):
        actor_id, actor_name = PerformanceConfigurationService._require(actor, "approve")
        expected = require_row_version(expected_row_version)
        with BaseService.transaction() as txn:
            row = PerformanceConfigurationRepository.rule(rule_id, db=txn)
            if not row:
                raise ValueError("绩效规则版本不存在")
            if not row["effective_from_month"]:
                raise ValueError("发布规则必须设置生效月份")
            if PerformanceConfigurationRepository.published_rule_overlap(
                row["effective_from_month"],
                row["effective_to_month"],
                exclude_id=rule_id,
                db=txn,
            ):
                raise PerformanceConflictError("绩效规则生效区间与已发布版本重叠")
            PerformanceConfigurationRepository.publish_rule(
                rule_id,
                expected,
                actor_id,
                actor_name,
                db=txn,
            )
            return PerformanceConfigurationRepository.rule(rule_id, db=txn)

    @staticmethod
    def delete_rule_version(rule_id, actor, db=None):
        PerformanceConfigurationService._require(actor, "prepare")
        with BaseService.transaction() as txn:
            if PerformanceConfigurationRepository.rule_reference_count(rule_id, db=txn):
                raise PerformanceConflictError("已被绩效批次引用的规则不能删除")
            PerformanceConfigurationRepository.delete_rule(rule_id, db=txn)
        return True

    @staticmethod
    def create_position_target_version(data, actor, db=None):
        actor_id, actor_name = PerformanceConfigurationService._require(
            actor, "prepare"
        )
        with BaseService.transaction() as txn:
            payload = PerformanceConfigurationService._target_payload(data or {}, txn)
            target_id = PerformanceConfigurationRepository.insert_target(
                {**payload, "created_by": actor_id, "created_by_name": actor_name},
                db=txn,
            )
            return PerformanceConfigurationRepository.target(target_id, db=txn)

    @staticmethod
    def list_position_target_versions(position_id=None, status="", db=None):
        return PerformanceConfigurationRepository.list_targets(
            position_id=position_id, status=status, db=db
        )

    @staticmethod
    def update_position_target_version(
        target_id, data, actor, expected_row_version, db=None
    ):
        PerformanceConfigurationService._require(actor, "prepare")
        expected = require_row_version(expected_row_version)
        with BaseService.transaction() as txn:
            current = PerformanceConfigurationRepository.target(target_id, db=txn)
            if not current:
                raise ValueError("岗位目标版本不存在")
            if PerformanceConfigurationRepository.target_reference_count(
                target_id, db=txn
            ):
                raise PerformanceConflictError("已被评分引用的岗位目标不能修改")
            merged = {
                "position_id": current["position_id"],
                "target_output_qty": current["target_output_qty"],
                "minimum_effective_work_days": current[
                    "minimum_effective_work_days"
                ],
                "effective_from_month": current["effective_from_month"],
                "effective_to_month": current["effective_to_month"],
            }
            merged.update(data or {})
            payload = PerformanceConfigurationService._target_payload(merged, txn)
            PerformanceConfigurationRepository.update_target_draft(
                target_id, expected, payload, db=txn
            )
            return PerformanceConfigurationRepository.target(target_id, db=txn)

    @staticmethod
    def approve_position_target_version(target_id, actor, expected_row_version, db=None):
        actor_id, actor_name = PerformanceConfigurationService._require(
            actor, "approve"
        )
        expected = require_row_version(expected_row_version)
        with BaseService.transaction() as txn:
            row = PerformanceConfigurationRepository.target(target_id, db=txn)
            if not row:
                raise ValueError("岗位目标版本不存在")
            if row["effective_to_month"] == "":
                raise ValueError("批准岗位目标必须设置生效结束月份")
            if PerformanceConfigurationRepository.approved_target_overlap(
                row["position_id"],
                row["effective_from_month"],
                row["effective_to_month"],
                exclude_id=target_id,
                db=txn,
            ):
                raise PerformanceConflictError("岗位目标生效区间重叠")
            PerformanceConfigurationRepository.approve_target(
                target_id,
                expected,
                actor_id,
                actor_name,
                db=txn,
            )
            return PerformanceConfigurationRepository.target(target_id, db=txn)

    @staticmethod
    def delete_position_target_version(target_id, actor, db=None):
        PerformanceConfigurationService._require(actor, "prepare")
        with BaseService.transaction() as txn:
            if PerformanceConfigurationRepository.target_reference_count(
                target_id, db=txn
            ):
                raise PerformanceConflictError("已被评分引用的岗位目标不能删除")
            PerformanceConfigurationRepository.delete_target(target_id, db=txn)
        return True

    @staticmethod
    def get_position_target(position_id, production_month, db=None):
        validate_production_month(production_month)
        if not PerformanceConfigurationRepository.position(position_id, db=db):
            raise NotFoundError("岗位不存在")
        target = PerformanceConfigurationRepository.approved_target_for_month(
            position_id, production_month, db=db
        )
        if not target:
            raise NotFoundError("岗位目标不存在")
        return target

    @staticmethod
    def get_rule_for_month(production_month, db=None):
        validate_production_month(production_month)
        rule = PerformanceConfigurationRepository.published_rule_for_month(
            production_month, db=db
        )
        if not rule:
            raise ValueError("绩效规则版本不存在")
        return rule
