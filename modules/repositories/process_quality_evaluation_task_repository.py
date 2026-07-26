"""Process quality evaluation task persistence."""

import json

from modules.repositories.context import resolve_db


class ProcessQualityEvaluationTaskRepository:
    @staticmethod
    def _json_value(value, default):
        try:
            parsed = json.loads(value or "")
        except (TypeError, json.JSONDecodeError):
            return default
        return parsed if isinstance(parsed, type(default)) else default

    @staticmethod
    def upstream_processes(order_id, evaluator_process_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT upstream.process_id, upstream.seq_order, p.name AS process_name, o.route_id "
            "FROM order_processes current "
            "JOIN order_processes upstream ON upstream.order_id = current.order_id "
            "AND upstream.seq_order < current.seq_order "
            "JOIN processes p ON p.id = upstream.process_id "
            "JOIN orders o ON o.id = current.order_id "
            "WHERE current.order_id = ? AND current.process_id = ? "
            "ORDER BY upstream.seq_order DESC",
            (order_id, evaluator_process_id),
        ).fetchall()

    @staticmethod
    def matching_template(route_id, process_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM process_quality_evaluation_templates "
            "WHERE process_id = ? AND status = 'active' AND (route_id = ? OR route_id IS NULL) "
            "ORDER BY CASE WHEN route_id = ? THEN 0 ELSE 1 END, id DESC LIMIT 1",
            (process_id, route_id, route_id),
        ).fetchone()

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
            "target_work_record_id, target_user_id, evaluator_user_id, quantity, is_required, attribution_type, "
            "template_id, template_snapshot_json"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                data["trigger_work_record_id"], data["order_id"], data.get("serial_no", ""),
                data["target_process_id"], data["evaluator_process_id"], data.get("target_work_record_id"),
                data.get("target_user_id"), data["evaluator_user_id"], data.get("quantity", 1),
                1 if data.get("is_required") else 0, data.get("attribution_type", "worker"),
                data.get("template_id"),
                json.dumps(data.get("template_snapshot", {}), ensure_ascii=False),
            ),
        )
        return cursor.rowcount

    @classmethod
    def task_by_id(cls, task_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT task.*, o.order_no, o.product_name, o.product_code, "
            "o.status AS order_status, COALESCE(o.deleted_at, '') AS order_deleted_at, "
            "target_p.name AS target_process_name, evaluator_p.name AS evaluator_process_name, "
            "target_u.name AS target_user_name, target_u.employee_no AS target_employee_no, "
            "evaluator_u.name AS evaluator_name, waiver_u.name AS waived_by_name "
            "FROM process_quality_evaluation_tasks task "
            "JOIN orders o ON o.id = task.order_id "
            "JOIN processes target_p ON target_p.id = task.target_process_id "
            "JOIN processes evaluator_p ON evaluator_p.id = task.evaluator_process_id "
            "LEFT JOIN users target_u ON target_u.id = task.target_user_id "
            "JOIN users evaluator_u ON evaluator_u.id = task.evaluator_user_id "
            "LEFT JOIN users waiver_u ON waiver_u.id = task.waived_by "
            "WHERE task.id = ?",
            (task_id,),
        ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["template_snapshot"] = cls._json_value(
            item.pop("template_snapshot_json", "{}"), {}
        )
        return item

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

    @classmethod
    def list_tasks(cls, evaluator_user_id=None, status="pending", keyword="", page=1, per_page=100, db=None):
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
            "o.status AS order_status, COALESCE(o.deleted_at, '') AS order_deleted_at, "
            "target_p.name AS target_process_name, evaluator_p.name AS evaluator_process_name, "
            "target_u.name AS target_user_name, target_u.employee_no AS target_employee_no, "
            "evaluator_u.name AS evaluator_name, waiver_u.name AS waived_by_name, "
            "ROUND(MAX(0, (julianday('now','localtime') - julianday(task.created_at)) * 24), 1) AS age_hours, "
            "CASE WHEN task.created_at <= datetime('now','localtime','-72 hours') THEN 'critical' "
            "WHEN task.created_at <= datetime('now','localtime','-24 hours') THEN 'warning' "
            "ELSE 'normal' END AS age_level "
            "FROM process_quality_evaluation_tasks task "
            "JOIN orders o ON o.id = task.order_id "
            "JOIN processes target_p ON target_p.id = task.target_process_id "
            "JOIN processes evaluator_p ON evaluator_p.id = task.evaluator_process_id "
            "LEFT JOIN users target_u ON target_u.id = task.target_user_id "
            "JOIN users evaluator_u ON evaluator_u.id = task.evaluator_user_id "
            "LEFT JOIN users waiver_u ON waiver_u.id = task.waived_by "
            "WHERE " + where_clause + " ORDER BY task.is_required DESC, task.created_at DESC, task.id DESC "
            "LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["template_snapshot"] = cls._json_value(
                item.pop("template_snapshot_json", "{}"), {}
            )
            items.append(item)
        return {"items": items, "total": total, "page": page, "per_page": per_page}

    @staticmethod
    def pending_count(evaluator_user_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) FROM process_quality_evaluation_tasks WHERE evaluator_user_id = ? AND status = 'pending'",
            (evaluator_user_id,),
        ).fetchone()[0]

    @staticmethod
    def pending_required_count(evaluator_user_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) FROM process_quality_evaluation_tasks "
            "WHERE evaluator_user_id = ? AND status = 'pending' AND is_required = 1",
            (evaluator_user_id,),
        ).fetchone()[0]

    @staticmethod
    def pending_required_task(evaluator_user_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT task.id, o.order_no, target_process.name AS target_process_name, "
            "evaluator_process.name AS evaluator_process_name "
            "FROM process_quality_evaluation_tasks task "
            "JOIN orders o ON o.id = task.order_id "
            "JOIN processes target_process ON target_process.id = task.target_process_id "
            "JOIN processes evaluator_process ON evaluator_process.id = task.evaluator_process_id "
            "WHERE task.evaluator_user_id = ? AND task.status = 'pending' "
            "AND task.is_required = 1 ORDER BY task.created_at, task.id LIMIT 1",
            (evaluator_user_id,),
        ).fetchone()

    @staticmethod
    def complete_task(task_id, db):
        db.execute(
            "UPDATE process_quality_evaluation_tasks SET status = 'completed', "
            "completed_at = datetime('now','localtime'), updated_at = datetime('now','localtime') WHERE id = ?",
            (task_id,),
        )

    @staticmethod
    def skip_task(task_id, reason, db):
        cursor = db.execute(
            "UPDATE process_quality_evaluation_tasks SET status = 'skipped', skip_reason = ?, "
            "skipped_at = datetime('now','localtime'), updated_at = datetime('now','localtime') "
            "WHERE id = ? AND status = 'pending' AND is_required = 0",
            (reason, task_id),
        )
        return cursor.rowcount

    @staticmethod
    def task_disposal_summary(db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT "
            "COUNT(*) AS pending_total, "
            "COALESCE(SUM(CASE WHEN task.is_required = 1 THEN 1 ELSE 0 END), 0) AS required_pending, "
            "COALESCE(SUM(CASE WHEN task.is_required = 0 THEN 1 ELSE 0 END), 0) AS optional_pending, "
            "COALESCE(SUM(CASE WHEN task.is_required = 1 AND task.created_at <= datetime('now','localtime','-24 hours') THEN 1 ELSE 0 END), 0) AS overdue_24h, "
            "COALESCE(SUM(CASE WHEN task.is_required = 1 AND task.created_at <= datetime('now','localtime','-72 hours') THEN 1 ELSE 0 END), 0) AS overdue_72h, "
            "COALESCE(SUM(CASE WHEN task.is_required = 0 AND task.created_at <= datetime('now','localtime','-24 hours') THEN 1 ELSE 0 END), 0) AS optional_overdue_24h, "
            "COALESCE(SUM(CASE WHEN task.is_required = 0 AND task.created_at <= datetime('now','localtime','-72 hours') THEN 1 ELSE 0 END), 0) AS optional_overdue_72h, "
            "COALESCE(SUM(CASE WHEN task.is_required = 1 AND orders.status = 'completed' THEN 1 ELSE 0 END), 0) AS completed_order_required, "
            "COALESCE(SUM(CASE WHEN task.is_required = 1 AND orders.status = 'producing' THEN 1 ELSE 0 END), 0) AS producing_order_required, "
            "COUNT(DISTINCT task.evaluator_user_id) AS affected_workers "
            "FROM process_quality_evaluation_tasks task "
            "JOIN orders ON orders.id = task.order_id "
            "WHERE task.status = 'pending'"
        ).fetchone()
        return dict(row)

    @staticmethod
    def pending_task_ids_for_order(order_id, required_only=True, db=None):
        db = resolve_db(db)
        where = "order_id = ? AND status = 'pending'"
        params = [order_id]
        if required_only:
            where += " AND is_required = 1"
        return [row[0] for row in db.execute(
            "SELECT id FROM process_quality_evaluation_tasks WHERE " + where + " ORDER BY id",
            params,
        ).fetchall()]

    @staticmethod
    def pending_tasks_by_ids(task_ids, db=None):
        db = resolve_db(db)
        if not task_ids:
            return []
        placeholders = ",".join("?" for _ in task_ids)
        return db.execute(
            "SELECT task.id, task.order_id, task.evaluator_user_id, task.is_required, orders.order_no, "
            "orders.status AS order_status, COALESCE(orders.deleted_at, '') AS order_deleted_at "
            "FROM process_quality_evaluation_tasks task "
            "JOIN orders ON orders.id = task.order_id "
            f"WHERE task.id IN ({placeholders}) AND task.status = 'pending' ORDER BY task.id",
            task_ids,
        ).fetchall()

    @staticmethod
    def waive_tasks(task_ids, reason_code, reason, operator_user_id, db):
        if not task_ids:
            return 0
        placeholders = ",".join("?" for _ in task_ids)
        cursor = db.execute(
            "UPDATE process_quality_evaluation_tasks SET status = 'waived', "
            "waiver_reason_code = ?, waiver_reason = ?, "
            "waived_by = ?, waived_at = datetime('now','localtime'), "
            "updated_at = datetime('now','localtime') "
            f"WHERE id IN ({placeholders}) AND status = 'pending'",
            [reason_code, reason, operator_user_id, *task_ids],
        )
        if cursor.rowcount:
            for task_id in task_ids:
                audit_cursor = db.execute(
                    "INSERT INTO process_quality_evaluation_task_audits ("
                    "task_id, action, operator_user_id, operator_name, reason_code, reason, "
                    "order_id, order_no, order_status, order_deleted_at, product_code, product_name, "
                    "serial_no, target_process_id, target_process_name, evaluator_process_id, "
                    "evaluator_process_name, target_user_id, target_user_name, evaluator_user_id, "
                    "evaluator_name, is_required, task_status, task_created_at) "
                    "SELECT task.id, 'waived', ?, COALESCE(operator.name, ''), ?, ?, "
                    "task.order_id, orders.order_no, orders.status, COALESCE(orders.deleted_at, ''), "
                    "orders.product_code, orders.product_name, task.serial_no, task.target_process_id, "
                    "target_process.name, task.evaluator_process_id, evaluator_process.name, "
                    "task.target_user_id, COALESCE(target_user.name, ''), task.evaluator_user_id, "
                    "evaluator.name, task.is_required, task.status, task.created_at "
                    "FROM process_quality_evaluation_tasks task "
                    "JOIN orders ON orders.id = task.order_id "
                    "JOIN processes target_process ON target_process.id = task.target_process_id "
                    "JOIN processes evaluator_process ON evaluator_process.id = task.evaluator_process_id "
                    "JOIN users evaluator ON evaluator.id = task.evaluator_user_id "
                    "LEFT JOIN users target_user ON target_user.id = task.target_user_id "
                    "LEFT JOIN users operator ON operator.id = ? WHERE task.id = ?",
                    (operator_user_id, reason_code, reason, operator_user_id, task_id),
                )
                if audit_cursor.rowcount != 1:
                    raise RuntimeError("评价任务豁免审计快照写入失败")
        return cursor.rowcount

    @staticmethod
    def list_task_audits(keyword="", page=1, per_page=100, db=None):
        db = resolve_db(db)
        where = "1=1"
        params = []
        if keyword:
            where = (
                "(order_no LIKE ? OR product_name LIKE ? OR product_code LIKE ? OR "
                "serial_no LIKE ? OR target_process_name LIKE ? OR evaluator_name LIKE ?)"
            )
            value = f"%{keyword}%"
            params = [value, value, value, value, value, value]
        total = db.execute(
            "SELECT COUNT(*) FROM process_quality_evaluation_task_audits WHERE " + where,
            params,
        ).fetchone()[0]
        offset = (page - 1) * per_page
        rows = db.execute(
            "SELECT audit.*, 1 AS audit_record, audit.reason AS waiver_reason, "
            "audit.reason_code AS waiver_reason_code, audit.operator_name AS waived_by_name, "
            "audit.created_at AS waived_at, 'audit' AS status, "
            "ROUND(MAX(0, (julianday(audit.created_at) - julianday(audit.task_created_at)) * 24), 1) AS age_hours, "
            "CASE WHEN audit.task_created_at <= datetime(audit.created_at, '-72 hours') THEN 'critical' "
            "WHEN audit.task_created_at <= datetime(audit.created_at, '-24 hours') THEN 'warning' "
            "ELSE 'normal' END AS age_level "
            "FROM process_quality_evaluation_task_audits audit WHERE " + where +
            " ORDER BY audit.created_at DESC, audit.id DESC LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["created_at"] = item.get("task_created_at") or item["created_at"]
            items.append(item)
        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
        }
