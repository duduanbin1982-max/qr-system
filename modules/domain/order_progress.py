"""Pure order progress, bottleneck, and deadline policies."""

from datetime import datetime


def parse_datetime(value, end_of_day=False):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if len(text) == 10:
            parsed = datetime.strptime(text, "%Y-%m-%d")
            return parsed.replace(hour=23, minute=59, second=59) if end_of_day else parsed
        return datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def hours_between(start, end):
    if not start or not end:
        return None
    return round(max((end - start).total_seconds() / 3600, 0), 1)


class WorkpieceProgressCalculator:
    @staticmethod
    def _record_map(work_records):
        records = {}
        for record in work_records:
            records.setdefault(record["serial_no"], {})[record["process_id"]] = {
                "completed_at": record["created_at"],
                "worker_name": record["worker_name"] or "",
            }
        return records

    @staticmethod
    def _build_steps(item, processes, records, standard_minutes, estimate_sources):
        steps = []
        completed_times = []
        serial_records = records.get(item.get("serial_no") or "", {})
        for process in processes:
            process_id = process["process_id"]
            record = serial_records.get(process_id)
            completed_at = None
            worker_name = ""
            if record:
                status = "completed"
                completed_at = record["completed_at"]
                worker_name = record["worker_name"]
            elif item.get("status") == "completed":
                status = "completed"
                completed_at = item.get("completed_at") or None
            elif item.get("current_process_id") == process_id:
                status = "current"
            else:
                status = "pending"
            parsed_at = parse_datetime(completed_at)
            if parsed_at:
                completed_times.append(parsed_at)
            steps.append({
                "process_id": process_id,
                "process_name": process["process_name"],
                "seq_order": process["seq_order"],
                "status": status,
                "completed_at": completed_at,
                "worker_name": worker_name,
                "estimated_minutes_per_unit": round(standard_minutes.get(process_id, 0), 1),
                "estimate_source": estimate_sources.get(process_id, "missing"),
            })
        return steps, completed_times

    @staticmethod
    def _calculate_item(item, processes, records, standards, sources, now, threshold, order_created_at):
        steps, completed_times = WorkpieceProgressCalculator._build_steps(
            item, processes, records, standards, sources
        )
        remaining_steps = [step for step in steps if step["status"] != "completed"]
        all_completed = bool(steps) and not remaining_steps
        has_started = any(step["status"] in ("completed", "current") for step in steps)
        status = "completed" if all_completed else ("in_progress" if has_started else "pending")
        blocking_step = next((step for step in steps if step["status"] == "current"), None)
        blocking_step = blocking_step or next(
            (step for step in steps if step["status"] != "completed"), None
        )
        wait_start = None
        if status != "completed":
            wait_start = max(completed_times) if completed_times else (
                parse_datetime(item.get("created_at")) or order_created_at
            )
        wait_hours = hours_between(wait_start, now) if wait_start else None
        remaining_minutes = sum(standards.get(step["process_id"], 0) for step in remaining_steps)
        return {
            "serial_no": item.get("serial_no") or "",
            "position_no": item.get("position_no"),
            "current_process_id": item.get("current_process_id"),
            "status": status,
            "steps": steps,
            "completed_steps": len(steps) - len(remaining_steps),
            "remaining_steps": len(remaining_steps),
            "last_completed_at": max(completed_times).strftime("%Y-%m-%d %H:%M:%S") if completed_times else "",
            "blocking_process_id": blocking_step["process_id"] if blocking_step else None,
            "blocking_process_name": blocking_step["process_name"] if blocking_step else "",
            "wait_hours": wait_hours,
            "is_stuck": status != "completed" and wait_hours is not None and wait_hours >= threshold,
            "estimated_remaining_minutes": round(remaining_minutes, 1),
            "missing_standard": any(step["process_id"] not in standards for step in remaining_steps),
        }

    @staticmethod
    def calculate(items, processes, work_records, standards, sources, now, threshold, order_created_at):
        records = WorkpieceProgressCalculator._record_map(work_records)
        return [
            WorkpieceProgressCalculator._calculate_item(
                item, processes, records, standards, sources, now, threshold, order_created_at
            )
            for item in items
        ]

    @staticmethod
    def process_stats(progress, processes, standards, sources):
        total = len(progress)
        stats = []
        for process in processes:
            process_id = process["process_id"]
            completed = sum(
                1 for item in progress for step in item["steps"]
                if step["process_id"] == process_id and step["status"] == "completed"
            )
            stats.append({
                "process_id": process_id,
                "process_name": process["process_name"],
                "seq_order": process["seq_order"],
                "completed": completed,
                "current": sum(1 for item in progress if item["blocking_process_id"] == process_id and item["status"] == "in_progress"),
                "pending": sum(1 for item in progress if item["blocking_process_id"] == process_id and item["status"] == "pending"),
                "stuck": sum(1 for item in progress if item["blocking_process_id"] == process_id and item["is_stuck"]),
                "estimate_source": sources.get(process_id, "missing"),
                "estimated_minutes_per_unit": round(standards.get(process_id, 0), 1),
                "backlog": max(total - completed, 0),
                "total": total,
                "completion_pct": round(completed / max(total, 1) * 100, 1),
            })
        return stats


class BottleneckPolicy:
    @staticmethod
    def stuck_items(progress, limit=50):
        fields = (
            "serial_no", "position_no", "status", "blocking_process_id",
            "blocking_process_name", "wait_hours", "remaining_steps", "last_completed_at",
        )
        items = [{field: item[field] for field in fields} for item in progress if item["is_stuck"]]
        return sorted(items, key=lambda item: item["wait_hours"] or 0, reverse=True)[:limit]

    @staticmethod
    def bottlenecks(process_stats, limit=5):
        pending = [stat for stat in process_stats if stat["backlog"] > 0]
        return sorted(
            pending,
            key=lambda stat: (-stat["stuck"], -stat["backlog"], stat["seq_order"]),
        )[:limit]


class DeadlineRiskPolicy:
    @staticmethod
    def evaluate(deadline_text, now, total, completed, estimated_hours, stuck_items):
        deadline_at = parse_datetime(deadline_text, end_of_day=True)
        hours_to_deadline = hours_between(now, deadline_at) if deadline_at else None
        if total and completed == total:
            level, reason = "none", "订单内工件已全部完成"
        elif deadline_at and now > deadline_at:
            level, reason = "overdue", "已超过计划交期且仍有工件未完成"
        elif hours_to_deadline is not None and hours_to_deadline <= 24:
            level, reason = "high", "距离交期不足 24 小时且仍有工件未完成"
        elif estimated_hours is not None and hours_to_deadline is not None and estimated_hours > hours_to_deadline:
            level, reason = "high", "按标准工时估算，剩余工时超过交期剩余时间"
        elif stuck_items:
            level, reason = "medium", "存在滞留工件，需要优先处理卡点"
        elif hours_to_deadline is not None and hours_to_deadline <= 72:
            level, reason = "medium", "距离交期不足 3 天"
        else:
            level, reason = "low", "暂未发现明显交期风险"
        return {
            "level": level,
            "reason": reason,
            "deadline": deadline_text,
            "days_remaining": round(hours_to_deadline / 24, 1) if hours_to_deadline is not None else None,
            "estimated_remaining_hours": estimated_hours,
        }


class ProgressRecommendationPolicy:
    @staticmethod
    def build(tracking_mode, summary, bottlenecks, stuck_items, threshold, risk, sources, progress):
        recommendations = []
        total = summary["total_workpieces"]
        completed = summary["completed_workpieces"]
        remaining = summary["remaining_workpieces"]
        if tracking_mode == "order":
            recommendations.append("当前订单未生成单件序列号，无法定位每件工件卡点；建议后续订单使用序列号模式。")
        if 0 < completed < total:
            recommendations.append(f"已有 {completed} 件完成，可按业务规则先入库或安排部分发货，剩余 {remaining} 件继续生产。")
        if bottlenecks:
            top = bottlenecks[0]
            recommendations.append(f"优先处理「{top['process_name']}」工序：积压 {top['backlog']} 件，其中滞留 {top['stuck']} 件。")
        if stuck_items:
            recommendations.append(f"发现 {len(stuck_items)} 件超过 {threshold:g} 小时未推进，建议班组长按卡点清单逐件分派。")
        if risk["level"] in ("high", "overdue"):
            recommendations.append("交期风险较高，建议临时加派人员、调整排程优先级或与客户确认分批交付。")
        if "actual_history" in sources.values():
            recommendations.append("部分剩余工时已按审核通过的历史实际工时修正，排程估算比纯标准工时更接近现场产能。")
        if progress and any(item["missing_standard"] for item in progress):
            recommendations.append("部分工序缺少标准工时且缺少足够历史工时，建议在工时管理中补齐标准后再用系统估算剩余产能。")
        return recommendations or ["当前未发现明显卡点，按现有排程继续推进。"]


class OrderProgressPolicy:
    @staticmethod
    def build(order_id, order, items, processes, work_records, standards, sources, now, threshold):
        tracking_mode = "serial" if items else "order"
        progress = WorkpieceProgressCalculator.calculate(
            items, processes, work_records, standards, sources, now, threshold,
            parse_datetime(order.get("created_at")),
        )
        process_stats = WorkpieceProgressCalculator.process_stats(progress, processes, standards, sources)
        total = len(progress)
        completed = sum(1 for item in progress if item["status"] == "completed")
        in_progress = sum(1 for item in progress if item["status"] == "in_progress")
        total_steps = total * len(processes)
        estimated_hours = None
        if progress and any(not item["missing_standard"] for item in progress):
            estimated_hours = round(sum(item["estimated_remaining_minutes"] for item in progress) / 60, 1)
        stuck_items = BottleneckPolicy.stuck_items(progress)
        bottlenecks = BottleneckPolicy.bottlenecks(process_stats)
        summary = {
            "total_workpieces": total,
            "completed_workpieces": completed,
            "in_progress_workpieces": in_progress,
            "pending_workpieces": total - completed - in_progress,
            "stuck_workpieces": len(stuck_items),
            "remaining_workpieces": max(total - completed, 0),
            "total_processes": len(processes),
            "total_remaining_steps": sum(item["remaining_steps"] for item in progress),
            "estimated_remaining_hours": estimated_hours,
            "overall_progress_pct": round(sum(item["completed_steps"] for item in progress) / max(total_steps, 1) * 100, 1),
            "process_stats": process_stats,
        }
        deadline_text = order.get("deadline") or order.get("plan_end") or ""
        risk = DeadlineRiskPolicy.evaluate(deadline_text, now, total, completed, estimated_hours, stuck_items)
        recommendations = ProgressRecommendationPolicy.build(
            tracking_mode, summary, bottlenecks, stuck_items, threshold, risk, sources, progress
        )
        return {
            "order_id": order_id,
            "order_no": order.get("order_no"),
            "product_name": order.get("product_name"),
            "quantity": order.get("quantity"),
            "route_name": order.get("route_name", ""),
            "deadline": deadline_text,
            "progress": progress,
            "summary": summary,
            "processes": [
                {"process_id": process["process_id"], "name": process["process_name"], "seq_order": process["seq_order"]}
                for process in processes
            ],
            "analysis": {
                "tracking_mode": tracking_mode,
                "stuck_threshold_hours": threshold,
                "deadline_risk": risk,
                "stuck_items": stuck_items,
                "bottlenecks": bottlenecks,
                "recommendations": recommendations,
            },
        }
