"""qr-system - EmailReportsService (Repository-refactored)"""
from modules.services import BaseService
from modules.repositories.email_reports_repository import EmailReportsRepository


class EmailReportsService:
    @staticmethod
    def daily_stats(today):
        total_orders, new_orders, completed_orders = EmailReportsRepository.get_daily_order_stats(today)
        wr_sum, top_workers, proc_breakdown = EmailReportsRepository.get_daily_work_records(today)
        return {
            'total_orders': total_orders, 'new_orders': new_orders,
            'completed_orders': completed_orders, 'wr_sum': dict(wr_sum),
            'top_workers': [dict(w) for w in top_workers],
            'proc_breakdown': [dict(p) for p in proc_breakdown],
        }

    @staticmethod
    def weekly_stats(week_start, week_end):
        total_orders, completed = EmailReportsRepository.get_weekly_order_stats(week_start, week_end)
        wr_sum, top_workers = EmailReportsRepository.get_weekly_work_records(week_start, week_end)
        return {
            'total_orders': total_orders, 'completed': completed,
            'wr_sum': dict(wr_sum), 'top_workers': [dict(w) for w in top_workers],
        }
