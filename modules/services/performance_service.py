"""Performance evaluation and improvement workflow service."""
from datetime import datetime

from modules.services import BaseService
from modules.repositories.performance_repository import PerformanceRepository
from modules.repositories.work_time_repository import WorkTimeRepository
from modules.services.process_quality_evaluation_service import ProcessQualityEvaluationService
from modules.services.performance_scoring_policy import PerformanceScoringPolicy


class PerformanceService:
    @staticmethod
    def current_month():
        return datetime.now().strftime("%Y-%m")

    scoring_policy = PerformanceScoringPolicy

    @staticmethod
    def _score_worker(metrics, max_output, review=None, handoff=None):
        return PerformanceService.scoring_policy.score_legacy_worker(
            metrics, max_output, review, handoff
        )

    @staticmethod
    def rules():
        return PerformanceService.scoring_policy.rules()

    @staticmethod
    def worker_month_metrics(user_id, year_month, db=None):
        return {
            **PerformanceRepository.worker_month_metrics(user_id, year_month, db),
            **WorkTimeRepository.approved_user_month_metrics(user_id, year_month, db),
        }

    @staticmethod
    def work_record_count(year_month, db=None):
        return (
            PerformanceRepository.work_record_count(year_month, db)
            + WorkTimeRepository.approved_month_record_count(year_month, db)
        )

    @staticmethod
    def resolve_display_month(requested_month, latest_score_month, requested_score_count):
        if requested_score_count:
            return requested_month
        return latest_score_month or requested_month

    @staticmethod
    def overview(year_month=None):
        current_month = PerformanceService.current_month()
        requested_month = year_month or current_month
        latest_score_month = PerformanceRepository.latest_score_month()
        current_summary = PerformanceRepository.summary(current_month)
        requested_summary = current_summary if requested_month == current_month else PerformanceRepository.summary(requested_month)
        current_score_count = current_summary.get("total") or 0
        requested_score_count = requested_summary.get("total") or 0
        display_month = PerformanceService.resolve_display_month(
            requested_month,
            latest_score_month,
            requested_score_count,
        )
        return {
            "current_month": current_month,
            "requested_month": requested_month,
            "display_month": display_month,
            "latest_score_month": latest_score_month,
            "current_month_score_count": current_score_count,
            "current_month_work_record_count": PerformanceService.work_record_count(current_month),
            "requested_month_score_count": requested_score_count,
            "requested_month_work_record_count": PerformanceService.work_record_count(requested_month),
            "months": PerformanceRepository.list_score_months(),
        }

    @staticmethod
    def _position_group_key(worker):
        return worker.get("position_id") or 0

    @staticmethod
    def _position_group_name(worker):
        return worker.get("position_name") or "未设置岗位"

    @staticmethod
    def generate_month(year_month=None):
        year_month = year_month or PerformanceService.current_month()
        workers = [dict(row) for row in PerformanceRepository.eligible_workers()]
        metrics_by_user = {}
        max_output_by_position = {}
        for worker in workers:
            metrics = PerformanceService.worker_month_metrics(worker["id"], year_month)
            metrics_by_user[worker["id"]] = metrics
            position_key = PerformanceService._position_group_key(worker)
            max_output_by_position[position_key] = max(
                max_output_by_position.get(position_key, 0),
                metrics["output_qty"],
            )
        handoff_metrics = ProcessQualityEvaluationService.monthly_metrics(year_month)
        with BaseService.transaction() as db:
            for worker in workers:
                metrics = metrics_by_user[worker["id"]]
                review = PerformanceRepository.get_review(worker["id"], year_month, db) or {}
                handoff = handoff_metrics.get(worker["id"], {})
                position_key = PerformanceService._position_group_key(worker)
                position_max_output = max_output_by_position.get(position_key, 0)
                score = PerformanceService._score_worker(metrics, position_max_output, review, handoff)
                score_details = score.get("score_details", {})
                score_details.update({
                    "scoring_scope": "position",
                    "position_id": worker.get("position_id"),
                    "position_name": PerformanceService._position_group_name(worker),
                    "position_max_output": position_max_output,
                })
                score["score_details"] = score_details
                PerformanceRepository.upsert_score({
                    "user_id": worker["id"],
                    "year_month": year_month,
                    "role_type": worker.get("role") or "worker",
                    **metrics,
                    **score,
                    "status": "generated",
                }, db)
            PerformanceRepository.update_ranks(year_month, db)
        return {"ok": True, "year_month": year_month, "generated": len(workers)}

    @staticmethod
    def list_scores(year_month=None, warning_level="", search="", position_id="", page=1, per_page=50):
        year_month = year_month or PerformanceService.current_month()
        result = PerformanceRepository.list_scores(year_month, warning_level, search, position_id, page, per_page)
        result["summary"] = PerformanceRepository.summary(year_month, position_id)
        result["all_summary"] = PerformanceRepository.summary(year_month)
        result["position_options"] = PerformanceRepository.score_positions(year_month)
        result["position_id"] = position_id
        result["year_month"] = year_month
        return result

    @staticmethod
    def save_review(data, current_user_id=None):
        required = ["user_id", "year_month"]
        for field in required:
            if not data.get(field):
                raise ValueError(f"缺少必填字段: {field}")
        payload = {
            "user_id": int(data["user_id"]),
            "year_month": str(data["year_month"]),
            "discipline_deduction": PerformanceService.scoring_policy.clamp(
                PerformanceService.scoring_policy.as_float(data.get("discipline_deduction")), 0.0, 10.0
            ),
            "discipline_reason": str(data.get("discipline_reason") or "").strip(),
            "improvement_adjustment": PerformanceService.scoring_policy.clamp(
                PerformanceService.scoring_policy.as_float(data.get("improvement_adjustment")), -5.0, 5.0
            ),
            "improvement_reason": str(data.get("improvement_reason") or "").strip(),
            "manual_score": PerformanceService.scoring_policy.clamp(
                PerformanceService.scoring_policy.as_float(data.get("manual_score"), 10.0), 0.0, 10.0
            ),
            "manual_comment": str(data.get("manual_comment") or "").strip(),
            "reviewed_by": current_user_id,
        }
        with BaseService.transaction() as db:
            PerformanceRepository.upsert_review(payload, db)
        PerformanceService.generate_month(payload["year_month"])
        return {"ok": True, "year_month": payload["year_month"]}

    @staticmethod
    def create_plan(data, current_user_id=None):
        required = ["user_id", "year_month", "reason", "goal"]
        for field in required:
            if not data.get(field):
                raise ValueError(f"缺少必填字段: {field}")
        payload = dict(data)
        payload["created_by"] = current_user_id
        with BaseService.transaction() as db:
            plan_id = PerformanceRepository.create_plan(payload, db)
        return plan_id

    @staticmethod
    def list_plans(year_month="", status="", user_id=None):
        return PerformanceRepository.list_plans(year_month, status, user_id)

    @staticmethod
    def update_plan(plan_id, data):
        with BaseService.transaction() as db:
            PerformanceRepository.update_plan(plan_id, data, db)
        return {"ok": True}
