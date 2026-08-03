"""qr-system — ReportsRepository（报表数据访问层）"""
from modules.product_query import ProductQueryFilter
from modules.repositories.context import resolve_db


class ReportsRepository:
    """报表数据访问 — 封装所有报表 SQL 查询。"""

    @staticmethod
    def _date_filter(start, end, prefix, field="created_at"):
        where = []
        params = []
        if start:
            where.append(f"DATE({prefix}.{field}) >= ?")
            params.append(start)
        if end:
            where.append(f"DATE({prefix}.{field}) <= ?")
            params.append(end)
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
            ).snapshot_clause("qi.product_code")
            where.append(clause)
            params.extend(clause_params)
        return ReportsRepository.fetch_quality_inspection_by_process(
            " AND ".join(where), params, db=db
        )

    @staticmethod
    def product_report(start="", end="", product_code="", db=None):
        where = ["o.deleted_at IS NULL"]
        order_dates, params = ReportsRepository._date_filter(start, end, "o")
        where.extend(order_dates)
        if product_code:
            clause, clause_params = ReportsRepository._product_filter(
                product_code, db
            ).order_clause("o")
            where.append(clause)
            params.extend(clause_params)
        item_dates, item_params = ReportsRepository._date_filter(start, end, "pi", "completed_at")
        scrap_dates, _ = ReportsRepository._date_filter(start, end, "sr")
        work_dates, _ = ReportsRepository._date_filter(start, end, "wr")
        item_where = "".join(f" AND {condition}" for condition in item_dates)
        scrap_where = "".join(f" AND {condition}" for condition in scrap_dates)
        work_where = "".join(f" AND {condition}" for condition in work_dates)
        where_sql = " AND ".join(where)
        return (
            ReportsRepository.fetch_product_report(
                where_sql, params, item_where, scrap_where, work_where, item_params, db=db
            ),
            ReportsRepository.fetch_product_report_summary(
                where_sql, params, item_where, item_params, db=db
            ),
        )

    @staticmethod
    def material_usage(start="", end="", product_code="", db=None):
        date_where, params = ReportsRepository._date_filter(start, end, "mc")
        where = ["1=1", *date_where]
        if product_code:
            clause, clause_params = ReportsRepository._product_filter(
                product_code, db
            ).order_clause("o2")
            where.append("mc.order_id IN (SELECT o2.id FROM orders o2 WHERE " + clause + ")")
            params.extend(clause_params)
        date_sql = " AND ".join(date_where)
        date_params = params[:len(date_where)]
        return (
            ReportsRepository.fetch_material_usage(" AND ".join(where), params, db=db),
            ReportsRepository.fetch_material_usage_summary(date_sql, date_params, db=db),
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
            ).order_clause("o")
            product_where = (
                "s.id IN (SELECT si.shipment_id FROM shipment_items si "
                "JOIN orders o ON si.order_id=o.id WHERE "
                + clause + ")"
            )
            where.append(product_where)
            actual_where.append(product_where)
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
        return db.execute(
            "SELECT dates.d as date, "
            "COALESCE(COUNT(DISTINCT CASE WHEN pi.status='completed' THEN pi.id END),0) as output, "
            "COALESCE(COUNT(DISTINCT CASE WHEN pi.status='scrapped' THEN pi.id END),0) as scrap, "
            "COALESCE(SUM(CASE WHEN wr.type='rework' THEN wr.quantity ELSE 0 END),0) as rework, "
            "COUNT(wr.id) as report_count "
            "FROM (WITH RECURSIVE dates(d) AS (SELECT ? UNION ALL SELECT date(d,'+1 day') FROM dates WHERE d<?) SELECT d FROM dates) dates "
            "LEFT JOIN product_items pi ON DATE(pi.completed_at)=dates.d AND pi.status IN ('completed','scrapped') AND pi.order_id IN (SELECT id FROM orders WHERE deleted_at IS NULL) "
            "LEFT JOIN work_records wr ON DATE(wr.created_at)=dates.d "
            "AND wr.order_id IN (SELECT id FROM orders WHERE deleted_at IS NULL) "
            "GROUP BY dates.d ORDER BY dates.d ASC",
            (start_date, end_date)
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
            "COUNT(DISTINCT DATE(wr.created_at)) as work_days, COUNT(wr.id) as report_count "
            "FROM users u LEFT JOIN work_records wr ON wr.user_id=u.id AND " + where_clause + " "
            "WHERE u.status='active' "
            "GROUP BY u.id ORDER BY output DESC",
            params
        ).fetchall()

    # ========== quality_analysis ==========
    @staticmethod
    def fetch_quality_by_process(where_clause, params, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT p.id, p.name, p.category, "
            "COALESCE(SUM(CASE WHEN wr.type='normal' THEN wr.quantity ELSE 0 END),0) as output, "
            "COALESCE(SUM(CASE WHEN wr.type='scrap' THEN wr.quantity ELSE 0 END),0) as scrap, "
            "COALESCE(SUM(CASE WHEN wr.type='rework' THEN wr.quantity ELSE 0 END),0) as rework "
            "FROM processes p JOIN work_records wr ON wr.process_id=p.id "
            "WHERE " + where_clause + " GROUP BY p.id ORDER BY output DESC",
            params
        ).fetchall()

    @staticmethod
    def fetch_quality_by_product(where_clause, params, pi_w, sr_w, wr_w, item_params, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT p.id, p.product_name, p.product_code, p.model, p.spec, p.category, "
            "p.price, p.upper_opening, p.lower_opening, p.plate_thickness, p.weight, "
            "COALESCE(SUM(o.quantity),0) as order_qty, "
            "COALESCE((SELECT COUNT(*) FROM product_items pi JOIN orders o2 ON pi.order_id=o2.id "
            "JOIN order_product_links opl2 ON opl2.order_id=o2.id "
            "WHERE opl2.product_id=p.id AND o2.deleted_at IS NULL AND pi.status='completed'" + pi_w + "),0) as output, "
            "COALESCE((SELECT COUNT(DISTINCT sr.id) FROM scrap_records sr JOIN orders o2 ON sr.order_id=o2.id "
            "JOIN order_product_links opl2 ON opl2.order_id=o2.id "
            "WHERE opl2.product_id=p.id AND o2.deleted_at IS NULL" + sr_w + "),0) as scrap, "
            "COALESCE((SELECT COUNT(DISTINCT wr.id) FROM work_records wr JOIN orders o2 ON wr.order_id=o2.id "
            "JOIN order_product_links opl2 ON opl2.order_id=o2.id "
            "WHERE opl2.product_id=p.id AND o2.deleted_at IS NULL AND wr.type='rework' AND wr.status='approved'" + wr_w + "),0) as rework, "
            "COUNT(DISTINCT o.id) as order_count "
            "FROM products p "
            "LEFT JOIN order_product_links opl ON opl.product_id=p.id "
            "LEFT JOIN orders o ON o.id=opl.order_id AND o.deleted_at IS NULL "
            "WHERE " + where_clause + " GROUP BY p.id ORDER BY output DESC LIMIT 200",
            params + item_params + item_params + item_params
        ).fetchall()

    @staticmethod
    def fetch_quality_summary(where_clause, params, pi_w, item_params, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(DISTINCT p.id) as product_count, "
            "COUNT(DISTINCT o.id) as order_count, "
            "COALESCE((SELECT COUNT(*) FROM product_items pi JOIN orders o2 ON pi.order_id=o2.id "
            "WHERE o2.deleted_at IS NULL AND pi.status='completed'" + pi_w + "),0) as total_output "
            "FROM products p "
            "LEFT JOIN order_product_links opl ON opl.product_id=p.id "
            "LEFT JOIN orders o ON o.id=opl.order_id AND o.deleted_at IS NULL "
            "WHERE " + where_clause,
            params + item_params
        ).fetchone()

    @staticmethod
    def fetch_quality_inspection_by_process(where_clause, params, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT p.name, COUNT(*) as total_inspections, "
            "COALESCE(SUM(CASE WHEN qi.result='pass' THEN 1 ELSE 0 END),0) as pass_count, "
            "COALESCE(SUM(CASE WHEN qi.result IN('fail','partial') THEN 1 ELSE 0 END),0) as fail_count, "
            "COALESCE(SUM(CASE WHEN qi.result='scrap' THEN 1 ELSE 0 END),0) as scrap_count, "
            "COALESCE(SUM(CASE WHEN qi.result='rework' THEN 1 ELSE 0 END),0) as rework_count "
            "FROM quality_inspections qi "
            "JOIN processes p ON qi.process_id = p.id "
            "JOIN orders o ON qi.order_id = o.id AND o.deleted_at IS NULL "
            "WHERE " + where_clause + " "
            "GROUP BY p.name ORDER BY total_inspections DESC",
            params
        ).fetchall()

    # ========== product_report ==========
    @staticmethod
    def fetch_product_report(where_clause, params, pi_w, sr_w, wr_w, item_params, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT p.id, p.product_name, p.product_code, p.model, p.spec, p.category, "
            "p.price, p.upper_opening, p.lower_opening, p.plate_thickness, p.weight, "
            "COALESCE(SUM(o.quantity),0) as order_qty, "
            "COALESCE((SELECT COUNT(*) FROM product_items pi JOIN orders o2 ON pi.order_id=o2.id "
            "JOIN order_product_links opl2 ON opl2.order_id=o2.id "
            "WHERE opl2.product_id=p.id AND o2.deleted_at IS NULL AND pi.status='completed'" + pi_w + "),0) as output, "
            "COALESCE((SELECT COUNT(DISTINCT sr.id) FROM scrap_records sr JOIN orders o2 ON sr.order_id=o2.id "
            "JOIN order_product_links opl2 ON opl2.order_id=o2.id "
            "WHERE opl2.product_id=p.id AND o2.deleted_at IS NULL" + sr_w + "),0) as scrap, "
            "COALESCE((SELECT COUNT(DISTINCT wr.id) FROM work_records wr JOIN orders o2 ON wr.order_id=o2.id "
            "JOIN order_product_links opl2 ON opl2.order_id=o2.id "
            "WHERE opl2.product_id=p.id AND o2.deleted_at IS NULL AND wr.type='rework' AND wr.status='approved'" + wr_w + "),0) as rework, "
            "COUNT(DISTINCT o.id) as order_count "
            "FROM products p "
            "LEFT JOIN order_product_links opl ON opl.product_id=p.id "
            "LEFT JOIN orders o ON o.id=opl.order_id AND o.deleted_at IS NULL "
            "WHERE " + where_clause + " GROUP BY p.id ORDER BY output DESC LIMIT 200",
            params + item_params + item_params + item_params
        ).fetchall()

    @staticmethod
    def fetch_product_report_summary(where_clause, params, pi_w, item_params, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(DISTINCT p.id) as product_count, "
            "COUNT(DISTINCT o.id) as order_count, "
            "COALESCE((SELECT COUNT(*) FROM product_items pi JOIN orders o2 ON pi.order_id=o2.id "
            "WHERE o2.deleted_at IS NULL AND pi.status='completed'" + pi_w + "),0) as total_output "
            "FROM products p "
            "LEFT JOIN order_product_links opl ON opl.product_id=p.id "
            "LEFT JOIN orders o ON o.id=opl.order_id AND o.deleted_at IS NULL "
            "WHERE " + where_clause,
            params + item_params
        ).fetchone()

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
            "GROUP BY m.id ORDER BY total_used DESC LIMIT 200",
            params
        ).fetchall()

    @staticmethod
    def fetch_material_usage_summary(date_w, date_p, db=None):
        db = resolve_db(db)
        extra = (" AND " + date_w) if date_w else ""
        return db.execute(
            "SELECT COUNT(DISTINCT m.id) as material_count, "
            "COALESCE(SUM(mc.quantity),0) as total_consumed "
            "FROM materials m "
            "LEFT JOIN material_consumptions mc ON mc.material_id=m.id" + extra,
            date_p
        ).fetchone()

    # ========== shipment_stats ==========
    @staticmethod
    def fetch_shipment_by_status(where_clause, params, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT s.status, COUNT(*) as count, COALESCE(SUM(s.total_quantity),0) as total_qty "
            "FROM shipments s WHERE " + where_clause + " GROUP BY s.status ORDER BY count DESC",
            params
        ).fetchall()

    @staticmethod
    def fetch_shipment_by_customer(where_clause, params, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT s.customer, COUNT(*) as shipment_count, "
            "COALESCE(SUM(s.total_quantity),0) as total_qty "
            "FROM shipments s WHERE " + where_clause + " "
            "GROUP BY s.customer ORDER BY total_qty DESC LIMIT 50",
            params
        ).fetchall()

    @staticmethod
    def fetch_shipment_monthly_trend(where_clause, params, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT substr(s.completed_at,1,7) as month, COUNT(*) as count, "
            "COALESCE(SUM(s.total_quantity),0) as total_qty "
            "FROM shipments s WHERE " + where_clause + " "
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
        return db.execute(
            "SELECT p.product_code, p.product_name, p.model, p.spec, "
            "pr.id as process_id, pr.name as process_name, pr.seq_order, "
            "COALESCE(SUM(CASE WHEN wr.type='normal' THEN wr.quantity ELSE 0 END),0) as output "
            "FROM products p "
            "JOIN order_product_links opl ON opl.product_id=p.id "
            "JOIN orders o ON o.id=opl.order_id AND o.deleted_at IS NULL "
            "JOIN work_records wr ON wr.order_id=o.id AND " + where_clause + " "
            "JOIN processes pr ON wr.process_id=pr.id "
            "GROUP BY p.product_code, p.product_name, p.model, p.spec, pr.id, pr.name, pr.seq_order "
            "ORDER BY p.product_code, pr.seq_order, pr.name",
            params
        ).fetchall()

    # ========== model_process_stats ==========
    @staticmethod
    def fetch_model_process_stats(where_clause, params, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT p.model, pr.name as process_name, "
            "COALESCE(SUM(CASE WHEN wr.type='normal' THEN wr.quantity ELSE 0 END),0) as output, "
            "COALESCE(SUM(CASE WHEN wr.type='scrap' THEN wr.quantity ELSE 0 END),0) as scrap "
            "FROM products p "
            "JOIN order_product_links opl ON opl.product_id=p.id "
            "JOIN orders o ON o.id=opl.order_id AND o.deleted_at IS NULL "
            "JOIN work_records wr ON wr.order_id=o.id AND " + where_clause + " "
            "JOIN processes pr ON wr.process_id=pr.id "
            "GROUP BY p.model, pr.name ORDER BY output DESC",
            params
        ).fetchall()

    # ========== product_process_stats ==========
    @staticmethod
    def fetch_product_process_proc_names(where_clause, params, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT DISTINCT pr.name FROM processes pr "
            "JOIN work_records wr ON wr.process_id=pr.id "
            "JOIN orders o ON wr.order_id=o.id "
            "WHERE " + where_clause + " ORDER BY pr.name", params
        ).fetchall()

    @staticmethod
    def fetch_product_process_matrix_data(where_clause, params, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT p.product_code, p.product_name, p.model, p.spec, p.category, "
            "pr.name as process_name, "
            "COALESCE(SUM(CASE WHEN wr.type='normal' THEN wr.quantity ELSE 0 END),0) as output, "
            "COALESCE(SUM(CASE WHEN wr.type='scrap' THEN wr.quantity ELSE 0 END),0) as scrap "
            "FROM products p "
            "JOIN order_product_links opl ON opl.product_id=p.id "
            "JOIN orders o ON o.id=opl.order_id "
            "JOIN work_records wr ON wr.order_id=o.id "
            "JOIN processes pr ON wr.process_id=pr.id "
            "WHERE " + where_clause + " GROUP BY p.product_code, pr.name ORDER BY p.product_code",
            params
        ).fetchall()

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
            "COALESCE(SUM(CASE WHEN o.status='completed' THEN o.quantity ELSE 0 END),0) as completed_qty, "
            "COALESCE((SELECT COUNT(*) FROM product_items pi JOIN orders o2 ON pi.order_id=o2.id WHERE o2.deleted_at IS NULL AND pi.status='completed' AND substr(pi.completed_at,1,7)=strftime('%Y-%m','now')),0) as output "
            "FROM orders o WHERE o.deleted_at IS NULL AND substr(o.created_at,1,7)=strftime('%Y-%m','now')"
        ).fetchone()

    @staticmethod
    def fetch_monthly_summary_last(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(DISTINCT o.id) as orders, "
            "COALESCE(SUM(o.quantity),0) as total_qty, "
            "COALESCE(SUM(CASE WHEN o.status='completed' THEN o.quantity ELSE 0 END),0) as completed_qty, "
            "COALESCE((SELECT COUNT(*) FROM product_items pi JOIN orders o2 ON pi.order_id=o2.id WHERE o2.deleted_at IS NULL AND pi.status='completed' AND substr(pi.completed_at,1,7)=strftime('%Y-%m','now','-1 month')),0) as output "
            "FROM orders o WHERE o.deleted_at IS NULL AND substr(o.created_at,1,7)=strftime('%Y-%m','now','-1 month')"
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
            "SELECT COUNT(*) FROM orders WHERE deleted_at IS NULL AND status='completed' AND substr(updated_at,1,7)=strftime('%Y-%m','now')"
        ).fetchone()[0]

    @staticmethod
    def kpi_output_month(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) FROM product_items pi JOIN orders o ON pi.order_id=o.id WHERE pi.status='completed' AND o.deleted_at IS NULL AND substr(pi.completed_at,1,7)=strftime('%Y-%m','now')"
        ).fetchone()[0] or 0

    @staticmethod
    def kpi_scrap_total(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) FROM product_items pi JOIN orders o ON pi.order_id=o.id WHERE pi.status IN ('completed','scrapped') AND o.deleted_at IS NULL AND substr(pi.completed_at,1,7)=strftime('%Y-%m','now')"
        ).fetchone()[0] or 0

    @staticmethod
    def kpi_scrap_count(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) FROM product_items pi JOIN orders o ON pi.order_id=o.id WHERE pi.status='scrapped' AND o.deleted_at IS NULL AND substr(pi.completed_at,1,7)=strftime('%Y-%m','now')"
        ).fetchone()[0] or 0

    @staticmethod
    def kpi_active_workers(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(DISTINCT wr.user_id) FROM work_records wr JOIN orders o ON wr.order_id=o.id WHERE o.deleted_at IS NULL AND wr.status='approved' AND DATE(wr.created_at)=date('now')"
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
        db = resolve_db(db)
        return db.execute(
            "SELECT dates.d as date, "
            "COALESCE(COUNT(DISTINCT pi.id),0) as output "
            "FROM (WITH RECURSIVE dates(d) AS (SELECT date('now','-6 days') UNION ALL SELECT date(d,'+1 day') FROM dates WHERE d<date('now')) SELECT d FROM dates) dates "
            "LEFT JOIN product_items pi ON DATE(pi.completed_at)=dates.d AND pi.status='completed' "
            "LEFT JOIN orders o ON pi.order_id=o.id AND o.deleted_at IS NULL "
            "GROUP BY dates.d ORDER BY dates.d ASC"
        ).fetchall()
