"""qr-system - BoardService (Data Kanban) - delegates to BoardRepository"""
from datetime import datetime
from modules.repositories.board_repository import BoardRepository


class BoardService:

    @staticmethod
    def get_board_data(category=""):
        """Aggregate all kanban data with optional category filter."""
        today = datetime.now().strftime("%Y-%m-%d")
        cat_sql, cat_params = BoardRepository.category_filter(category)

        total, producing, completed = BoardRepository.get_order_counts(cat_sql, cat_params)
        output, scrap, reports, rework = BoardRepository.get_today_output(today, cat_sql, cat_params)

        return {
            "total_orders": total,
            "producing_orders": producing,
            "completed_orders": completed,
            "today_output": output,
            "today_scrap": scrap,
            "today_reports": reports,
            "today_rework": rework,
            "recent_work": BoardRepository.get_recent_work(cat_sql, cat_params),
            "orders_in_progress": BoardRepository.get_orders_in_progress(cat_sql, cat_params),
            "process_efficiency": BoardRepository.get_process_efficiency(cat_sql, cat_params),
            "monthly_completion": BoardRepository.get_monthly_completion(cat_sql, cat_params),
            "overdue_orders": BoardRepository.get_overdue_orders(today, cat_sql, cat_params),
            "worker_stats": BoardRepository.get_worker_stats_today(today, cat_sql, cat_params),
        }
