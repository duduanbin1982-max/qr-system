"""
qr-system - ReworkRepository

All SQL for rework_records table.
"""
from modules.repositories.context import resolve_db
from modules.process_fact_projection import (
    capture_process_fact_binding,
    process_value_sql,
    process_version_join,
    warn_legacy_fact_rows,
)


class ReworkRepository:
    """Rework data access."""

    @staticmethod
    def list_rework(status="", search="", date_from="", date_to="",
                    page=1, per_page=50, worker_id=None, process_id=None, db=None):
        """List rework records with filters and pagination using static SQL."""
        db = resolve_db(db)
        where_parts = []
        params = []

        if status:
            where_parts.append("rw.status = ?")
            params.append(status)
        if search:
            where_parts.append(
                "(o.order_no LIKE ? OR rw.process_name_snapshot LIKE ? "
                "OR process_version.name LIKE ? OR p.name LIKE ? OR u.name LIKE ?)"
            )
            like = "%" + search + "%"
            params.extend([like] * 5)
        if date_from:
            where_parts.append("rw.created_at >= ?")
            params.append(date_from)
        if date_to:
            where_parts.append("rw.created_at <= ?")
            params.append(date_to + " 23:59:59")
        if worker_id:
            where_parts.append("rw.user_id = ?")
            params.append(worker_id)
        if process_id:
            where_parts.append("rw.process_id = ?")
            params.append(process_id)

        where_clause = " AND ".join(where_parts) if where_parts else "1=1"

        total = db.execute(
            "SELECT COUNT(*) FROM rework_records rw "
            "JOIN orders o ON rw.order_id = o.id "
            "JOIN processes p ON rw.process_id = p.id "
            + process_version_join("rw", "process_version")
            + "LEFT JOIN users u ON rw.user_id = u.id "
            "WHERE " + where_clause, params
        ).fetchone()[0]

        offset = (page - 1) * per_page
        process_name = process_value_sql("rw", "process_version", "p")
        rows = db.execute(
            "SELECT rw.*, o.order_no, o.product_name, "
            "COALESCE(c.name, o.customer) as customer_name, "
            + process_name + " as process_name,u.name as worker_name,"
            "cu.name as completed_by_name "
            "FROM rework_records rw "
            "JOIN orders o ON rw.order_id = o.id "
            "LEFT JOIN customers c ON o.customer_id = c.id "
            "JOIN processes p ON rw.process_id = p.id "
            + process_version_join("rw", "process_version")
            + "LEFT JOIN users u ON rw.user_id = u.id "
            "LEFT JOIN users cu ON rw.completed_by = cu.id "
            "WHERE " + where_clause + " "
            "ORDER BY rw.created_at DESC LIMIT ? OFFSET ?",
            params + [per_page, offset]
        ).fetchall()
        warn_legacy_fact_rows("rework_records", rows)

        return {
            "ok": True, "items": [dict(r) for r in rows],
            "total": total, "page": page, "per_page": per_page
        }

    @staticmethod
    def find_by_id(rework_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM rework_records WHERE id = ?", (rework_id,)
        ).fetchone()

    @staticmethod
    def find_order_process_context(order_id, process_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT o.id AS order_id, o.status AS order_status, o.deleted_at, "
            "op.id AS order_process_id "
            "FROM orders o LEFT JOIN order_processes op "
            "ON op.order_id = o.id AND op.process_id = ? WHERE o.id = ?",
            (process_id, order_id),
        ).fetchone()

    @staticmethod
    def find_recent_duplicate(order_id, process_id, user_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id FROM rework_records WHERE order_id = ? AND process_id = ? "
            "AND user_id = ? AND created_at > datetime('now', '-10 seconds') "
            "ORDER BY id DESC LIMIT 1",
            (order_id, process_id, user_id),
        ).fetchone()

    @staticmethod
    def find_by_source_ncr_id(source_ncr_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id FROM rework_records WHERE source_ncr_id = ? ORDER BY id LIMIT 1",
            (source_ncr_id,),
        ).fetchone()

    @staticmethod
    def find_ncr_context(source_ncr_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT ncr.id,ncr.inspection_id,ncr.order_id,ncr.process_id,"
            "ncr.responsible_user_id,task.work_record_id AS target_work_record_id "
            "FROM quality_nonconformances ncr "
            "LEFT JOIN quality_inspection_tasks task ON task.id=ncr.task_id "
            "WHERE ncr.id=?",
            (source_ncr_id,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def insert_rework_txn(
        order_id, process_id, user_id, quantity, reason, db, source_ncr_id=None
    ):
        binding = capture_process_fact_binding(
            db, order_id=order_id, process_id=process_id
        )
        cur = db.execute(
            "INSERT INTO rework_records "
            "(order_id,process_id,user_id,quantity,reason,source_ncr_id,"
            "process_version_id,process_code_snapshot,process_name_snapshot,"
            "process_category_snapshot,route_id,route_version_id,route_name_snapshot,"
            "version_binding_source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                order_id, process_id, user_id, quantity, reason, source_ncr_id,
                binding["process_version_id"], binding["process_code_snapshot"],
                binding["process_name_snapshot"], binding["process_category_snapshot"],
                binding["route_id"], binding["route_version_id"],
                binding["route_name_snapshot"], binding["version_binding_source"],
            )
        )
        return cur.lastrowid

    @staticmethod
    def increment_order_process_rework_txn(order_id, process_id, quantity, db):
        cursor = db.execute(
            "UPDATE order_processes SET rework = COALESCE(rework,0) + ? "
            "WHERE order_id = ? AND process_id = ?",
            (quantity, order_id, process_id)
        )
        return cursor.rowcount

    @staticmethod
    def sync_order_rework_txn(order_id, db):
        cursor = db.execute(
            "UPDATE orders SET rework = ("
            "SELECT COALESCE(SUM(rework),0) FROM order_processes WHERE order_id = ?"
            "), updated_at = datetime('now','localtime') WHERE id = ?",
            (order_id, order_id)
        )
        return cursor.rowcount

    @staticmethod
    def update_reason_pending(rework_id, reason, db=None):
        db = resolve_db(db)
        cursor = db.execute(
            "UPDATE rework_records SET reason = ? WHERE id = ? AND status = 'pending'",
            (reason, rework_id)
        )
        return cursor.rowcount

    @staticmethod
    def complete_rework_txn(rework_id, reason, user_id, result, result_remark, duration, db):
        cursor = db.execute(
            "UPDATE rework_records SET status = 'completed', reason = ?, "
            "completed_by = ?, result = ?, result_remark = ?, "
            "completed_at = datetime('now','localtime'), duration_hours = ? "
            "WHERE id = ? AND status = 'pending'",
            (reason, user_id, result, result_remark, duration, rework_id)
        )
        return cursor.rowcount

    @staticmethod
    def get_stats(db=None):
        from datetime import datetime, timedelta
        db = resolve_db(db)
        today = datetime.now().strftime("%Y-%m-%d")
        now = datetime.now()
        week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
        month_start = now.strftime("%Y-%m-01")

        row = db.execute(
            "SELECT "
            "COALESCE(SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END),0) as pending_count, "
            "COALESCE(SUM(CASE WHEN status='pending' THEN quantity ELSE 0 END),0) as pending_qty, "
            "COALESCE(SUM(CASE WHEN DATE(created_at)=? THEN 1 ELSE 0 END),0) as today_count, "
            "COALESCE(SUM(CASE WHEN DATE(created_at)=? THEN quantity ELSE 0 END),0) as today_qty, "
            "COALESCE(SUM(CASE WHEN DATE(completed_at)=? THEN 1 ELSE 0 END),0) as today_done, "
            "COALESCE(SUM(CASE WHEN DATE(completed_at)=? THEN quantity ELSE 0 END),0) as today_done_qty, "
            "COALESCE(SUM(CASE WHEN DATE(created_at)>=? THEN quantity ELSE 0 END),0) as week_rework_qty, "
            "COALESCE(SUM(CASE WHEN DATE(created_at)>=? THEN quantity ELSE 0 END),0) as month_rework_qty "
            "FROM rework_records",
            (today, today, today, today, week_start, month_start)
        ).fetchone()

        week_work = db.execute(
            "SELECT COALESCE(SUM(quantity),0) FROM work_records "
            "WHERE DATE(created_at) >= ? AND type != 'scrap'", (week_start,)
        ).fetchone()[0]
        month_work = db.execute(
            "SELECT COALESCE(SUM(quantity),0) FROM work_records "
            "WHERE DATE(created_at) >= ? AND type != 'scrap'", (month_start,)
        ).fetchone()[0]

        week_rate = round(row["week_rework_qty"] / week_work * 100, 1) if week_work > 0 else 0
        month_rate = round(row["month_rework_qty"] / month_work * 100, 1) if month_work > 0 else 0

        return {
            "ok": True,
            "pending_count": row["pending_count"],
            "pending_qty": row["pending_qty"],
            "today_count": row["today_count"],
            "today_qty": row["today_qty"],
            "today_done": row["today_done"],
            "today_done_qty": row["today_done_qty"],
            "week_rework_qty": row["week_rework_qty"],
            "month_rework_qty": row["month_rework_qty"],
            "week_rate": week_rate,
            "month_rate": month_rate,
        }

    @staticmethod
    def rework_trend(period="week", months=3, db=None):
        db = resolve_db(db)
        months_val = -abs(months)
        if period == "week":
            rows = db.execute(
                "SELECT strftime('%Y-W%W', created_at) as week_label, "
                "COUNT(*) as cnt, COALESCE(SUM(quantity),0) as qty "
                "FROM rework_records "
                "WHERE created_at >= date('now', ? || ' months') "
                "GROUP BY week_label ORDER BY week_label",
                (str(months_val),)
            ).fetchall()
            return [{"label": r["week_label"], "count": r["cnt"], "quantity": r["qty"]} for r in rows]
        else:
            rows = db.execute(
                "SELECT strftime('%Y-%m', created_at) as month_label, "
                "COUNT(*) as cnt, COALESCE(SUM(quantity),0) as qty "
                "FROM rework_records "
                "WHERE created_at >= date('now', ? || ' months') "
                "GROUP BY month_label ORDER BY month_label",
                (str(months_val),)
            ).fetchall()
            return [{"label": r["month_label"], "count": r["cnt"], "quantity": r["qty"]} for r in rows]

    @staticmethod
    def top_rework_processes(top_n=5, db=None):
        db = resolve_db(db)
        process_name = process_value_sql("rw", "process_version", "p")
        rows = db.execute(
            "SELECT rw.process_id,rw.process_version_id," + process_name + " AS process_name,"
            "COUNT(*) as rework_count, "
            "COALESCE(SUM(rw.quantity),0) as rework_qty "
            "FROM rework_records rw "
            "JOIN processes p ON rw.process_id=p.id "
            + process_version_join("rw", "process_version")
            + "GROUP BY rw.process_id,rw.process_version_id," + process_name + " "
            "ORDER BY rework_count DESC LIMIT ?",
            (top_n,)
        ).fetchall()
        total_work = db.execute(
            "SELECT wr.process_id,wr.process_version_id,COALESCE(SUM(wr.quantity),0) as total_qty "
            "FROM work_records wr "
            "WHERE wr.type != 'scrap' "
            "GROUP BY wr.process_id,wr.process_version_id"
        ).fetchall()
        work_map = {
            (r["process_id"], r["process_version_id"]): r["total_qty"]
            for r in total_work
        }
        warn_legacy_fact_rows("rework_records", rows)
        result = []
        for r in rows:
            total = work_map.get((r["process_id"], r["process_version_id"]), 0)
            rate = round(r["rework_qty"] / total * 100, 1) if total > 0 else 0
            result.append({
                "process_name": r["process_name"],
                "process_id": r["process_id"],
                "process_version_id": r["process_version_id"],
                "rework_count": r["rework_count"],
                "rework_qty": r["rework_qty"],
                "total_qty": total,
                "rate": rate
            })
        return result

    @staticmethod
    def worker_rework_stats(db=None):
        db = resolve_db(db)
        rows = db.execute(
            "SELECT u.name as worker_name, u.id as worker_id, "
            "COUNT(*) as rework_count, "
            "COALESCE(SUM(rw.quantity),0) as rework_qty, "
            "COUNT(DISTINCT rw.order_id) as affected_orders, "
            "COALESCE(SUM(CASE WHEN rw.result='scrap' THEN rw.quantity ELSE 0 END),0) as scrap_qty, "
            "ROUND(AVG(rw.duration_hours),1) as avg_duration "
            "FROM rework_records rw "
            "JOIN users u ON rw.user_id = u.id "
            "GROUP BY rw.user_id "
            "ORDER BY rework_count DESC"
        ).fetchall()
        total_work = db.execute(
            "SELECT u.id as worker_id, COALESCE(SUM(wr.quantity),0) as total_qty "
            "FROM work_records wr "
            "JOIN users u ON wr.user_id = u.id "
            "WHERE wr.type != 'scrap' "
            "GROUP BY wr.user_id"
        ).fetchall()
        work_map = {r["worker_id"]: r["total_qty"] for r in total_work}
        result = []
        for r in rows:
            total = work_map.get(r["worker_id"], 0)
            rate = round(r["rework_qty"] / total * 100, 1) if total > 0 else 0
            result.append({
                "worker_name": r["worker_name"],
                "worker_id": r["worker_id"],
                "rework_count": r["rework_count"],
                "rework_qty": r["rework_qty"],
                "affected_orders": r["affected_orders"],
                "scrap_qty": r["scrap_qty"],
                "avg_duration": r["avg_duration"],
                "total_qty": total,
                "rate": rate,
            })
        return result

    @staticmethod
    def find_all_for_export(status="", search="", date_from="", date_to="",
                            worker_id=None, process_id=None, db=None):
        """Get all matching rework records for export (no pagination)."""
        db = resolve_db(db)
        process_name = process_value_sql("rw", "process_version", "p")
        where_parts = []
        params = []

        if status:
            where_parts.append("rw.status = ?")
            params.append(status)
        if search:
            where_parts.append(
                "(o.order_no LIKE ? OR " + process_name + " LIKE ? OR u.name LIKE ?)"
            )
            like = "%" + search + "%"
            params.extend([like, like, like])
        if date_from:
            where_parts.append("rw.created_at >= ?")
            params.append(date_from)
        if date_to:
            where_parts.append("rw.created_at <= ?")
            params.append(date_to + " 23:59:59")
        if worker_id:
            where_parts.append("rw.user_id = ?")
            params.append(worker_id)
        if process_id:
            where_parts.append("rw.process_id = ?")
            params.append(process_id)

        where_clause = " AND ".join(where_parts) if where_parts else "1=1"

        rows = db.execute(
            "SELECT rw.*, o.order_no, o.product_name, "
            "COALESCE(c.name, o.customer) as customer_name, "
            + process_name + " AS process_name,u.name as worker_name "
            "FROM rework_records rw "
            "JOIN orders o ON rw.order_id = o.id "
            "LEFT JOIN customers c ON o.customer_id = c.id "
            "JOIN processes p ON rw.process_id = p.id "
            + process_version_join("rw", "process_version")
            + "LEFT JOIN users u ON rw.user_id = u.id WHERE " + where_clause + " "
            "ORDER BY rw.created_at DESC",
            params
        ).fetchall()
        warn_legacy_fact_rows("rework_records", rows)
        return rows
