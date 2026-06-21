"""qr-system - StatsService"""
from modules.repositories.stats_repository import StatsRepository


class StatsService:
    @staticmethod
    def get_daily_records(date, product_code="", page_param=1, per_page_param=500):
        page = int(page_param or 1)
        per_page = min(int(per_page_param or 500), 2000)
        offset = (page - 1) * per_page
        records = StatsRepository.get_daily_records(date, product_code, per_page, offset)
        summary = StatsRepository.get_daily_summary(date, product_code)
        total = StatsRepository.get_daily_count(date, product_code)
        return {
            "records": records,
            "summary": summary,
            "total": total,
            "page": page,
            "per_page": per_page
        }

    @staticmethod
    def get_scrap_records(start="", end="", product_code=""):
        records = StatsRepository.get_scrap_records(start, end, product_code)
        summary = StatsRepository.get_scrap_summary(start, end, product_code)
        by_process = StatsRepository.get_scrap_by_process(start, end, product_code)
        return {
            "records": records,
            "summary": summary if summary else {},
            "by_process": by_process,
        }

    @staticmethod
    def get_order_progress(start="", end="", product_code=""):
        return StatsRepository.get_order_progress(start, end, product_code)

    @staticmethod
    def get_worker_stats(sort_by="quantity", sort_dir="desc", start="", end="", product_code=""):
        return StatsRepository.get_worker_stats(sort_by, sort_dir, start, end, product_code)

    @staticmethod
    def get_worker_detail(user_id, start='', end=''):
        return StatsRepository.get_worker_detail(user_id, start, end)
