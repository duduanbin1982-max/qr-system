"""Order progress application service."""

from datetime import datetime

from modules.domain.order_progress import OrderProgressPolicy
from modules.repositories.order_repository import OrderRepository
from modules.repositories.work_time_repository import WorkTimeRepository
from modules.setting_reader import get_setting


class OrderProgressAnalyzer:
    """Loads progress data and delegates production rules to pure policies."""

    @staticmethod
    def _workpiece_stuck_threshold_hours():
        try:
            value = float(get_setting("workpiece_stuck_threshold_hours", "24") or 24)
            return max(value, 1)
        except (TypeError, ValueError):
            return 24

    @staticmethod
    def _estimate_catalog(order, processes):
        standards = {}
        sources = {}
        for row in OrderRepository.get_route_work_time_standards(order.get("route_id")):
            base_minutes = float(row["standard_minutes_per_unit"] or 0)
            factor = float(row["difficulty_factor"] or 1)
            if base_minutes > 0:
                standards[row["process_id"]] = base_minutes * factor
                sources[row["process_id"]] = "standard"
        history = WorkTimeRepository.historical_effective_minutes_by_process(
            order.get("route_id"),
            [process["process_id"] for process in processes],
            order.get("product_code") or "",
        )
        for process_id, metrics in history.items():
            average = float(metrics.get("avg_minutes_per_unit") or 0)
            if average > 0:
                standards[process_id] = average
                sources[process_id] = "actual_history"
        return standards, sources

    @staticmethod
    def analyze(order_id):
        """获取订单工件进度、卡点和交期风险分析。"""
        order = OrderRepository.find_by_id(order_id)
        if not order:
            raise ValueError("订单不存在")
        items, processes, work_records = OrderRepository.get_workpiece_progress_rows(order_id)
        order_data = dict(order)
        item_data = [dict(item) for item in items]
        process_data = [dict(process) for process in processes]
        standards, sources = OrderProgressAnalyzer._estimate_catalog(order_data, process_data)
        return OrderProgressPolicy.build(
            order_id=order_id,
            order=order_data,
            items=item_data,
            processes=process_data,
            work_records=work_records,
            standards=standards,
            sources=sources,
            now=datetime.now(),
            threshold=OrderProgressAnalyzer._workpiece_stuck_threshold_hours(),
        )
