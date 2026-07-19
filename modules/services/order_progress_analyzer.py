"""Order workpiece progress, bottleneck, and deadline analysis."""

from datetime import datetime

from modules.repositories.order_repository import OrderRepository
from modules.repositories.work_time_repository import WorkTimeRepository
from modules.setting_reader import get_setting


class OrderProgressAnalyzer:
    """Builds order progress analysis without depending on OrderService."""

    @staticmethod
    def _parse_datetime(value, end_of_day=False):
        if not value:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            if len(text) == 10:
                parsed = datetime.strptime(text, "%Y-%m-%d")
                if end_of_day:
                    return parsed.replace(hour=23, minute=59, second=59)
                return parsed
            return datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _hours_between(start, end):
        if not start or not end:
            return None
        return round(max((end - start).total_seconds() / 3600, 0), 1)

    @staticmethod
    def _workpiece_stuck_threshold_hours():
        try:
            value = float(get_setting("workpiece_stuck_threshold_hours", "24") or 24)
            return max(value, 1)
        except (TypeError, ValueError):
            return 24

    @staticmethod
    def analyze(order_id):
        """获取订单工件进度、卡点和交期风险分析。"""
        order = OrderRepository.find_by_id(order_id)
        if not order:
            raise ValueError("订单不存在")
        items, processes, work_records = OrderRepository.get_workpiece_progress_rows(order_id)
        order_data = dict(order)
        items = [dict(item) for item in items]
        processes = [dict(process) for process in processes]
        record_map = {}
        for record in work_records:
            serial_no = record["serial_no"]
            record_map.setdefault(serial_no, {})[record["process_id"]] = {
                "status": record["status"],
                "completed_at": record["created_at"],
                "worker_name": record["worker_name"] or "",
            }

        process_ids = [process["process_id"] for process in processes]
        standard_rows = OrderRepository.get_route_work_time_standards(order_data.get("route_id"))
        standard_minutes = {}
        estimate_sources = {}
        for row in standard_rows:
            base_minutes = float(row["standard_minutes_per_unit"] or 0)
            factor = float(row["difficulty_factor"] or 1)
            if base_minutes > 0:
                standard_minutes[row["process_id"]] = base_minutes * factor
                estimate_sources[row["process_id"]] = "standard"
        history_minutes = WorkTimeRepository.historical_effective_minutes_by_process(
            order_data.get("route_id"),
            process_ids,
            order_data.get("product_code") or "",
        )
        for process_id, history in history_minutes.items():
            avg_minutes = float(history.get("avg_minutes_per_unit") or 0)
            if avg_minutes > 0:
                standard_minutes[process_id] = avg_minutes
                estimate_sources[process_id] = "actual_history"

        now = datetime.now()
        threshold_hours = OrderProgressAnalyzer._workpiece_stuck_threshold_hours()
        tracking_mode = "serial" if items else "order"
        order_created_at = OrderProgressAnalyzer._parse_datetime(order_data.get("created_at"))
        progress = []

        for item in items:
            serial_no = item.get("serial_no") or ""
            steps = []
            completed_times = []
            for process in processes:
                process_id = process["process_id"]
                record = record_map.get(serial_no, {}).get(process_id)
                completed_at = None
                worker_name = ""
                if record:
                    step_status = "completed"
                    completed_at = record["completed_at"]
                    worker_name = record.get("worker_name", "")
                    parsed_at = OrderProgressAnalyzer._parse_datetime(completed_at)
                    if parsed_at:
                        completed_times.append(parsed_at)
                elif item.get("status") == "completed":
                    step_status = "completed"
                    completed_at = item.get("completed_at") or None
                    parsed_at = OrderProgressAnalyzer._parse_datetime(completed_at)
                    if parsed_at:
                        completed_times.append(parsed_at)
                elif item.get("current_process_id") and process_id == item.get("current_process_id"):
                    step_status = "current"
                else:
                    step_status = "pending"

                steps.append({
                    "process_id": process_id,
                    "process_name": process["process_name"],
                    "seq_order": process["seq_order"],
                    "status": step_status,
                    "completed_at": completed_at,
                    "worker_name": worker_name,
                    "estimated_minutes_per_unit": round(standard_minutes.get(process_id, 0), 1),
                    "estimate_source": estimate_sources.get(process_id, "missing"),
                })

            all_completed = bool(steps) and all(step["status"] == "completed" for step in steps)
            has_started = any(step["status"] in ("completed", "current") for step in steps)
            workpiece_status = "completed" if all_completed else ("in_progress" if has_started else "pending")
            blocking_step = next((step for step in steps if step["status"] == "current"), None)
            if not blocking_step:
                blocking_step = next((step for step in steps if step["status"] != "completed"), None)

            last_completed_at = max(completed_times).strftime("%Y-%m-%d %H:%M:%S") if completed_times else ""
            wait_start = None
            if workpiece_status != "completed":
                wait_start = max(completed_times) if completed_times else (
                    OrderProgressAnalyzer._parse_datetime(item.get("created_at")) or order_created_at
                )
            wait_hours = OrderProgressAnalyzer._hours_between(wait_start, now) if wait_start else None
            is_stuck = workpiece_status != "completed" and wait_hours is not None and wait_hours >= threshold_hours
            remaining_steps = [step for step in steps if step["status"] != "completed"]
            remaining_minutes = sum(standard_minutes.get(step["process_id"], 0) for step in remaining_steps)
            missing_standard = any(step["process_id"] not in standard_minutes for step in remaining_steps)

            progress.append({
                "serial_no": serial_no,
                "position_no": item.get("position_no"),
                "current_process_id": item.get("current_process_id"),
                "status": workpiece_status,
                "steps": steps,
                "completed_steps": len(steps) - len(remaining_steps),
                "remaining_steps": len(remaining_steps),
                "last_completed_at": last_completed_at,
                "blocking_process_id": blocking_step["process_id"] if blocking_step else None,
                "blocking_process_name": blocking_step["process_name"] if blocking_step else "",
                "wait_hours": wait_hours,
                "is_stuck": is_stuck,
                "estimated_remaining_minutes": round(remaining_minutes, 1),
                "missing_standard": missing_standard,
            })

        total_items = len(progress)
        total_steps = len(processes)
        completed_items = sum(1 for item in progress if item["status"] == "completed")
        in_progress_items = sum(1 for item in progress if item["status"] == "in_progress")
        pending_items = total_items - completed_items - in_progress_items
        completed_step_count = sum(item["completed_steps"] for item in progress)
        total_step_count = total_items * total_steps

        process_stats = []
        for process in processes:
            process_id = process["process_id"]
            completed_count = sum(
                1 for item in progress
                for step in item["steps"]
                if step["process_id"] == process_id and step["status"] == "completed"
            )
            current_count = sum(1 for item in progress if item["blocking_process_id"] == process_id and item["status"] == "in_progress")
            pending_count = sum(1 for item in progress if item["blocking_process_id"] == process_id and item["status"] == "pending")
            stuck_count = sum(1 for item in progress if item["blocking_process_id"] == process_id and item["is_stuck"])
            process_stats.append({
                "process_id": process_id,
                "process_name": process["process_name"],
                "seq_order": process["seq_order"],
                "completed": completed_count,
                "current": current_count,
                "pending": pending_count,
                "stuck": stuck_count,
                "estimate_source": estimate_sources.get(process_id, "missing"),
                "estimated_minutes_per_unit": round(standard_minutes.get(process_id, 0), 1),
                "backlog": max(total_items - completed_count, 0),
                "total": total_items,
                "completion_pct": round(completed_count / max(total_items, 1) * 100, 1),
            })

        stuck_items = sorted(
            [
                {
                    "serial_no": item["serial_no"],
                    "position_no": item["position_no"],
                    "status": item["status"],
                    "blocking_process_id": item["blocking_process_id"],
                    "blocking_process_name": item["blocking_process_name"],
                    "wait_hours": item["wait_hours"],
                    "remaining_steps": item["remaining_steps"],
                    "last_completed_at": item["last_completed_at"],
                }
                for item in progress if item["is_stuck"]
            ],
            key=lambda item: item["wait_hours"] or 0,
            reverse=True,
        )[:50]

        bottlenecks = sorted(
            [stat for stat in process_stats if stat["backlog"] > 0],
            key=lambda stat: (-stat["stuck"], -stat["backlog"], stat["seq_order"]),
        )[:5]

        estimated_remaining_hours = None
        if progress and any(not item["missing_standard"] for item in progress):
            estimated_remaining_hours = round(
                sum(item["estimated_remaining_minutes"] for item in progress) / 60,
                1,
            )

        deadline_text = order_data.get("deadline") or order_data.get("plan_end") or ""
        deadline_at = OrderProgressAnalyzer._parse_datetime(deadline_text, end_of_day=True)
        hours_to_deadline = OrderProgressAnalyzer._hours_between(now, deadline_at) if deadline_at else None
        days_remaining = round(hours_to_deadline / 24, 1) if hours_to_deadline is not None else None
        remaining_workpieces = max(total_items - completed_items, 0)
        if total_items and completed_items == total_items:
            risk_level = "none"
            risk_reason = "订单内工件已全部完成"
        elif deadline_at and now > deadline_at:
            risk_level = "overdue"
            risk_reason = "已超过计划交期且仍有工件未完成"
        elif deadline_at and hours_to_deadline is not None and hours_to_deadline <= 24:
            risk_level = "high"
            risk_reason = "距离交期不足 24 小时且仍有工件未完成"
        elif estimated_remaining_hours is not None and hours_to_deadline is not None and estimated_remaining_hours > hours_to_deadline:
            risk_level = "high"
            risk_reason = "按标准工时估算，剩余工时超过交期剩余时间"
        elif stuck_items:
            risk_level = "medium"
            risk_reason = "存在滞留工件，需要优先处理卡点"
        elif deadline_at and hours_to_deadline is not None and hours_to_deadline <= 72:
            risk_level = "medium"
            risk_reason = "距离交期不足 3 天"
        else:
            risk_level = "low"
            risk_reason = "暂未发现明显交期风险"

        recommendations = []
        if tracking_mode == "order":
            recommendations.append("当前订单未生成单件序列号，无法定位每件工件卡点；建议后续订单使用序列号模式。")
        if 0 < completed_items < total_items:
            recommendations.append(f"已有 {completed_items} 件完成，可按业务规则先入库或安排部分发货，剩余 {remaining_workpieces} 件继续生产。")
        if bottlenecks:
            top = bottlenecks[0]
            recommendations.append(f"优先处理「{top['process_name']}」工序：积压 {top['backlog']} 件，其中滞留 {top['stuck']} 件。")
        if stuck_items:
            recommendations.append(f"发现 {len(stuck_items)} 件超过 {threshold_hours:g} 小时未推进，建议班组长按卡点清单逐件分派。")
        if risk_level in ("high", "overdue"):
            recommendations.append("交期风险较高，建议临时加派人员、调整排程优先级或与客户确认分批交付。")
        if any(source == "actual_history" for source in estimate_sources.values()):
            recommendations.append("部分剩余工时已按审核通过的历史实际工时修正，排程估算比纯标准工时更接近现场产能。")
        if progress and any(item["missing_standard"] for item in progress):
            recommendations.append("部分工序缺少标准工时且缺少足够历史工时，建议在工时管理中补齐标准后再用系统估算剩余产能。")
        if not recommendations:
            recommendations.append("当前未发现明显卡点，按现有排程继续推进。")

        summary = {
            "total_workpieces": total_items,
            "completed_workpieces": completed_items,
            "in_progress_workpieces": in_progress_items,
            "pending_workpieces": pending_items,
            "stuck_workpieces": len(stuck_items),
            "remaining_workpieces": remaining_workpieces,
            "total_processes": total_steps,
            "total_remaining_steps": sum(item["remaining_steps"] for item in progress),
            "estimated_remaining_hours": estimated_remaining_hours,
            "overall_progress_pct": round(completed_step_count / max(total_step_count, 1) * 100, 1),
            "process_stats": process_stats,
        }

        return {
            "order_id": order_id,
            "order_no": order_data.get("order_no"),
            "product_name": order_data.get("product_name"),
            "quantity": order_data.get("quantity"),
            "route_name": order_data.get("route_name", ""),
            "deadline": deadline_text,
            "progress": progress,
            "summary": summary,
            "processes": [
                {"process_id": process["process_id"], "name": process["process_name"], "seq_order": process["seq_order"]}
                for process in processes
            ],
            "analysis": {
                "tracking_mode": tracking_mode,
                "stuck_threshold_hours": threshold_hours,
                "deadline_risk": {
                    "level": risk_level,
                    "reason": risk_reason,
                    "deadline": deadline_text,
                    "days_remaining": days_remaining,
                    "estimated_remaining_hours": estimated_remaining_hours,
                },
                "stuck_items": stuck_items,
                "bottlenecks": bottlenecks,
                "recommendations": recommendations,
            },
        }
