"""Pure policies for order completion focus decisions."""


class OrderFocusPolicy:
    LABELS = {
        "tail": "尾数清理",
        "stuck": "滞留卡点",
        "partial": "部分完工",
        "pending": "待集中启动",
    }

    @staticmethod
    def first_backlog_process(process_stats):
        return next((stat for stat in process_stats or [] if stat.get("backlog", 0) > 0), None)

    @staticmethod
    def focus_type(summary, completion_pct, tail_percent):
        if summary.get("completed_workpieces", 0) and completion_pct >= tail_percent:
            return "tail"
        if summary.get("stuck_workpieces", 0):
            return "stuck"
        if summary.get("in_progress_workpieces", 0) or summary.get("completed_workpieces", 0):
            return "partial"
        return "pending"

    @staticmethod
    def focus_label(focus_type):
        return OrderFocusPolicy.LABELS.get(focus_type, "待处理")

    @staticmethod
    def fallback_summary(total, completed, processes):
        process_stats = []
        for process in processes:
            process_completed = min(process["completed"] or 0, total)
            process_stats.append({
                "process_id": process["process_id"],
                "process_name": process["process_name"],
                "seq_order": process["seq_order"],
                "completed": process_completed,
                "current": 0,
                "pending": max(total - process_completed, 0),
                "stuck": 0,
                "backlog": max(total - process_completed, 0),
                "total": total,
                "completion_pct": round(process_completed / max(total, 1) * 100, 1),
            })
        return {
            "total_workpieces": total,
            "completed_workpieces": completed,
            "remaining_workpieces": max(total - completed, 0),
            "in_progress_workpieces": 0,
            "pending_workpieces": max(total - completed, 0),
            "stuck_workpieces": 0,
            "process_stats": process_stats,
            "overall_progress_pct": round(completed / max(total, 1) * 100, 1),
        }

    @staticmethod
    def board_item(progress, order, exception, tail_percent, fallback_processes):
        summary = progress.get("summary", {})
        analysis = progress.get("analysis", {})
        total = summary.get("total_workpieces") or progress.get("quantity") or order.get("quantity") or 0
        completed = summary.get("completed_workpieces", 0)
        if not summary.get("total_workpieces"):
            completed = min(order.get("completed") or 0, total)
            summary = {
                **summary,
                **OrderFocusPolicy.fallback_summary(total, completed, fallback_processes),
            }
        remaining = summary.get("remaining_workpieces", 0)
        if not total or remaining <= 0:
            return None
        completed = summary.get("completed_workpieces", completed)
        completion_pct = round(completed / max(total, 1) * 100, 1)
        bottlenecks = analysis.get("bottlenecks") or []
        bottleneck = bottlenecks[0] if bottlenecks else OrderFocusPolicy.first_backlog_process(
            summary.get("process_stats")
        )
        focus_type = "exception" if exception else OrderFocusPolicy.focus_type(
            summary, completion_pct, tail_percent
        )
        return {
            "order_id": progress.get("order_id"),
            "order_no": progress.get("order_no"),
            "product_name": progress.get("product_name"),
            "product_code": order.get("product_code") or "",
            "customer": order.get("customer_name") or order.get("customer") or "",
            "route_name": progress.get("route_name") or order.get("route_name") or "",
            "quantity": progress.get("quantity"),
            "created_at": order.get("created_at") or "",
            "deadline": progress.get("deadline") or "",
            "completed_workpieces": completed,
            "remaining_workpieces": remaining,
            "in_progress_workpieces": summary.get("in_progress_workpieces", 0),
            "pending_workpieces": summary.get("pending_workpieces", 0),
            "stuck_workpieces": summary.get("stuck_workpieces", 0),
            "completion_pct": completion_pct,
            "overall_progress_pct": summary.get("overall_progress_pct", 0),
            "focus_type": focus_type,
            "focus_label": "例外放行" if exception else OrderFocusPolicy.focus_label(focus_type),
            "is_exception": bool(exception),
            "exception": exception,
            "exception_reason": exception.get("reason") if exception else "",
            "exception_expires_at": exception.get("expires_at") if exception else "",
            "priority_process_id": bottleneck.get("process_id") if bottleneck else None,
            "priority_process_name": bottleneck.get("process_name") if bottleneck else "",
            "priority_backlog": bottleneck.get("backlog", 0) if bottleneck else 0,
            "priority_stuck": bottleneck.get("stuck", 0) if bottleneck else 0,
            "risk_level": (analysis.get("deadline_risk") or {}).get("level", "low"),
            "risk_reason": (analysis.get("deadline_risk") or {}).get("reason", ""),
            "recommendations": analysis.get("recommendations", [])[:3],
        }

    @staticmethod
    def sort_key(item):
        return (
            item["created_at"] or "",
            1 if item["is_exception"] else 0,
            0 if item["focus_type"] == "tail" else 1,
            -item["completion_pct"],
            item["order_id"] or 0,
        )

    @staticmethod
    def summarize(items):
        return {
            "total": len(items),
            "tail": sum(1 for item in items if item["focus_type"] == "tail"),
            "stuck": sum(1 for item in items if item["stuck_workpieces"] > 0),
            "partial": sum(1 for item in items if item["focus_type"] == "partial"),
            "pending": sum(1 for item in items if item["focus_type"] == "pending"),
            "exception": sum(1 for item in items if item["is_exception"]),
        }

    @staticmethod
    def priority_warning(priority, mode, hard_block_enabled, bypass_allowed):
        backlog = int(priority["backlog"] or 0)
        blocking = hard_block_enabled and not bypass_allowed
        message = (
            f"集中完工{'强拦截' if blocking else '提示'}：同路线/同产品存在更早下达订单"
            f"「{priority['order_no']}」的「{priority['process_name']}」还剩 {backlog} 件。"
            + (
                "请先完成前序订单，或联系班组长/管理员设置例外后再报工。"
                if blocking else
                "当前订单允许继续报工，但建议先按班组排程完成前序订单尾数。"
            )
        )
        return {
            "enabled": True,
            "mode": mode,
            "blocking": blocking,
            "bypass_allowed": bypass_allowed,
            "severity": "danger" if blocking else "warning",
            "message": message,
            "recommended_order_id": priority["id"],
            "recommended_order_no": priority["order_no"],
            "recommended_process_id": priority["process_id"],
            "recommended_process_name": priority["process_name"],
            "recommended_backlog": backlog,
        }
