"""QualityTaskService quality subdomain."""

import json
import math
from datetime import datetime, timedelta

from modules.domain.errors import ConflictError, NotFoundError, ValidationError
from modules.domain.quality_rules import QUALITY_MANAGEMENT_DEFAULT_RULES
from modules.repositories.quality_management import QualityManagementRepository
from modules.repositories.setting_repository import SettingRepository
from modules.services import BaseService
from modules.services.quality_management.base import QualityManagementBase


class QualityTaskService(QualityManagementBase):
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

    @classmethod
    def start_task(cls, task_id, user_id):
        task = cls.get_task(task_id)
        if task["status"] != "pending":
            raise ConflictError("只有待检任务可以开始")
        with BaseService.transaction() as db:
            QualityManagementRepository.start_task(task_id, user_id, db)
