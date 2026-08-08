"""Performance formal-result query facade and legacy support helpers."""
from datetime import datetime
import json

from flask import current_app, has_app_context

from modules import config
from modules.domain.performance_policy import validate_production_month
from modules.domain.reporting_day import reporting_month_bounds
from modules.repositories.performance_authorization_repository import (
    PerformanceAuthorizationRepository,
)
from modules.repositories.performance_repository import PerformanceRepository
from modules.repositories.work_time_repository import WorkTimeRepository
from modules.services.performance_authorization_service import (
    PerformanceAuthorizationService,
)
from modules.services.performance_scoring_policy import PerformanceScoringPolicy


class PerformanceService:
    SCORE_FIELDS = (
        "output_score",
        "quality_score",
        "delivery_score",
        "discipline_score",
        "improvement_score",
        "total_score",
        "rank_no",
        "rank_total",
        "warning_level",
    )

    @staticmethod
    def current_month():
        return datetime.now().strftime("%Y-%m")

    scoring_policy = PerformanceScoringPolicy

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
    def _v2_query_enabled():
        if not has_app_context():
            return config.PERFORMANCE_LEDGER_V2_QUERY_ENABLED
        return bool(
            current_app.config.get(
                "PERFORMANCE_LEDGER_V2_QUERY_ENABLED",
                config.PERFORMANCE_LEDGER_V2_QUERY_ENABLED,
            )
        )

    @staticmethod
    def overview(year_month=None, actor=None):
        current_month = PerformanceService.current_month()
        requested_month = year_month or current_month
        validate_production_month(requested_month)
        months = PerformanceRepository.formal_result_months(
            PerformanceService._v2_query_enabled()
        )
        latest_score_month = months[0]["year_month"] if months else ""
        current_summary = PerformanceService.list_scores(
            current_month, page=1, per_page=1, actor=actor
        )["all_summary"]
        requested_summary = (
            current_summary
            if requested_month == current_month
            else PerformanceService.list_scores(
                requested_month, page=1, per_page=1, actor=actor
            )["all_summary"]
        )
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
            "months": months,
        }

    @staticmethod
    def _normalize_score(item, year_month):
        item = dict(item)
        try:
            details = json.loads(item.get("score_details_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            details = {}
        if not isinstance(details, dict):
            details = {}
        item.update(
            {
                "user_name": item.get("employee_name_snapshot") or "",
                "employee_no": item.get("employee_no_snapshot") or "",
                "role": item.get("role_type_snapshot") or "worker",
                "department_id": item.get("department_id_snapshot"),
                "department_name": item.get("department_name_snapshot") or "",
                "position_id": item.get("position_id_snapshot"),
                "position_name": item.get("position_name_snapshot") or "未设置岗位",
                "score_details": details,
                "year_month": year_month,
                "eligible": item.get("eligibility_status") == "eligible",
            }
        )
        if not item["eligible"]:
            for field in PerformanceService.SCORE_FIELDS:
                item[field] = None
            item["warning_reason"] = ""
        return item

    @staticmethod
    def _empty_result(year_month, position_id, page, per_page):
        period_start, period_end = reporting_month_bounds(year_month)
        empty_summary = {
            "total": 0,
            "eligible_count": 0,
            "insufficient_data_count": 0,
            "avg_score": None,
            "green": 0,
            "yellow": 0,
            "orange": 0,
            "red": 0,
        }
        return {
            "items": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "summary": dict(empty_summary),
            "all_summary": dict(empty_summary),
            "position_options": [],
            "position_id": position_id,
            "year_month": year_month,
            "result_source": "legacy_v1",
            "batch_id": None,
            "version": None,
            "batch_status": "unavailable",
            "period_start": period_start,
            "period_end": period_end,
            "source_cutoff_at": "",
        }

    @staticmethod
    def list_scores(
        year_month=None,
        warning_level="",
        search="",
        position_id="",
        page=1,
        per_page=50,
        user_id=None,
        department_id=None,
        actor=None,
        db=None,
    ):
        year_month = validate_production_month(
            year_month or PerformanceService.current_month()
        )
        try:
            page = max(int(page or 1), 1)
            per_page = min(max(int(per_page or 50), 1), 200)
            user_id = int(user_id) if user_id not in (None, "") else None
            department_id = (
                int(department_id) if department_id not in (None, "") else None
            )
            if position_id not in (None, "", "__unassigned__"):
                position_id = int(position_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("绩效查询筛选参数无效") from exc
        if warning_level not in ("", "green", "yellow", "orange", "red"):
            raise ValueError("绩效预警等级无效")
        batch = PerformanceRepository.formal_result_batch(
            year_month, PerformanceService._v2_query_enabled(), db=db
        )
        scope = PerformanceAuthorizationService.require_visible_filters(
            actor,
            batch["id"] if batch else None,
            user_id=user_id,
            department_id=department_id,
            db=db,
        )
        if not batch:
            return PerformanceService._empty_result(
                year_month, position_id, page, per_page
            )
        rows = PerformanceAuthorizationRepository.list_score_revisions(
            scope,
            batch_id=batch["id"],
            user_id=user_id,
            department_id=department_id,
            warning_level=warning_level,
            search=str(search or "").strip(),
            position_id=position_id,
            page=page,
            limit=per_page,
            db=db,
        )
        summary = PerformanceAuthorizationRepository.score_summary(
            scope, batch["id"], position_id=position_id, db=db
        )
        all_summary = PerformanceAuthorizationRepository.score_summary(
            scope, batch["id"], db=db
        )
        return {
            "items": [
                PerformanceService._normalize_score(item, year_month)
                for item in rows["items"]
            ],
            "total": rows["total"],
            "page": rows["page"],
            "per_page": rows["limit"],
            "summary": summary,
            "all_summary": all_summary,
            "position_options": PerformanceAuthorizationRepository.score_positions(
                scope, batch["id"], db=db
            ),
            "position_id": position_id,
            "year_month": year_month,
            "result_source": (
                "legacy_v1" if batch.get("legacy_imported") else "ledger_v2"
            ),
            "batch_id": batch["id"],
            "version": batch["version"],
            "batch_status": batch["status"],
            "period_start": batch["period_start"],
            "period_end": batch["period_end"],
            "source_cutoff_at": batch.get("source_cutoff_at") or "",
        }
