"""Full-process quality evaluation workflow."""

import json

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
    DEFAULT_RULES = {
        "enabled": True,
        "required_previous_process": True,
        "low_score_threshold": 60,
        "dimensions": [
            {"key": "processing_quality", "label": "加工质量"},
            {"key": "dimensional_accuracy", "label": "尺寸或精度"},
            {"key": "appearance_quality", "label": "外观质量"},
            {"key": "process_continuity", "label": "工序可接续性"},
            {"key": "cleanliness_protection", "label": "清洁及防护"},
        ],
        "issue_tags": ["尺寸问题", "外观问题", "漏加工", "毛刺锐边", "标识不清", "清洁防护", "返修风险", "其他"],
    }

    @classmethod
    def rules(cls, db=None):
        raw = SettingRepository.get_value("process_quality_evaluation_rules", "", db=db)
        try:
            value = json.loads(raw) if raw else {}
        except (TypeError, json.JSONDecodeError):
            value = {}
        rules = dict(cls.DEFAULT_RULES)
        rules.update(value if isinstance(value, dict) else {})
        rules["low_score_threshold"] = cls._score_threshold(rules.get("low_score_threshold"))
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
        if isinstance(data.get("issue_tags"), list):
            rules["issue_tags"] = [str(tag).strip() for tag in data["issue_tags"] if str(tag).strip()]
        with BaseService.transaction() as db:
            SettingRepository.upsert_txn(
                "process_quality_evaluation_rules",
                json.dumps(rules, ensure_ascii=False),
                db,
            )
        return rules

    @staticmethod
    def _score_threshold(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 60

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
            }, db)
        return created

    @classmethod
    def pending_tasks(cls, evaluator_user_id=None, status="pending", keyword="", page=1, per_page=100):
        return ProcessQualityEvaluationRepository.list_tasks(
            evaluator_user_id, status, keyword, page, per_page
        )

    @classmethod
    def pending_count(cls, evaluator_user_id):
        return ProcessQualityEvaluationRepository.pending_count(evaluator_user_id)

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
            threshold = rules["low_score_threshold"]
            for entry in entries:
                task_id = entry.get("task_id")
                task = ProcessQualityEvaluationRepository.task_by_id(task_id, db) if task_id else None
                if not task:
                    raise ValueError("评价任务不存在")
                if int(task["evaluator_user_id"]) != int(user_id):
                    raise ValueError("只能提交分配给当前操作员的评价")
                if task["status"] != "pending":
                    raise ValueError("该评价任务已完成")
                dimensions = {
                    key: cls._rating(entry.get(key), label)
                    for key, label in cls.DIMENSIONS
                }
                total_score = round(sum(dimensions.values()) / len(dimensions) * 20, 1)
                issue_tags = entry.get("issue_tags", [])
                if isinstance(issue_tags, str):
                    issue_tags = [issue_tags.strip()] if issue_tags.strip() else []
                if not isinstance(issue_tags, list):
                    raise ValueError("问题标签格式不正确")
                issue_tags = [str(tag).strip() for tag in issue_tags if str(tag).strip()]
                comment = str(entry.get("comment") or "").strip()
                if total_score < threshold and not (issue_tags or comment):
                    raise ValueError("低分评价必须填写问题标签或备注")
                status = "pending_verification" if total_score < threshold else "confirmed"
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
                    **dimensions,
                    "total_score": total_score,
                    "grade": cls._grade(total_score),
                    "issue_tags": issue_tags,
                    "comment": comment,
                    "status": status,
                }, db)
                ProcessQualityEvaluationRepository.complete_task(task["id"], db)
                results.append({"id": evaluation_id, "task_id": task["id"], "status": status, "total_score": total_score})
        return {"ok": True, "items": results}

    @classmethod
    def list_evaluations(cls, **filters):
        return ProcessQualityEvaluationRepository.list_evaluations(**filters)

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
        with BaseService.transaction() as db:
            ProcessQualityEvaluationRepository.review_evaluation(
                evaluation_id, status, reviewer_id, note, db
            )
        return {"ok": True, "status": status}

    @classmethod
    def stats(cls, year_month=""):
        threshold = cls.rules().get("low_score_threshold", 60)
        return ProcessQualityEvaluationRepository.stats(year_month, threshold)

    @classmethod
    def monthly_metrics(cls, year_month, db=None):
        threshold = cls.rules(db).get("low_score_threshold", 60)
        rows = ProcessQualityEvaluationRepository.monthly_metrics(year_month, threshold, db)
        return {row["user_id"]: dict(row) for row in rows if row["user_id"] is not None}

    @classmethod
    def record_legacy_handoff(cls, review_id, data, db):
        rating = cls._rating(data.get("rating"), "评分")
        task = ProcessQualityEvaluationRepository.find_matching_pending_task({
            "order_id": data["order_id"],
            "serial_no": data.get("serial_no", ""),
            "target_process_id": data["from_process_id"],
            "evaluator_process_id": data["to_process_id"],
            "evaluator_user_id": data["evaluator_user_id"],
        }, db)
        issue_tags = [data["issue_type"]] if data.get("issue_type") else []
        total_score = rating * 20.0
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
        }, db)
        if task:
            ProcessQualityEvaluationRepository.complete_task(task["id"], db)
        return evaluation_id
