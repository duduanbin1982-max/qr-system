"""Process handoff quality review workflow."""
from modules.services import BaseService
from modules.repositories.handoff_review_repository import HandoffReviewRepository


class HandoffReviewService:
    LOW_RATING_PENDING_THRESHOLD = 2

    @staticmethod
    def _rating(value):
        try:
            rating = int(value)
        except (TypeError, ValueError):
            raise ValueError("评分必须是1-5分")
        if rating < 1 or rating > 5:
            raise ValueError("评分必须是1-5分")
        return rating

    @staticmethod
    def pending_context(order_id, to_process_id, evaluator_user_id, serial_no=""):
        prev = HandoffReviewRepository.previous_process(order_id, to_process_id)
        if not prev:
            return {"required": False, "reason": "首道工序无需交接评价"}
        from_process_id = prev["process_id"]
        work = HandoffReviewRepository.latest_previous_work(order_id, from_process_id, serial_no)
        if not work:
            reason = "未找到上一工序已审批报工记录"
            if not serial_no:
                reason = "订单模式上一工序存在多名操作员或无明确来源，暂不计入交接绩效"
            return {"required": False, "reason": reason}
        if int(work["user_id"]) == int(evaluator_user_id):
            return {"required": False, "reason": "上一工序与当前操作人为同一人"}
        existing = HandoffReviewRepository.existing_review(
            order_id, from_process_id, to_process_id, evaluator_user_id, serial_no
        )
        if existing:
            return {"required": False, "already_reviewed": True, "review_id": existing["id"]}
        return {
            "required": True,
            "order_id": order_id,
            "serial_no": serial_no or "",
            "from_process_id": from_process_id,
            "from_process_name": prev["process_name"],
            "to_process_id": to_process_id,
            "to_process_name": HandoffReviewRepository.process_name(to_process_id),
            "from_user_id": work["user_id"],
            "from_user_name": work["worker_name"],
            "from_employee_no": work["employee_no"],
            "source_work_record_id": work["id"],
            "quantity": work["quantity"] or 1,
        }

    @staticmethod
    def create_review(data, current_user):
        user_id = current_user.get("id") if current_user else None
        if not user_id:
            raise ValueError("未登录")
        order_id = data.get("order_id")
        to_process_id = data.get("to_process_id") or data.get("process_id")
        if not order_id or not to_process_id:
            raise ValueError("缺少订单或当前工序信息")
        serial_no = (data.get("serial_no") or "").strip()
        rating = HandoffReviewService._rating(data.get("rating"))
        issue_type = (data.get("issue_type") or "").strip()
        comment = (data.get("comment") or "").strip()
        if rating <= HandoffReviewService.LOW_RATING_PENDING_THRESHOLD and not (issue_type or comment):
            raise ValueError("低分评价必须填写问题类型或备注")

        context = HandoffReviewService.pending_context(int(order_id), int(to_process_id), int(user_id), serial_no)
        if not context.get("required"):
            raise ValueError(context.get("reason") or "无需重复评价")
        status = "pending" if rating <= HandoffReviewService.LOW_RATING_PENDING_THRESHOLD else "confirmed"
        payload = {
            **context,
            "evaluator_user_id": user_id,
            "rating": rating,
            "issue_type": issue_type,
            "comment": comment,
            "status": status,
        }
        with BaseService.transaction() as db:
            review_id = HandoffReviewRepository.insert_review(payload, db)
        return {"ok": True, "id": review_id, "status": status}

    @staticmethod
    def list_reviews(year_month="", status="", user_id=None, page=1, per_page=100):
        return HandoffReviewRepository.list_reviews(year_month, status, user_id, page, per_page)

    @staticmethod
    def monthly_metrics(year_month):
        rows = HandoffReviewRepository.monthly_metrics(year_month)
        return {row["user_id"]: dict(row) for row in rows}

    @staticmethod
    def update_status(review_id, data, current_user):
        status = data.get("status", "confirmed")
        if status not in {"confirmed", "rejected"}:
            raise ValueError("状态只能是 confirmed 或 rejected")
        payload = dict(data)
        payload["status"] = status
        payload["confirmed_by"] = current_user.get("id") if current_user else None
        with BaseService.transaction() as db:
            HandoffReviewRepository.update_status(review_id, payload, db)
        return {"ok": True}
