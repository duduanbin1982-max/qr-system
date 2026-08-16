"""qr-system — ReportsRepository（报表数据访问层）"""
from datetime import datetime, timedelta

from modules.product_query import ProductQueryFilter
from modules.repositories.context import resolve_db
from modules.process_fact_projection import (
    process_value_sql,
    process_version_join,
    warn_legacy_fact_rows,
)
from modules.domain.reporting_day import (
    current_reporting_day,
    reporting_day_bounds,
    reporting_range_bounds,
)


class ReportsRepository:
    """报表数据访问 — 封装所有报表 SQL 查询。"""

    @staticmethod
    def _date_filter(start, end, prefix, field="created_at"):
        where = []
        params = []
        period_start, period_end = reporting_range_bounds(start, end)
        if period_start:
            where.append(f"{prefix}.{field} >= ?")
            params.append(period_start)
        if period_end:
            where.append(f"{prefix}.{field} < ?")
            params.append(period_end)
        return where, params

    @staticmethod
    def _product_filter(product_code, db=None):
        return ProductQueryFilter.resolve(resolve_db(db), product_code)

    @staticmethod
    def worker_efficiency(start="", end="", product_code="", db=None):
        where = [
            "wr.order_id IN (SELECT id FROM orders WHERE deleted_at IS NULL)",
            "wr.status = 'approved'",
        ]
        date_where, params = ReportsRepository._date_filter(start, end, "wr")
        where.extend(date_where)
        if product_code:
            clause, clause_params = ReportsRepository._product_filter(
                product_code, db
            ).order_clause("o2")
            where.append("wr.order_id IN (SELECT o2.id FROM orders o2 WHERE " + clause + ")")
            params.extend(clause_params)
        return ReportsRepository.fetch_worker_efficiency(" AND ".join(where), params, db=db)

    @staticmethod
    def quality_by_process(start="", end="", product_code="", db=None):
        where = [
            "wr.order_id IN (SELECT id FROM orders WHERE deleted_at IS NULL)",
            "wr.status = 'approved'",
        ]
        date_where, params = ReportsRepository._date_filter(start, end, "wr")
        where.extend(date_where)
        if product_code:
            clause, clause_params = ReportsRepository._product_filter(
                product_code, db
            ).order_clause("o2")
            where.append("wr.order_id IN (SELECT o2.id FROM orders o2 WHERE " + clause + ")")
            params.extend(clause_params)
        return ReportsRepository.fetch_quality_by_process(" AND ".join(where), params, db=db)

    @staticmethod
    def quality_inspection_by_process(start="", end="", product_code="", db=None):
        where = ["1=1"]
        date_where, params = ReportsRepository._date_filter(start, end, "qi", "inspected_at")
        where.extend(date_where)
        if product_code:
            clause, clause_params = ReportsRepository._product_filter(
                product_code, db
            ).order_clause("o")
            where.append(clause)
            params.extend(clause_params)
        return ReportsRepository.fetch_quality_inspection_by_process(
            " AND ".join(where), params, db=db
        )

    @staticmethod
    def product_report(start="", end="", product_code="", db=None):
        order_dates, order_params = ReportsRepository._date_filter(start, end, "o")
        item_dates, item_params = ReportsRepository._date_filter(
            start, end, "pi", "completed_at"
        )
        scrap_dates, scrap_params = ReportsRepository._date_filter(start, end, "sr")
        work_dates, work_params = ReportsRepository._date_filter(start, end, "wr")
        product_where = "1=1"
        product_params = []
        if product_code:
            product_where, product_params = ReportsRepository._product_filter(
                product_code, db
            ).product_clause("p")
        rows = ReportsRepository.fetch_product_report(
            " AND ".join(["o.deleted_at IS NULL", *order_dates]),
            order_params,
            " AND ".join([
                "o.deleted_at IS NULL", "pi.status='completed'", *item_dates,
            ]),
            item_params,
            " AND ".join(["o.deleted_at IS NULL", *scrap_dates]),
            scrap_params,
            " AND ".join([
                "o.deleted_at IS NULL", "wr.type='rework'",
                "wr.status='approved'", *work_dates,
            ]),
            work_params,
            product_where,
            product_params,
            db=db,
        )
        summary = {
            "product_count": len(rows),
            "order_count": sum(row["order_count"] or 0 for row in rows),
            "total_output": sum(row["output"] or 0 for row in rows),
        }
        return rows, summary

    @staticmethod
    def material_usage(start="", end="", product_code="", db=None):
        date_where, params = ReportsRepository._date_filter(start, end, "mc")
        where = ["mc.status = 'active'", *date_where]
        if product_code:
            clause, clause_params = ReportsRepository._product_filter(
                product_code, db
            ).order_clause("o2")
            where.append("mc.order_id IN (SELECT o2.id FROM orders o2 WHERE " + clause + ")")
            params.extend(clause_params)
        where_sql = " AND ".join(where)
        return (
            ReportsRepository.fetch_material_usage(where_sql, params, db=db),
            ReportsRepository.fetch_material_usage_summary(where_sql, params, db=db),
        )

    @staticmethod
    def shipment_stats(start="", end="", product_code="", db=None):
        date_where, params = ReportsRepository._date_filter(start, end, "s")
        where = ["1=1", *date_where]
        actual_dates, actual_params = ReportsRepository._date_filter(
            start, end, "s", "completed_at"
        )
        actual_where = ["s.status IN ('completed','received')", *actual_dates]
        if product_code:
            clause, clause_params = ReportsRepository._product_filter(
                product_code, db
            ).order_or_snapshot_clause("o", "si.product_model")
            where.append(clause)
            actual_where.append(clause)
            params.extend(clause_params)
            actual_params.extend(clause_params)
        where_sql = " AND ".join(where)
        actual_where_sql = " AND ".join(actual_where)
        return (
            ReportsRepository.fetch_shipment_by_status(where_sql, params, db=db),
            ReportsRepository.fetch_shipment_by_customer(
                actual_where_sql, actual_params, db=db
            ),
            ReportsRepository.fetch_shipment_monthly_trend(
                actual_where_sql + " AND s.completed_at>=date('now','-12 months')",
                actual_params,
                db=db,
            ),
        )

    @staticmethod
    def product_process_matrix(start="", end="", product_code="", db=None):
        date_where, params = ReportsRepository._date_filter(start, end, "wr")
        where = ["wr.status = 'approved'", "o.deleted_at IS NULL", *date_where]
        if product_code:
            clause, clause_params = ReportsRepository._product_filter(
                product_code, db
            ).product_clause("p")
            where.append(clause)
            params.extend(clause_params)
        return ReportsRepository.fetch_product_process_matrix(" AND ".join(where), params, db=db)

    @staticmethod
    def model_process_stats(start="", end="", db=None):
        date_where, params = ReportsRepository._date_filter(start, end, "wr")
        where = ["wr.status = 'approved'", "o.deleted_at IS NULL", *date_where]
        return ReportsRepository.fetch_model_process_stats(" AND ".join(where), params, db=db)

    @staticmethod
    def product_process_stats(start="", end="", db=None):
        date_where, params = ReportsRepository._date_filter(start, end, "wr")
        where = [
            "wr.status = 'approved'", "o.deleted_at IS NULL",
            "o.status != 'cancelled'", *date_where,
        ]
        where_sql = " AND ".join(where)
        return (
            ReportsRepository.fetch_product_process_proc_names(where_sql, params, db=db),
            ReportsRepository.fetch_product_process_matrix_data(where_sql, params, db=db),
        )

    @staticmethod
    def customer_stats(start="", end="", db=None):
        date_where, params = ReportsRepository._date_filter(start, end, "o")
        return ReportsRepository.fetch_customer_stats(
            " AND ".join(["o.deleted_at IS NULL", *date_where]), params, db=db
        )

    @staticmethod
    def production_line_stats(start="", end="", db=None):
        date_where, params = ReportsRepository._date_filter(start, end, "o")
        return ReportsRepository.fetch_production_line_stats(
            " AND ".join(["o.deleted_at IS NULL", *date_where]), params, db=db
        )

    # ========== production_trend ==========
    @staticmethod
    def fetch_production_trend(start_date, end_date, db=None):
        db = resolve_db(db)
        period_start, period_end = reporting_range_bounds(start_date, end_date)
        return db.execute(
            "WITH RECURSIVE dates(d) AS ("
            "SELECT ? UNION ALL SELECT date(d,'+1 day') FROM dates WHERE d<?"
            "), item_agg AS ("
            "SELECT DATE(pi.completed_at,'-7 hours') AS d, "
            "SUM(CASE WHEN pi.status='completed' THEN 1 ELSE 0 END) AS output, "
            "SUM(CASE WHEN pi.status='scrapped' THEN 1 ELSE 0 END) AS scrap "
            "FROM product_items pi JOIN orders o ON pi.order_id=o.id "
            "WHERE o.deleted_at IS NULL AND pi.status IN ('completed','scrapped') "
            "AND pi.completed_at>=? AND pi.completed_at<? GROUP BY d"
            "), work_agg AS ("
            "SELECT DATE(wr.created_at,'-7 hours') AS d, "
            "SUM(CASE WHEN wr.type='rework' THEN wr.quantity ELSE 0 END) AS rework, "
            "COUNT(*) AS report_count FROM work_records wr "
            "JOIN orders o ON wr.order_id=o.id "
            "WHERE o.deleted_at IS NULL AND wr.status='approved' "
            "AND wr.created_at>=? AND wr.created_at<? GROUP BY d"
            ") SELECT dates.d AS date, COALESCE(i.output,0) AS output, "
            "COALESCE(i.scrap,0) AS scrap, COALESCE(w.rework,0) AS rework, "
            "COALESCE(w.report_count,0) AS report_count FROM dates "
            "LEFT JOIN item_agg i ON i.d=dates.d "
            "LEFT JOIN work_agg w ON w.d=dates.d ORDER BY dates.d ASC",
            (
                start_date, end_date, period_start, period_end,
                period_start, period_end,
            ),
        ).fetchall()

    # ========== worker_efficiency ==========
    @staticmethod
    def fetch_worker_efficiency(where_clause, params, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT u.id, u.name, u.employee_no, "
            "COALESCE(SUM(CASE WHEN wr.type='normal' THEN wr.quantity ELSE 0 END),0) as output, "
            "COALESCE(SUM(CASE WHEN wr.type='scrap' THEN wr.quantity ELSE 0 END),0) as scrap, "
            "COALESCE(SUM(CASE WHEN wr.type='rework' THEN wr.quantity ELSE 0 END),0) as rework, "
            "COUNT(DISTINCT DATE(wr.created_at,'-7 hours')) as work_days, "
            "COUNT(wr.id) as report_count "
            "FROM users u LEFT JOIN work_records wr ON wr.user_id=u.id AND " + where_clause + " "
            "WHERE u.status='active' "
            "GROUP BY u.id ORDER BY output DESC",
            params
        ).fetchall()

    # ========== quality_analysis ==========
    @staticmethod
    def fetch_quality_by_process(where_clause, params, db=None):
        db = resolve_db(db)
        process_name = process_value_sql("wr", "process_version", "p")
        process_category = process_value_sql(
            "wr", "process_version", "p", field="category"
        )
        rows = db.execute(
            "SELECT p.id," + process_name + " AS name," + process_category
            + " AS category,wr.process_id,wr.process_version_id,"
            "COALESCE(SUM(CASE WHEN wr.type='normal' THEN wr.quantity ELSE 0 END),0) as output, "
            "COALESCE(SUM(CASE WHEN wr.type='scrap' THEN wr.quantity ELSE 0 END),0) as scrap, "
            "COALESCE(SUM(CASE WHEN wr.type='rework' THEN wr.quantity ELSE 0 END),0) as rework "
            "FROM processes p JOIN work_records wr ON wr.process_id=p.id "
            + process_version_join("wr", "process_version")
            + "WHERE " + where_clause + " GROUP BY wr.process_id,wr.process_version_id,"
            + process_name + "," + process_category + " ORDER BY output DESC",
            params
        ).fetchall()
        warn_legacy_fact_rows("work_records", rows)
        return rows

    @staticmethod
    def fetch_quality_inspection_by_process(where_clause, params, db=None):
        db = resolve_db(db)
        process_name = process_value_sql("qi", "process_version", "p")
        rows = db.execute(
            "SELECT " + process_name + " AS name,qi.process_id,qi.process_version_id,"
            "COUNT(*) as total_inspections, "
            "COALESCE(SUM(CASE WHEN qi.result='pass' THEN 1 ELSE 0 END),0) as pass_count, "
            "COALESCE(SUM(CASE WHEN qi.result IN('fail','partial') THEN 1 ELSE 0 END),0) as fail_count, "
            "COALESCE(SUM(CASE WHEN qi.result='scrap' THEN 1 ELSE 0 END),0) as scrap_count, "
            "COALESCE(SUM(CASE WHEN qi.result='rework' THEN 1 ELSE 0 END),0) as rework_count "
            "FROM quality_inspections qi "
            "JOIN processes p ON qi.process_id = p.id "
            + process_version_join("qi", "process_version")
            + "JOIN orders o ON qi.order_id = o.id AND o.deleted_at IS NULL "
            "WHERE " + where_clause + " "
            "GROUP BY qi.process_id,qi.process_version_id," + process_name
            + " ORDER BY total_inspections DESC",
            params
        ).fetchall()
        warn_legacy_fact_rows("quality_inspections", rows)
        return rows

    # ========== product_report ==========
    @staticmethod
    def fetch_product_report(
        order_where, order_params, output_where, output_params,
        scrap_where, scrap_params, rework_where, rework_params,
        product_where, product_params, db=None,
    ):
        db = resolve_db(db)
        return db.execute(
            "WITH order_agg AS ("
            "SELECT opl.product_id, SUM(o.quantity) AS order_qty, "
            "COUNT(DISTINCT o.id) AS order_count FROM orders o "
            "JOIN order_product_links opl ON opl.order_id=o.id "
            "WHERE " + order_where + " AND opl.product_id IS NOT NULL GROUP BY opl.product_id"
            "), output_agg AS ("
            "SELECT opl.product_id, COUNT(pi.id) AS output FROM product_items pi "
            "JOIN orders o ON pi.order_id=o.id "
            "JOIN order_product_links opl ON opl.order_id=o.id "
            "WHERE " + output_where + " AND opl.product_id IS NOT NULL GROUP BY opl.product_id"
            "), scrap_agg AS ("
            "SELECT opl.product_id, COALESCE(SUM(sr.quantity),0) AS scrap "
            "FROM scrap_records sr JOIN orders o ON sr.order_id=o.id "
            "JOIN order_product_links opl ON opl.order_id=o.id "
            "WHERE " + scrap_where + " AND opl.product_id IS NOT NULL GROUP BY opl.product_id"
            "), rework_agg AS ("
            "SELECT opl.product_id, COALESCE(SUM(wr.quantity),0) AS rework "
            "FROM work_records wr JOIN orders o ON wr.order_id=o.id "
            "JOIN order_product_links opl ON opl.order_id=o.id "
            "WHERE " + rework_where + " AND opl.product_id IS NOT NULL GROUP BY opl.product_id"
            "), activity AS ("
            "SELECT product_id FROM order_agg UNION SELECT product_id FROM output_agg "
            "UNION SELECT product_id FROM scrap_agg UNION SELECT product_id FROM rework_agg"
            ") SELECT p.id, p.product_name, p.product_code, p.model, p.spec, p.category, "
            "p.price, p.upper_opening, p.lower_opening, p.plate_thickness, p.weight, "
            "COALESCE(oa.order_qty,0) AS order_qty, COALESCE(out.output,0) AS output, "
            "COALESCE(sa.scrap,0) AS scrap, COALESCE(ra.rework,0) AS rework, "
            "COALESCE(oa.order_count,0) AS order_count FROM activity a "
            "JOIN products p ON p.id=a.product_id "
            "LEFT JOIN order_agg oa ON oa.product_id=p.id "
            "LEFT JOIN output_agg out ON out.product_id=p.id "
            "LEFT JOIN scrap_agg sa ON sa.product_id=p.id "
            "LEFT JOIN rework_agg ra ON ra.product_id=p.id "
            "WHERE " + product_where + " ORDER BY output DESC, p.id",
            order_params + output_params + scrap_params + rework_params + product_params,
        ).fetchall()

    # ========== material_usage ==========
    @staticmethod
    def fetch_material_usage(where_clause, params, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT m.id, m.name, m.spec, m.material_type, m.unit, "
            "m.quantity as stock_qty, m.safe_stock, "
            "COALESCE(SUM(mc.quantity),0) as total_used, "
            "COUNT(DISTINCT mc.order_id) as order_count "
            "FROM materials m "
            "LEFT JOIN material_consumptions mc ON mc.material_id=m.id AND " + where_clause + " "
            "GROUP BY m.id ORDER BY total_used DESC",
            params
        ).fetchall()

    @staticmethod
    def fetch_material_usage_summary(where_clause, params, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(DISTINCT CASE WHEN mc.id IS NOT NULL THEN m.id END) as material_count, "
            "COALESCE(SUM(mc.quantity),0) as total_consumed "
            "FROM materials m "
            "LEFT JOIN material_consumptions mc ON mc.material_id=m.id AND " + where_clause,
            params,
        ).fetchone()

    # ========== shipment_stats ==========
    @staticmethod
    def fetch_shipment_by_status(where_clause, params, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT s.status, COUNT(DISTINCT s.id) as count, "
            "COALESCE(SUM(si.quantity),0) as total_qty FROM shipments s "
            "JOIN shipment_items si ON si.shipment_id=s.id "
            "LEFT JOIN orders o ON si.order_id=o.id "
            "WHERE " + where_clause + " GROUP BY s.status ORDER BY count DESC",
            params
        ).fetchall()

    @staticmethod
    def fetch_shipment_by_customer(where_clause, params, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT s.customer, COUNT(DISTINCT s.id) as shipment_count, "
            "COALESCE(SUM(si.quantity),0) as total_qty FROM shipments s "
            "JOIN shipment_items si ON si.shipment_id=s.id "
            "LEFT JOIN orders o ON si.order_id=o.id WHERE " + where_clause + " "
            "GROUP BY s.customer ORDER BY total_qty DESC LIMIT 50",
            params
        ).fetchall()

    @staticmethod
    def fetch_shipment_monthly_trend(where_clause, params, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT strftime('%Y-%m',s.completed_at,'-7 hours') as month, "
            "COUNT(DISTINCT s.id) as count, COALESCE(SUM(si.quantity),0) as total_qty "
            "FROM shipments s JOIN shipment_items si ON si.shipment_id=s.id "
            "LEFT JOIN orders o ON si.order_id=o.id WHERE " + where_clause + " "
            "GROUP BY month ORDER BY month ASC",
            params
        ).fetchall()

    # ========== order_analysis ==========
    @staticmethod
    def fetch_order_status_distribution(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT o.status, COUNT(*) as count, COALESCE(SUM(o.quantity),0) as qty, "
            "COALESCE(SUM(o.completed),0) as done FROM orders o WHERE o.deleted_at IS NULL "
            "GROUP BY o.status ORDER BY COUNT(*) DESC"
        ).fetchall()

    @staticmethod
    def fetch_order_monthly_trend(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT substr(o.created_at,1,7) as month, COUNT(*) as count, "
            "COALESCE(SUM(o.quantity),0) as total_qty, COALESCE(SUM(o.completed),0) as total_done "
            "FROM orders o WHERE o.deleted_at IS NULL AND o.created_at>=date('now','-12 months') "
            "GROUP BY substr(o.created_at,1,7) ORDER BY month ASC"
        ).fetchall()

    # ========== product_process_matrix ==========
    @staticmethod
    def fetch_product_process_matrix(where_clause, params, db=None):
        db = resolve_db(db)
        process_name = process_value_sql("wr", "process_version", "pr")
        rows = db.execute(
            "SELECT p.product_code, p.product_name, p.model, p.spec, "
            "pr.id as process_id,wr.process_version_id," + process_name
            + " as process_name,pr.seq_order,"
            "COALESCE(SUM(CASE WHEN wr.type='normal' THEN wr.quantity ELSE 0 END),0) as output "
            "FROM products p "
            "JOIN order_product_links opl ON opl.product_id=p.id "
            "JOIN orders o ON o.id=opl.order_id AND o.deleted_at IS NULL "
            "JOIN work_records wr ON wr.order_id=o.id AND " + where_clause + " "
            "JOIN processes pr ON wr.process_id=pr.id "
            + process_version_join("wr", "process_version")
            + "GROUP BY p.product_code,p.product_name,p.model,p.spec,pr.id,"
            "wr.process_version_id," + process_name + ",pr.seq_order "
            "ORDER BY p.product_code,pr.seq_order,process_name",
            params
        ).fetchall()
        warn_legacy_fact_rows("work_records", rows)
        return rows

    # ========== model_process_stats ==========
    @staticmethod
    def fetch_model_process_stats(where_clause, params, db=None):
        db = resolve_db(db)
        process_name = process_value_sql("wr", "process_version", "pr")
        rows = db.execute(
            "SELECT p.model,wr.process_id,wr.process_version_id," + process_name
            + " as process_name,"
            "COALESCE(SUM(CASE WHEN wr.type='normal' THEN wr.quantity ELSE 0 END),0) as output, "
            "COALESCE(SUM(CASE WHEN wr.type='scrap' THEN wr.quantity ELSE 0 END),0) as scrap "
            "FROM products p "
            "JOIN order_product_links opl ON opl.product_id=p.id "
            "JOIN orders o ON o.id=opl.order_id AND o.deleted_at IS NULL "
            "JOIN work_records wr ON wr.order_id=o.id AND " + where_clause + " "
            "JOIN processes pr ON wr.process_id=pr.id "
            + process_version_join("wr", "process_version")
            + "GROUP BY p.model,wr.process_id,wr.process_version_id," + process_name
            + " ORDER BY output DESC",
            params
        ).fetchall()
        warn_legacy_fact_rows("work_records", rows)
        return rows

    # ========== product_process_stats ==========
    @staticmethod
    def fetch_product_process_proc_names(where_clause, params, db=None):
        db = resolve_db(db)
        process_name = process_value_sql("wr", "process_version", "pr")
        rows = db.execute(
            "SELECT DISTINCT " + process_name + " AS name,wr.process_id,"
            "wr.process_version_id FROM processes pr "
            "JOIN work_records wr ON wr.process_id=pr.id "
            + process_version_join("wr", "process_version")
            + "JOIN orders o ON wr.order_id=o.id "
            "WHERE " + where_clause + " ORDER BY name", params
        ).fetchall()
        warn_legacy_fact_rows("work_records", rows)
        return rows

    @staticmethod
    def fetch_product_process_matrix_data(where_clause, params, db=None):
        db = resolve_db(db)
        process_name = process_value_sql("wr", "process_version", "pr")
        rows = db.execute(
            "SELECT p.product_code, p.product_name, p.model, p.spec, p.category, "
            "wr.process_id,wr.process_version_id," + process_name + " as process_name,"
            "COALESCE(SUM(CASE WHEN wr.type='normal' THEN wr.quantity ELSE 0 END),0) as output, "
            "COALESCE(SUM(CASE WHEN wr.type='scrap' THEN wr.quantity ELSE 0 END),0) as scrap "
            "FROM products p "
            "JOIN order_product_links opl ON opl.product_id=p.id "
            "JOIN orders o ON o.id=opl.order_id "
            "JOIN work_records wr ON wr.order_id=o.id "
            "JOIN processes pr ON wr.process_id=pr.id "
            + process_version_join("wr", "process_version")
            + "WHERE " + where_clause + " GROUP BY p.product_code,wr.process_id,"
            "wr.process_version_id," + process_name + " ORDER BY p.product_code",
            params
        ).fetchall()
        warn_legacy_fact_rows("work_records", rows)
        return rows

    # ========== customer_stats ==========
    @staticmethod
    def fetch_customer_stats(where_clause, params, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COALESCE(c.name, o.customer) as customer_name, "
            "COUNT(DISTINCT o.id) as order_count, SUM(o.quantity) as total_qty, "
            "COALESCE(SUM(CASE WHEN o.status='completed' THEN o.quantity ELSE 0 END),0) as completed_qty, "
            "COALESCE((SELECT COUNT(*) FROM orders o2 WHERE COALESCE((SELECT name FROM customers c2 WHERE c2.id=o2.customer_id), o2.customer) = COALESCE(c.name, o.customer) AND o2.deleted_at IS NULL AND o2.status IN ('pending','producing','paused')),0) as active_orders "
            "FROM orders o LEFT JOIN customers c ON o.customer_id = c.id "
            "WHERE " + where_clause + " GROUP BY customer_name ORDER BY total_qty DESC LIMIT 200",
            params
        ).fetchall()

    # ========== production_line_stats ==========
    @staticmethod
    def fetch_production_line_stats(where_clause, params, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT pl.id as line_id, pl.name as line_name, "
            "COUNT(DISTINCT o.id) as order_count, SUM(o.quantity) as total_qty, "
            "COALESCE(SUM(CASE WHEN o.status='completed' THEN o.quantity ELSE 0 END),0) as completed_qty, "
            "COALESCE((SELECT COUNT(*) FROM orders o2 WHERE o2.production_line_id=pl.id AND o2.deleted_at IS NULL AND o2.status IN ('pending','producing','paused')),0) as active_orders "
            "FROM production_lines pl "
            "LEFT JOIN orders o ON o.production_line_id = pl.id AND " + where_clause + " "
            "GROUP BY pl.id ORDER BY total_qty DESC",
            params
        ).fetchall()

    # ========== monthly_summary ==========
    @staticmethod
    def fetch_monthly_summary_this(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(DISTINCT o.id) as orders, "
            "COALESCE(SUM(o.quantity),0) as total_qty, "
            "COALESCE((SELECT SUM(o3.quantity) FROM orders o3 "
            "WHERE o3.deleted_at IS NULL AND o3.status='completed' "
            "AND strftime('%Y-%m',o3.completed_at,'-7 hours')="
            "strftime('%Y-%m','now','localtime','-7 hours')),0) as completed_qty, "
            "COALESCE((SELECT COUNT(*) FROM product_items pi JOIN orders o2 ON pi.order_id=o2.id "
            "WHERE o2.deleted_at IS NULL AND pi.status='completed' "
            "AND strftime('%Y-%m',pi.completed_at,'-7 hours')="
            "strftime('%Y-%m','now','localtime','-7 hours')),0) as output "
            "FROM orders o WHERE o.deleted_at IS NULL "
            "AND strftime('%Y-%m',o.created_at,'-7 hours')="
            "strftime('%Y-%m','now','localtime','-7 hours')"
        ).fetchone()

    @staticmethod
    def fetch_monthly_summary_last(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(DISTINCT o.id) as orders, "
            "COALESCE(SUM(o.quantity),0) as total_qty, "
            "COALESCE((SELECT SUM(o3.quantity) FROM orders o3 "
            "WHERE o3.deleted_at IS NULL AND o3.status='completed' "
            "AND strftime('%Y-%m',o3.completed_at,'-7 hours')="
            "strftime('%Y-%m','now','localtime','-1 month','-7 hours')),0) as completed_qty, "
            "COALESCE((SELECT COUNT(*) FROM product_items pi JOIN orders o2 ON pi.order_id=o2.id "
            "WHERE o2.deleted_at IS NULL AND pi.status='completed' "
            "AND strftime('%Y-%m',pi.completed_at,'-7 hours')="
            "strftime('%Y-%m','now','localtime','-1 month','-7 hours')),0) as output "
            "FROM orders o WHERE o.deleted_at IS NULL "
            "AND strftime('%Y-%m',o.created_at,'-7 hours')="
            "strftime('%Y-%m','now','localtime','-1 month','-7 hours')"
        ).fetchone()

    # ========== KPI methods ==========
    @staticmethod
    def kpi_active_orders(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) FROM orders WHERE deleted_at IS NULL AND status IN ('pending','producing','paused')"
        ).fetchone()[0]

    @staticmethod
    def kpi_completed_month(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) FROM orders WHERE deleted_at IS NULL AND status='completed' "
            "AND strftime('%Y-%m',completed_at,'-7 hours')="
            "strftime('%Y-%m','now','localtime','-7 hours')"
        ).fetchone()[0]

    @staticmethod
    def kpi_output_month(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) FROM product_items pi JOIN orders o ON pi.order_id=o.id "
            "WHERE pi.status='completed' AND o.deleted_at IS NULL "
            "AND strftime('%Y-%m',pi.completed_at,'-7 hours')="
            "strftime('%Y-%m','now','localtime','-7 hours')"
        ).fetchone()[0] or 0

    @staticmethod
    def kpi_scrap_total(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) FROM product_items pi JOIN orders o ON pi.order_id=o.id "
            "WHERE pi.status IN ('completed','scrapped') AND o.deleted_at IS NULL "
            "AND strftime('%Y-%m',pi.completed_at,'-7 hours')="
            "strftime('%Y-%m','now','localtime','-7 hours')"
        ).fetchone()[0] or 0

    @staticmethod
    def kpi_scrap_count(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) FROM product_items pi JOIN orders o ON pi.order_id=o.id "
            "WHERE pi.status='scrapped' AND o.deleted_at IS NULL "
            "AND strftime('%Y-%m',pi.completed_at,'-7 hours')="
            "strftime('%Y-%m','now','localtime','-7 hours')"
        ).fetchone()[0] or 0

    @staticmethod
    def kpi_active_workers(db=None):
        db = resolve_db(db)
        period_start, period_end = reporting_day_bounds(current_reporting_day())
        return db.execute(
            "SELECT COUNT(DISTINCT wr.user_id) FROM work_records wr "
            "JOIN orders o ON wr.order_id=o.id WHERE o.deleted_at IS NULL "
            "AND wr.status='approved' AND wr.created_at>=? AND wr.created_at<?",
            (period_start, period_end),
        ).fetchone()[0] or 0

    @staticmethod
    def kpi_pending_shipments(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) FROM shipments WHERE status='pending'"
        ).fetchone()[0] or 0

    @staticmethod
    def kpi_low_stock(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) FROM materials WHERE safe_stock > 0 AND quantity <= safe_stock"
        ).fetchone()[0] or 0

    @staticmethod
    def kpi_weekly_trend(db=None):
        reporting_end = current_reporting_day()
        reporting_start = (
            datetime.strptime(reporting_end, "%Y-%m-%d") - timedelta(days=6)
        ).strftime("%Y-%m-%d")
        return ReportsRepository.fetch_production_trend(
            reporting_start, reporting_end, db=db
        )
