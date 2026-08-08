"""
qr-system - QualityRepository

All SQL for quality_inspections and quality_attachments tables.
"""
from modules.domain.reporting_day import (
    current_reporting_day,
    reporting_day_bounds,
    reporting_range_bounds,
)
from modules.product_query import ProductQueryFilter
from modules.repositories.context import resolve_db


class QualityRepository:
    """Quality inspection data access."""

    @staticmethod
    def _analytics_filter(start, end, product_code, db):
        where_parts = ["o.deleted_at IS NULL"]
        params = []
        period_start, period_end = reporting_range_bounds(start, end)
        if period_start:
            where_parts.append("qi.inspected_at >= ?")
            params.append(period_start)
        if period_end:
            where_parts.append("qi.inspected_at < ?")
            params.append(period_end)
        if product_code:
            clause, clause_params = ProductQueryFilter.resolve(
                db, product_code
            ).order_clause("o")
            where_parts.append(clause)
            params.extend(clause_params)
        return where_parts, params

    # ============================================================
    # Inspection CRUD
    # ============================================================

    @staticmethod
    def list_inspections(order_id=None, process_id=None, inspection_type="",
                         result="", search="", date_from="", date_to="",
                         page=1, per_page=20, db=None):
        db = resolve_db(db)
        where_parts = []
        params = []

        if order_id:
            where_parts.append("qi.order_id = ?")
            params.append(order_id)
        if process_id:
            where_parts.append("qi.process_id = ?")
            params.append(process_id)
        if inspection_type:
            where_parts.append("qi.inspection_type = ?")
            params.append(inspection_type)
        if result:
            where_parts.append("qi.result = ?")
            params.append(result)
        if search:
            where_parts.append("(o.order_no LIKE ? OR p.name LIKE ?)")
            like = "%" + search + "%"
            params.extend([like, like])
        if date_from:
            where_parts.append("qi.inspected_at >= ?")
            params.append(date_from)
        if date_to:
            where_parts.append("qi.inspected_at <= ?")
            params.append(date_to + " 23:59:59")

        where_clause = " AND ".join(where_parts) if where_parts else "1=1"

        total = db.execute(
            "SELECT COUNT(*) FROM quality_inspections qi "
            "JOIN orders o ON qi.order_id = o.id "
            "JOIN processes p ON qi.process_id = p.id "
            "WHERE " + where_clause, params
        ).fetchone()[0]

        offset = (page - 1) * per_page
        rows = db.execute(
            "SELECT qi.*, o.order_no, o.product_name, "
            "COALESCE(c.name, o.customer) as customer_name, "
            "p.name as process_name, u.name as inspector_name "
            "FROM quality_inspections qi "
            "JOIN orders o ON qi.order_id = o.id "
            "LEFT JOIN customers c ON o.customer_id = c.id "
            "JOIN processes p ON qi.process_id = p.id "
            "LEFT JOIN users u ON qi.inspector_id = u.id "
            "WHERE " + where_clause + " "
            "ORDER BY qi.inspected_at DESC LIMIT ? OFFSET ?",
            params + [per_page, offset]
        ).fetchall()

        return {
            "ok": True, "items": [dict(r) for r in rows],
            "total": total, "page": page, "per_page": per_page
        }

    @staticmethod
    def find_all_for_export(order_id=None, process_id=None, inspection_type="",
                            result="", search="", date_from="", date_to="", db=None):
        db = resolve_db(db)
        where_parts = []
        params = []
        if order_id:
            where_parts.append("qi.order_id = ?"); params.append(order_id)
        if process_id:
            where_parts.append("qi.process_id = ?"); params.append(process_id)
        if inspection_type:
            where_parts.append("qi.inspection_type = ?"); params.append(inspection_type)
        if result:
            where_parts.append("qi.result = ?"); params.append(result)
        if search:
            where_parts.append("(o.order_no LIKE ? OR p.name LIKE ?)")
            like = "%" + search + "%"
            params.extend([like, like])
        if date_from:
            where_parts.append("qi.inspected_at >= ?"); params.append(date_from)
        if date_to:
            where_parts.append("qi.inspected_at <= ?"); params.append(date_to + " 23:59:59")
        where_clause = " AND ".join(where_parts) if where_parts else "1=1"

        return db.execute(
            "SELECT qi.*, o.order_no, o.product_name, "
            "COALESCE(c.name, o.customer) as customer_name, "
            "p.name as process_name, u.name as inspector_name "
            "FROM quality_inspections qi "
            "JOIN orders o ON qi.order_id = o.id "
            "LEFT JOIN customers c ON o.customer_id = c.id "
            "JOIN processes p ON qi.process_id = p.id "
            "LEFT JOIN users u ON qi.inspector_id = u.id "
            "WHERE " + where_clause + " "
            "ORDER BY qi.inspected_at DESC",
            params
        ).fetchall()

    @staticmethod
    def find_by_id(inspection_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM quality_inspections WHERE id = ?", (inspection_id,)
        ).fetchone()

    @staticmethod
    def check_order_exists(order_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id, deleted_at FROM orders WHERE id = ?", (order_id,)
        ).fetchone()

    @staticmethod
    def insert_inspection_txn(data, user_id, db):
        cur = db.execute(
            "INSERT INTO quality_inspections "
            "(order_id, process_id, inspection_type, inspector_id, quantity_checked, "
            "quantity_passed, quantity_failed, result, defect_category, defect_quantity, "
            "notes, inspected_at, score_total, score_detail_json, defect_level, "
            "defect_items_json, suggested_result, final_result, override_reason) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (data["order_id"], data["process_id"], data.get("inspection_type", "first_article"),
             user_id, data.get("quantity_checked", 0), data.get("quantity_passed", 0),
             data.get("quantity_failed", 0), data.get("result", "pending"),
             data.get("defect_category", ""), data.get("defect_quantity", 0),
             data.get("notes", ""), data.get("inspected_at", None),
             data.get("score_total", 0), data.get("score_detail_json", "{}"),
             data.get("defect_level", ""), data.get("defect_items_json", "[]"),
             data.get("suggested_result", ""), data.get("final_result", ""),
             data.get("override_reason", ""))
        )
        return cur.lastrowid

    @staticmethod
    def update_inspection_txn(inspection_id, data, db):
        db.execute(
            "UPDATE quality_inspections SET inspection_type=?, quantity_checked=?, "
            "quantity_passed=?, quantity_failed=?, result=?, defect_category=?, "
            "defect_quantity=?, notes=?, inspected_at=?, score_total=?, "
            "score_detail_json=?, defect_level=?, defect_items_json=?, suggested_result=?, "
            "final_result=?, override_reason=? WHERE id=?",
            (data.get("inspection_type"), data.get("quantity_checked"),
             data.get("quantity_passed"), data.get("quantity_failed"),
             data.get("result"), data.get("defect_category", ""),
             data.get("defect_quantity", 0), data.get("notes", ""),
             data.get("inspected_at"), data.get("score_total", 0),
             data.get("score_detail_json", "{}"), data.get("defect_level", ""),
             data.get("defect_items_json", "[]"), data.get("suggested_result", ""),
             data.get("final_result", ""), data.get("override_reason", ""),
             inspection_id)
        )

    @staticmethod
    def delete_inspection_txn(inspection_id, db):
        db.execute("DELETE FROM quality_inspections WHERE id = ?", (inspection_id,))

    # ============================================================
    # Statistics & Analytics
    # ============================================================

    @staticmethod
    def get_stats(db=None):
        db = resolve_db(db)
        period_start, period_end = reporting_day_bounds(current_reporting_day())
        agg = db.execute(
            "SELECT COUNT(*) as total, "
            "COALESCE(SUM(CASE WHEN result='pass' THEN 1 ELSE 0 END),0) as pass_count, "
            "COALESCE(SUM(CASE WHEN result IN ('rework','scrap','fail','partial') THEN 1 ELSE 0 END),0) as fail_count, "
            "ROUND(AVG(NULLIF(score_total, 0)), 1) as avg_score "
            "FROM quality_inspections"
        ).fetchone()
        today_count = db.execute(
            "SELECT COUNT(*) FROM quality_inspections "
            "WHERE inspected_at>=? AND inspected_at<?", (period_start, period_end)
        ).fetchone()[0]
        return {
            "ok": True, "total": agg["total"], "today_count": today_count,
            "pass_count": agg["pass_count"], "fail_count": agg["fail_count"],
            "avg_score": agg["avg_score"] or 0
        }

    @staticmethod
    def defect_pareto(date_from="", date_to="", db=None):
        db = resolve_db(db)
        where_parts = []
        params = []
        if date_from:
            where_parts.append("inspected_at >= ?"); params.append(date_from)
        if date_to:
            where_parts.append("inspected_at <= ?"); params.append(date_to + " 23:59:59")
        where_clause = "WHERE " + " AND ".join(where_parts) if where_parts else ""

        rows = db.execute(
            "SELECT defect_category, COUNT(*) as cnt, "
            "COALESCE(SUM(defect_quantity),0) as total_qty "
            "FROM quality_inspections " + where_clause + " "
            "GROUP BY defect_category ORDER BY cnt DESC", params
        ).fetchall()
        total = sum(r["cnt"] for r in rows) if rows else 0
        cumulative = 0
        result = []
        for r in rows:
            cumulative += r["cnt"]
            result.append({
                "category": r["defect_category"] or "unknown",
                "count": r["cnt"],
                "quantity": r["total_qty"],
                "pct": round(r["cnt"] / total * 100, 1) if total else 0,
                "cumulative_pct": round(cumulative / total * 100, 1) if total else 0,
            })
        return {"ok": True, "data": result}

    @staticmethod
    def spc_p_chart(
        order_id=None, process_id=None, date_from="", date_to="",
        product_code="", db=None,
    ):
        db = resolve_db(db)
        where_parts, params = QualityRepository._analytics_filter(
            date_from, date_to, product_code, db
        )
        if order_id:
            where_parts.append("qi.order_id = ?"); params.append(order_id)
        if process_id:
            where_parts.append("qi.process_id = ?"); params.append(process_id)
        where_clause = "WHERE " + " AND ".join(where_parts)

        rows = db.execute(
            "SELECT DATE(qi.inspected_at,'-7 hours') as sample_date, "
            "SUM(qi.quantity_checked) as checked, SUM(qi.quantity_failed) as failed "
            "FROM quality_inspections qi JOIN orders o ON qi.order_id=o.id "
            + where_clause + " GROUP BY sample_date ORDER BY sample_date", params
        ).fetchall()

        import math
        samples = []
        for row in rows:
            checked = row["checked"] or 0
            failed = row["failed"] or 0
            samples.append({
                "date": row["sample_date"], "checked": checked, "failed": failed,
                "rate": round(failed / checked * 100, 1) if checked else 0,
            })
        total_checked = sum(s["checked"] for s in samples) if samples else 0
        total_failed = sum(s["failed"] for s in samples) if samples else 0
        p_bar = total_failed / total_checked if total_checked > 0 else 0
        n_bar = total_checked / len(samples) if samples else 1
        sigma = math.sqrt(p_bar * (1 - p_bar) / n_bar) if n_bar > 0 else 0
        ucl = round(min(p_bar + 3 * sigma, 1) * 100, 1)
        cl = round(p_bar * 100, 1)
        lcl = round(max(p_bar - 3 * sigma, 0) * 100, 1)

        return {
            "ok": True, "samples": samples, "ucl": ucl, "cl": cl, "lcl": lcl,
            "total_checked": total_checked, "total_failed": total_failed
        }

    @staticmethod
    def inspector_performance(start="", end="", product_code="", db=None):
        db = resolve_db(db)
        where_parts, params = QualityRepository._analytics_filter(
            start, end, product_code, db
        )
        return db.execute(
            "SELECT u.id, u.name, COUNT(*) as inspection_count, "
            "COALESCE(SUM(qi.quantity_checked),0) as total_checked, "
            "COALESCE(SUM(qi.quantity_failed),0) as total_failed, "
            "COUNT(DISTINCT qi.order_id) as orders_covered, "
            "ROUND(AVG(CASE WHEN qi.quantity_checked>0 THEN qi.quantity_failed*100.0/qi.quantity_checked ELSE 0 END),1) as avg_defect_rate "
            "FROM quality_inspections qi "
            "JOIN users u ON qi.inspector_id = u.id "
            "JOIN orders o ON qi.order_id=o.id "
            "WHERE " + " AND ".join(where_parts) + " "
            "GROUP BY qi.inspector_id ORDER BY inspection_count DESC",
            params,
        ).fetchall()

    @staticmethod
    def supplier_quality(start="", end="", product_code="", db=None):
        db = resolve_db(db)
        where_parts, params = QualityRepository._analytics_filter(
            start, end, product_code, db
        )
        where_parts.append("c.id IS NOT NULL")
        return db.execute(
            "SELECT c.id as customer_id, c.name as customer_name, "
            "COUNT(*) as inspection_count, "
            "COALESCE(SUM(qi.quantity_checked),0) as total_checked, "
            "COALESCE(SUM(qi.quantity_failed),0) as total_failed, "
            "COALESCE(SUM(CASE WHEN qi.result='pass' THEN 1 ELSE 0 END),0) as pass_count, "
            "COALESCE(SUM(CASE WHEN qi.result IN ('fail','partial') THEN 1 ELSE 0 END),0) as fail_count "
            "FROM quality_inspections qi "
            "JOIN orders o ON qi.order_id = o.id "
            "JOIN customers c ON o.customer_id = c.id "
            "WHERE " + " AND ".join(where_parts) + " "
            "GROUP BY c.id ORDER BY inspection_count DESC",
            params,
        ).fetchall()

    @staticmethod
    def pass_rate_trend(weeks=6, start="", end="", product_code="", db=None):
        db = resolve_db(db)
        where_parts, params = QualityRepository._analytics_filter(
            start, end, product_code, db
        )
        if start or end:
            where_clause = "WHERE " + " AND ".join(where_parts)
            rows = db.execute(
                "SELECT strftime('%Y-W%W', qi.inspected_at,'-7 hours') as week, "
                "COUNT(*) as total, "
                "COALESCE(SUM(CASE WHEN qi.result='pass' THEN 1 ELSE 0 END),0) as pass_count "
                "FROM quality_inspections qi JOIN orders o ON qi.order_id=o.id "
                + where_clause + " "
                "GROUP BY week ORDER BY week", params
            ).fetchall()
        else:
            days_val = str(-abs(weeks * 7))
            where_parts.append("qi.inspected_at >= datetime('now','localtime', ? || ' days')")
            params.append(days_val)
            rows = db.execute(
                "SELECT strftime('%Y-W%W', qi.inspected_at,'-7 hours') as week, "
                "COUNT(*) as total, "
                "COALESCE(SUM(CASE WHEN qi.result='pass' THEN 1 ELSE 0 END),0) as pass_count "
                "FROM quality_inspections qi JOIN orders o ON qi.order_id=o.id "
                "WHERE " + " AND ".join(where_parts) + " "
                "GROUP BY week ORDER BY week", params
            ).fetchall()
        result = []
        for r in rows:
            rate = round(r["pass_count"] / r["total"] * 100, 1) if r["total"] > 0 else 0
            result.append({"label": r["week"], "total": r["total"], "pass": r["pass_count"], "rate": rate})
        return result

    # ============================================================
    # Attachments
    # ============================================================

    @staticmethod
    def list_attachments(inspection_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id, file_name, file_type, file_size, uploaded_by, created_at "
            "FROM quality_attachments WHERE inspection_id = ? ORDER BY id DESC",
            (inspection_id,)
        ).fetchall()

    @staticmethod
    def insert_attachment_txn(inspection_id, file_name, file_type, file_size, file_data, user_id, db):
        db.execute(
            "INSERT INTO quality_attachments (inspection_id, file_name, file_type, "
            "file_size, file_data, uploaded_by, created_at) "
            "VALUES (?,?,?,?,?,?,datetime('now','localtime'))",
            (inspection_id, file_name, file_type, file_size, file_data, user_id)
        )

    @staticmethod
    def find_attachment_by_id(att_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM quality_attachments WHERE id = ?", (att_id,)
        ).fetchone()

    @staticmethod
    def delete_attachment_txn(att_id, db):
        db.execute("DELETE FROM quality_attachments WHERE id = ?", (att_id,))

    # ============================================================
    # Mobile Inspection
    # ============================================================

    @staticmethod
    @staticmethod
    def insert_mobile_inspection_txn(data, user_id, db):
        process_id = data.get("process_id")
        # Auto-convert empty string to None for robust null checks
        if process_id == "" or process_id == 0:
            process_id = None
        if not process_id and data.get("process_name") and data.get("order_id"):
            row = db.execute(
                "SELECT op.process_id FROM order_processes op "
                "JOIN processes p ON op.process_id = p.id "
                "WHERE op.order_id = ? AND p.name = ?",
                (data["order_id"], data["process_name"])
            ).fetchone()
            if row:
                process_id = row["process_id"]
        if not process_id:
            # Last resort: get first process of the order
            order_id = data.get("order_id")
            if order_id:
                row = db.execute(
                    "SELECT op.process_id FROM order_processes op "
                    "WHERE op.order_id = ? ORDER BY op.seq_order LIMIT 1",
                    (order_id,)
                ).fetchone()
                if row:
                    process_id = row["process_id"]
        if not process_id:
            raise ValueError("无法确定抽检工序，请选择工序后重试")
        cur = db.execute(
            "INSERT INTO quality_inspections "
            "(order_id, process_id, order_no, product_code, process_name, inspector_name, "
            "inspector_id, result, notes, rework_process, remark, serial_no, "
            "quantity_checked, quantity_passed, quantity_failed, score_total, "
            "score_detail_json, defect_level, defect_items_json, suggested_result, "
            "final_result, override_reason) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (data.get("order_id"), process_id,
             data.get("order_no", ""), data.get("product_code", ""),
             data.get("process_name", ""), data.get("inspector_name", ""),
             user_id, data.get("result", ""), data.get("notes", ""),
             data.get("rework_process", ""), data.get("remark", ""),
             data.get("serial_no", ""), data.get("quantity_checked", 1),
             data.get("quantity_passed", 1 if data.get("result") == "pass" else 0),
             data.get("quantity_failed", 0 if data.get("result") == "pass" else 1),
             data.get("score_total", 0), data.get("score_detail_json", "{}"),
             data.get("defect_level", ""), data.get("defect_items_json", "[]"),
             data.get("suggested_result", ""), data.get("final_result", ""),
             data.get("override_reason", ""))
        )
        return cur.lastrowid

    @staticmethod
    def list_inspections_simple(keyword="", page=1, limit=20, result="", db=None):
        db = resolve_db(db)
        where_parts = []
        params = []
        if keyword:
            where_parts.append("(order_no LIKE ? OR product_code LIKE ?)")
            like = "%" + keyword + "%"
            params.extend([like, like])
        if result:
            where_parts.append("result = ?"); params.append(result)
        where_clause = "WHERE " + " AND ".join(where_parts) if where_parts else ""

        total = db.execute(
            "SELECT COUNT(*) FROM quality_inspections " + where_clause, params
        ).fetchone()[0]

        offset = (page - 1) * limit
        rows = db.execute(
            "SELECT * FROM quality_inspections " + where_clause + " "
            "ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset]
        ).fetchall()

        return {"ok": True, "items": [dict(r) for r in rows],
                "total": total, "page": page, "limit": limit}

    @staticmethod
    def get_mobile_inspection_stats(db=None):
        db = resolve_db(db)
        total = db.execute("SELECT COUNT(*) FROM quality_inspections").fetchone()[0]
        pass_count = db.execute(
            "SELECT COUNT(*) FROM quality_inspections WHERE result='pass'"
        ).fetchone()[0]
        rework_count = db.execute(
            "SELECT COUNT(*) FROM quality_inspections WHERE result='rework'"
        ).fetchone()[0]
        scrap_count = db.execute(
            "SELECT COUNT(*) FROM quality_inspections WHERE result='scrap'"
        ).fetchone()[0]
        avg_score = db.execute(
            "SELECT ROUND(AVG(NULLIF(score_total, 0)), 1) FROM quality_inspections"
        ).fetchone()[0] or 0
        return {"total": total, "pass": pass_count, "rework": rework_count, "scrap": scrap_count, "avg_score": avg_score}
