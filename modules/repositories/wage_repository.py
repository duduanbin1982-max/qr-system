"""
qr-system — WageRepository（工资核算数据访问层）
"""
from datetime import datetime

from modules.repositories.context import resolve_db
from modules.domain.payroll_policy import (
    validate_payroll_month,
    work_amount_cents,
    yuan_to_micros,
)
from modules.domain.reporting_day import (
    REPORTING_DAY_START_HOUR,
    current_reporting_day,
    reporting_day_bounds,
    reporting_month_bounds,
)
from modules.process_fact_projection import (
    process_value_sql,
    process_version_join,
    warn_legacy_fact_rows,
)


def _estimate_amount_cents(quantity, unit_price_micros, rework_rate_basis_points):
    """Invalid/unsettleable facts contribute no money to a live estimate.

    Formal payroll keeps such facts blocking in its exception workflow.  The
    estimate must neither pay their normal rate nor let a SQLite callback turn
    invalid source data into an unhandled OperationalError.
    """
    try:
        return work_amount_cents(quantity, unit_price_micros, rework_rate_basis_points)
    except (ValueError, TypeError, OverflowError):
        return 0


def _legacy_price_micros(value):
    try:
        return yuan_to_micros(value or 0)
    except (ValueError, TypeError, OverflowError):
        return 0


class WageRepository:
    """工资核算数据访问 — 集中管理报工记录、工序汇总、工资计算相关查询。"""

    @staticmethod
    def _has_versioned_prices(db):
        return db.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='route_price_versions'"
        ).fetchone() is not None

    @classmethod
    def _price_projection(cls, db, work_alias="wr", order_alias="o"):
        """Build the canonical live-price projection used by wage estimates.

        Versioned work records must resolve against the exact route/process
        revision captured on the fact.  Once the versioned price table exists,
        unbound facts are blocked instead of falling back to root IDs.  The old
        ``route_prices`` table remains a compatibility path only when the
        versioned price table is absent.
        """
        route_expr = f"COALESCE({work_alias}.route_id,{order_alias}.route_id)"
        exact_bound = (
            f"{work_alias}.route_version_id IS NOT NULL AND "
            f"{work_alias}.process_version_id IS NOT NULL"
        )

        if cls._has_versioned_prices(db):
            exact_where = (
                "p.route_version_id={work}.route_version_id "
                "AND p.process_version_id={work}.process_version_id "
                "AND p.status='approved' "
                "AND p.valid_from<={work}.created_at "
                "AND (COALESCE(p.valid_to,'')='' OR p.valid_to>{work}.created_at)"
            ).format(work=work_alias)
            exact_exists = f"EXISTS (SELECT 1 FROM route_price_versions p WHERE {exact_where})"
            def exact_field(field):
                return (
                    f"(SELECT p.{field} FROM route_price_versions p WHERE {exact_where} "
                    "ORDER BY p.valid_from DESC,p.id DESC LIMIT 1)"
                )

            exact_micros = exact_field("normal_unit_price_micros")
            exact_value = f"({exact_micros} / 10000.0)"
            exact_id = (
                f"(SELECT p.id FROM route_price_versions p WHERE {exact_where} "
                "ORDER BY p.valid_from DESC,p.id DESC LIMIT 1)"
            )
            unit_price = (
                f"CASE WHEN {exact_bound} THEN COALESCE({exact_value},0) ELSE 0 END"
            )
            price_version_id = f"CASE WHEN {exact_bound} THEN {exact_id} ELSE NULL END"
            price_source = (
                f"CASE WHEN {exact_bound} AND {exact_exists} THEN 'versioned_exact' "
                f"WHEN {exact_bound} THEN 'missing_exact' "
                "ELSE 'missing_exact' END"
            )
            price_match_reason = (
                f"CASE WHEN {exact_bound} AND {exact_exists} AND {exact_value}=0 "
                "THEN '工价为0' "
                f"WHEN {exact_bound} AND {exact_exists} THEN '按路线版本和工序版本精确匹配' "
                f"WHEN {exact_bound} THEN '未找到对应路线版本和工序版本工价' "
                "ELSE '报工缺少路线版本和工序版本，无法精确匹配' END"
            )
            return {
                "unit_price": unit_price,
                "unit_price_micros": (
                    f"CASE WHEN {exact_bound} THEN COALESCE({exact_micros},0) ELSE 0 END"
                ),
                "rework_rate_basis_points": (
                    f"CASE WHEN {exact_bound} THEN {exact_field('rework_rate_basis_points')} "
                    "ELSE NULL END"
                ),
                "rework_rate_configured": (
                    f"CASE WHEN {exact_bound} "
                    f"THEN COALESCE({exact_field('rework_rate_configured')},0) ELSE 0 END"
                ),
                "price_version_id": price_version_id,
                "price_source": price_source,
                "price_match_reason": price_match_reason,
            }

        legacy_where = (
            f"rp.route_id={route_expr} AND rp.process_id={work_alias}.process_id "
            f"AND rp.status='active' AND rp.effective_date<=DATE({work_alias}.created_at)"
        )
        legacy_exists = f"EXISTS (SELECT 1 FROM route_prices rp WHERE {legacy_where})"
        legacy_value = (
            f"(SELECT rp.unit_price FROM route_prices rp WHERE {legacy_where} "
            "ORDER BY rp.effective_date DESC,rp.id DESC LIMIT 1)"
        )
        db.create_function("wage_legacy_price_micros", 1, _legacy_price_micros, deterministic=True)
        return {
            "unit_price": f"COALESCE({legacy_value},0)",
            "unit_price_micros": f"wage_legacy_price_micros({legacy_value})",
            "rework_rate_basis_points": "NULL",
            "rework_rate_configured": "0",
            "price_version_id": "NULL",
            "price_source": f"CASE WHEN {legacy_exists} THEN 'legacy' ELSE 'missing' END",
            "price_match_reason": (
                f"CASE WHEN {legacy_exists} AND {legacy_value}=0 THEN '工价为0' "
                f"WHEN {legacy_exists} THEN '按旧工价表匹配' ELSE '未匹配到工价' END"
            ),
        }

    @classmethod
    def _work_amount_expr(cls, db, price=None, work_alias="wr", order_alias="o"):
        """Round each fact in integer cents before any SQL aggregation."""
        db.create_function("wage_estimate_amount_cents", 3, _estimate_amount_cents, deterministic=True)
        price = price or cls._price_projection(db, work_alias, order_alias)
        rate = (
            f"CASE WHEN {work_alias}.type='rework' THEN "
            f"CASE WHEN {price['rework_rate_configured']}=1 "
            f"THEN COALESCE({price['rework_rate_basis_points']},-1) ELSE -1 END "
            "ELSE NULL END"
        )
        return (
            f"wage_estimate_amount_cents({work_alias}.quantity,"
            f"{price['unit_price_micros']},{rate})"
        )

    @classmethod
    def _unit_price_expr(cls, db=None, work_alias="wr", order_alias="o"):
        db = resolve_db(db)
        return cls._price_projection(db, work_alias, order_alias)["unit_price"]

    @staticmethod
    def get_worker_role_code(db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT COALESCE((SELECT value FROM system_settings WHERE key='worker_role_code'), 'worker')"
        ).fetchone()
        return row[0] if row else "worker"

    @staticmethod
    def get_worker_wage_summary(user_where, user_params, p1_params, p2_params, db=None):
        """按工人统计报工汇总（含工资估算）。"""
        db = resolve_db(db)
        query = ("""SELECT u.id as user_id, u.name as employee_name, u.employee_no,
            COUNT(DISTINCT DATE(wr.created_at)) as work_days,
            COUNT(wr.id) as record_count,
            COALESCE(SUM(CASE WHEN wr.type='normal' THEN wr.quantity ELSE 0 END),0) as total_output,
            COALESCE(SUM(CASE WHEN wr.type='scrap' THEN wr.quantity ELSE 0 END),0) as total_scrap,
            COALESCE(SUM(CASE WHEN wr.type='rework' THEN wr.quantity ELSE 0 END),0) as total_rework
            FROM work_records wr
            JOIN users u ON wr.user_id=u.id
            JOIN orders o ON wr.order_id=o.id
            WHERE o.deleted_at IS NULL AND o.status != 'cancelled'
        """ + user_where + """
            GROUP BY u.id
            ORDER BY total_output DESC
            LIMIT ? OFFSET ?""")
        return db.execute(query, p2_params).fetchall()

    @staticmethod
    def get_worker_paged(user_where, user_params, db=None, page=1, limit=50):
        """分页查询工人列表（含岗位名）。"""
        db = resolve_db(db)
        total = db.execute(
            "SELECT COUNT(*) FROM users u WHERE " + user_where, user_params
        ).fetchone()[0]
        rows = db.execute(
            "SELECT u.id, u.name, u.employee_no, COALESCE(pos.name, '') as position_name "
            "FROM users u LEFT JOIN positions pos ON u.position_id = pos.id "
            "WHERE " + user_where + " ORDER BY u.id LIMIT ? OFFSET ?",
            user_params + [limit, (page - 1) * limit]
        ).fetchall()
        return rows, total

    @classmethod
    def get_worker_paged_by_role(
        cls, employee_id="", db=None, page=1, limit=50,
        matching_work_where="", matching_work_params=None,
    ):
        db = resolve_db(db)
        user_where = (
            "u.status = 'active' "
            "AND u.id IN ("
            "SELECT ur.user_id FROM user_roles ur "
            "JOIN roles r ON ur.role_id = r.id "
            "WHERE r.code = ? AND r.status = 'active')"
        )
        user_params = [cls.get_worker_role_code(db)]
        if employee_id:
            user_where += " AND u.id = ?"
            user_params.append(employee_id)
        if matching_work_where:
            user_where += (
                " AND COALESCE((SELECT SUM(wr.quantity) FROM work_records wr "
                "WHERE wr.user_id=u.id AND " + matching_work_where + "),0)>0"
            )
            user_params.extend(matching_work_params or [])
        return cls.get_worker_paged(user_where, user_params, db, page, limit)

    @classmethod
    def get_wage_rows_for_workers(cls, wr_where, wr_params, user_ids, db=None):
        db = resolve_db(db)
        if not user_ids:
            return []
        placeholders = ",".join(["?" for _ in user_ids])
        price = cls._price_projection(db)
        process_name = process_value_sql("wr", "process_version", "p")
        query = (
            """SELECT u.id as user_id, u.name as employee_name, u.employee_no,
                   wr.quantity, wr.type as work_type,wr.created_at, wr.id as wr_id,wr.process_id,
                   wr.process_version_id,"""
            + process_name
            + """ as process_name,
                   o.order_no, o.product_name, o.product_code as order_product_code,
                   """
            + price["unit_price"]
            + " as unit_price, "
            + price["unit_price_micros"]
            + " as unit_price_micros, "
            + price["rework_rate_basis_points"]
            + " as rework_rate_basis_points, "
            + price["rework_rate_configured"]
            + " as rework_rate_configured, "
            + price["price_version_id"]
            + " as price_version_id, "
            + price["price_source"]
            + " as price_source, "
            + price["price_match_reason"]
            + " as price_match_reason"
            + """
            FROM users u
            LEFT JOIN work_records wr ON u.id = wr.user_id AND """
            + wr_where
            + """
            LEFT JOIN processes p ON wr.process_id = p.id
            """
            + process_version_join("wr", "process_version")
            + """
            LEFT JOIN orders o ON wr.order_id = o.id
            """
            + """
            WHERE u.id IN ("""
            + placeholders
            + """)
            ORDER BY u.id"""
        )
        rows = db.execute(query, wr_params + user_ids).fetchall()
        warn_legacy_fact_rows("work_records", rows)
        return rows

    @classmethod
    def get_daily_report_rows(cls, date, db=None):
        db = resolve_db(db)
        period_start, period_end = reporting_day_bounds(date)
        price = cls._price_projection(db)
        process_name = process_value_sql("wr", "process_version", "p")
        query = (
            """
            SELECT wr.*, u.name as employee_name, u.employee_no,"""
            + process_name
            + """ as process_name,
                   """
            + price["unit_price"]
            + " as unit_price, "
            + price["price_version_id"]
            + " as price_version_id, "
            + price["price_source"]
            + " as price_source, "
            + price["price_match_reason"]
            + " as price_match_reason"
            + """
            FROM work_records wr
            LEFT JOIN users u ON wr.user_id = u.id
            LEFT JOIN processes p ON wr.process_id = p.id
            """
            + process_version_join("wr", "process_version")
            + """
            LEFT JOIN orders o ON wr.order_id = o.id
            """
            + """
            WHERE wr.status = 'approved' AND wr.type = 'normal'
            AND wr.created_at >= ? AND wr.created_at < ?
            ORDER BY wr.user_id, wr.process_id
            """
        )
        rows = db.execute(query, (period_start, period_end)).fetchall()
        warn_legacy_fact_rows("work_records", rows)
        return rows

    @staticmethod
    def count_active_orders(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) FROM orders WHERE deleted_at IS NULL AND status != 'cancelled'"
        ).fetchone()[0]

    @staticmethod
    def get_production_orders(page=1, limit=50, db=None):
        db = resolve_db(db)
        return db.execute(
            """
            SELECT o.*, COALESCE(o.completed, 0) as done_qty,
                   (SELECT COUNT(*) FROM product_items pi WHERE pi.order_id = o.id AND pi.status = 'completed') as actual_completed
            FROM orders o
            WHERE o.deleted_at IS NULL AND o.status != 'cancelled'
            ORDER BY o.created_at DESC LIMIT ? OFFSET ?
            """,
            (limit, (page - 1) * limit),
        ).fetchall()

    @staticmethod
    def get_production_processes(order_id, db=None):
        db = resolve_db(db)
        return db.execute(
            """
            SELECT op.order_id, op.process_id,
                   COALESCE(NULLIF(op.process_name_snapshot,''),version.name,p.name,'') as process_name,
                   op.completed,
                   (SELECT COUNT(*) FROM product_items pi WHERE pi.order_id = op.order_id) as total_items,
                   op.required_audit,
                   COALESCE((
                       SELECT SUM(wr.quantity)
                       FROM work_records wr
                       WHERE wr.order_id = op.order_id
                         AND wr.process_id = op.process_id
                         AND wr.type = 'scrap'
                         AND wr.status = 'approved'
                   ), 0) as scrapped
            FROM order_processes op
            JOIN processes p ON op.process_id = p.id
            LEFT JOIN process_versions version ON version.id=op.process_version_id
            WHERE op.order_id = ? ORDER BY op.seq_order
            """,
            (order_id,),
        ).fetchall()

    @classmethod
    def get_monthly_summary(cls, year_month, page=1, limit=100, db=None):
        db = resolve_db(db)
        month_start, month_end = reporting_month_bounds(validate_payroll_month(year_month))
        amount_cents = cls._work_amount_expr(db)
        rows = db.execute(
            """
            SELECT wr.user_id, u.name as employee_name, u.employee_no,
                   SUM(wr.quantity) as total_quantity,
                   SUM("""
            + amount_cents
            + """) / 100.0 as total_wage
            FROM work_records wr
            JOIN users u ON wr.user_id = u.id
            LEFT JOIN orders o ON wr.order_id = o.id
            WHERE wr.status = 'approved' AND wr.type = 'normal'
              AND wr.created_at >= ? AND wr.created_at < ?
            GROUP BY wr.user_id
            ORDER BY total_wage DESC
            LIMIT ? OFFSET ?
            """,
            (month_start, month_end, limit, (page - 1) * limit),
        ).fetchall()
        total_count = db.execute(
            """
            SELECT COUNT(DISTINCT wr.user_id) FROM work_records wr
            WHERE wr.status = 'approved' AND wr.type = 'normal'
              AND wr.created_at >= ? AND wr.created_at < ?
            """,
            (month_start, month_end),
        ).fetchone()[0]
        grand_total = db.execute(
            """
            SELECT COALESCE(SUM(wr.quantity),0) as total_qty,
                   COALESCE(SUM("""
            + amount_cents
            + """),0) / 100.0 as total_wage
            FROM work_records wr
            LEFT JOIN orders o ON wr.order_id = o.id
            WHERE wr.status = 'approved' AND wr.type = 'normal'
              AND wr.created_at >= ? AND wr.created_at < ?
            """,
            (month_start, month_end),
        ).fetchone()
        return rows, total_count, grand_total

    @classmethod
    def get_process_wage_summary(cls, year_month, db=None):
        db = resolve_db(db)
        month_start, month_end = reporting_month_bounds(validate_payroll_month(year_month))
        amount_cents = cls._work_amount_expr(db)
        process_name = process_value_sql("wr", "process_version", "p")
        process_category = process_value_sql(
            "wr", "process_version", "p", field="category"
        )
        rows = db.execute(
            """
            SELECT wr.process_id,wr.process_version_id,"""
            + process_name
            + """ as process_name,"""
            + process_category
            + """ as category,
                   SUM(wr.quantity) as total_quantity,
                   SUM("""
            + amount_cents
            + """) / 100.0 as total_wage,
                   COUNT(DISTINCT wr.user_id) as worker_count
            FROM work_records wr
            JOIN processes p ON wr.process_id = p.id
            """
            + process_version_join("wr", "process_version")
            + """
            LEFT JOIN orders o ON wr.order_id = o.id
            WHERE wr.status = 'approved' AND wr.type = 'normal'
              AND wr.created_at >= ? AND wr.created_at < ?
            GROUP BY wr.process_id,wr.process_version_id,"""
            + process_name
            + ","
            + process_category
            + """
            ORDER BY total_wage DESC
            """,
            (month_start, month_end),
        ).fetchall()
        warn_legacy_fact_rows("work_records", rows)
        return rows

    @staticmethod
    def upsert_snapshot(employee, year_month, details_json, db=None):
        db = resolve_db(db)
        db.execute(
            "INSERT INTO wage_snapshots (employee_id,employee_name,employee_no,year_month,total_quantity,total_wage,rework_wage,details_json,status,updated_at) VALUES (?,?,?,?,?,?,?,?,'draft',datetime('now','localtime')) ON CONFLICT(employee_id,year_month) DO UPDATE SET total_quantity=excluded.total_quantity,total_wage=excluded.total_wage,rework_wage=excluded.rework_wage,details_json=excluded.details_json,updated_at=datetime('now','localtime')",
            (
                employee.get("employee_id", 0),
                employee.get("employee_name", ""),
                employee.get("employee_no", ""),
                year_month,
                employee.get("total_quantity", 0),
                employee.get("total_wage", 0),
                employee.get("rework_wage", 0),
                details_json,
            ),
        )

    @staticmethod
    def lock_snapshots(year_month, locked_by="system", notes="", db=None):
        db = resolve_db(db)
        db.execute(
            "UPDATE wage_snapshots SET status='locked',locked_at=datetime('now','localtime'),locked_by=?,notes=? WHERE year_month=? AND status='draft'",
            (locked_by, notes, year_month),
        )
        return db.execute("SELECT changes()").fetchone()[0]

    @staticmethod
    def list_snapshots(year_month, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM wage_snapshots WHERE year_month=? ORDER BY total_wage DESC",
            (year_month,),
        ).fetchall()

    @staticmethod
    def confirm_snapshots(year_month, confirmed_by="system", db=None):
        db = resolve_db(db)
        db.execute(
            "UPDATE wage_snapshots SET status='confirmed',confirmed_at=datetime('now','localtime'),confirmed_by=? WHERE year_month=? AND status IN ('draft','locked')",
            (confirmed_by, year_month),
        )
        return db.execute("SELECT changes()").fetchone()[0]

    @staticmethod
    def get_snapshot_status_rows(year_month, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT status, COUNT(*) as cnt, SUM(total_wage) as total_wage FROM wage_snapshots WHERE year_month=? GROUP BY status",
            (year_month,),
        ).fetchall()

    @staticmethod
    def list_adjustments(user_id=None, year_month=None, db=None):
        db = resolve_db(db)
        where = []
        params = []
        if user_id:
            where.append("user_id=?")
            params.append(user_id)
        if year_month:
            where.append("year_month=?")
            params.append(year_month)
        sql = "SELECT a.*, u.name as employee_name FROM wage_adjustments a LEFT JOIN users u ON a.user_id=u.id"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY a.created_at DESC"
        return db.execute(sql, params).fetchall()

    @staticmethod
    def find_adjustment_id(user_id, year_month, adj_type, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id FROM wage_adjustments WHERE user_id=? AND year_month=? AND type=?",
            (user_id, year_month, adj_type),
        ).fetchone()

    @staticmethod
    def update_adjustment(adj_id, amount, reason, created_by, db=None):
        db = resolve_db(db)
        db.execute(
            "UPDATE wage_adjustments SET amount=?, reason=?, created_by=? WHERE id=?",
            (amount, reason or "", created_by, adj_id),
        )

    @staticmethod
    def insert_adjustment(user_id, year_month, adj_type, amount, reason, created_by, db=None):
        db = resolve_db(db)
        db.execute(
            "INSERT INTO wage_adjustments (user_id, year_month, type, amount, reason, created_by) VALUES (?,?,?,?,?,?)",
            (user_id, year_month, adj_type, amount, reason or "", created_by),
        )
        return db.execute("SELECT last_insert_rowid()").fetchone()[0]

    @staticmethod
    def delete_adjustment(adj_id, db=None):
        db = resolve_db(db)
        db.execute("DELETE FROM wage_adjustments WHERE id=?", (adj_id,))
        return db.total_changes

    @staticmethod
    def get_adjustments_total_rows(user_id, year_month, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT type, SUM(amount) as total FROM wage_adjustments WHERE user_id=? AND year_month=? GROUP BY type",
            (user_id, year_month),
        ).fetchall()

    @staticmethod
    def get_wage_trend_snapshots(months=12, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT year_month, SUM(total_wage) as total_wage, SUM(total_quantity) as total_quantity, COUNT(DISTINCT employee_id) as employee_count FROM wage_snapshots WHERE status IN ('draft','locked','confirmed') GROUP BY year_month ORDER BY year_month DESC LIMIT ?",
            (months,),
        ).fetchall()

    @classmethod
    def get_live_wage_trends(cls, months=12, db=None):
        db = resolve_db(db)
        months = max(1, int(months))
        current = datetime.strptime(current_reporting_day(), "%Y-%m-%d")
        month_index = current.year * 12 + current.month - months
        month_start, _ = reporting_month_bounds(f"{month_index // 12:04d}-{month_index % 12 + 1:02d}")
        _, month_end = reporting_month_bounds(current.strftime("%Y-%m"))
        amount_cents = cls._work_amount_expr(db)
        reporting_month = (
            f"strftime('%Y-%m',wr.created_at,'-{REPORTING_DAY_START_HOUR} hours')"
        )
        return db.execute(
            "SELECT " + reporting_month + " as year_month, "
            "COALESCE(SUM(wr.quantity),0) as total_quantity, "
            "COALESCE(SUM(" + amount_cents + "),0) / 100.0 as total_wage, "
            "COUNT(DISTINCT wr.user_id) as employee_count "
            "FROM work_records wr "
            "LEFT JOIN orders o ON wr.order_id = o.id "
            + " "
            "WHERE wr.status = 'approved' AND wr.type = 'normal' "
            "AND wr.created_at >= ? AND wr.created_at < ? "
            "GROUP BY " + reporting_month + " "
            "ORDER BY year_month ASC",
            (month_start, month_end),
        ).fetchall()

    @classmethod
    def get_position_summary(cls, year_month, db=None):
        db = resolve_db(db)
        month_start, month_end = reporting_month_bounds(validate_payroll_month(year_month))
        amount_cents = cls._work_amount_expr(db)
        return db.execute(
            "SELECT COALESCE(pos.name, '未分配') as position_name, COUNT(DISTINCT wr.user_id) as employee_count, "
            "SUM(wr.quantity) as total_quantity, SUM("
            + amount_cents
            + ") / 100.0 as total_wage FROM work_records wr "
            "JOIN users u ON wr.user_id = u.id "
            "LEFT JOIN positions pos ON u.position_id = pos.id "
            "LEFT JOIN orders o ON wr.order_id = o.id AND o.deleted_at IS NULL "
            + " WHERE wr.status = 'approved' AND wr.type = 'normal' "
            "AND wr.created_at >= ? AND wr.created_at < ? "
            "GROUP BY pos.name ORDER BY total_wage DESC",
            (month_start, month_end),
        ).fetchall()

    @staticmethod
    def get_order_wages(start, end, db=None):
        """按订单统计工资汇总。"""
        db = resolve_db(db)
        date_filter = ""
        params = []
        if start:
            date_filter += " AND DATE(o.created_at) >= ?"
            params.append(start)
        if end:
            date_filter += " AND DATE(o.created_at) <= ?"
            params.append(end)
        rows = db.execute(
            """SELECT o.*, COALESCE(o.completed, 0) as done_qty,
               (SELECT COUNT(*) FROM product_items pi WHERE pi.order_id=o.id AND pi.status='completed') as actual_completed
               FROM orders o
               WHERE o.deleted_at IS NULL AND o.status != 'cancelled'""" + date_filter + """
               ORDER BY o.created_at DESC LIMIT 100""",
            params
        ).fetchall()
        return rows

    @staticmethod
    def get_process_breakdown(order_id, db=None):
        """获取订单工序完成情况。"""
        db = resolve_db(db)
        return db.execute(
            """SELECT op.order_id, op.process_id,
               COALESCE(NULLIF(op.process_name_snapshot,''),version.name,p.name,'') as process_name,
               op.completed,
               (SELECT COUNT(*) FROM product_items pi WHERE pi.order_id=op.order_id) as total_items
               FROM order_processes op
               JOIN processes p ON op.process_id=p.id
               LEFT JOIN process_versions version ON version.id=op.process_version_id
               WHERE op.order_id = ? ORDER BY op.seq_order""",
            (order_id,)
        ).fetchall()

    @staticmethod
    def get_daily_summary(start, end, db=None):
        """日报工汇总。"""
        db = resolve_db(db)
        date_filter = ""
        params = []
        if start:
            date_filter += " AND DATE(wr.created_at) >= ?"
            params.append(start)
        if end:
            date_filter += " AND DATE(wr.created_at) <= ?"
            params.append(end)
        return db.execute(
            """SELECT wr.user_id, u.name as employee_name, u.employee_no,
               COALESCE(SUM(CASE WHEN wr.type='normal' THEN wr.quantity ELSE 0 END),0) as total_output
               FROM work_records wr
               JOIN users u ON wr.user_id=u.id
               JOIN orders o ON wr.order_id=o.id
               WHERE o.deleted_at IS NULL""" + date_filter + """
               GROUP BY wr.user_id ORDER BY total_output DESC""",
            params
        ).fetchall()

    @staticmethod
    def get_process_summary(start, end, db=None):
        """按工序统计报工汇总。"""
        db = resolve_db(db)
        date_filter = ""
        params = []
        if start:
            date_filter += " AND DATE(wr.created_at) >= ?"
            params.append(start)
        if end:
            date_filter += " AND DATE(wr.created_at) <= ?"
            params.append(end)
        process_name = process_value_sql("wr", "process_version", "p")
        process_category = process_value_sql(
            "wr", "process_version", "p", field="category"
        )
        rows = db.execute(
            """SELECT wr.process_id,wr.process_version_id,"""
            + process_name
            + """ as process_name,"""
            + process_category
            + """ as category,
               COALESCE(SUM(CASE WHEN wr.type='normal' THEN wr.quantity ELSE 0 END),0) as total_output,
               COUNT(DISTINCT wr.user_id) as worker_count
               FROM work_records wr
               JOIN processes p ON wr.process_id=p.id
               """
            + process_version_join("wr", "process_version")
            + """
               JOIN orders o ON wr.order_id=o.id
               WHERE o.deleted_at IS NULL""" + date_filter + """
               GROUP BY wr.process_id,wr.process_version_id,"""
            + process_name
            + ","
            + process_category
            + " ORDER BY total_output DESC",
            params
        ).fetchall()
        warn_legacy_fact_rows("work_records", rows)
        return rows
