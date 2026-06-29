"""qr-system - BoardService (Data Kanban) — decomposed"""
from datetime import datetime
from modules.services import BaseService
from modules.repositories.board_repository import BoardRepository


class BoardService:

    @staticmethod
    def get_board_data(category=""):
        """Aggregate all kanban data with optional category filter."""
        db = BaseService.db()
        today = datetime.now().strftime("%Y-%m-%d")
        cat_sql, cat_params = BoardRepository.category_filter(category)

        total, producing, completed = BoardRepository.get_order_counts(cat_sql, cat_params, db=db)
        output, scrap, reports, rework = BoardRepository.get_today_output(today, cat_sql, cat_params, db=db)

        return {
            "total_orders": total,
            "producing_orders": producing,
            "completed_orders": completed,
            "today_output": output,
            "today_scrap": scrap,
            "today_reports": reports,
            "today_rework": rework,
            "recent_work": BoardRepository.get_recent_work(cat_sql, cat_params, db=db),
            "orders_in_progress": BoardRepository.get_orders_in_progress(cat_sql, cat_params, db=db),
            "process_efficiency": BoardRepository.get_process_efficiency(cat_sql, cat_params, db=db),
            "monthly_completion": BoardRepository.get_monthly_completion(cat_sql, cat_params, db=db),
            "overdue_orders": BoardRepository.get_overdue_orders(today, cat_sql, cat_params, db=db),
            "worker_stats": BoardRepository.get_worker_stats_today(today, cat_sql, cat_params, db=db),
        }

    # ============================================================
    # Board Auth Sessions
    # ============================================================
    @staticmethod
    def create_auth_session(token, expires_at):
        with BaseService.transaction() as txn:
            BoardRepository.insert_session_txn(token, expires_at, db=txn)

    @staticmethod
    def rotate_auth_token(token_hash, created_at):
        with BaseService.transaction() as txn:
            BoardRepository.upsert_setting_txn('board_token', token_hash, db=txn)
            BoardRepository.upsert_setting_txn('board_token_created_at', created_at, db=txn)
            BoardRepository.delete_sessions_txn(db=txn)

    @staticmethod
    def count_active_sessions():
        return BoardRepository.count_active_sessions()

    @staticmethod
    def verify_session(token):
        if not token:
            return False
        return BoardRepository.find_active_session(token) is not None

    @staticmethod
    def cleanup_expired_sessions():
        with BaseService.transaction() as txn:
            BoardRepository.cleanup_expired_sessions_txn(db=txn)
