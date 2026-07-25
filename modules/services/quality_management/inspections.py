"""QualityInspectionService quality subdomain."""

import json
import math
from datetime import datetime, timedelta

from modules.domain.errors import ConflictError, NotFoundError, ValidationError
from modules.domain.quality_rules import QUALITY_MANAGEMENT_DEFAULT_RULES
from modules.repositories.quality_management import QualityManagementRepository
from modules.repositories.setting_repository import SettingRepository
from modules.services import BaseService
from modules.services.quality_management.tasks import QualityTaskService


class QualityInspectionService(QualityTaskService):
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
