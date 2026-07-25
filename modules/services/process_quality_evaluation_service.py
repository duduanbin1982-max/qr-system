"""Full-process quality evaluation workflow."""

import json
import re

from modules.domain.errors import ConflictError
from modules.domain.quality_rules import PROCESS_QUALITY_EVALUATION_DEFAULT_RULES
from modules.repositories.process_quality_evaluation_repository import ProcessQualityEvaluationRepository
from modules.repositories.setting_repository import SettingRepository
from modules.services import BaseService


class ProcessQualityEvaluationService:
    DIMENSIONS = (
        ("processing_quality", "加工质量"),
        ("dimensional_accuracy", "尺寸或精度"),
        ("appearance_quality", "外观质量"),
        ("process_continuity", "工序可接续性"),
        ("cleanliness_protection", "清洁及防护"),
    )
    @classmethod
    def rules(cls, db=None):
        raw = SettingRepository.get_value("process_quality_evaluation_rules", "", db=db)
        try:
            value = json.loads(raw) if raw else {}
        except (TypeError, json.JSONDecodeError):
            value = {}
        rules = dict(PROCESS_QUALITY_EVALUATION_DEFAULT_RULES)
        rules.update(value if isinstance(value, dict) else {})
        rules["low_score_threshold"] = cls._score_threshold(rules.get("low_score_threshold"))
        rules["critical_score_threshold"] = cls._score_threshold(rules.get("critical_score_threshold"), 40)
        rules["minimum_samples_for_performance"] = max(
            cls._positive_int(rules.get("minimum_samples_for_performance"), 3), 1
        )
        return rules

    @classmethod
    def save_rules(cls, data):
        rules = cls.rules()
        if "enabled" in data:
            rules["enabled"] = bool(data["enabled"])
        if "required_previous_process" in data:
            rules["required_previous_process"] = bool(data["required_previous_process"])
        if "low_score_threshold" in data:
            threshold = cls._score_threshold(data["low_score_threshold"])
            if threshold < 0 or threshold > 100:
                raise ValueError("低分核验阈值必须是0-100分")
            rules["low_score_threshold"] = threshold
        if "critical_score_threshold" in data:
            critical = cls._score_threshold(data["critical_score_threshold"], 40)
            if critical < 0 or critical > rules["low_score_threshold"]:
                raise ValueError("严重缺陷阈值必须在0到低分阈值之间")
            rules["critical_score_threshold"] = critical
        if "minimum_samples_for_performance" in data:
            rules["minimum_samples_for_performance"] = max(
                cls._positive_int(data["minimum_samples_for_performance"], 3), 1
            )
        for key in ("hide_target_identity", "auto_open_mobile"):
            if key in data:
                rules[key] = bool(data[key])
        if isinstance(data.get("issue_tags"), list):
            rules["issue_tags"] = [str(tag).strip() for tag in data["issue_tags"] if str(tag).strip()]
        if isinstance(data.get("critical_issue_tags"), list):
            rules["critical_issue_tags"] = [
                str(tag).strip() for tag in data["critical_issue_tags"] if str(tag).strip()
            ]
        if rules["critical_score_threshold"] > rules["low_score_threshold"]:
            raise ValueError("严重缺陷阈值不能高于低分核验阈值")
        with BaseService.transaction() as db:
            SettingRepository.upsert_txn(
                "process_quality_evaluation_rules",
                json.dumps(rules, ensure_ascii=False),
                db,
            )
        return rules

    @staticmethod
    def _score_threshold(value, default=60):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _positive_int(value, default=1):
        try:
            result = int(value)
        except (TypeError, ValueError):
            return default
        return result if result > 0 else default

    @staticmethod
    def _rating(value, label):
        try:
            rating = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label}必须是1-5分") from exc
        if rating < 1 or rating > 5:
            raise ValueError(f"{label}必须是1-5分")
        return rating

    @staticmethod
    def _grade(total_score):
        if total_score >= 90:
            return "优秀"
        if total_score >= 80:
            return "良好"
        if total_score >= 60:
            return "合格"
        if total_score >= 40:
            return "待改进"
        return "不合格"

    @classmethod
    def _default_template(cls, rules):
        dimensions = []
        for index, dimension in enumerate(rules.get("dimensions") or []):
            dimensions.append({
                "key": str(dimension.get("key") or f"dimension_{index + 1}"),
                "label": str(dimension.get("label") or f"评价项{index + 1}"),
                "weight": cls._positive_int(dimension.get("weight"), 1),
                "required": dimension.get("required", True) is not False,
            })
        return {
            "id": None,
            "name": "通用评价模板",
            "dimensions": dimensions,
            "issue_tags": list(rules.get("issue_tags") or []),
            "critical_issue_tags": list(rules.get("critical_issue_tags") or []),
            "low_score_threshold": rules["low_score_threshold"],
            "critical_score_threshold": rules["critical_score_threshold"],
        }

    @classmethod
    def _template_snapshot(cls, template, rules):
        if not template:
            return cls._default_template(rules)
        item = dict(template)
        for key in ("dimensions_json", "issue_tags_json", "critical_issue_tags_json"):
            raw = item.pop(key, "")
            output_key = key.replace("_json", "")
            try:
                item[output_key] = json.loads(raw or "[]")
            except (TypeError, json.JSONDecodeError):
                item[output_key] = []
        item["dimensions"] = [
            {
                "key": str(dimension.get("key") or ""),
                "label": str(dimension.get("label") or ""),
                "weight": cls._positive_int(dimension.get("weight"), 1),
                "required": dimension.get("required", True) is not False,
            }
            for dimension in item.get("dimensions", [])
            if isinstance(dimension, dict) and dimension.get("key") and dimension.get("label")
        ]
        if not item["dimensions"]:
            return cls._default_template(rules)
        return item

    @classmethod
    def _normalize_template(cls, data):
        name = str(data.get("name") or "").strip()
        process_id = data.get("process_id")
        if not name or not process_id:
            raise ValueError("评价模板必须填写名称并选择工序")
        dimensions = data.get("dimensions")
        if not isinstance(dimensions, list) or not dimensions:
            raise ValueError("评价模板至少需要一个评分维度")
        normalized = []
        seen = set()
        for index, dimension in enumerate(dimensions):
            if not isinstance(dimension, dict):
                raise ValueError("评分维度格式不正确")
            key = str(dimension.get("key") or "").strip()
            label = str(dimension.get("label") or "").strip()
            if not key:
                key = re.sub(r"[^a-z0-9_]+", "_", label.lower()).strip("_") or f"dimension_{index + 1}"
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,49}", key):
                raise ValueError("评分维度编码必须以小写字母开头，只能包含字母、数字和下划线")
            if not label or key in seen:
                raise ValueError("评分维度名称不能为空且编码不能重复")
            seen.add(key)
            normalized.append({
                "key": key,
                "label": label,
                "weight": cls._positive_int(dimension.get("weight"), 1),
                "required": dimension.get("required", True) is not False,
            })
        low = cls._score_threshold(data.get("low_score_threshold"), 60)
        critical = cls._score_threshold(data.get("critical_score_threshold"), 40)
        if low < 0 or low > 100 or critical < 0 or critical > low:
            raise ValueError("模板评分阈值设置无效")
        return {
            "name": name,
            "route_id": data.get("route_id") or None,
            "process_id": process_id,
            "dimensions": normalized,
            "issue_tags": [str(tag).strip() for tag in data.get("issue_tags", []) if str(tag).strip()],
            "critical_issue_tags": [
                str(tag).strip() for tag in data.get("critical_issue_tags", []) if str(tag).strip()
            ],
            "low_score_threshold": low,
            "critical_score_threshold": critical,
            "status": data.get("status") if data.get("status") in {"active", "inactive"} else "active",
        }

    @staticmethod
    def references():
        return ProcessQualityEvaluationRepository.references()

    @staticmethod
    def list_templates(status=""):
        return ProcessQualityEvaluationRepository.list_templates(status)

    @classmethod
    def save_template(cls, data, current_user, template_id=None):
        normalized = cls._normalize_template(data)
        with BaseService.transaction() as db:
            if template_id and not ProcessQualityEvaluationRepository.template_by_id(template_id, db):
                raise ValueError("评价模板不存在")
            if normalized["route_id"] and not ProcessQualityEvaluationRepository.route_contains_process(
                normalized["route_id"], normalized["process_id"], db
            ):
                raise ValueError("所选工序不属于该工序路线")
            saved_id = ProcessQualityEvaluationRepository.save_template(
                normalized, current_user.get("id"), template_id, db
            )
        return {"ok": True, "id": saved_id}

    @classmethod
    def generate_tasks(cls, command, trigger_work_record_id, db):
        if not trigger_work_record_id:
            return 0
        rules = cls.rules(db)
        if not rules.get("enabled", True):
            return 0
        upstream = ProcessQualityEvaluationRepository.upstream_processes(
            command.order_id, command.process_id, db
        )
        if not upstream:
            return 0

        created = 0
        is_serial = bool(command.serial_no)
        nearest_seq = upstream[0]["seq_order"]
        for process in upstream:
            template_row = ProcessQualityEvaluationRepository.matching_template(
                process["route_id"], process["process_id"], db
            )
            template_snapshot = cls._template_snapshot(template_row, rules)
            target_user_id = None
            target_work_record_id = None
            quantity = command.effective_quantity
            attribution_type = "process"
            if is_serial:
                work = ProcessQualityEvaluationRepository.serial_target_work(
                    command.order_id, process["process_id"], command.serial_no, db
                )
                if not work:
                    continue
                target_user_id = work["user_id"]
                target_work_record_id = work["id"]
                quantity = work["quantity"] or 1
                attribution_type = "worker"
            else:
                contributors = ProcessQualityEvaluationRepository.order_target_contributors(
                    command.order_id, process["process_id"], db
                )
                if not contributors:
                    continue
                quantity = sum(row["quantity"] or 0 for row in contributors) or command.effective_quantity
                if len(contributors) == 1:
                    target_user_id = contributors[0]["user_id"]
                    target_work_record_id = contributors[0]["latest_work_record_id"]
                    attribution_type = "worker"

            if target_user_id and int(target_user_id) == int(command.user_id):
                continue
            created += ProcessQualityEvaluationRepository.insert_task({
                "trigger_work_record_id": trigger_work_record_id,
                "order_id": command.order_id,
                "serial_no": command.serial_no or "",
                "target_process_id": process["process_id"],
                "evaluator_process_id": command.process_id,
                "target_work_record_id": target_work_record_id,
                "target_user_id": target_user_id,
                "evaluator_user_id": command.user_id,
                "quantity": quantity,
                "is_required": bool(
                    rules.get("required_previous_process", True)
                    and process["seq_order"] == nearest_seq
                ),
                "attribution_type": attribution_type,
                "template_id": template_snapshot.get("id"),
                "template_snapshot": template_snapshot,
            }, db)
        return created

    @classmethod
    def pending_tasks(
        cls, evaluator_user_id=None, status="pending", keyword="", page=1, per_page=100,
        include_target_identity=False,
    ):
        result = ProcessQualityEvaluationRepository.list_tasks(
            evaluator_user_id, status, keyword, page, per_page
        )
        if cls.rules().get("hide_target_identity", True) and not include_target_identity:
            for item in result["items"]:
                item.pop("target_user_name", None)
                item.pop("target_employee_no", None)
                item.pop("target_user_id", None)
        return result

    @classmethod
    def pending_count(cls, evaluator_user_id):
        return ProcessQualityEvaluationRepository.pending_count(evaluator_user_id)

    @classmethod
    def pending_required_count(cls, evaluator_user_id):
        result = ProcessQualityEvaluationRepository.list_tasks(
            evaluator_user_id=evaluator_user_id, status="pending", page=1, per_page=500
        )
        return sum(1 for item in result["items"] if item.get("is_required"))

    @staticmethod
    def assert_required_tasks_completed(evaluator_user_id, db=None):
        task = ProcessQualityEvaluationRepository.pending_required_task(
            evaluator_user_id, db
        )
        if task:
            raise ConflictError(
                f"您有未完成的必评任务：订单 {task['order_no']} 的"
                f"{task['target_process_name']}工序，请先完成评价后再继续报工"
            )

    @classmethod
    def skip_task(cls, task_id, data, current_user):
        task = ProcessQualityEvaluationRepository.task_by_id(task_id)
        if not task:
            raise ValueError("评价任务不存在")
        if int(task["evaluator_user_id"]) != int(current_user.get("id") or 0):
            raise ValueError("只能处理分配给当前操作员的评价任务")
        if task["is_required"]:
            raise ValueError("直接上一道工序为必评，不能跳过")
        reason = str(data.get("reason") or "历史工序选评跳过").strip()
        with BaseService.transaction() as db:
            if not ProcessQualityEvaluationRepository.skip_task(task_id, reason, db):
                raise ValueError("该评价任务已处理")
        return {"ok": True, "status": "skipped"}

    @classmethod
    def _evaluate_dimensions(cls, entry, template_snapshot):
        configured = template_snapshot.get("dimensions") or cls._default_template(cls.rules())["dimensions"]
        supplied = entry.get("dimension_scores")
        if not isinstance(supplied, dict):
            supplied = {key: entry.get(key) for key, _ in cls.DIMENSIONS if entry.get(key) is not None}
        scores = {}
        weighted_total = 0
        weight_total = 0
        for dimension in configured:
            key = dimension["key"]
            if key not in supplied and dimension.get("required", True):
                raise ValueError(f"{dimension['label']}必须评分")
            if key not in supplied:
                continue
            rating = cls._rating(supplied.get(key), dimension["label"])
            weight = cls._positive_int(dimension.get("weight"), 1)
            scores[key] = rating
            weighted_total += rating * weight
            weight_total += weight
        if not scores or weight_total <= 0:
            raise ValueError("至少填写一个评分维度")
        total_score = round(weighted_total / (5 * weight_total) * 100, 1)
        fallback_rating = max(1, min(5, round(total_score / 20)))
        legacy = {
            key: scores.get(key, fallback_rating)
            for key, _ in cls.DIMENSIONS
        }
        return scores, legacy, total_score

    @classmethod
    def submit(cls, data, current_user):
        user_id = current_user.get("id") if current_user else None
        if not user_id:
            raise ValueError("未登录")
        entries = data.get("evaluations") if isinstance(data, dict) else None
        if entries is None:
            entries = [data]
        if not isinstance(entries, list) or not entries:
            raise ValueError("至少提交一条评价")

        results = []
        with BaseService.transaction() as db:
            rules = cls.rules(db)
            for entry in entries:
                task_id = entry.get("task_id")
                task = ProcessQualityEvaluationRepository.task_by_id(task_id, db) if task_id else None
                if not task:
                    raise ValueError("评价任务不存在")
                if int(task["evaluator_user_id"]) != int(user_id):
                    raise ValueError("只能提交分配给当前操作员的评价")
                if task["status"] != "pending":
                    raise ValueError("该评价任务已完成")
                template_snapshot = task.get("template_snapshot") or cls._default_template(rules)
                dimension_scores, legacy_dimensions, total_score = cls._evaluate_dimensions(
                    entry, template_snapshot
                )
                issue_tags = entry.get("issue_tags", [])
                if isinstance(issue_tags, str):
                    issue_tags = [issue_tags.strip()] if issue_tags.strip() else []
                if not isinstance(issue_tags, list):
                    raise ValueError("问题标签格式不正确")
                issue_tags = [str(tag).strip() for tag in issue_tags if str(tag).strip()]
                comment = str(entry.get("comment") or "").strip()
                threshold = cls._score_threshold(
                    template_snapshot.get("low_score_threshold"), rules["low_score_threshold"]
                )
                critical_threshold = cls._score_threshold(
                    template_snapshot.get("critical_score_threshold"), rules["critical_score_threshold"]
                )
                critical_tags = set(template_snapshot.get("critical_issue_tags") or rules.get("critical_issue_tags") or [])
                if total_score < threshold and not (issue_tags or comment):
                    raise ValueError("低分评价必须填写问题标签或备注")
                severity = "critical" if total_score < critical_threshold or critical_tags.intersection(issue_tags) else (
                    "warning" if total_score < threshold else "normal"
                )
                status = "pending_verification" if severity in {"warning", "critical"} else "confirmed"
                evaluation_id = ProcessQualityEvaluationRepository.insert_evaluation({
                    "task_id": task["id"],
                    "order_id": task["order_id"],
                    "serial_no": task["serial_no"],
                    "target_process_id": task["target_process_id"],
                    "evaluator_process_id": task["evaluator_process_id"],
                    "target_work_record_id": task["target_work_record_id"],
                    "trigger_work_record_id": task["trigger_work_record_id"],
                    "target_user_id": task["target_user_id"],
                    "evaluator_user_id": user_id,
                    "quantity": task["quantity"],
                    "attribution_type": task["attribution_type"],
                    **legacy_dimensions,
                    "total_score": total_score,
                    "grade": cls._grade(total_score),
                    "issue_tags": issue_tags,
                    "comment": comment,
                    "status": status,
                    "template_id": task.get("template_id"),
                    "dimension_scores": dimension_scores,
                    "template_snapshot": template_snapshot,
                    "severity": severity,
                }, db)
                ProcessQualityEvaluationRepository.complete_task(task["id"], db)
                if status == "pending_verification":
                    from modules.services.quality_management_service import QualityManagementService
                    QualityManagementService.generate_for_low_evaluation({
                        "id": evaluation_id,
                        "order_id": task["order_id"],
                        "serial_no": task["serial_no"],
                        "target_process_id": task["target_process_id"],
                        "target_work_record_id": task["target_work_record_id"],
                        "quantity": task["quantity"],
                        "severity": severity,
                    }, user_id, db)
                results.append({
                    "id": evaluation_id, "task_id": task["id"], "status": status,
                    "total_score": total_score, "severity": severity,
                })
        return {"ok": True, "items": results}

    @classmethod
    def list_evaluations(cls, **filters):
        return ProcessQualityEvaluationRepository.list_evaluations(**filters)

    @classmethod
    def my_evaluations(cls, current_user, year_month="", page=1, per_page=100):
        return ProcessQualityEvaluationRepository.list_evaluations(
            year_month=year_month,
            user_id=current_user.get("id"),
            page=page,
            per_page=per_page,
        )

    @classmethod
    def review(cls, evaluation_id, data, current_user):
        reviewer_id = current_user.get("id") if current_user else None
        status = str(data.get("status") or "").strip()
        if status not in {"confirmed", "rejected"}:
            raise ValueError("核验状态只能是 confirmed 或 rejected")
        evaluation = ProcessQualityEvaluationRepository.evaluation_by_id(evaluation_id)
        if not evaluation:
            raise ValueError("评价记录不存在")
        if evaluation["status"] != "pending_verification":
            raise ValueError("当前评价不在待核验状态")
        note = str(data.get("note") or "").strip()
        if status == "rejected" and not note:
            raise ValueError("驳回评价必须填写核验说明")
        with BaseService.transaction() as db:
            ProcessQualityEvaluationRepository.review_evaluation(
                evaluation_id, status, reviewer_id, note, db
            )
            if status == "rejected":
                cls._cancel_rejected_evaluation_tasks(
                    evaluation_id, evaluation["order_id"], reviewer_id, note, db
                )
        return {"ok": True, "status": status}

    @staticmethod
    def _cancel_rejected_evaluation_tasks(evaluation_id, order_id, reviewer_id, note, db):
        from modules.services.order_completion_service import OrderCompletionService
        from modules.services.quality_management_service import QualityManagementService

        QualityManagementService.cancel_tasks_for_evaluation(
            evaluation_id, f"关联评价已被驳回：{note}", db
        )
        OrderCompletionService.reconcile(
            order_id,
            trigger="quality_evaluation_rejected",
            actor_id=reviewer_id,
            db=db,
        )

    @classmethod
    def create_appeal(cls, evaluation_id, data, current_user):
        evaluation = ProcessQualityEvaluationRepository.evaluation_by_id(evaluation_id)
        if not evaluation:
            raise ValueError("评价记录不存在")
        user_id = current_user.get("id") if current_user else None
        if not evaluation["target_user_id"] or int(evaluation["target_user_id"]) != int(user_id or 0):
            raise ValueError("只能对归属于本人的评价提出申诉")
        if evaluation["status"] != "confirmed":
            raise ValueError("只有已确认评价可以申诉")
        reason = str(data.get("reason") or "").strip()
        if len(reason) < 5:
            raise ValueError("申诉原因至少填写5个字符")
        try:
            with BaseService.transaction() as db:
                appeal_id = ProcessQualityEvaluationRepository.create_appeal(
                    evaluation_id, user_id, reason, db
                )
        except Exception as exc:
            if "UNIQUE constraint" in str(exc):
                raise ValueError("该评价已有待处理申诉") from exc
            raise
        return {"ok": True, "id": appeal_id, "status": "pending"}

    @staticmethod
    def list_appeals(status="", current_user=None, mine=False, year_month=""):
        requester_id = current_user.get("id") if mine and current_user else None
        return {
            "items": ProcessQualityEvaluationRepository.list_appeals(
                status, requester_id, year_month
            )
        }

    @classmethod
    def review_appeal(cls, appeal_id, data, current_user):
        status = str(data.get("status") or "").strip()
        if status not in {"accepted", "rejected"}:
            raise ValueError("申诉处理结果无效")
        note = str(data.get("note") or "").strip()
        if not note:
            raise ValueError("申诉复核必须填写处理说明")
        appeal = ProcessQualityEvaluationRepository.appeal_by_id(appeal_id)
        if not appeal:
            raise ValueError("申诉记录不存在")
        if appeal["status"] != "pending":
            raise ValueError("该申诉已经处理")
        reviewer_id = current_user.get("id") if current_user else None
        with BaseService.transaction() as db:
            ProcessQualityEvaluationRepository.review_appeal(
                appeal_id, status, reviewer_id, note, db
            )
            if status == "accepted":
                ProcessQualityEvaluationRepository.review_evaluation(
                    appeal["evaluation_id"], "rejected", reviewer_id, f"申诉成立：{note}", db
                )
                cls._cancel_rejected_evaluation_tasks(
                    appeal["evaluation_id"], appeal["order_id"], reviewer_id, f"申诉成立：{note}", db
                )
        return {"ok": True, "status": status}

    @classmethod
    def stats(cls, year_month=""):
        return ProcessQualityEvaluationRepository.stats(year_month)

    @classmethod
    def monthly_metrics(cls, year_month, db=None):
        rules = cls.rules(db)
        minimum_samples = rules.get("minimum_samples_for_performance", 3)
        rows = ProcessQualityEvaluationRepository.monthly_metrics(
            year_month, minimum_samples, db
        )
        return {row["user_id"]: dict(row) for row in rows if row["user_id"] is not None}

    @classmethod
    def record_legacy_handoff(cls, review_id, data, db):
        rating = cls._rating(data.get("rating"), "评分")
        rules = cls.rules(db)
        task = ProcessQualityEvaluationRepository.find_matching_pending_task({
            "order_id": data["order_id"],
            "serial_no": data.get("serial_no", ""),
            "target_process_id": data["from_process_id"],
            "evaluator_process_id": data["to_process_id"],
            "evaluator_user_id": data["evaluator_user_id"],
        }, db)
        issue_tags = [data["issue_type"]] if data.get("issue_type") else []
        total_score = rating * 20.0
        template_snapshot = cls._default_template(rules)
        dimension_scores = {key: rating for key, _ in cls.DIMENSIONS}
        evaluation_id = ProcessQualityEvaluationRepository.insert_evaluation({
            "task_id": task["id"] if task else None,
            "order_id": data["order_id"],
            "serial_no": data.get("serial_no", ""),
            "target_process_id": data["from_process_id"],
            "evaluator_process_id": data["to_process_id"],
            "target_work_record_id": data.get("source_work_record_id"),
            "trigger_work_record_id": None,
            "target_user_id": data["from_user_id"],
            "evaluator_user_id": data["evaluator_user_id"],
            "quantity": data.get("quantity", 1),
            "attribution_type": "worker",
            "processing_quality": rating,
            "dimensional_accuracy": rating,
            "appearance_quality": rating,
            "process_continuity": rating,
            "cleanliness_protection": rating,
            "total_score": total_score,
            "grade": cls._grade(total_score),
            "issue_tags": issue_tags,
            "comment": data.get("comment", ""),
            "status": "pending_verification" if data.get("status") == "pending" else "confirmed",
            "source_type": "legacy_handoff",
            "source_handoff_review_id": review_id,
            "dimension_scores": dimension_scores,
            "template_snapshot": template_snapshot,
            "severity": "warning" if total_score < rules["low_score_threshold"] else "normal",
        }, db)
        if task:
            ProcessQualityEvaluationRepository.complete_task(task["id"], db)
        return evaluation_id
