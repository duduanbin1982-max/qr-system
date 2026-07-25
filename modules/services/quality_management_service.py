"""Quality management application service."""

import json
import math
from datetime import datetime, timedelta

from modules.domain.errors import ConflictError, NotFoundError, ValidationError
from modules.migration_quality_management import DEFAULT_RULES
from modules.repositories.quality_management_repository import QualityManagementRepository
from modules.repositories.setting_repository import SettingRepository
from modules.services import BaseService


class QualityManagementService:
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
        result = dict(DEFAULT_RULES)
        if isinstance(stored, dict):
            result.update(stored)
        return result

    @classmethod
    def save_rules(cls, data):
        rules = cls.rules()
        for key in DEFAULT_RULES:
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

    @classmethod
    def _sample_qty(cls, plan, lot_qty):
        lot_qty = max(cls._positive_int(lot_qty, 1), 1)
        mode = plan.get("sampling_mode") or "fixed"
        value = max(cls._number(plan.get("sample_value"), 1), 0.01)
        if mode == "full":
            return lot_qty
        if mode == "ratio":
            return min(max(math.ceil(lot_qty * value / 100), 1), lot_qty)
        return min(max(math.ceil(value), 1), lot_qty)

    @classmethod
    def _new_code(cls, prefix, table_name, db):
        sequence = QualityManagementRepository.next_sequence(table_name, db)
        return f"{prefix}-{datetime.now().strftime('%Y%m%d')}-{sequence:04d}"

    @classmethod
    def _create_task(cls, plan, context, trigger_key, db, **extra):
        task_no = cls._new_code("QT", "quality_inspection_tasks", db)
        due_minutes = max(cls._positive_int(plan.get("due_minutes"), 120), 1)
        due_at = (datetime.now() + timedelta(minutes=due_minutes)).strftime("%Y-%m-%d %H:%M:%S")
        standard = None
        if plan.get("standard_id"):
            standard = QualityManagementRepository.standard_by_id(plan["standard_id"], db=db)
        data = {
            "task_no": task_no,
            "trigger_key": trigger_key,
            "plan_id": plan.get("id"),
            "standard_id": plan.get("standard_id"),
            "standard_version": (standard or {}).get("version", plan.get("standard_version", 1)),
            "order_id": context.get("order_id"),
            "process_id": context.get("process_id"),
            "work_record_id": context.get("work_record_id"),
            "shipment_id": context.get("shipment_id"),
            "serial_no": context.get("serial_no", ""),
            "batch_no": context.get("batch_no", ""),
            "inspection_type": plan["inspection_type"],
            "trigger_type": plan["trigger_type"],
            "gate_mode": plan.get("gate_mode", "soft"),
            "sample_qty": cls._sample_qty(plan, context.get("lot_qty", 1)),
            "priority": extra.get("priority", "normal"),
            "assigned_to": extra.get("assigned_to"),
            "due_at": due_at,
            "created_by": cls._foreign_id(extra.get("created_by")),
            "supplier_id": extra.get("supplier_id"),
            "material_id": extra.get("material_id"),
            "source_evaluation_id": extra.get("source_evaluation_id"),
            "source_ncr_id": extra.get("source_ncr_id"),
        }
        return QualityManagementRepository.insert_task(data, db)

    @classmethod
    def generate_for_report(cls, order_id, process_id, work_record_id, serial_no, user_id, db):
        rules = cls.rules(db)
        if not rules.get("enabled", True):
            return []
        context_row = QualityManagementRepository.report_context(order_id, process_id, db)
        if not context_row:
            return []
        context = dict(context_row)
        context.update({"work_record_id": work_record_id, "serial_no": serial_no or "", "lot_qty": context["quantity"]})
        task_ids = []
        if context["approved_reports"] == 1 and rules.get("auto_first_article", True):
            for plan_row in QualityManagementRepository.matching_plans(order_id, process_id, "first_report", db):
                plan = dict(plan_row)
                plan["gate_mode"] = rules.get("first_article_gate", plan.get("gate_mode", "hard"))
                task_ids.append(cls._create_task(plan, context, f"first-report:{order_id}:{process_id}", db, created_by=user_id))
        for plan_row in QualityManagementRepository.matching_plans(order_id, process_id, "quantity_interval", db):
            plan = dict(plan_row)
            frequency = max(cls._positive_int(plan.get("frequency_qty"), rules.get("in_process_frequency", 20)), 1)
            bucket = cls._positive_int(context.get("completed"), 0) // frequency
            if bucket > 0:
                plan["gate_mode"] = rules.get("in_process_gate", plan.get("gate_mode", "soft"))
                task_ids.append(cls._create_task(plan, context, f"interval:{order_id}:{process_id}:{bucket}", db, created_by=user_id))
        is_final = context.get("seq_order") == context.get("last_seq_order")
        is_complete = cls._positive_int(context.get("completed"), 0) >= cls._positive_int(context.get("quantity"), 0) > 0
        if is_final and is_complete and rules.get("auto_final_inspection", True):
            for plan_row in QualityManagementRepository.matching_plans(order_id, process_id, "final_process", db):
                plan = dict(plan_row)
                plan["gate_mode"] = rules.get("final_gate", plan.get("gate_mode", "hard"))
                task_id = cls._create_task(plan, context, f"final-process:{order_id}", db, created_by=user_id, priority="urgent")
                task_ids.append(task_id)
                if task_id and plan["gate_mode"] == "hard":
                    QualityManagementRepository.set_inventory_quality(
                        order_id, "quarantined", f"等待完工检验任务 QT#{task_id} 放行", db
                    )
        return [task_id for task_id in task_ids if task_id]

    @classmethod
    def generate_for_shipment(cls, shipment_id, user_id, db):
        rules = cls.rules(db)
        if not rules.get("enabled", True) or not rules.get("auto_outgoing_inspection", True):
            return []
        task_ids = []
        for context_row in QualityManagementRepository.shipment_order_contexts(shipment_id, db):
            context = dict(context_row)
            process_id = context.get("process_id")
            if not process_id:
                continue
            context.update({"shipment_id": shipment_id, "lot_qty": context.get("quantity", 1)})
            for plan_row in QualityManagementRepository.matching_plans(context["order_id"], process_id, "shipment", db):
                plan = dict(plan_row)
                plan["gate_mode"] = rules.get("shipment_gate", plan.get("gate_mode", "hard"))
                task_ids.append(cls._create_task(
                    plan, context, f"shipment:{shipment_id}:{context['order_id']}", db, created_by=user_id, priority="urgent"
                ))
        return [task_id for task_id in task_ids if task_id]

    @classmethod
    def generate_for_rework(cls, rework_id, user_id, db):
        context_row = QualityManagementRepository.rework_context(rework_id, db)
        if not context_row:
            return None
        context = dict(context_row)
        context["lot_qty"] = context.get("quantity", 1)
        plans = QualityManagementRepository.matching_plans(context["order_id"], context["process_id"], "rework_complete", db)
        if not plans:
            return None
        return cls._create_task(
            dict(plans[0]), context, f"rework:{rework_id}", db, created_by=user_id,
            source_ncr_id=context.get("source_ncr_id"), priority="urgent",
        )

    @classmethod
    def generate_for_low_evaluation(cls, evaluation, user_id, db):
        rules = cls.rules(db)
        if not rules.get("enabled", True) or not rules.get("low_evaluation_creates_task", True):
            return None
        standard_row = QualityManagementRepository.default_standard("in_process", db)
        standard = dict(standard_row) if standard_row else {}
        plan = {
            "id": None, "standard_id": standard.get("id"), "standard_version": standard.get("version", 1),
            "inspection_type": "quality_verification", "trigger_type": "low_evaluation",
            "gate_mode": "hard" if evaluation.get("severity") == "critical" else "soft",
            "sampling_mode": "fixed", "sample_value": max(cls._positive_int(evaluation.get("quantity"), 1), 1),
            "due_minutes": 120,
        }
        context = {
            "order_id": evaluation.get("order_id"), "process_id": evaluation.get("target_process_id"),
            "serial_no": evaluation.get("serial_no", ""), "work_record_id": evaluation.get("target_work_record_id"),
            "lot_qty": evaluation.get("quantity", 1),
        }
        return cls._create_task(
            plan, context, f"quality-evaluation:{evaluation['id']}", db, created_by=user_id,
            source_evaluation_id=evaluation["id"], priority="urgent",
        )

    @classmethod
    def create_manual_task(cls, data, user_id):
        order_id = data.get("order_id")
        process_id = data.get("process_id")
        if not order_id or not process_id:
            raise ValidationError("手工检验任务必须选择订单和工序")
        inspection_type = cls._text(data.get("inspection_type") or "manual")
        if inspection_type not in cls.INSPECTION_TYPES:
            raise ValidationError("检验类型无效")
        standard = QualityManagementRepository.standard_by_id(data.get("standard_id")) if data.get("standard_id") else None
        plan = {
            "id": None, "standard_id": data.get("standard_id"),
            "inspection_type": inspection_type, "trigger_type": "manual",
            "gate_mode": cls._text(data.get("gate_mode") or "soft"), "sampling_mode": "fixed",
            "sample_value": max(cls._positive_int(data.get("sample_qty"), 1), 1),
            "due_minutes": max(cls._positive_int(data.get("due_minutes"), 120), 1),
            "standard_version": (standard or {}).get("version", 1),
        }
        if plan["gate_mode"] not in cls.GATE_MODES:
            raise ValidationError("门禁模式无效")
        context = {
            "order_id": order_id, "process_id": process_id, "serial_no": cls._text(data.get("serial_no")),
            "lot_qty": data.get("sample_qty", 1), "batch_no": cls._text(data.get("batch_no")),
        }
        with BaseService.transaction() as db:
            trigger_key = f"manual:{datetime.now().strftime('%Y%m%d%H%M%S%f')}:{user_id}"
            return cls._create_task(
                plan, context, trigger_key, db, created_by=user_id,
                assigned_to=data.get("assigned_to"), priority=cls._text(data.get("priority") or "normal"),
            )

    @staticmethod
    def list_tasks(**filters):
        return QualityManagementRepository.list_tasks(**filters)

    @staticmethod
    def get_task(task_id):
        task = QualityManagementRepository.task_by_id(task_id)
        if not task:
            raise NotFoundError("检验任务不存在")
        return task

    @staticmethod
    def start_task(task_id, user_id):
        task = QualityManagementService.get_task(task_id)
        if task["status"] != "pending":
            raise ConflictError("只有待检任务可以开始")
        with BaseService.transaction() as db:
            QualityManagementRepository.start_task(task_id, user_id, db)

    @classmethod
    def _evaluate_measurements(cls, standard_items, measurements):
        supplied = {}
        for value in measurements if isinstance(measurements, list) else []:
            item_id = value.get("item_id")
            item_code = cls._text(value.get("item_code")).upper()
            if item_id:
                supplied[("id", int(item_id))] = value
            if item_code:
                supplied[("code", item_code)] = value
        normalized = []
        failed_items = []
        score_total = 0.0
        score_max = 0.0
        for item in standard_items:
            measurement = supplied.get(("id", item["id"])) or supplied.get(("code", item["item_code"])) or {}
            raw_value = measurement.get("value", "")
            passed = True
            reason = ""
            item_type = item["item_type"]
            if item_type == "numeric":
                if raw_value in (None, ""):
                    passed = not bool(item["required"])
                    reason = "缺少实测值" if not passed else ""
                else:
                    try:
                        numeric = float(raw_value)
                        if item["lower_limit"] not in (None, "") and numeric < float(item["lower_limit"]):
                            passed, reason = False, "低于下限"
                        if item["upper_limit"] not in (None, "") and numeric > float(item["upper_limit"]):
                            passed, reason = False, "高于上限"
                    except (TypeError, ValueError):
                        passed, reason = False, "实测值格式错误"
            elif item_type == "boolean":
                passed = raw_value in (True, 1, "1", "pass", "yes", "合格")
                if not passed:
                    reason = "判定不合格"
            elif item_type == "score":
                score_max += max(cls._number(item.get("weight"), 0), 0)
                score = cls._number(raw_value, 0)
                score = min(max(score, 0), max(cls._number(item.get("weight"), 0), 0))
                score_total += score
                passed = score >= cls._number(item.get("weight"), 0) * 0.6
                if not passed:
                    reason = "单项评分偏低"
            elif item_type == "text":
                passed = bool(cls._text(raw_value)) or not bool(item["required"])
                if not passed:
                    reason = "缺少检验说明"
            normalized.append({
                "item_id": item["id"], "item_code": item["item_code"], "item_name": item["item_name"],
                "item_type": item_type, "value": raw_value, "unit": item.get("unit", ""),
                "passed": passed, "note": cls._text(measurement.get("note")), "reason": reason,
                "standard": {
                    "nominal": item.get("nominal_value", ""), "lower": item.get("lower_limit", ""),
                    "upper": item.get("upper_limit", ""), "criteria": item.get("acceptance_criteria", ""),
                },
            })
            if item["required"] and not passed:
                failed_items.append({"item_code": item["item_code"], "item_name": item["item_name"], "reason": reason})
        normalized_score = round(score_total / score_max * 100, 1) if score_max > 0 else 0
        return normalized, failed_items, normalized_score

    @classmethod
    def inspect_task(cls, task_id, data, user, inspection_context=None):
        user_id = user.get("id") if user else None
        inspection_context = inspection_context or {}
        task = cls.get_task(task_id)
        if task["status"] not in {"pending", "in_progress"}:
            raise ConflictError("该检验任务已经结束")
        quantity_checked = max(cls._positive_int(data.get("quantity_checked"), task.get("sample_qty", 1)), 1)
        quantity_failed = min(cls._positive_int(data.get("quantity_failed"), 0), quantity_checked)
        quantity_passed = quantity_checked - quantity_failed
        measurements, failed_items, measured_score = cls._evaluate_measurements(
            task.get("standard_items", []), data.get("measurements", [])
        )
        score_total = cls._number(data.get("score_total"), measured_score)
        if measured_score:
            score_total = measured_score
        min_score = cls._number(task.get("min_score"), 85)
        derived_pass = not failed_items and quantity_failed == 0 and (not score_total or score_total >= min_score)
        requested = cls._text(data.get("result") or ("pass" if derived_pass else "rework"))
        if requested not in {"pass", "rework", "scrap"}:
            raise ValidationError("检验判定无效")
        if requested == "pass" and not derived_pass:
            requested = "rework"
        defect_level = cls._text(data.get("defect_level"))
        if requested != "pass" and defect_level not in {"minor", "general", "severe", "critical"}:
            raise ValidationError("不合格检验必须选择缺陷等级")
        inspected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        inspection_data = {
            "task_id": task_id, "order_id": task.get("order_id"), "process_id": task.get("process_id"),
            "inspection_type": task["inspection_type"], "quantity_checked": quantity_checked,
            "quantity_passed": quantity_passed, "quantity_failed": quantity_failed or (1 if requested != "pass" else 0),
            "result": requested, "defect_category": cls._text(data.get("defect_category")),
            "defect_quantity": quantity_failed or (1 if requested != "pass" else 0),
            "notes": cls._text(data.get("notes")), "inspected_at": inspected_at,
            "order_no": inspection_context.get("order_no") or task.get("order_no", ""),
            "product_code": inspection_context.get("product_code") or task.get("product_code", ""),
            "process_name": inspection_context.get("process_name") or task.get("process_name", ""),
            "inspector_name": user.get("name", "") if user else "",
            "serial_no": inspection_context.get("serial_no") or task.get("serial_no", ""), "score_total": score_total,
            "score_detail_json": json.dumps(data.get("score_detail", {}), ensure_ascii=False),
            "defect_level": defect_level, "defect_items_json": json.dumps(failed_items, ensure_ascii=False),
            "suggested_result": "pass" if derived_pass else "rework", "final_result": requested,
            "override_reason": cls._text(data.get("override_reason")), "standard_id": task.get("standard_id"),
            "standard_version": task.get("standard_version", 1), "measurements_json": json.dumps(measurements, ensure_ascii=False),
            "quality_status": "released" if requested == "pass" else "nonconforming",
            "batch_no": task.get("batch_no", ""), "scope_type": "production",
        }
        with BaseService.transaction() as db:
            inspection_id = QualityManagementRepository.insert_inspection(inspection_data, user_id, db)
            QualityManagementRepository.complete_task(
                task_id, inspection_id, "passed" if requested == "pass" else "failed", user_id, db
            )
            ncr_id = None
            if requested != "pass":
                ncr_no = cls._new_code("NCR", "quality_nonconformances", db)
                ncr_id = QualityManagementRepository.insert_ncr({
                    "ncr_no": ncr_no, "task_id": task_id, "inspection_id": inspection_id,
                    "order_id": task.get("order_id"), "process_id": task.get("process_id"),
                    "serial_no": task.get("serial_no", ""), "defect_category": inspection_data["defect_category"],
                    "defect_level": defect_level, "defect_quantity": inspection_data["defect_quantity"],
                    "description": inspection_data["notes"] or "；".join(item["item_name"] for item in failed_items),
                    "disposition": cls._text(data.get("disposition") or "pending"), "status": "open",
                    "responsible_user_id": data.get("responsible_user_id"),
                    "responsible_process_id": data.get("responsible_process_id") or task.get("process_id"),
                    "owner_id": data.get("owner_id"), "due_at": cls._text(data.get("due_at")),
                }, user_id, db)
                QualityManagementRepository.add_ncr_action(ncr_id, "create", "", "open", "检验不合格自动创建", user_id, db)
            elif task.get("source_ncr_id"):
                cls._close_ncr_after_reinspection(task["source_ncr_id"], user_id, inspection_id, db)
            if requested == "pass" and task.get("inspection_type") == "final" and task.get("order_id"):
                QualityManagementRepository.set_inventory_quality(task["order_id"], "released", "", db)
                from modules.services.order_completion_service import OrderCompletionService
                OrderCompletionService.reconcile(
                    task["order_id"], trigger="quality_final_release", actor_id=user_id, db=db
                )
        return {"inspection_id": inspection_id, "ncr_id": ncr_id, "result": requested, "score_total": score_total}

    @classmethod
    def inspect_from_mobile(cls, data, user):
        context_row = QualityManagementRepository.mobile_inspection_context(
            order_id=data.get("order_id"), order_no=cls._text(data.get("order_no")),
            process_id=data.get("process_id"), process_name=cls._text(data.get("process_name")),
        )
        if not context_row:
            raise ValidationError("无法确定抽检订单和工序，请重新扫码后选择工序")
        context = dict(context_row)
        serial_no = cls._text(data.get("serial_no"))
        task_row = QualityManagementRepository.pending_mobile_task(
            context["order_id"], context["process_id"], serial_no,
        )
        if task_row:
            task_id = task_row["id"]
        else:
            standard_row = QualityManagementRepository.default_standard("in_process")
            task_id = cls.create_manual_task({
                "order_id": context["order_id"], "process_id": context["process_id"],
                "inspection_type": "in_process", "standard_id": standard_row["id"] if standard_row else None,
                "serial_no": serial_no, "sample_qty": data.get("quantity_checked") or 1,
                "gate_mode": "soft", "priority": "normal",
            }, user.get("id") if user else None)

        task = cls.get_task(task_id)
        try:
            score_detail = json.loads(data.get("score_detail_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            score_detail = {}
        score_keys = {
            "DIMENSION": "dimension_accuracy", "PROCESS": "process_conformance",
            "APPEARANCE": "appearance_quality", "FUNCTION": "function_impact",
            "DOCUMENT": "documentation_other",
        }
        measurements = []
        for item in task.get("standard_items", []):
            item_type = item.get("item_type")
            value = ""
            if item_type == "score":
                score_value = score_detail.get(score_keys.get(item.get("item_code"), ""), {})
                value = score_value.get("score", item.get("weight", 0)) if isinstance(score_value, dict) else score_value
            elif item_type == "boolean":
                value = True
            elif item_type == "numeric":
                value = item.get("nominal_value") or item.get("lower_limit") or item.get("upper_limit") or 0
            elif item_type == "text":
                value = "符合"
            measurements.append({"item_id": item["id"], "item_code": item["item_code"], "value": value})

        result = cls._text(data.get("final_result") or data.get("result") or "pass")
        defect_level = cls._text(data.get("defect_level"))
        if result != "pass" and not defect_level:
            defect_level = "general" if result == "rework" else "severe"
        payload = {
            "quantity_checked": data.get("quantity_checked") or task.get("sample_qty") or 1,
            "quantity_failed": data.get("quantity_failed", 0 if result == "pass" else 1),
            "result": result, "defect_level": defect_level,
            "defect_category": cls._text(data.get("defect_category") or "other" if result != "pass" else ""),
            "notes": cls._text(data.get("notes") or data.get("remark")),
            "score_total": data.get("score_total", 0),
            "score_detail": score_detail, "override_reason": cls._text(data.get("override_reason")),
            "measurements": measurements,
        }
        inspected = cls.inspect_task(task_id, payload, user, inspection_context={
            "order_no": cls._text(data.get("order_no")) or context["order_no"],
            "product_code": cls._text(data.get("product_code")) or context["product_code"],
            "process_name": cls._text(data.get("process_name")) or context["process_name"],
            "serial_no": serial_no,
        })
        return {**inspected, "task_id": task_id}

    @classmethod
    def _close_ncr_after_reinspection(cls, ncr_id, user_id, inspection_id, db):
        row = QualityManagementRepository.ncr_by_id(ncr_id, db)
        if not row:
            return
        ncr = dict(row)
        old_status = ncr["status"]
        ncr.update({
            "status": "closed", "verification_result": f"复检通过，检验记录 #{inspection_id}",
            "closed_by": user_id, "closed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        QualityManagementRepository.update_ncr(ncr_id, ncr, db)
        QualityManagementRepository.add_ncr_action(ncr_id, "reinspection_pass", old_status, "closed", ncr["verification_result"], user_id, db)
        if ncr.get("task_id"):
            QualityManagementRepository.release_task(ncr["task_id"], db)
            original_task = QualityManagementRepository.task_by_id(ncr["task_id"], db)
            if original_task and original_task.get("inspection_type") == "final" and original_task.get("order_id"):
                QualityManagementRepository.set_inventory_quality(original_task["order_id"], "released", "", db)
                from modules.services.order_completion_service import OrderCompletionService
                OrderCompletionService.reconcile(
                    original_task["order_id"], trigger="quality_reinspection_release", actor_id=user_id, db=db
                )

    @staticmethod
    def list_inspections(**filters):
        return QualityManagementRepository.list_inspections(**filters)

    @staticmethod
    def get_inspection(inspection_id):
        inspection = QualityManagementRepository.inspection_by_id(inspection_id)
        if not inspection:
            raise NotFoundError("检验记录不存在")
        return dict(inspection)

    @classmethod
    def review_inspection(cls, inspection_id, data, user_id):
        inspection = QualityManagementRepository.inspection_by_id(inspection_id)
        if not inspection:
            raise NotFoundError("检验记录不存在")
        status = cls._text(data.get("status"))
        note = cls._text(data.get("note"))
        if status not in {"approved", "rejected"}:
            raise ValidationError("审核状态无效")
        if status == "rejected" and not note:
            raise ValidationError("驳回检验记录必须填写原因")
        current = dict(inspection)
        if current.get("review_status") != "unreviewed":
            raise ConflictError("检验记录已经完成审核，不能重复审核")
        quality_status = "released" if status == "approved" and current.get("result") == "pass" else "nonconforming"
        with BaseService.transaction() as db:
            QualityManagementRepository.review_inspection(
                inspection_id, status, note, user_id, quality_status, db
            )
            ncr_id = None
            if status == "rejected":
                existing = QualityManagementRepository.ncr_by_inspection(inspection_id, db)
                if existing:
                    ncr_id = existing["id"]
                else:
                    ncr_id = QualityManagementRepository.insert_ncr({
                        "ncr_no": cls._new_code("NCR", "quality_nonconformances", db),
                        "inspection_id": inspection_id,
                        "task_id": current.get("task_id"),
                        "order_id": current.get("order_id"),
                        "process_id": current.get("process_id"),
                        "serial_no": current.get("serial_no", ""),
                        "defect_category": current.get("defect_category", ""),
                        "defect_level": current.get("defect_level") or "general",
                        "defect_quantity": max(int(current.get("defect_quantity") or 1), 1),
                        "description": note,
                        "disposition": "pending",
                        "status": "open",
                        "source_type": "inspection_review",
                    }, user_id, db)
                    QualityManagementRepository.add_ncr_action(
                        ncr_id, "review_reject", current.get("review_status", ""), "open", note, user_id, db
                    )
                QualityManagementRepository.reject_task_for_review(current.get("task_id"), db)
                if current.get("order_id"):
                    QualityManagementRepository.set_inventory_quality(
                        current["order_id"], "quarantined", f"检验记录 {inspection_id} 审核驳回", db
                    )
            elif current.get("result") == "pass" and current.get("inspection_type") == "final" and current.get("order_id"):
                QualityManagementRepository.set_inventory_quality(current["order_id"], "released", "", db)
            return {"inspection_id": inspection_id, "review_status": status, "ncr_id": ncr_id}

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
