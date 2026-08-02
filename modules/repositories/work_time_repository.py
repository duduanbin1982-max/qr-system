"""Work time management data access."""

from modules.repositories.context import resolve_db
from modules.domain.reporting_day import reporting_day_bounds


class WorkTimeRepository:
    @staticmethod
    def _pagination(page, per_page):
        page = max(int(page or 1), 1)
        per_page = min(max(int(per_page or 20), 1), 200)
        return page, per_page, (page - 1) * per_page

    @staticmethod
    def find_product(product_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id, product_code, product_name FROM products WHERE id = ?",
            (product_id,),
        ).fetchone()

    @staticmethod
    def find_process(process_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id, name FROM processes WHERE id = ?",
            (process_id,),
        ).fetchone()

    @staticmethod
    def find_route(route_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id, name, category FROM process_routes WHERE id = ?",
            (route_id,),
        ).fetchone()

    @staticmethod
    def find_route_process(route_id, process_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT pri.*, p.name AS process_name "
            "FROM process_route_items pri "
            "JOIN processes p ON pri.process_id = p.id "
            "WHERE pri.route_id = ? AND pri.process_id = ?",
            (route_id, process_id),
        ).fetchone()

    @staticmethod
    def list_route_processes(route_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT pri.route_id, pri.process_id, pri.seq_order, p.name AS process_name "
            "FROM process_route_items pri "
            "JOIN processes p ON pri.process_id = p.id "
            "WHERE pri.route_id = ? "
            "ORDER BY pri.seq_order ASC, pri.id ASC",
            (route_id,),
        ).fetchall()

    @staticmethod
    def find_active_standard_for_route_process(route_id, process_id, exclude_id=None, db=None):
        db = resolve_db(db)
        params = [route_id, process_id]
        where = "route_id = ? AND process_id = ? AND status = 'active'"
        if exclude_id:
            where += " AND id != ?"
            params.append(exclude_id)
        return db.execute(
            "SELECT id FROM work_time_standards WHERE " + where + " LIMIT 1",
            params,
        ).fetchone()

    @staticmethod
    def find_user(user_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id, name FROM users WHERE id = ? AND deleted_at IS NULL",
            (user_id,),
        ).fetchone()

    @staticmethod
    def find_order(order_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT o.id, o.order_no, o.product_code, o.product_name, o.route_id, "
            "COALESCE(r.name, '') AS route_name "
            "FROM orders o "
            "LEFT JOIN process_routes r ON o.route_id = r.id "
            "WHERE o.id = ? AND o.deleted_at IS NULL",
            (order_id,),
        ).fetchone()

    @staticmethod
    def find_order_process(order_id, process_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT op.*, p.name AS process_name "
            "FROM order_processes op "
            "JOIN processes p ON op.process_id = p.id "
            "WHERE op.order_id = ? AND op.process_id = ?",
            (order_id, process_id),
        ).fetchone()

    @staticmethod
    def find_standard(standard_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM work_time_standards WHERE id = ?",
            (standard_id,),
        ).fetchone()

    @staticmethod
    def find_best_standard(product_id=None, product_code="", route_id=None, process_id=None, db=None):
        db = resolve_db(db)
        where = ["process_id = ?", "status = 'active'"]
        params = [process_id]
        if route_id:
            where.append("route_id = ?")
            params.append(route_id)
        elif product_id:
            where.append("(product_id = ? OR product_id IS NULL)")
            params.append(product_id)
        elif product_code:
            where.append("(product_code = ? OR product_code = '')")
            params.append(product_code)
        where_clause = " AND ".join(where)
        return db.execute(
            "SELECT * FROM work_time_standards WHERE " + where_clause + " "
            "ORDER BY "
            "CASE WHEN route_id IS NOT NULL THEN 0 ELSE 1 END, "
            "CASE WHEN product_id IS NOT NULL THEN 0 ELSE 1 END, "
            "effective_from DESC, id DESC LIMIT 1",
            params,
        ).fetchone()

    @staticmethod
    def list_standards(filters, page=1, per_page=20, db=None):
        db = resolve_db(db)
        page, per_page, offset = WorkTimeRepository._pagination(page, per_page)
        where = []
        params = []
        keyword = (filters.get("keyword") or "").strip()
        if keyword:
            like = f"%{keyword}%"
            where.append(
                "(pr.name LIKE ? OR r.name LIKE ?)"
            )
            params.extend([like, like])
        if filters.get("status"):
            where.append("w.status = ?")
            params.append(filters["status"])
        if filters.get("process_id"):
            where.append("w.process_id = ?")
            params.append(filters["process_id"])
        if filters.get("route_id"):
            where.append("w.route_id = ?")
            params.append(filters["route_id"])
        where_clause = (" WHERE " + " AND ".join(where)) if where else ""
        total = db.execute(
            "SELECT COUNT(*) FROM work_time_standards w "
            "LEFT JOIN processes pr ON w.process_id = pr.id "
            "LEFT JOIN process_routes r ON w.route_id = r.id "
            "LEFT JOIN process_route_items pri ON pri.route_id = w.route_id AND pri.process_id = w.process_id "
            + where_clause,
            params,
        ).fetchone()[0]
        rows = db.execute(
            "SELECT w.*, "
            "pr.name AS process_name, r.name AS route_name, pri.seq_order AS route_seq_order, "
            "creator.name AS created_by_name, updater.name AS updated_by_name "
            "FROM work_time_standards w "
            "LEFT JOIN processes pr ON w.process_id = pr.id "
            "LEFT JOIN process_routes r ON w.route_id = r.id "
            "LEFT JOIN process_route_items pri ON pri.route_id = w.route_id AND pri.process_id = w.process_id "
            "LEFT JOIN users creator ON w.created_by = creator.id "
            "LEFT JOIN users updater ON w.updated_by = updater.id " + where_clause + " "
            "ORDER BY r.name ASC, COALESCE(pri.seq_order, 9999) ASC, w.status ASC, w.id DESC "
            "LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total, "page": page, "per_page": per_page}

    @staticmethod
    def list_standard_routes(filters, page=1, per_page=20, db=None):
        db = resolve_db(db)
        page, per_page, offset = WorkTimeRepository._pagination(page, per_page)
        route_where = [
            "EXISTS (SELECT 1 FROM process_route_items pri_exists WHERE pri_exists.route_id = r.id)"
        ]
        route_params = []
        keyword = (filters.get("keyword") or "").strip()
        if keyword:
            like = f"%{keyword}%"
            route_where.append(
                "(r.name LIKE ? OR EXISTS ("
                "SELECT 1 FROM process_route_items pri_kw "
                "JOIN processes p_kw ON p_kw.id = pri_kw.process_id "
                "WHERE pri_kw.route_id = r.id AND p_kw.name LIKE ?"
                "))"
            )
            route_params.extend([like, like])
        if filters.get("route_id"):
            route_where.append("r.id = ?")
            route_params.append(filters["route_id"])
        if filters.get("process_id"):
            route_where.append(
                "EXISTS (SELECT 1 FROM process_route_items pri_proc "
                "WHERE pri_proc.route_id = r.id AND pri_proc.process_id = ?)"
            )
            route_params.append(filters["process_id"])
        if filters.get("status"):
            route_where.append(
                "EXISTS (SELECT 1 FROM work_time_standards w_status "
                "WHERE w_status.route_id = r.id AND w_status.status = ?)"
            )
            route_params.append(filters["status"])
        route_clause = " WHERE " + " AND ".join(route_where)
        total = db.execute(
            "SELECT COUNT(*) FROM process_routes r" + route_clause,
            route_params,
        ).fetchone()[0]
        routes = db.execute(
            "SELECT r.id, r.name, r.category, r.description "
            "FROM process_routes r" + route_clause + " "
            "ORDER BY r.name COLLATE NOCASE ASC, r.id ASC LIMIT ? OFFSET ?",
            route_params + [per_page, offset],
        ).fetchall()
        route_ids = [row["id"] for row in routes]
        if not route_ids:
            return {"route_groups": [], "items": [], "total": total, "page": page, "per_page": per_page}

        placeholders = ",".join("?" for _ in route_ids)
        status = (filters.get("status") or "").strip()
        sub_status_clause = ""
        params = []
        if status:
            sub_status_clause = " AND w2.status = ?"
            params.append(status)
        params.extend(route_ids)
        item_where = [f"pri.route_id IN ({placeholders})"]
        if filters.get("process_id"):
            item_where.append("pri.process_id = ?")
            params.append(filters["process_id"])
        if status:
            item_where.append("w.id IS NOT NULL")
        item_clause = " WHERE " + " AND ".join(item_where)
        rows = db.execute(
            "SELECT pri.route_id, r.name AS route_name, pri.process_id, "
            "pri.seq_order AS route_seq_order, p.name AS process_name, "
            "w.id, w.product_id, w.product_code, w.product_name, "
            "w.standard_minutes_per_unit, w.setup_minutes, w.difficulty_factor, "
            "w.effective_from, w.effective_to, w.status, w.version, w.remark, "
            "w.created_by, w.updated_by, w.created_at, w.updated_at, "
            "creator.name AS created_by_name, updater.name AS updated_by_name "
            "FROM process_route_items pri "
            "JOIN process_routes r ON r.id = pri.route_id "
            "JOIN processes p ON p.id = pri.process_id "
            "LEFT JOIN work_time_standards w ON w.id = ("
            "SELECT w2.id FROM work_time_standards w2 "
            "WHERE w2.route_id = pri.route_id AND w2.process_id = pri.process_id"
            + sub_status_clause +
            " ORDER BY CASE WHEN w2.status = 'active' THEN 0 ELSE 1 END, "
            "w2.updated_at DESC, w2.id DESC LIMIT 1) "
            "LEFT JOIN users creator ON w.created_by = creator.id "
            "LEFT JOIN users updater ON w.updated_by = updater.id "
            + item_clause + " "
            "ORDER BY r.name COLLATE NOCASE ASC, r.id ASC, pri.seq_order ASC, pri.id ASC",
            params,
        ).fetchall()
        route_lookup = {row["id"]: dict(row) for row in routes}
        item_rows = [dict(row) for row in rows]
        items_by_route = {}
        for item in item_rows:
            items_by_route.setdefault(item["route_id"], []).append(item)
        groups = []
        for route in routes:
            route_items = items_by_route.get(route["id"], [])
            groups.append({
                "route_id": route["id"],
                "route_name": route["name"],
                "category": route["category"],
                "description": route["description"],
                "items": route_items,
                "process_count": len(route_items),
                "configured_count": sum(1 for item in route_items if item.get("id")),
                "active_count": sum(1 for item in route_items if item.get("status") == "active"),
            })
        return {"route_groups": groups, "items": item_rows, "total": total, "page": page, "per_page": per_page}

    @staticmethod
    def insert_standard(data, db):
        cur = db.execute(
            "INSERT INTO work_time_standards ("
            "product_id, product_code, product_name, route_id, process_id, "
            "standard_minutes_per_unit, setup_minutes, difficulty_factor, "
            "effective_from, effective_to, status, version, remark, created_by, updated_by"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                data.get("product_id"), data.get("product_code", ""), data.get("product_name", ""),
                data.get("route_id"), data["process_id"], data["standard_minutes_per_unit"],
                data.get("setup_minutes", 0), data.get("difficulty_factor", 1),
                data.get("effective_from", ""), data.get("effective_to", ""),
                data.get("status", "active"), data.get("version", 1), data.get("remark", ""),
                data.get("created_by"), data.get("updated_by"),
            ),
        )
        return cur.lastrowid

    @staticmethod
    def update_standard(standard_id, data, db):
        db.execute(
            "UPDATE work_time_standards SET "
            "product_id=?, product_code=?, product_name=?, route_id=?, process_id=?, "
            "standard_minutes_per_unit=?, setup_minutes=?, difficulty_factor=?, "
            "effective_from=?, effective_to=?, status=?, version=?, remark=?, updated_by=?, "
            "updated_at=datetime('now','localtime') WHERE id=?",
            (
                data.get("product_id"), data.get("product_code", ""), data.get("product_name", ""),
                data.get("route_id"), data["process_id"], data["standard_minutes_per_unit"],
                data.get("setup_minutes", 0), data.get("difficulty_factor", 1),
                data.get("effective_from", ""), data.get("effective_to", ""),
                data.get("status", "active"), data.get("version", 1), data.get("remark", ""),
                data.get("updated_by"), standard_id,
            ),
        )

    @staticmethod
    def deactivate_standard(standard_id, user_id, db):
        db.execute(
            "UPDATE work_time_standards SET status='inactive', updated_by=?, "
            "updated_at=datetime('now','localtime') WHERE id=?",
            (user_id, standard_id),
        )

    @staticmethod
    def list_records(filters, page=1, per_page=20, db=None):
        db = resolve_db(db)
        page, per_page, offset = WorkTimeRepository._pagination(page, per_page)
        where = []
        params = []
        keyword = (filters.get("keyword") or "").strip()
        if keyword:
            like = f"%{keyword}%"
            where.append(
                "(wr.order_no LIKE ? OR o.order_no LIKE ? OR wr.serial_no LIKE ? "
                "OR wr.product_code LIKE ? OR wr.product_name LIKE ? OR o.product_code LIKE ? OR o.product_name LIKE ? "
                "OR wr.route_name LIKE ? OR r.name LIKE ? "
                "OR wr.user_name LIKE ? OR u.name LIKE ? OR wr.process_name LIKE ? OR p.name LIKE ?)"
            )
            params.extend([like, like, like, like, like, like, like, like, like, like, like, like, like])
        for key in ("status", "review_status"):
            if filters.get(key):
                where.append(f"wr.{key} = ?")
                params.append(filters[key])
        if filters.get("user_id"):
            where.append("wr.user_id = ?")
            params.append(filters["user_id"])
        if filters.get("process_id"):
            where.append("wr.process_id = ?")
            params.append(filters["process_id"])
        if filters.get("order_id"):
            where.append("wr.order_id = ?")
            params.append(filters["order_id"])
        if filters.get("route_id"):
            where.append("wr.route_id = ?")
            params.append(filters["route_id"])
        if filters.get("standard_missing") not in (None, ""):
            where.append("wr.standard_missing = ?")
            params.append(1 if str(filters["standard_missing"]) in {"1", "true", "True"} else 0)
        if filters.get("date_from"):
            where.append("substr(wr.start_time, 1, 10) >= ?")
            params.append(filters["date_from"])
        if filters.get("date_to"):
            where.append("substr(wr.start_time, 1, 10) <= ?")
            params.append(filters["date_to"])
        where_clause = (" WHERE " + " AND ".join(where)) if where else ""
        total = db.execute(
            "SELECT COUNT(*) FROM work_time_records wr "
            "LEFT JOIN orders o ON wr.order_id = o.id "
            "LEFT JOIN process_routes r ON wr.route_id = r.id "
            "LEFT JOIN users u ON wr.user_id = u.id "
            "LEFT JOIN processes p ON wr.process_id = p.id" + where_clause,
            params,
        ).fetchone()[0]
        rows = db.execute(
            "SELECT wr.*, COALESCE(o.order_no, wr.order_no, '') AS order_no_display, "
            "COALESCE(wr.product_code, o.product_code, '') AS product_code_display, "
            "COALESCE(wr.product_name, o.product_name, '') AS product_name_display, "
            "COALESCE(wr.route_name, r.name, '') AS route_name_display, "
            "COALESCE(u.name, wr.user_name, '') AS user_name_display, "
            "COALESCE(p.name, wr.process_name, '') AS process_name_display, "
            "reviewer.name AS reviewer_name "
            "FROM work_time_records wr "
            "LEFT JOIN orders o ON wr.order_id = o.id "
            "LEFT JOIN process_routes r ON wr.route_id = r.id "
            "LEFT JOIN users u ON wr.user_id = u.id "
            "LEFT JOIN processes p ON wr.process_id = p.id "
            "LEFT JOIN users reviewer ON wr.reviewed_by = reviewer.id" + where_clause + " "
            "ORDER BY wr.start_time DESC, wr.id DESC LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total, "page": page, "per_page": per_page}

    @staticmethod
    def find_record(record_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM work_time_records WHERE id = ?",
            (record_id,),
        ).fetchone()

    @staticmethod
    def insert_record(data, db):
        cur = db.execute(
            "INSERT INTO work_time_records ("
            "order_id, order_no, serial_no, route_id, route_name, product_code, product_name, standard_missing, "
            "process_id, process_name, user_id, user_name, standard_id, source_work_record_id, "
            "quantity, standard_minutes, start_time, end_time, pause_minutes, actual_minutes, "
            "effective_minutes, status, abnormal_reason, review_status, reviewed_by, reviewed_at, review_note, created_by"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                data.get("order_id"), data.get("order_no", ""), data.get("serial_no", ""),
                data.get("route_id"), data.get("route_name", ""), data.get("product_code", ""),
                data.get("product_name", ""), data.get("standard_missing", 0),
                data["process_id"], data.get("process_name", ""), data["user_id"], data.get("user_name", ""),
                data.get("standard_id"), data.get("source_work_record_id"), data.get("quantity", 1),
                data.get("standard_minutes", 0), data.get("start_time", ""), data.get("end_time", ""),
                data.get("pause_minutes", 0), data.get("actual_minutes", 0),
                data.get("effective_minutes", 0), data.get("status", "completed"),
                data.get("abnormal_reason", ""), data.get("review_status", "approved"),
                data.get("reviewed_by"), data.get("reviewed_at", ""), data.get("review_note", ""),
                data.get("created_by"),
            ),
        )
        return cur.lastrowid

    @staticmethod
    def review_record(record_id, data, db):
        db.execute(
            "UPDATE work_time_records SET effective_minutes=?, status=?, review_status=?, "
            "abnormal_reason=?, reviewed_by=?, reviewed_at=datetime('now','localtime'), "
            "review_note=?, updated_at=datetime('now','localtime') WHERE id=?",
            (
                data["effective_minutes"], data["status"], data["review_status"],
                data.get("abnormal_reason", ""), data["reviewed_by"],
                data.get("review_note", ""), record_id,
            ),
        )

    @staticmethod
    def insert_review_log(record_id, old_effective, new_effective, old_status, new_status, reason, reviewer_id, db):
        db.execute(
            "INSERT INTO work_time_review_logs ("
            "record_id, old_effective_minutes, new_effective_minutes, "
            "old_review_status, new_review_status, reason, reviewer_id"
            ") VALUES (?,?,?,?,?,?,?)",
            (record_id, old_effective, new_effective, old_status, new_status, reason, reviewer_id),
        )

    @staticmethod
    def daily_summary(date, product_code='', db=None):
        db = resolve_db(db)
        period_start, period_end = reporting_day_bounds(date)
        record_time = "COALESCE(NULLIF(wr.end_time, ''), NULLIF(wr.start_time, ''), wr.created_at)"
        where = [
            "wr.review_status = 'approved'",
            record_time + " >= ?",
            record_time + " < ?",
        ]
        params = [period_start, period_end]
        product_code = (product_code or '').strip()
        if product_code:
            where.append(
                "(wr.product_code = ? OR o.product_code = ? OR "
                "opl.product_id = "
                "(SELECT a.product_id FROM product_code_aliases a WHERE a.product_code = ?))"
            )
            params.extend([product_code, product_code, product_code])
        where_clause = " AND ".join(where)
        row = db.execute(
            "SELECT COUNT(*) AS record_count, "
            "COUNT(DISTINCT wr.user_id) AS worker_count, "
            "COUNT(DISTINCT wr.order_id) AS order_count, "
            "COUNT(DISTINCT COALESCE(CAST(opl.product_id AS TEXT), "
            "NULLIF(wr.product_code, ''), wr.product_name, o.product_code, o.product_name)) AS product_count, "
            "COALESCE(SUM(wr.quantity), 0) AS quantity, "
            "COALESCE(SUM(wr.standard_minutes), 0) AS standard_minutes, "
            "COALESCE(SUM(wr.actual_minutes), 0) AS actual_minutes, "
            "COALESCE(SUM(wr.effective_minutes), 0) AS effective_minutes, "
            "SUM(CASE WHEN wr.status = 'abnormal' THEN 1 ELSE 0 END) AS abnormal_count, "
            "SUM(CASE WHEN wr.standard_missing = 1 THEN 1 ELSE 0 END) AS missing_standard_count, "
            "ROUND(AVG(CASE WHEN wr.effective_minutes > 0 AND wr.standard_minutes > 0 "
            "THEN wr.standard_minutes * 100.0 / wr.effective_minutes END), 1) AS efficiency "
            "FROM work_time_records wr "
            "LEFT JOIN orders o ON wr.order_id = o.id "
            "LEFT JOIN order_product_links opl ON opl.order_id = o.id "
            "WHERE " + where_clause,
            params,
        ).fetchone()
        return {
            "record_count": int(row["record_count"] or 0),
            "worker_count": int(row["worker_count"] or 0),
            "order_count": int(row["order_count"] or 0),
            "product_count": int(row["product_count"] or 0),
            "quantity": int(row["quantity"] or 0),
            "standard_minutes": round(float(row["standard_minutes"] or 0), 2),
            "actual_minutes": round(float(row["actual_minutes"] or 0), 2),
            "effective_minutes": round(float(row["effective_minutes"] or 0), 2),
            "effective_hours": round(float(row["effective_minutes"] or 0) / 60, 2),
            "abnormal_count": int(row["abnormal_count"] or 0),
            "missing_standard_count": int(row["missing_standard_count"] or 0),
            "efficiency": float(row["efficiency"] or 0),
        }

    @staticmethod
    def approved_user_month_metrics(user_id, year_month, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT "
            "COUNT(*) AS record_count, "
            "COUNT(DISTINCT substr(COALESCE(NULLIF(end_time, ''), start_time, created_at), 1, 10)) AS work_days, "
            "COALESCE(SUM(quantity), 0) AS quantity, "
            "COALESCE(SUM(standard_minutes), 0) AS standard_minutes, "
            "COALESCE(SUM(actual_minutes), 0) AS actual_minutes, "
            "COALESCE(SUM(effective_minutes), 0) AS effective_minutes, "
            "SUM(CASE WHEN status = 'abnormal' THEN 1 ELSE 0 END) AS abnormal_count, "
            "SUM(CASE WHEN standard_missing = 1 THEN 1 ELSE 0 END) AS missing_standard_count, "
            "ROUND(AVG(CASE WHEN effective_minutes > 0 AND standard_minutes > 0 "
            "THEN standard_minutes * 100.0 / effective_minutes END), 1) AS efficiency "
            "FROM work_time_records "
            "WHERE user_id = ? AND review_status = 'approved' "
            "AND substr(COALESCE(NULLIF(end_time, ''), start_time, created_at), 1, 7) = ?",
            (user_id, year_month),
        ).fetchone()
        return {
            "work_time_record_count": int(row["record_count"] or 0),
            "work_time_days": int(row["work_days"] or 0),
            "work_time_quantity": int(row["quantity"] or 0),
            "work_time_standard_minutes": round(float(row["standard_minutes"] or 0), 2),
            "work_time_actual_minutes": round(float(row["actual_minutes"] or 0), 2),
            "work_time_effective_minutes": round(float(row["effective_minutes"] or 0), 2),
            "work_time_abnormal_count": int(row["abnormal_count"] or 0),
            "work_time_missing_standard_count": int(row["missing_standard_count"] or 0),
            "work_time_efficiency": float(row["efficiency"] or 0),
        }

    @staticmethod
    def approved_month_record_count(year_month, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT COUNT(*) AS total FROM work_time_records "
            "WHERE review_status = 'approved' "
            "AND substr(COALESCE(NULLIF(end_time, ''), start_time, created_at), 1, 7) = ?",
            (year_month,),
        ).fetchone()
        return int(row["total"] or 0)

    @staticmethod
    def historical_effective_minutes_by_process(route_id, process_ids, product_code='', min_samples=3, db=None):
        db = resolve_db(db)
        process_ids = [int(pid) for pid in (process_ids or []) if pid]
        if not route_id or not process_ids:
            return {}
        placeholders = ','.join('?' for _ in process_ids)
        params = [route_id, *process_ids]
        product_clause = ""
        product_code = (product_code or '').strip()
        if product_code:
            product_clause = " AND (product_code = ? OR product_code = '')"
            params.append(product_code)
        params.append(max(int(min_samples or 1), 1))
        rows = db.execute(
            f"SELECT process_id, COUNT(*) AS sample_count, "
            "ROUND(AVG(effective_minutes / CASE WHEN quantity > 0 THEN quantity ELSE 1 END), 2) AS avg_minutes_per_unit "
            "FROM work_time_records "
            f"WHERE route_id = ? AND process_id IN ({placeholders}) "
            "AND review_status = 'approved' AND effective_minutes > 0 "
            f"{product_clause} "
            "GROUP BY process_id HAVING COUNT(*) >= ?",
            params,
        ).fetchall()
        return {row["process_id"]: dict(row) for row in rows}

    @staticmethod
    def stats(db=None):
        db = resolve_db(db)
        standards = db.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) AS active "
            "FROM work_time_standards"
        ).fetchone()
        records = db.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN review_status='pending' THEN 1 ELSE 0 END) AS pending_review, "
            "SUM(CASE WHEN status='abnormal' THEN 1 ELSE 0 END) AS abnormal, "
            "SUM(CASE WHEN standard_missing=1 THEN 1 ELSE 0 END) AS missing_standard, "
            "ROUND(COALESCE(SUM(effective_minutes),0) / 60.0, 2) AS effective_hours, "
            "ROUND(AVG(CASE WHEN effective_minutes > 0 AND standard_minutes > 0 "
            "THEN standard_minutes * 100.0 / effective_minutes END), 1) AS avg_efficiency "
            "FROM work_time_records"
        ).fetchone()
        return {
            "standards_total": int(standards["total"] or 0),
            "standards_active": int(standards["active"] or 0),
            "records_total": int(records["total"] or 0),
            "pending_review": int(records["pending_review"] or 0),
            "abnormal": int(records["abnormal"] or 0),
            "missing_standard": int(records["missing_standard"] or 0),
            "effective_hours": float(records["effective_hours"] or 0),
            "avg_efficiency": float(records["avg_efficiency"] or 0),
        }
