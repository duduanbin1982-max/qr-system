"""Full-process quality evaluation persistence."""

import json
import sqlite3

from modules.domain.errors import ConflictError
from modules.domain.reporting_day import reporting_month_bounds
from modules.repositories.context import resolve_db
from modules.process_fact_projection import (
    capture_process_fact_binding,
    process_value_sql,
    process_version_join,
    warn_legacy_fact_rows,
)


class ProcessQualityEvaluationRepository:
    @staticmethod
    def _json_value(value, default):
        try:
            parsed = json.loads(value or "")
        except (TypeError, json.JSONDecodeError):
            return default
        return parsed if isinstance(parsed, type(default)) else default

    @staticmethod
    def _task_binding(task_row, role):
        if not task_row:
            return None
        task_row = dict(task_row)
        return {
            "process_id": task_row[f"{role}_process_id"],
            "process_version_id": task_row.get(f"{role}_process_version_id"),
            "process_code_snapshot": task_row.get(f"{role}_process_code_snapshot", ""),
            "process_name_snapshot": task_row.get(f"{role}_process_name_snapshot", ""),
            "process_category_snapshot": task_row.get(f"{role}_process_category_snapshot", ""),
            "route_id": task_row.get("route_id"),
            "route_version_id": task_row.get("route_version_id"),
            "route_name_snapshot": task_row.get("route_name_snapshot", ""),
        }

    @classmethod
    def _fact_bindings(cls, data, db):
        task_row = None
        task_id = data.get("task_id")
        if task_id:
            task_row = db.execute(
                "SELECT * FROM process_quality_evaluation_tasks WHERE id=?", (task_id,)
            ).fetchone()
        target = cls._task_binding(task_row, "target")
        evaluator = cls._task_binding(task_row, "evaluator")
        if not target or target.get("process_version_id") is None:
            target = capture_process_fact_binding(
                db,
                order_id=data["order_id"],
                process_id=data["target_process_id"],
                source_work_record_id=data.get("target_work_record_id"),
            )
        if not evaluator or evaluator.get("process_version_id") is None:
            evaluator = capture_process_fact_binding(
                db,
                order_id=data["order_id"],
                process_id=data["evaluator_process_id"],
                source_work_record_id=data.get("trigger_work_record_id"),
            )
        return target, evaluator

    @staticmethod
    def insert_evaluation(data, db):
        target_binding, evaluator_binding = ProcessQualityEvaluationRepository._fact_bindings(data, db)
        cursor = db.execute(
            "INSERT INTO process_quality_evaluations ("
            "task_id, order_id, serial_no, target_process_id, evaluator_process_id, target_work_record_id, "
            "trigger_work_record_id, target_user_id, evaluator_user_id, quantity, attribution_type, "
            "processing_quality, dimensional_accuracy, appearance_quality, process_continuity, "
            "cleanliness_protection, total_score, grade, issue_tags_json, comment, status, source_type, "
            "source_handoff_review_id, template_id, dimension_scores_json, template_snapshot_json, severity, "
            "target_process_version_id,target_process_code_snapshot,target_process_name_snapshot,"
            "target_process_category_snapshot,evaluator_process_version_id,evaluator_process_code_snapshot,"
            "evaluator_process_name_snapshot,evaluator_process_category_snapshot,route_id,route_version_id,"
            "route_name_snapshot,version_binding_source"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                data.get("task_id"), data["order_id"], data.get("serial_no", ""), data["target_process_id"],
                data["evaluator_process_id"], data.get("target_work_record_id"), data.get("trigger_work_record_id"),
                data.get("target_user_id"), data["evaluator_user_id"], data.get("quantity", 1),
                data.get("attribution_type", "worker"), data["processing_quality"], data["dimensional_accuracy"],
                data["appearance_quality"], data["process_continuity"], data["cleanliness_protection"],
                data["total_score"], data["grade"], json.dumps(data.get("issue_tags", []), ensure_ascii=False),
                data.get("comment", ""), data.get("status", "confirmed"), data.get("source_type", "full_process"),
                data.get("source_handoff_review_id"), data.get("template_id"),
                json.dumps(data.get("dimension_scores", {}), ensure_ascii=False),
                json.dumps(data.get("template_snapshot", {}), ensure_ascii=False),
                data.get("severity", "normal"),
                target_binding["process_version_id"], target_binding.get("process_code_snapshot", ""),
                target_binding.get("process_name_snapshot", ""), target_binding.get("process_category_snapshot", ""),
                evaluator_binding["process_version_id"], evaluator_binding.get("process_code_snapshot", ""),
                evaluator_binding.get("process_name_snapshot", ""), evaluator_binding.get("process_category_snapshot", ""),
                evaluator_binding.get("route_id") or target_binding.get("route_id"),
                evaluator_binding.get("route_version_id") or target_binding.get("route_version_id"),
                evaluator_binding.get("route_name_snapshot") or target_binding.get("route_name_snapshot", ""),
                "captured",
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def list_evaluations(year_month="", status="", process_id=None, user_id=None, keyword="", page=1, per_page=100, db=None):
        db = resolve_db(db)
        where = []
        params = []
        if year_month:
            period_start, period_end = reporting_month_bounds(year_month)
            where.extend(["evaluation.created_at >= ?", "evaluation.created_at < ?"])
            params.extend([period_start, period_end])
        if status:
            where.append("evaluation.status = ?")
            params.append(status)
        if process_id:
            where.append("evaluation.target_process_id = ?")
            params.append(process_id)
        if user_id:
            where.append("evaluation.target_user_id = ?")
            params.append(user_id)
        if keyword:
            target_name = process_value_sql("evaluation", "target_version", "target_p", role="target_process")
            where.append("(o.order_no LIKE ? OR o.product_name LIKE ? OR evaluation.serial_no LIKE ? OR " + target_name + " LIKE ?)")
            value = f"%{keyword}%"
            params.extend([value, value, value, value])
        where_clause = " AND ".join(where) if where else "1=1"
        total = db.execute(
            "SELECT COUNT(*) FROM process_quality_evaluations evaluation "
            "JOIN orders o ON o.id = evaluation.order_id JOIN processes target_p ON target_p.id = evaluation.target_process_id "
            + process_version_join("evaluation", "target_version", "target_process") +
            "WHERE " + where_clause,
            params,
        ).fetchone()[0]
        offset = (page - 1) * per_page
        target_name = process_value_sql("evaluation", "target_version", "target_p", role="target_process")
        evaluator_name = process_value_sql("evaluation", "evaluator_version", "evaluator_p", role="evaluator_process")
        rows = db.execute(
            "SELECT evaluation.*, o.order_no, o.product_name, o.product_code, "
            + target_name + " AS target_process_name, " + evaluator_name + " AS evaluator_process_name, "
            + "target_u.name AS target_user_name, evaluator_u.name AS evaluator_name, reviewer.name AS reviewer_name, "
            "appeal.id AS appeal_id, appeal.status AS appeal_status, appeal.reason AS appeal_reason, "
            "appeal.review_note AS appeal_review_note, appeal.created_at AS appeal_created_at "
            "FROM process_quality_evaluations evaluation "
            "JOIN orders o ON o.id = evaluation.order_id "
            "JOIN processes target_p ON target_p.id = evaluation.target_process_id "
            "JOIN processes evaluator_p ON evaluator_p.id = evaluation.evaluator_process_id "
            + process_version_join("evaluation", "target_version", "target_process")
            + process_version_join("evaluation", "evaluator_version", "evaluator_process")
            + "LEFT JOIN users target_u ON target_u.id = evaluation.target_user_id "
            "JOIN users evaluator_u ON evaluator_u.id = evaluation.evaluator_user_id "
            "LEFT JOIN users reviewer ON reviewer.id = evaluation.reviewed_by "
            "LEFT JOIN process_quality_evaluation_appeals appeal ON appeal.id = ("
            "SELECT MAX(candidate.id) FROM process_quality_evaluation_appeals candidate "
            "WHERE candidate.evaluation_id = evaluation.id) "
            "WHERE " + where_clause + " ORDER BY evaluation.created_at DESC, evaluation.id DESC LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ).fetchall()
        warn_legacy_fact_rows("process_quality_evaluations", rows, roles=("target_process", "evaluator_process"))
        items = []
        for row in rows:
            item = dict(row)
            try:
                item["issue_tags"] = json.loads(item.pop("issue_tags_json") or "[]")
            except (TypeError, json.JSONDecodeError):
                item["issue_tags"] = []
            item["dimension_scores"] = ProcessQualityEvaluationRepository._json_value(
                item.pop("dimension_scores_json", "{}"), {}
            )
            item["template_snapshot"] = ProcessQualityEvaluationRepository._json_value(
                item.pop("template_snapshot_json", "{}"), {}
            )
            items.append(item)
        return {"items": items, "total": total, "page": page, "per_page": per_page}

    @staticmethod
    def evaluation_by_id(evaluation_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT evaluation.*, "
            + process_value_sql("evaluation", "target_version", "target_p", role="target_process")
            + " AS target_process_name, "
            + process_value_sql("evaluation", "evaluator_version", "evaluator_p", role="evaluator_process")
            + " AS evaluator_process_name FROM process_quality_evaluations evaluation "
            "JOIN processes target_p ON target_p.id=evaluation.target_process_id "
            "JOIN processes evaluator_p ON evaluator_p.id=evaluation.evaluator_process_id "
            + process_version_join("evaluation", "target_version", "target_process")
            + process_version_join("evaluation", "evaluator_version", "evaluator_process")
            + " WHERE evaluation.id = ?",
            (evaluation_id,),
        ).fetchone()

    @staticmethod
    def evaluation_by_legacy_handoff(handoff_review_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM process_quality_evaluations WHERE source_handoff_review_id = ?",
            (handoff_review_id,),
        ).fetchone()

    @staticmethod
    def review_evaluation(evaluation_id, status, reviewer_user_id, note, db, expected_status=None):
        where = "id = ?"
        params = [status, reviewer_user_id, note, evaluation_id]
        if expected_status:
            where += " AND status = ?"
            params.append(expected_status)
        cursor = db.execute(
            "UPDATE process_quality_evaluations SET status = ?, reviewed_by = ?, review_note = ?, "
            "reviewed_at = datetime('now','localtime'), updated_at = datetime('now','localtime') WHERE "
            + where,
            params,
        )
        if cursor.rowcount != 1:
            return False
        db.execute(
            "INSERT INTO process_quality_evaluation_reviews (evaluation_id, action, reviewer_user_id, note) "
            "VALUES (?,?,?,?)",
            (evaluation_id, status, reviewer_user_id, note),
        )
        return True

    @staticmethod
    def references(db=None):
        db = resolve_db(db)
        return {
            "routes": [dict(row) for row in db.execute(
                "SELECT id, name FROM process_routes WHERE status = 'active' ORDER BY name"
            ).fetchall()],
            "processes": [dict(row) for row in db.execute(
                "SELECT id, name FROM processes WHERE status = 'active' ORDER BY category, seq_order, name"
            ).fetchall()],
        }

    @staticmethod
    def route_contains_process(route_id, process_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT 1 FROM process_route_items WHERE route_id = ? AND process_id = ? LIMIT 1",
            (route_id, process_id),
        ).fetchone() is not None

    @staticmethod
    def active_process_exists(process_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT 1 FROM processes WHERE id = ? AND status = 'active' LIMIT 1",
            (process_id,),
        ).fetchone() is not None

    @staticmethod
    def list_templates(status="", db=None):
        db = resolve_db(db)
        params = []
        where = "1=1"
        if status:
            where = "template.status = ?"
            params.append(status)
        rows = db.execute(
            "SELECT template.*, route.name AS route_name, process.name AS process_name "
            "FROM process_quality_evaluation_templates template "
            "LEFT JOIN process_routes route ON route.id = template.route_id "
            "JOIN processes process ON process.id = template.process_id "
            "WHERE " + where + " ORDER BY process.name, route.name, template.id DESC",
            params,
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["dimensions"] = ProcessQualityEvaluationRepository._json_value(
                item.pop("dimensions_json", "[]"), []
            )
            item["issue_tags"] = ProcessQualityEvaluationRepository._json_value(
                item.pop("issue_tags_json", "[]"), []
            )
            item["critical_issue_tags"] = ProcessQualityEvaluationRepository._json_value(
                item.pop("critical_issue_tags_json", "[]"), []
            )
            items.append(item)
        return items

    @staticmethod
    def template_by_id(template_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM process_quality_evaluation_templates WHERE id = ?",
            (template_id,),
        ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["dimensions"] = ProcessQualityEvaluationRepository._json_value(
            item.pop("dimensions_json", "[]"), []
        )
        item["issue_tags"] = ProcessQualityEvaluationRepository._json_value(
            item.pop("issue_tags_json", "[]"), []
        )
        item["critical_issue_tags"] = ProcessQualityEvaluationRepository._json_value(
            item.pop("critical_issue_tags_json", "[]"), []
        )
        return item

    @staticmethod
    def save_template(data, user_id, template_id=None, db=None):
        db = resolve_db(db)
        if data["status"] == "active":
            route_clause = "route_id = ?" if data.get("route_id") else "route_id IS NULL"
            params = [data["process_id"]]
            if data.get("route_id"):
                params.append(data["route_id"])
            exclude_clause = ""
            if template_id:
                exclude_clause = " AND id != ?"
                params.append(template_id)
            db.execute(
                "UPDATE process_quality_evaluation_templates SET status = 'inactive', "
                "updated_at = datetime('now','localtime') WHERE status = 'active' "
                f"AND process_id = ? AND {route_clause}{exclude_clause}",
                params,
            )
        values = (
            data["name"], data.get("route_id"), data["process_id"],
            json.dumps(data["dimensions"], ensure_ascii=False),
            json.dumps(data.get("issue_tags", []), ensure_ascii=False),
            json.dumps(data.get("critical_issue_tags", []), ensure_ascii=False),
            data["low_score_threshold"], data["critical_score_threshold"], data["status"],
        )
        if template_id:
            db.execute(
                "UPDATE process_quality_evaluation_templates SET name = ?, route_id = ?, process_id = ?, "
                "dimensions_json = ?, issue_tags_json = ?, critical_issue_tags_json = ?, "
                "low_score_threshold = ?, critical_score_threshold = ?, status = ?, "
                "updated_at = datetime('now','localtime') WHERE id = ?",
                values + (template_id,),
            )
            return template_id
        cursor = db.execute(
            "INSERT INTO process_quality_evaluation_templates ("
            "name, route_id, process_id, dimensions_json, issue_tags_json, critical_issue_tags_json, "
            "low_score_threshold, critical_score_threshold, status, created_by"
            ") VALUES (?,?,?,?,?,?,?,?,?,?)",
            values + (user_id,),
        )
        return cursor.lastrowid

    @staticmethod
    def create_appeal(evaluation_id, requester_user_id, reason, db):
        try:
            cursor = db.execute(
                "INSERT INTO process_quality_evaluation_appeals "
                "(evaluation_id, requester_user_id, reason) VALUES (?,?,?)",
                (evaluation_id, requester_user_id, reason),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError("该评价已有待处理申诉") from exc
        return cursor.lastrowid

    @staticmethod
    def appeal_by_id(appeal_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT appeal.*, evaluation.order_id, evaluation.target_user_id, "
            "evaluation.status AS evaluation_status "
            "FROM process_quality_evaluation_appeals appeal "
            "JOIN process_quality_evaluations evaluation ON evaluation.id = appeal.evaluation_id "
            "WHERE appeal.id = ?",
            (appeal_id,),
        ).fetchone()

    @staticmethod
    def list_appeals(status="", requester_user_id=None, year_month="", page=1, per_page=100, db=None):
        db = resolve_db(db)
        where = []
        params = []
        if status:
            where.append("appeal.status = ?")
            params.append(status)
        if requester_user_id:
            where.append("appeal.requester_user_id = ?")
            params.append(requester_user_id)
        if year_month:
            period_start, period_end = reporting_month_bounds(year_month)
            where.extend(["appeal.created_at >= ?", "appeal.created_at < ?"])
            params.extend([period_start, period_end])
        clause = " AND ".join(where) if where else "1=1"
        total = db.execute(
            "SELECT COUNT(*) FROM process_quality_evaluation_appeals appeal WHERE " + clause,
            params,
        ).fetchone()[0]
        offset = (page - 1) * per_page
        rows = db.execute(
            "SELECT appeal.*, evaluation.total_score, evaluation.grade, evaluation.serial_no, "
            "evaluation.target_process_id, evaluation.target_user_id, o.order_no, o.product_name, "
            + process_value_sql("evaluation", "target_version", "process", role="target_process")
            + " AS target_process_name, requester.name AS requester_name, reviewer.name AS reviewer_name "
            + "FROM process_quality_evaluation_appeals appeal "
            "JOIN process_quality_evaluations evaluation ON evaluation.id = appeal.evaluation_id "
            "JOIN orders o ON o.id = evaluation.order_id "
            "JOIN processes process ON process.id = evaluation.target_process_id "
            + process_version_join("evaluation", "target_version", "target_process")
            + "JOIN users requester ON requester.id = appeal.requester_user_id "
            "LEFT JOIN users reviewer ON reviewer.id = appeal.reviewed_by "
            "WHERE " + clause + " ORDER BY appeal.created_at DESC, appeal.id DESC LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ).fetchall()
        return {
            "items": [dict(row) for row in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
        }

    @staticmethod
    def review_appeal(appeal_id, status, reviewer_user_id, note, db, expected_status="pending"):
        cursor = db.execute(
            "UPDATE process_quality_evaluation_appeals SET status = ?, reviewed_by = ?, review_note = ?, "
            "reviewed_at = datetime('now','localtime'), updated_at = datetime('now','localtime') "
            "WHERE id = ? AND status = ?",
            (status, reviewer_user_id, note, appeal_id, expected_status),
        )
        return cursor.rowcount == 1

    @staticmethod
    def stats(year_month="", db=None):
        db = resolve_db(db)
        conditions = ["evaluation.status != 'rejected'"]
        date_params = []
        if year_month:
            period_start, period_end = reporting_month_bounds(year_month)
            conditions.extend(["evaluation.created_at >= ?", "evaluation.created_at < ?"])
            date_params.extend([period_start, period_end])
        date_clause = "WHERE " + " AND ".join(conditions)
        summary = dict(db.execute(
            "SELECT COUNT(*) AS total, ROUND(COALESCE(AVG(total_score), 0), 1) AS avg_score, "
            "SUM(CASE WHEN status = 'pending_verification' THEN 1 ELSE 0 END) AS pending_verification, "
            "SUM(CASE WHEN severity IN ('warning','critical') THEN 1 ELSE 0 END) AS low_score_count, "
            "SUM(CASE WHEN attribution_type = 'worker' AND target_user_id IS NOT NULL THEN 1 ELSE 0 END) AS attributed_count "
            "FROM process_quality_evaluations evaluation " + date_clause,
            date_params,
        ).fetchone())
        process_name = process_value_sql("evaluation", "target_version", "p", role="target_process")
        process_rows = db.execute(
            "SELECT p.id AS process_id, evaluation.target_process_version_id, " + process_name + " AS process_name, COUNT(*) AS evaluation_count, "
            "ROUND(AVG(evaluation.total_score), 1) AS avg_score, "
            "SUM(CASE WHEN evaluation.severity IN ('warning','critical') THEN 1 ELSE 0 END) AS low_score_count "
            "FROM process_quality_evaluations evaluation JOIN processes p ON p.id = evaluation.target_process_id "
            + process_version_join("evaluation", "target_version", "target_process")
            + date_clause + " GROUP BY p.id, evaluation.target_process_version_id, " + process_name + " ORDER BY avg_score ASC, evaluation_count DESC",
            date_params,
        ).fetchall()
        evaluator_rows = db.execute(
            "SELECT evaluator.id AS evaluator_user_id, evaluator.name AS evaluator_name, "
            "COUNT(*) AS evaluation_count, ROUND(AVG(evaluation.total_score), 1) AS avg_score, "
            "SUM(CASE WHEN evaluation.severity IN ('warning','critical') THEN 1 ELSE 0 END) AS low_score_count "
            "FROM process_quality_evaluations evaluation "
            "JOIN users evaluator ON evaluator.id = evaluation.evaluator_user_id "
            + date_clause + " GROUP BY evaluator.id, evaluator.name "
            "ORDER BY avg_score ASC, evaluation_count DESC",
            date_params,
        ).fetchall()
        appeal_clause = ""
        appeal_params = []
        if year_month:
            period_start, period_end = reporting_month_bounds(year_month)
            appeal_clause = "WHERE created_at >= ? AND created_at < ?"
            appeal_params = [period_start, period_end]
        appeal_summary = dict(db.execute(
            "SELECT COUNT(*) AS total, SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending "
            "FROM process_quality_evaluation_appeals " + appeal_clause,
            appeal_params,
        ).fetchone())
        return {
            "summary": summary,
            "processes": [dict(row) for row in process_rows],
            "evaluators": [dict(row) for row in evaluator_rows],
            "appeals": appeal_summary,
            "year_month": year_month,
        }

    @staticmethod
    def monthly_metrics(year_month, minimum_samples=1, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT target_user_id AS user_id, COUNT(*) AS review_count, "
            "ROUND(AVG(total_score) / 20.0, 2) AS avg_rating, "
            "SUM(CASE WHEN severity IN ('warning','critical') THEN 1 ELSE 0 END) AS low_count, "
            "SUM(CASE WHEN total_score >= 80 THEN 1 ELSE 0 END) AS good_count "
            "FROM process_quality_evaluations "
            "WHERE created_at >= ? AND created_at < ? AND status = 'confirmed' "
            "AND attribution_type = 'worker' AND target_user_id IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM process_quality_evaluation_appeals appeal "
            "WHERE appeal.evaluation_id = process_quality_evaluations.id AND appeal.status = 'pending') "
            "GROUP BY target_user_id HAVING COUNT(*) >= ?",
            (*reporting_month_bounds(year_month), minimum_samples),
        ).fetchall()
