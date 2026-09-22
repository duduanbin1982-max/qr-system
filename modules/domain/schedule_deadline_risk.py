"""Pure deadline-risk policy for precision production schedules."""

from datetime import datetime, timedelta


def parse_schedule_datetime(value, *, end_of_day=False):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if len(text) == 10:
            parsed = datetime.strptime(text, "%Y-%m-%d")
            if end_of_day:
                return parsed + timedelta(days=1) - timedelta(seconds=1)
            return parsed
        return datetime.fromisoformat(text.replace("T", " "))
    except (TypeError, ValueError):
        return None


def format_schedule_datetime(value):
    if value is None:
        return ""
    if value.second or value.microsecond:
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return value.strftime("%Y-%m-%d %H:%M")


class ScheduleDeadlineRiskPolicy:
    """Evaluate projected delivery risk using the precision schedule facts."""

    @staticmethod
    def evaluate(
        *,
        deadline_text="",
        projected_completion_at="",
        plan_end="",
        now=None,
        completed=False,
        blocked_count=0,
        blocked_reasons=(),
        conflict_count=0,
        conflict_details=(),
        bottleneck_process="",
        bottleneck_node="",
    ):
        now = now or datetime.now()
        deadline_at = parse_schedule_datetime(deadline_text, end_of_day=True)
        projected_at = parse_schedule_datetime(projected_completion_at)
        if projected_at is None:
            projected_at = parse_schedule_datetime(plan_end, end_of_day=True)

        blocked_count = max(int(blocked_count or 0), 0)
        conflict_count = max(int(conflict_count or 0), 0)
        reasons = [str(reason).strip() for reason in (blocked_reasons or ()) if str(reason).strip()]
        blocked_reason = reasons[0] if reasons else "前置条件不满足"
        conflict_rows = [dict(item) for item in (conflict_details or ())]
        primary_conflict = conflict_rows[0] if conflict_rows else {}

        delay_minutes = 0
        if not completed and deadline_at and projected_at and projected_at > deadline_at:
            delay_minutes = int((projected_at - deadline_at).total_seconds() // 60)

        if completed:
            level = "none"
            reason = "订单已完成"
            primary_source = "completed"
        elif deadline_at and now > deadline_at:
            overdue_basis = max(now, projected_at or now)
            delay_minutes = max(
                delay_minutes,
                int((overdue_basis - deadline_at).total_seconds() // 60),
            )
            level = "overdue"
            reason = "已超过交期且订单仍未完成"
            primary_source = "deadline_overdue"
            if blocked_count:
                reason += f"；排程阻断：{blocked_reason}"
            elif conflict_count:
                reason += f"；存在 {conflict_count} 处生产节点冲突"
        elif blocked_count:
            level = "high"
            reason = f"排程被阻断：{blocked_reason}"
            primary_source = "blocked"
            if projected_at and deadline_at and projected_at > deadline_at:
                reason += "；预计完成时间晚于交期"
        elif conflict_count:
            level = "high" if delay_minutes > 0 else "medium"
            primary_source = "conflict"
            conflict_reason = str(primary_conflict.get("reason") or "").strip()
            reason = f"存在 {conflict_count} 处生产节点冲突"
            if conflict_reason:
                reason += f"：{conflict_reason}"
            else:
                reason += "，需重新确认产能"
            if delay_minutes > 0:
                reason += "；预计完成时间晚于交期"
        elif delay_minutes > 0:
            level = "high"
            reason = "按当前精确排程，预计完成时间晚于交期"
            primary_source = "deadline_delay"
        elif deadline_at:
            minutes_to_deadline = int((deadline_at - now).total_seconds() // 60)
            if minutes_to_deadline <= 24 * 60:
                level = "high"
                reason = "距离交期不足 24 小时，排程缓冲不足"
                primary_source = "insufficient_buffer"
            elif minutes_to_deadline <= 72 * 60:
                level = "medium"
                reason = "距离交期不足 3 天"
                primary_source = "insufficient_buffer"
            elif minutes_to_deadline <= 7 * 24 * 60:
                level = "low"
                reason = "距离交期不足 7 天"
                primary_source = "insufficient_buffer"
            else:
                level = "none"
                reason = "当前排程在交期前，且有足够缓冲"
                primary_source = "none"
        else:
            level = "none"
            reason = "未设置交期，暂无法进行交期风险评估"
            primary_source = "missing_deadline"

        slack_minutes = None
        if deadline_at and projected_at:
            # Truncate toward zero so a one-second remainder does not turn
            # 150 minutes of slack into -151 minutes.
            slack_minutes = int((deadline_at - projected_at).total_seconds() / 60)

        suggested_actions = []
        if blocked_count:
            suggested_actions.append("补齐阻断工序的标准工时、节点能力或日历配置")
        if conflict_count:
            suggested_actions.append("调整冲突工序的生产节点或计划时间")
            if any(
                row.get("conflict_type") == "locked_task_conflict"
                for row in conflict_rows
            ):
                suggested_actions.append("由授权人员复核已锁定任务后再调整")
            if any(
                row.get("conflict_type") == "downtime_overlap"
                for row in conflict_rows
            ):
                suggested_actions.append("避开停机时段或安排可用替代节点")
        if delay_minutes > 0:
            suggested_actions.append("评估加急、加班、拆批、换节点或调整交期")
        if primary_source == "insufficient_buffer":
            suggested_actions.append("持续监控实际报工进度并预留异常缓冲")

        return {
            "level": level,
            "reason": reason,
            "deadline": deadline_text or "",
            "deadline_at": format_schedule_datetime(deadline_at),
            "projected_completion_at": format_schedule_datetime(projected_at),
            "delay_minutes": max(delay_minutes, 0),
            "slack_minutes": slack_minutes,
            "blocked_count": blocked_count,
            "conflict_count": conflict_count,
            "primary_source": primary_source,
            "bottleneck_process": str(bottleneck_process or ""),
            "bottleneck_node": str(bottleneck_node or ""),
            "suggested_actions": suggested_actions,
        }


__all__ = [
    "ScheduleDeadlineRiskPolicy",
    "format_schedule_datetime",
    "parse_schedule_datetime",
]
