"""qr-system - BoardService (Data Kanban) — decomposed"""
from datetime import datetime
from modules.services import BaseService


class BoardService:

    @staticmethod
    def _category_filter(category):
        """Build SQL filter clause for product category."""
        if not category:
            return "", []
        return " AND p.category = ?", [category]

    @staticmethod
    def _board_order_counts(db, cat_sql, cat_params):
        """Total / producing / completed order counts."""
        base = ("FROM orders o LEFT JOIN products p ON o.product_code = p.product_code "
                "WHERE o.deleted_at IS NULL{}")
        total = db.execute("SELECT COUNT(DISTINCT o.id) " + base.format(cat_sql), cat_params).fetchone()[0]
        producing = db.execute("SELECT COUNT(DISTINCT o.id) " + base.format(cat_sql) + " AND o.status='producing'", cat_params).fetchone()[0]
        completed = db.execute("SELECT COUNT(DISTINCT o.id) " + base.format(cat_sql) + " AND o.status='completed'", cat_params).fetchone()[0]
        return total, producing, completed

    @staticmethod
    def _board_today_output(db, today, cat_sql, cat_params):
        """Today output + scrap + reports + rework counts."""
        base = ("FROM work_records wr JOIN orders o ON wr.order_id = o.id "
                "LEFT JOIN products p ON o.product_code = p.product_code "
                "WHERE date(wr.created_at) = ? AND o.deleted_at IS NULL{}")
        output = db.execute("SELECT COALESCE(SUM(wr.quantity),0) " + base.format(cat_sql), [today] + cat_params).fetchone()[0]
        scrap = db.execute("SELECT COALESCE(SUM(wr.quantity),0) " + base.format(cat_sql) + " AND wr.type='scrap'", [today] + cat_params).fetchone()[0]
        reports = db.execute("SELECT COUNT(*) " + base.format(cat_sql), [today] + cat_params).fetchone()[0]
        rework = db.execute("SELECT COALESCE(SUM(wr.quantity),0) " + base.format(cat_sql) + " AND wr.type='rework'", [today] + cat_params).fetchone()[0]
        return output or 0, scrap or 0, reports or 0, rework or 0

    @staticmethod
    def _board_recent_work(db, cat_sql, cat_params):
        """Recent 20 work records."""
        rows = db.execute(
            "SELECT wr.*, o.order_no, p.name as process_name, u.name as worker_name "
            "FROM work_records wr LEFT JOIN orders o ON wr.order_id = o.id "
            "LEFT JOIN products pr ON o.product_code = pr.product_code "
            "LEFT JOIN processes p ON wr.process_id = p.id "
            "LEFT JOIN users u ON wr.user_id = u.id "
            "WHERE o.deleted_at IS NULL{} ORDER BY wr.created_at DESC LIMIT 20".format(cat_sql),
            cat_params
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _board_orders_in_progress(db, cat_sql, cat_params):
        """Active orders (not completed/cancelled) with progress."""
        rows = db.execute(
            "SELECT o.*, COALESCE(c.name, o.customer) as customer_name "
            "FROM orders o LEFT JOIN customers c ON o.customer_id = c.id "
            "LEFT JOIN products p ON o.product_code = p.product_code "
            "WHERE o.deleted_at IS NULL AND o.status NOT IN ('completed','cancelled'){} "
            "ORDER BY o.created_at DESC LIMIT 50".format(cat_sql),
            cat_params
        ).fetchall()
        result = []
        for o in rows:
            d = dict(o)
            qty = d["quantity"] or 1
            d["progress_percent"] = min(round((d["completed"] or 0) / qty * 100), 100)
            result.append(d)
        return result

    @staticmethod
    def _board_process_efficiency(db, cat_sql, cat_params):
        """Process completion ratio per order."""
        rows = db.execute(
            "SELECT o.id as order_id, o.order_no, o.product_name, o.quantity, o.completed, "
            "COUNT(op.id) as total_processes, "
            "SUM(CASE WHEN op.status='completed' THEN 1 ELSE 0 END) as done_processes "
            "FROM orders o LEFT JOIN order_processes op ON op.order_id = o.id "
            "LEFT JOIN products p ON o.product_code = p.product_code "
            "WHERE o.deleted_at IS NULL AND o.status NOT IN ('completed','cancelled'){} "
            "GROUP BY o.id ORDER BY o.created_at DESC LIMIT 20".format(cat_sql),
            cat_params
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _board_overdue(db, today, cat_sql, cat_params):
        """Overdue orders (plan_end < today)."""
        rows = db.execute(
            "SELECT o.*, COALESCE(c.name, o.customer) as customer_name, "
            "CAST(julianday('now','localtime') - julianday(o.plan_end) AS INTEGER) as overdue_days "
            "FROM orders o LEFT JOIN customers c ON o.customer_id = c.id "
            "LEFT JOIN products p ON o.product_code = p.product_code "
            "WHERE o.deleted_at IS NULL AND o.status NOT IN ('completed','cancelled') "
            "AND o.plan_end != '' AND o.plan_end < ?{} ORDER BY o.plan_end ASC LIMIT 10".format(cat_sql),
            [today] + cat_params
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _board_worker_stats(db, today, cat_sql, cat_params):
        """Today worker output ranking."""
        rows = db.execute(
            "SELECT u.name as worker_name, COUNT(wr.id) as report_count, "
            "COALESCE(SUM(wr.quantity),0) as output, "
            "COALESCE(SUM(CASE WHEN wr.type='scrap' THEN wr.quantity ELSE 0 END),0) as scrap, "
            "COALESCE(SUM(CASE WHEN wr.type='rework' THEN wr.quantity ELSE 0 END),0) as rework "
            "FROM work_records wr JOIN users u ON wr.user_id = u.id "
            "JOIN orders o ON wr.order_id = o.id "
            "LEFT JOIN products p ON o.product_code = p.product_code "
            "WHERE date(wr.created_at) = ? AND o.deleted_at IS NULL{} "
            "GROUP BY u.name ORDER BY output DESC LIMIT 10".format(cat_sql),
            [today] + cat_params
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _board_monthly_completion(db, cat_sql, cat_params):
        """Monthly order completion trend (6 months)."""
        rows = db.execute(
            "SELECT substr(o.created_at,1,7) as month, COUNT(*) as total, "
            "SUM(CASE WHEN o.status='completed' THEN 1 ELSE 0 END) as completed "
            "FROM orders o LEFT JOIN products p ON o.product_code = p.product_code "
            "WHERE o.deleted_at IS NULL AND o.created_at >= date('now','-6 months'){} "
            "GROUP BY month ORDER BY month ASC".format(cat_sql),
            cat_params
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def get_board_data(category=""):
        """Aggregate all kanban data with optional category filter."""
        db = BaseService.db()
        today = datetime.now().strftime("%Y-%m-%d")
        cat_sql, cat_params = BoardService._category_filter(category)

        total, producing, completed = BoardService._board_order_counts(db, cat_sql, cat_params)
        output, scrap, reports, rework = BoardService._board_today_output(db, today, cat_sql, cat_params)

        return {
            "total_orders": total,
            "producing_orders": producing,
            "completed_orders": completed,
            "today_output": output,
            "today_scrap": scrap,
            "today_reports": reports,
            "today_rework": rework,
            "recent_work": BoardService._board_recent_work(db, cat_sql, cat_params),
            "orders_in_progress": BoardService._board_orders_in_progress(db, cat_sql, cat_params),
            "process_efficiency": BoardService._board_process_efficiency(db, cat_sql, cat_params),
            "monthly_completion": BoardService._board_monthly_completion(db, cat_sql, cat_params),
            "overdue_orders": BoardService._board_overdue(db, today, cat_sql, cat_params),
            "worker_stats": BoardService._board_worker_stats(db, today, cat_sql, cat_params),
        }
