"""Performance evaluation data access."""
import json

from modules.repositories.context import resolve_db


class PerformanceRepository:
    @staticmethod
    def eligible_workers(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT u.id, u.name, u.employee_no, u.role, u.position_id, u.department_id, "
            "COALESCE(p.name, '') AS position_name, COALESCE(d.name, '') AS department_name "
            "FROM users u "
            "LEFT JOIN positions p ON u.position_id = p.id "
            "LEFT JOIN departments d ON u.department_id = d.id "
            "WHERE u.status = 'active' AND u.deleted_at IS NULL "
            "AND COALESCE(u.role, 'worker') = 'worker' "
            "ORDER BY u.name"
        ).fetchall()

    @staticmethod
    def work_record_metrics(user_id, year_month, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT "
            "COUNT(*) AS report_count, "
            "COUNT(DISTINCT DATE(created_at)) AS work_days, "
            "COALESCE(SUM(CASE WHEN type='normal' THEN quantity ELSE 0 END),0) AS output_qty, "
            "COALESCE(SUM(CASE WHEN type='scrap' THEN quantity ELSE 0 END),0) AS scrap_qty, "
            "COALESCE(SUM(CASE WHEN type='rework' THEN quantity ELSE 0 END),0) AS rework_qty "
            "FROM work_records "
            "WHERE user_id = ? AND status = 'approved' AND created_at LIKE ?",
            (user_id, year_month + "%"),
        ).fetchone()
        return {
            "report_count": int(row["report_count"] or 0),
            "work_days": int(row["work_days"] or 0),
            "output_qty": int(row["output_qty"] or 0),
            "scrap_qty": int(row["scrap_qty"] or 0),
            "rework_qty": int(row["rework_qty"] or 0),
        }

    @staticmethod
    def scrap_record_metrics(user_id, year_month, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT COALESCE(SUM(quantity),0) AS scrap_qty "
            "FROM scrap_records WHERE user_id = ? AND created_at LIKE ?",
            (user_id, year_month + "%"),
        ).fetchone()
        return {"scrap_qty": int(row["scrap_qty"] or 0)}

    @staticmethod
    def inspection_metrics(user_id, year_month, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT COALESCE(SUM(quantity_failed),0) AS failed_qty "
            "FROM quality_inspections WHERE inspector_id = ? AND inspected_at LIKE ?",
            (user_id, year_month + "%"),
        ).fetchone()
        return {"inspection_failed_qty": int(row["failed_qty"] or 0)}

    @staticmethod
    def improvement_plan_metrics(user_id, year_month, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT "
            "SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) AS open_total, "
            "SUM(CASE WHEN status IN ('failed') THEN 1 ELSE 0 END) AS failed_total, "
            "SUM(CASE WHEN status IN ('closed','passed') THEN 1 ELSE 0 END) AS completed_total "
            "FROM performance_improvement_plans "
            "WHERE user_id = ? AND year_month < ?",
            (user_id, year_month),
        ).fetchone()
        return {
            "open_improvement_plans": int(row["open_total"] or 0),
            "failed_improvement_plans": int(row["failed_total"] or 0),
            "completed_improvement_plans": int(row["completed_total"] or 0),
        }

    @staticmethod
    def worker_month_metrics(user_id, year_month, db=None):
        db = resolve_db(db)
        work = PerformanceRepository.work_record_metrics(user_id, year_month, db)
        scrap = PerformanceRepository.scrap_record_metrics(user_id, year_month, db)
        inspection = PerformanceRepository.inspection_metrics(user_id, year_month, db)
        plans = PerformanceRepository.improvement_plan_metrics(user_id, year_month, db)
        return {
            **work,
            "scrap_qty": work["scrap_qty"] + scrap["scrap_qty"],
            **inspection,
            **plans,
        }

    @staticmethod
    def get_review(user_id, year_month, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM performance_reviews WHERE user_id = ? AND year_month = ?",
            (user_id, year_month),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def upsert_review(data, db):
        db.execute(
            "INSERT INTO performance_reviews ("
            "user_id, year_month, discipline_deduction, discipline_reason, "
            "improvement_adjustment, improvement_reason, manual_score, manual_comment, reviewed_by, updated_at"
            ") VALUES (?,?,?,?,?,?,?,?,?, datetime('now','localtime')) "
            "ON CONFLICT(user_id, year_month) DO UPDATE SET "
            "discipline_deduction=excluded.discipline_deduction, "
            "discipline_reason=excluded.discipline_reason, "
            "improvement_adjustment=excluded.improvement_adjustment, "
            "improvement_reason=excluded.improvement_reason, "
            "manual_score=excluded.manual_score, "
            "manual_comment=excluded.manual_comment, "
            "reviewed_by=excluded.reviewed_by, updated_at=datetime('now','localtime')",
            (
                data["user_id"], data["year_month"], data.get("discipline_deduction", 0),
                data.get("discipline_reason", ""), data.get("improvement_adjustment", 0),
                data.get("improvement_reason", ""), data.get("manual_score", 10),
                data.get("manual_comment", ""), data.get("reviewed_by"),
            ),
        )

    @staticmethod
    def upsert_score(score, db):
        db.execute(
            "INSERT INTO performance_scores ("
            "user_id, year_month, role_type, output_qty, report_count, work_days, "
            "scrap_qty, rework_qty, inspection_failed_qty, output_score, quality_score, "
            "delivery_score, discipline_score, improvement_score, total_score, "
            "rank_no, rank_total, warning_level, warning_reason, status, "
            "discipline_deduction, discipline_reason, improvement_deduction, improvement_reason, "
            "manual_score, manual_comment, score_details, reviewed_by, reviewed_at, updated_at"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, datetime('now','localtime')) "
            "ON CONFLICT(user_id, year_month) DO UPDATE SET "
            "role_type=excluded.role_type, output_qty=excluded.output_qty, "
            "report_count=excluded.report_count, work_days=excluded.work_days, "
            "scrap_qty=excluded.scrap_qty, rework_qty=excluded.rework_qty, "
            "inspection_failed_qty=excluded.inspection_failed_qty, "
            "output_score=excluded.output_score, quality_score=excluded.quality_score, "
            "delivery_score=excluded.delivery_score, discipline_score=excluded.discipline_score, "
            "improvement_score=excluded.improvement_score, total_score=excluded.total_score, "
            "warning_level=excluded.warning_level, warning_reason=excluded.warning_reason, "
            "status=excluded.status, discipline_deduction=excluded.discipline_deduction, "
            "discipline_reason=excluded.discipline_reason, improvement_deduction=excluded.improvement_deduction, "
            "improvement_reason=excluded.improvement_reason, manual_score=excluded.manual_score, "
            "manual_comment=excluded.manual_comment, score_details=excluded.score_details, "
            "reviewed_by=excluded.reviewed_by, reviewed_at=excluded.reviewed_at, "
            "updated_at=datetime('now','localtime')",
            (
                score["user_id"], score["year_month"], score.get("role_type", "worker"),
                score["output_qty"], score["report_count"], score["work_days"],
                score["scrap_qty"], score["rework_qty"], score["inspection_failed_qty"],
                score["output_score"], score["quality_score"], score["delivery_score"],
                score["discipline_score"], score["improvement_score"], score["total_score"],
                score.get("rank_no", 0), score.get("rank_total", 0),
                score["warning_level"], score["warning_reason"], score.get("status", "generated"),
                score.get("discipline_deduction", 0), score.get("discipline_reason", ""),
                score.get("improvement_deduction", 0), score.get("improvement_reason", ""),
                score.get("manual_score", 10), score.get("manual_comment", ""),
                json.dumps(score.get("score_details", {}), ensure_ascii=False),
                score.get("reviewed_by"), score.get("reviewed_at", ""),
            ),
        )

    @staticmethod
    def update_ranks(year_month, db):
        rows = db.execute(
            "SELECT id, total_score FROM performance_scores WHERE year_month = ? "
            "ORDER BY total_score DESC, output_qty DESC, id ASC",
            (year_month,),
        ).fetchall()
        total = len(rows)
        for index, row in enumerate(rows, 1):
            db.execute(
                "UPDATE performance_scores SET rank_no = ?, rank_total = ? WHERE id = ?",
                (index, total, row["id"]),
            )

    @staticmethod
    def latest_score_month(db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT year_month FROM performance_scores "
            "GROUP BY year_month ORDER BY year_month DESC LIMIT 1"
        ).fetchone()
        return row["year_month"] if row else ""

    @staticmethod
    def work_record_count(year_month, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT COUNT(*) AS total FROM work_records "
            "WHERE status = 'approved' AND created_at LIKE ?",
            (year_month + "%",),
        ).fetchone()
        return int(row["total"] or 0)

    @staticmethod
    def list_score_months(limit=12, db=None):
        db = resolve_db(db)
        rows = db.execute(
            "SELECT year_month, COUNT(*) AS score_count FROM performance_scores "
            "GROUP BY year_month ORDER BY year_month DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def list_scores(year_month, warning_level="", search="", page=1, per_page=50, db=None):
        db = resolve_db(db)
        where = ["ps.year_month = ?"]
        params = [year_month]
        if warning_level:
            where.append("ps.warning_level = ?")
            params.append(warning_level)
        if search:
            where.append("(u.name LIKE ? OR u.employee_no LIKE ?)")
            like = f"%{search}%"
            params.extend([like, like])
        where_clause = " AND ".join(where)
        total = db.execute(
            "SELECT COUNT(*) FROM performance_scores ps JOIN users u ON ps.user_id = u.id WHERE " + where_clause,
            params,
        ).fetchone()[0]
        offset = (page - 1) * per_page
        rows = db.execute(
            "SELECT ps.*, u.name AS user_name, u.employee_no, u.role, "
            "COALESCE(p.name, '') AS position_name, COALESCE(d.name, '') AS department_name, "
            "reviewer.name AS reviewer_name "
            "FROM performance_scores ps JOIN users u ON ps.user_id = u.id "
            "LEFT JOIN positions p ON u.position_id = p.id "
            "LEFT JOIN departments d ON u.department_id = d.id "
            "LEFT JOIN users reviewer ON ps.reviewed_by = reviewer.id "
            "WHERE " + where_clause + " ORDER BY ps.total_score DESC, ps.output_qty DESC LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            try:
                item["score_details"] = json.loads(item.get("score_details") or "{}")
            except (TypeError, json.JSONDecodeError):
                item["score_details"] = {}
            items.append(item)
        return {"items": items, "total": total, "page": page, "per_page": per_page}

    @staticmethod
    def summary(year_month, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT COUNT(*) AS total, ROUND(AVG(total_score),1) AS avg_score, "
            "SUM(CASE WHEN warning_level='green' THEN 1 ELSE 0 END) AS green, "
            "SUM(CASE WHEN warning_level='yellow' THEN 1 ELSE 0 END) AS yellow, "
            "SUM(CASE WHEN warning_level='orange' THEN 1 ELSE 0 END) AS orange, "
            "SUM(CASE WHEN warning_level='red' THEN 1 ELSE 0 END) AS red "
            "FROM performance_scores WHERE year_month = ?",
            (year_month,),
        ).fetchone()
        return dict(row) if row else {}

    @staticmethod
    def create_plan(data, db):
        cur = db.execute(
            "INSERT INTO performance_improvement_plans ("
            "score_id, user_id, year_month, warning_level, reason, goal, actions, owner_id, due_date, created_by"
            ") VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                data.get("score_id"), data["user_id"], data["year_month"], data.get("warning_level", "yellow"),
                data.get("reason", ""), data.get("goal", ""), data.get("actions", ""),
                data.get("owner_id"), data.get("due_date", ""), data.get("created_by"),
            ),
        )
        return cur.lastrowid

    @staticmethod
    def list_plans(year_month="", status="", user_id=None, db=None):
        db = resolve_db(db)
        where = []
        params = []
        if year_month:
            where.append("pip.year_month = ?")
            params.append(year_month)
        if status:
            where.append("pip.status = ?")
            params.append(status)
        if user_id:
            where.append("pip.user_id = ?")
            params.append(user_id)
        where_clause = " AND ".join(where) if where else "1=1"
        rows = db.execute(
            "SELECT pip.*, u.name AS user_name, u.employee_no, owner.name AS owner_name "
            "FROM performance_improvement_plans pip "
            "JOIN users u ON pip.user_id = u.id "
            "LEFT JOIN users owner ON pip.owner_id = owner.id "
            "WHERE " + where_clause + " ORDER BY pip.created_at DESC",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def update_plan(plan_id, data, db):
        db.execute(
            "UPDATE performance_improvement_plans SET status=?, review_result=?, review_notes=?, "
            "updated_at=datetime('now','localtime'), closed_at=CASE WHEN ? IN ('closed','passed','failed') THEN datetime('now','localtime') ELSE closed_at END "
            "WHERE id=?",
            (
                data.get("status", "open"), data.get("review_result", ""), data.get("review_notes", ""),
                data.get("status", "open"), plan_id,
            ),
        )
