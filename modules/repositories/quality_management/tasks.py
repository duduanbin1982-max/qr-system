"""QualityTaskRepository quality subdomain."""

from modules.repositories.context import resolve_db


class QualityTaskRepository(object):
    @staticmethod
    def matching_plans(order_id, process_id, trigger_type, db=None):
        db = resolve_db(db)
        rows = db.execute(
            "SELECT plan.*, standard.version AS standard_version, standard.min_score, "
            "o.product_code AS order_product_code, o.route_id AS order_route_id, "
            "((CASE WHEN plan.product_code != '' THEN 4 ELSE 0 END) + "
            " (CASE WHEN plan.route_id IS NOT NULL THEN 2 ELSE 0 END) + "
            " (CASE WHEN plan.process_id IS NOT NULL THEN 1 ELSE 0 END)) AS specificity "
            "FROM quality_inspection_plans plan "
            "JOIN orders o ON o.id = ? "
            "LEFT JOIN quality_standards standard ON standard.id = plan.standard_id "
            "WHERE plan.status='active' AND plan.trigger_type=? "
            "AND (plan.product_code='' OR plan.product_code=o.product_code) "
            "AND (plan.route_id IS NULL OR plan.route_id=o.route_id) "
            "AND (plan.process_id IS NULL OR plan.process_id=?) "
            "ORDER BY specificity DESC, plan.id DESC",
            (order_id, trigger_type, process_id),
        ).fetchall()
        selected = {}
        for row in rows:
            selected.setdefault(row["inspection_type"], row)
        return list(selected.values())

    @staticmethod
    def report_context(order_id, process_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT o.id AS order_id,o.order_no,o.product_code,o.route_id,o.quantity,"
            "op.process_id,op.completed,op.seq_order,"
            "(SELECT MAX(last_op.seq_order) FROM order_processes last_op WHERE last_op.order_id=o.id) AS last_seq_order,"
            "(SELECT COUNT(*) FROM work_records wr WHERE wr.order_id=o.id AND wr.process_id=op.process_id "
            "AND wr.type='normal' AND wr.status='approved') AS approved_reports "
            "FROM orders o JOIN order_processes op ON op.order_id=o.id AND op.process_id=? WHERE o.id=?",
            (process_id, order_id),
        ).fetchone()

    @staticmethod
    def shipment_order_contexts(shipment_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT DISTINCT si.order_id,o.order_no,o.product_code,o.route_id,o.quantity,"
            "(SELECT op.process_id FROM order_processes op WHERE op.order_id=o.id ORDER BY op.seq_order DESC,op.id DESC LIMIT 1) AS process_id "
            "FROM shipment_items si JOIN orders o ON o.id=si.order_id "
            "WHERE si.shipment_id=? AND si.order_id IS NOT NULL",
            (shipment_id,),
        ).fetchall()

    @staticmethod
    def rework_context(rework_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT rw.*,o.order_no,o.product_code,o.route_id FROM rework_records rw "
            "JOIN orders o ON o.id=rw.order_id WHERE rw.id=?",
            (rework_id,),
        ).fetchone()

    @staticmethod
    def next_sequence(table_name, db):
        allowed = {
            "quality_inspection_tasks", "quality_nonconformances", "quality_capa_records",
        }
        if table_name not in allowed:
            raise ValueError("invalid sequence table")
        return db.execute(f"SELECT COALESCE(MAX(id),0)+1 FROM {table_name}").fetchone()[0]

    @staticmethod
    def insert_task(data, db):
        cursor = db.execute(
            "INSERT OR IGNORE INTO quality_inspection_tasks "
            "(task_no, trigger_key, plan_id, standard_id, standard_version, order_id, process_id, work_record_id, "
            "shipment_id, supplier_id, material_id, source_evaluation_id, source_ncr_id, serial_no, batch_no, inspection_type, "
            "trigger_type, gate_mode, sample_qty, priority, status, assigned_to, due_at, created_by) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                data["task_no"], data["trigger_key"], data.get("plan_id"), data.get("standard_id"),
                data.get("standard_version", 1), data.get("order_id"), data.get("process_id"),
                data.get("work_record_id"), data.get("shipment_id"), data.get("supplier_id"),
                data.get("material_id"), data.get("source_evaluation_id"), data.get("source_ncr_id"),
                data.get("serial_no", ""), data.get("batch_no", ""), data["inspection_type"], data.get("trigger_type", "manual"),
                data.get("gate_mode", "soft"), data.get("sample_qty", 1), data.get("priority", "normal"),
                data.get("status", "pending"), data.get("assigned_to"), data.get("due_at", ""),
                data.get("created_by"),
            ),
        )
        if cursor.rowcount:
            return cursor.lastrowid
        row = db.execute(
            "SELECT id FROM quality_inspection_tasks WHERE trigger_key=?", (data["trigger_key"],)
        ).fetchone()
        return row["id"] if row else None

    @staticmethod
    def list_tasks(status="", inspection_type="", gate_mode="", keyword="", assigned_to=None,
                   date_from="", date_to="", page=1, limit=100, db=None):
        db = resolve_db(db)
        where = []
        params = []
        if status:
            where.append("task.status = ?"); params.append(status)
        if inspection_type:
            where.append("task.inspection_type = ?"); params.append(inspection_type)
        if gate_mode:
            where.append("task.gate_mode = ?"); params.append(gate_mode)
        if assigned_to:
            where.append("task.assigned_to = ?"); params.append(assigned_to)
        if keyword:
            where.append("(task.task_no LIKE ? OR o.order_no LIKE ? OR o.product_name LIKE ? OR task.serial_no LIKE ? OR process.name LIKE ?)")
            value = f"%{keyword}%"; params.extend([value, value, value, value, value])
        if date_from:
            where.append("task.created_at >= ?"); params.append(date_from)
        if date_to:
            where.append("task.created_at <= ?"); params.append(date_to + " 23:59:59")
        clause = " AND ".join(where) if where else "1=1"
        total = db.execute(
            "SELECT COUNT(*) FROM quality_inspection_tasks task "
            "LEFT JOIN orders o ON o.id=task.order_id LEFT JOIN processes process ON process.id=task.process_id "
            "WHERE " + clause,
            params,
        ).fetchone()[0]
        rows = db.execute(
            "SELECT task.*, o.order_no, o.product_name, o.product_code, process.name AS process_name, "
            "standard.standard_no, standard.name AS standard_name, assignee.name AS assigned_name, "
            "shipment.shipment_no, supplier.name AS supplier_name, material.name AS material_name, "
            "CASE WHEN task.status IN ('pending','in_progress') AND task.due_at != '' "
            "AND task.due_at < datetime('now','localtime') THEN 1 ELSE 0 END AS overdue "
            "FROM quality_inspection_tasks task "
            "LEFT JOIN orders o ON o.id=task.order_id LEFT JOIN processes process ON process.id=task.process_id "
            "LEFT JOIN quality_standards standard ON standard.id=task.standard_id "
            "LEFT JOIN users assignee ON assignee.id=task.assigned_to "
            "LEFT JOIN shipments shipment ON shipment.id=task.shipment_id "
            "LEFT JOIN suppliers supplier ON supplier.id=task.supplier_id "
            "LEFT JOIN materials material ON material.id=task.material_id "
            "WHERE " + clause + " ORDER BY overdue DESC, CASE task.priority WHEN 'urgent' THEN 0 ELSE 1 END, "
            "CASE task.status WHEN 'pending' THEN 0 WHEN 'in_progress' THEN 1 ELSE 2 END, task.id DESC "
            "LIMIT ? OFFSET ?",
            params + [limit, (page - 1) * limit],
        ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total, "page": page, "limit": limit}

    @staticmethod
    def task_by_id(task_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT task.*, o.order_no, o.product_name, o.product_code, process.name AS process_name, "
            "standard.standard_no, standard.name AS standard_name, standard.min_score, "
            "shipment.shipment_no, supplier.name AS supplier_name, material.name AS material_name "
            "FROM quality_inspection_tasks task "
            "LEFT JOIN orders o ON o.id=task.order_id LEFT JOIN processes process ON process.id=task.process_id "
            "LEFT JOIN quality_standards standard ON standard.id=task.standard_id "
            "LEFT JOIN shipments shipment ON shipment.id=task.shipment_id "
            "LEFT JOIN suppliers supplier ON supplier.id=task.supplier_id "
            "LEFT JOIN materials material ON material.id=task.material_id WHERE task.id=?",
            (task_id,),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["standard_items"] = [dict(item) for item in db.execute(
            "SELECT * FROM quality_standard_items WHERE standard_id=? ORDER BY sort_order,id",
            (result.get("standard_id"),),
        ).fetchall()] if result.get("standard_id") else []
        return result

    @staticmethod
    def mobile_inspection_context(order_id=None, order_no="", process_id=None, process_name="", db=None):
        db = resolve_db(db)
        where = "o.id=?" if order_id else "o.order_no=?"
        order_value = order_id if order_id else order_no
        if not order_value:
            return None
        params = [order_value]
        process_filter = ""
        if process_id:
            process_filter = " AND op.process_id=?"
            params.append(process_id)
        elif process_name:
            process_filter = " AND process.name=?"
            params.append(process_name)
        return db.execute(
            "SELECT o.id AS order_id,o.order_no,o.product_code,o.product_name,"
            "op.process_id,process.name AS process_name "
            "FROM orders o JOIN order_processes op ON op.order_id=o.id "
            "JOIN processes process ON process.id=op.process_id "
            f"WHERE {where} AND o.deleted_at IS NULL{process_filter} "
            "ORDER BY op.seq_order,op.id LIMIT 1",
            params,
        ).fetchone()

    @staticmethod
    def pending_mobile_task(order_id, process_id, serial_no="", db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id FROM quality_inspection_tasks WHERE order_id=? AND process_id=? "
            "AND shipment_id IS NULL AND status IN ('pending','in_progress') "
            "AND (serial_no='' OR serial_no=?) "
            "ORDER BY CASE WHEN serial_no!='' AND serial_no=? THEN 0 ELSE 1 END, "
            "CASE gate_mode WHEN 'hard' THEN 0 WHEN 'soft' THEN 1 ELSE 2 END, "
            "CASE priority WHEN 'urgent' THEN 0 ELSE 1 END,id LIMIT 1",
            (order_id, process_id, serial_no or "", serial_no or ""),
        ).fetchone()

    @staticmethod
    def start_task(task_id, user_id, db):
        return db.execute(
            "UPDATE quality_inspection_tasks SET status='in_progress', assigned_to=COALESCE(assigned_to,?), "
            "started_at=CASE WHEN started_at='' THEN datetime('now','localtime') ELSE started_at END, "
            "updated_at=datetime('now','localtime') WHERE id=? AND status='pending'",
            (user_id, task_id),
        ).rowcount

    @staticmethod
    def complete_task(task_id, inspection_id, status, user_id, db):
        db.execute(
            "UPDATE quality_inspection_tasks SET status=?, inspection_id=?, assigned_to=COALESCE(assigned_to,?), "
            "completed_at=datetime('now','localtime'), updated_at=datetime('now','localtime') WHERE id=?",
            (status, inspection_id, user_id, task_id),
        )

    @staticmethod
    def release_task(task_id, db):
        db.execute(
            "UPDATE quality_inspection_tasks SET status='passed', completed_at=COALESCE(NULLIF(completed_at,''),datetime('now','localtime')), "
            "updated_at=datetime('now','localtime') WHERE id=?",
            (task_id,),
        )

    @staticmethod
    def cancel_tasks_for_evaluation(evaluation_id, reason, db):
        return db.execute(
            "UPDATE quality_inspection_tasks SET status='cancelled', cancel_reason=?, "
            "cancelled_at=datetime('now','localtime'), "
            "completed_at=COALESCE(NULLIF(completed_at,''),datetime('now','localtime')), "
            "updated_at=datetime('now','localtime') WHERE source_evaluation_id=? "
            "AND status IN ('pending','in_progress','failed')",
            (reason, evaluation_id),
        ).rowcount

    @staticmethod
    def hard_report_gate(order_id, process_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT task.task_no, task.status, task.inspection_type, task.due_at "
            "FROM quality_inspection_tasks task WHERE task.order_id=? AND task.process_id=? "
            "AND task.inspection_type IN ('first_article','quality_verification') "
            "AND task.gate_mode='hard' "
            "AND task.status IN ('pending','in_progress','failed') ORDER BY task.id DESC LIMIT 1",
            (order_id, process_id),
        ).fetchone()

    @staticmethod
    def hard_completion_gate(order_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT task_no, status, inspection_type FROM quality_inspection_tasks "
            "WHERE order_id=? AND inspection_type!='outgoing' AND gate_mode='hard' "
            "AND status IN ('pending','in_progress','failed') ORDER BY id DESC LIMIT 1",
            (order_id,),
        ).fetchone()

    @staticmethod
    def hard_shipment_gate(shipment_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT task_no, status FROM quality_inspection_tasks WHERE shipment_id=? "
            "AND inspection_type='outgoing' AND gate_mode='hard' "
            "AND status IN ('pending','in_progress','failed') ORDER BY id DESC LIMIT 1",
            (shipment_id,),
        ).fetchone()

    @staticmethod
    def set_inventory_quality(order_id, status, reason, db):
        db.execute(
            "UPDATE inventory SET quality_status=?,quality_hold_reason=?,updated_at=datetime('now','localtime') "
            "WHERE order_id=?",
            (status, reason, order_id),
        )
