"""qr-system - PersonalStatsService"""
from datetime import datetime, timedelta
from modules.services import BaseService
from modules.repositories.personal_stats_repository import PersonalStatsRepository


class PersonalStatsService:
    @staticmethod
    def get_all_stats(user_id, today_start, week_start, month_start):
        today_records = PersonalStatsRepository.get_today_records(user_id, today_start)
        today_sum = PersonalStatsRepository.get_today_summary(user_id, today_start)
        week_sum = PersonalStatsRepository.get_week_summary(user_id, week_start)
        month_sum = PersonalStatsRepository.get_month_summary(user_id, month_start)
        process_breakdown = PersonalStatsRepository.get_process_breakdown(user_id, today_start)
        active_orders = PersonalStatsRepository.get_active_orders(user_id)

        trend = []
        now = datetime.now()
        for i in range(6, -1, -1):
            day = (now - timedelta(days=i)).strftime('%Y-%m-%d')
            ds = PersonalStatsRepository.get_day_stats(user_id, day + ' 00:00:00', day + ' 23:59:59')
            trend.append({'date': day, 'quantity': ds['qty'], 'records': ds['records']})

        return {
            'today_records': [dict(r) for r in today_records],
            'today_sum': dict(today_sum),
            'week_sum': dict(week_sum),
            'month_sum': dict(month_sum),
            'process_breakdown': [dict(r) for r in process_breakdown],
            'active_orders': [dict(r) for r in active_orders],
            'trend': trend,
        }
