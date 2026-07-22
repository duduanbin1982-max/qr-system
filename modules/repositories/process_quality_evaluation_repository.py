"""Full-process quality evaluation persistence."""

import json

from modules.repositories.context import resolve_db


class ProcessQualityEvaluationRepository:
    @staticmethod
    def upstream_processes(order_id, evaluator_process_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT upstream.process_id, upstream.seq_order, p.name AS process_name "
            "FROM order_processes current "
            "JOIN order_processes upstream ON upstream.order_id = current.order_id "
            "AND upstream.seq_order < current.seq_order "
            "JOIN processes p ON p.id = upstream.process_id "
            "WHERE current.order_id = ? AND current.process_id = ? "
            "ORDER BY upstream.seq_order DESC",
            (order_id, evaluator_process_id),
        ).fetchall()

    @staticmethod
    def serial_target_work(order_id, target_process_id, serial_no, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT wr.id, wr.user_id, wr.quantity, u.name AS worker_name, u.employee_no "
            "FROM work_records wr JOIN users u ON u.id = wr.user_id "
            "WHERE wr.order_id = ? AND wr.process_id = ? AND wr.serial_no = ? "
            "AND wr.type = 'normal' AND wr.status = 'approved' "
            "ORDER BY wr.created_at DESC, wr.id DESC LIMIT 1",
            (order_id, target_process_id, serial_no),
        ).fetchone()

    @staticmethod
    def order_target_contributors(order_id, target_process_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT wr.user_id, u.name AS worker_name, u.employee_no, "
            "COUNT(*) AS record_count, COALESCE(SUM(wr.quantity), 0) AS quantity, MAX(wr.id) AS latest_work_record_id "
            "FROM work_records wr JOIN users u ON u.id = wr.user_id "
            "WHERE wr.order_id = ? AND wr.process_id = ? "
            "AND wr.type = 'normal' AND wr.status = 'approved' "
            "GROUP BY wr.user_id ORDER BY quantity DESC, wr.user_id",
            (order_id, target_process_id),
        ).fetchall()

    @staticmethod
    def insert_task(data, db):
        cursor = db.execute(
            "INSERT OR IGNORE INTO process_quality_evaluation_tasks ("
            "trigger_work_record_id, order_id, serial_no, target_process_id, evaluator_process_id, "
            "target_work_record_id, target_user_id, evaluator_user_id, quantity, is_required, attribution_type"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                data["trigger_work_record_id"], data["order_id"], data.get("serial_no", ""),
                data["target_process_id"], data["evaluator_process_id"], data.get("target_work_record_id"),
                data.get("target_user_id"), data["evaluator_user_id"], data.get("quantity", 1),
                1 if data.get("is_required") else 0, data.get("attribution_type", "worker"),
            ),
        )
        return cursor.rowcount

    @staticmethod
    def task_by_id(task_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT task.*, o.order_no, o.product_name, o.product_code, "
            "target_p.name AS target_process_name, evaluator_p.name AS evaluator_process_name, "
            "target_u.name AS target_user_name, target_u.employee_no AS target_employee_no, "
            "evaluator_u.name AS evaluator_name "
            "FROM process_quality_evaluation_tasks task "
            "JOIN orders o ON o.id = task.order_id "
            "JOIN processes target_p ON target_p.id = task.target_process_id "
            "JOIN processes evaluator_p ON evaluator_p.id = task.evaluator_process_id "
            "LEFT JOIN users target_u ON target_u.id = task.target_user_id "
            "JOIN users evaluator_u ON evaluator_u.id = task.evaluator_user_id "
            "WHERE task.id = ?",
            (task_id,),
        ).fetchone()

    @staticmethod
    def find_matching_pending_task(data, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM process_quality_evaluation_tasks "
            "WHERE order_id = ? AND serial_no = ? AND target_process_id = ? "
            "AND evaluator_process_id = ? AND evaluator_user_id = ? AND status = 'pending' "
            "ORDER BY id DESC LIMIT 1",
            (
                data["order_id"], data.get("serial_no", ""), data["target_process_id"],
                data["evaluator_process_id"], data["evaluator_user_id"],
            ),
        ).fetchone()

    @staticmethod
    def list_tasks(evaluator_user_id=None, status="pending", keyword="", page=1, per_page=100, db=None):
        db = resolve_db(db)
        where = []
        params = []
        if evaluator_user_id:
            where.append("task.evaluator_user_id = ?")
            params.append(evaluator_user_id)
        if status:
            where.append("task.status = ?")
            params.append(status)
        if keyword:
            where.append("(o.order_no LIKE ? OR o.product_name LIKE ? OR task.serial_no LIKE ? OR target_p.name LIKE ?)")
            value = f"%{keyword}%"
            params.extend([value, value, value, value])
        where_clause = " AND ".join(where) if where else "1=1"
        total = db.execute(
            "SELECT COUNT(*) FROM process_quality_evaluation_tasks task "
            "JOIN orders o ON o.id = task.order_id JOIN processes target_p ON target_p.id = task.target_process_id "
            "WHERE " + where_clause,
            params,
        ).fetchone()[0]
        offset = (page - 1) * per_page
        rows = db.execute(
            "SELECT task.*, o.order_no, o.product_name, o.product_code, "
            "target_p.name AS target_process_name, evaluator_p.name AS evaluator_process_name, "
            "target_u.name AS target_user_name, target_u.employee_no AS target_employee_no, "
            "evaluator_u.name AS evaluator_name "
            "FROM process_quality_evaluation_tasks task "
            "JOIN orders o ON o.id = task.order_id "
            "JOIN processes target_p ON target_p.id = task.target_process_id "
            "JOIN processes evaluator_p ON evaluator_p.id = task.evaluator_process_id "
            "LEFT JOIN users target_u ON target_u.id = task.target_user_id "
            "JOIN users evaluator_u ON evaluator_u.id = task.evaluator_user_id "
            "WHERE " + where_clause + " ORDER BY task.is_required DESC, task.created_at DESC, task.id DESC "
            "LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total, "page": page, "per_page": per_page}

    @staticmethod
    def pending_count(evaluator_user_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) FROM process_quality_evaluation_tasks WHERE evaluator_user_id = ? AND status = 'pending'",
            (evaluator_user_id,),
        ).fetchone()[0]

    @staticmethod
    def insert_evaluation(data, db):
        cursor = db.execute(
            "INSERT INTO process_quality_evaluations ("
            "task_id, order_id, serial_no, target_process_id, evaluator_process_id, target_work_record_id, "
            "trigger_work_record_id, target_user_id, evaluator_user_id, quantity, attribution_type, "
            "processing_quality, dimensional_accuracy, appearance_quality, process_continuity, "
            "cleanliness_protection, total_score, grade, issue_tags_json, comment, status, source_type, "
            "source_handoff_review_id"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                data.get("task_id"), data["order_id"], data.get("serial_no", ""), data["target_process_id"],
                data["evaluator_process_id"], data.get("target_work_record_id"), data.get("trigger_work_record_id"),
                data.get("target_user_id"), data["evaluator_user_id"], data.get("quantity", 1),
                data.get("attribution_type", "worker"), data["processing_quality"], data["dimensional_accuracy"],
                data["appearance_quality"], data["process_continuity"], data["cleanliness_protection"],
                data["total_score"], data["grade"], json.dumps(data.get("issue_tags", []), ensure_ascii=False),
                data.get("comment", ""), data.get("status", "confirmed"), data.get("source_type", "full_process"),
                data.get("source_handoff_review_id"),
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def complete_task(task_id, db):
        db.execute(
            "UPDATE process_quality_evaluation_tasks SET status = 'completed', "
            "completed_at = datetime('now','localtime'), updated_at = datetime('now','localtime') WHERE id = ?",
            (task_id,),
        )

    @staticmethod
    def list_evaluations(year_month="", status="", process_id=None, user_id=None, keyword="", page=1, per_page=100, db=None):
        db = resolve_db(db)
        where = []
        params = []
        if year_month:
            where.append("evaluation.created_at LIKE ?")
            params.append(year_month + "%")
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
            where.append("(o.order_no LIKE ? OR o.product_name LIKE ? OR evaluation.serial_no LIKE ? OR target_p.name LIKE ?)")
            value = f"%{keyword}%"
            params.extend([value, value, value, value])
        where_clause = " AND ".join(where) if where else "1=1"
        total = db.execute(
            "SELECT COUNT(*) FROM process_quality_evaluations evaluation "
            "JOIN orders o ON o.id = evaluation.order_id JOIN processes target_p ON target_p.id = evaluation.target_process_id "
            "WHERE " + where_clause,
            params,
        ).fetchone()[0]
        offset = (page - 1) * per_page
        rows = db.execute(
            "SELECT evaluation.*, o.order_no, o.product_name, o.product_code, "
            "target_p.name AS target_process_name, evaluator_p.name AS evaluator_process_name, "
            "target_u.name AS target_user_name, evaluator_u.name AS evaluator_name, reviewer.name AS reviewer_name "
            "FROM process_quality_evaluations evaluation "
            "JOIN orders o ON o.id = evaluation.order_id "
            "JOIN processes target_p ON target_p.id = evaluation.target_process_id "
            "JOIN processes evaluator_p ON evaluator_p.id = evaluation.evaluator_process_id "
            "LEFT JOIN users target_u ON target_u.id = evaluation.target_user_id "
            "JOIN users evaluator_u ON evaluator_u.id = evaluation.evaluator_user_id "
            "LEFT JOIN users reviewer ON reviewer.id = evaluation.reviewed_by "
            "WHERE " + where_clause + " ORDER BY evaluation.created_at DESC, evaluation.id DESC LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            try:
                item["issue_tags"] = json.loads(item.pop("issue_tags_json") or "[]")
            except (TypeError, json.JSONDecodeError):
                item["issue_tags"] = []
            items.append(item)
        return {"items": items, "total": total, "page": page, "per_page": per_page}

    @staticmethod
    def evaluation_by_id(evaluation_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM process_quality_evaluations WHERE id = ?",
            (evaluation_id,),
        ).fetchone()

    @staticmethod
    def review_evaluation(evaluation_id, status, reviewer_user_id, note, db):
        db.execute(
            "UPDATE process_quality_evaluations SET status = ?, reviewed_by = ?, review_note = ?, "
            "reviewed_at = datetime('now','localtime'), updated_at = datetime('now','localtime') WHERE id = ?",
            (status, reviewer_user_id, note, evaluation_id),
        )
        db.execute(
            "INSERT INTO process_quality_evaluation_reviews (evaluation_id, action, reviewer_user_id, note) "
            "VALUES (?,?,?,?)",
            (evaluation_id, status, reviewer_user_id, note),
        )

    @staticmethod
    def update_legacy_status(handoff_review_id, status, reviewer_user_id, note, db):
        db.execute(
            "UPDATE process_quality_evaluations SET status = ?, reviewed_by = ?, review_note = ?, "
            "reviewed_at = datetime('now','localtime'), updated_at = datetime('now','localtime') "
            "WHERE source_handoff_review_id = ?",
            (status, reviewer_user_id, note, handoff_review_id),
        )

    @staticmethod
    def stats(year_month="", low_score_threshold=60, db=None):
        db = resolve_db(db)
        date_clause = "WHERE evaluation.created_at LIKE ?" if year_month else ""
        date_params = [year_month + "%"] if year_month else []
        summary = dict(db.execute(
            "SELECT COUNT(*) AS total, ROUND(COALESCE(AVG(total_score), 0), 1) AS avg_score, "
            "SUM(CASE WHEN status = 'pending_verification' THEN 1 ELSE 0 END) AS pending_verification, "
            "SUM(CASE WHEN total_score < ? THEN 1 ELSE 0 END) AS low_score_count, "
            "SUM(CASE WHEN attribution_type = 'worker' AND target_user_id IS NOT NULL THEN 1 ELSE 0 END) AS attributed_count "
            "FROM process_quality_evaluations evaluation " + date_clause,
            [low_score_threshold] + date_params,
        ).fetchone())
        process_rows = db.execute(
            "SELECT p.id AS process_id, p.name AS process_name, COUNT(*) AS evaluation_count, "
            "ROUND(AVG(evaluation.total_score), 1) AS avg_score, "
            "SUM(CASE WHEN evaluation.total_score < ? THEN 1 ELSE 0 END) AS low_score_count "
            "FROM process_quality_evaluations evaluation JOIN processes p ON p.id = evaluation.target_process_id "
            + date_clause + " GROUP BY p.id, p.name ORDER BY avg_score ASC, evaluation_count DESC",
            [low_score_threshold] + date_params,
        ).fetchall()
        return {"summary": summary, "processes": [dict(row) for row in process_rows], "year_month": year_month}

    @staticmethod
    def monthly_metrics(year_month, low_score_threshold=60, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT target_user_id AS user_id, COUNT(*) AS review_count, "
            "ROUND(AVG(total_score) / 20.0, 2) AS avg_rating, "
            "SUM(CASE WHEN total_score < ? THEN 1 ELSE 0 END) AS low_count, "
            "SUM(CASE WHEN total_score >= 80 THEN 1 ELSE 0 END) AS good_count "
            "FROM process_quality_evaluations "
            "WHERE created_at LIKE ? AND status = 'confirmed' "
            "AND attribution_type = 'worker' AND target_user_id IS NOT NULL "
            "GROUP BY target_user_id",
            (low_score_threshold, year_month + "%"),
        ).fetchall()
