"""Persistence gateway for the quality management workflow."""

from modules.repositories.context import resolve_db


class QualityManagementRepository:
    @staticmethod
    def reference_data(db=None):
        db = resolve_db(db)
        return {
            "orders": [dict(row) for row in db.execute(
                "SELECT id, order_no, product_name, product_code, route_id FROM orders "
                "WHERE deleted_at IS NULL AND status IN ('pending','producing','completed') ORDER BY id DESC LIMIT 1000"
            ).fetchall()],
            "products": [dict(row) for row in db.execute(
                "SELECT id, product_code, product_name, route_id FROM products "
                "WHERE deleted_at IS NULL ORDER BY product_name"
            ).fetchall()],
            "routes": [dict(row) for row in db.execute(
                "SELECT id, name FROM process_routes WHERE status = 'active' ORDER BY name"
            ).fetchall()],
            "processes": [dict(row) for row in db.execute(
                "SELECT id, name FROM processes WHERE status = 'active' ORDER BY name"
            ).fetchall()],
            "users": [dict(row) for row in db.execute(
                "SELECT id, name, employee_no FROM users WHERE status = 'active' ORDER BY name"
            ).fetchall()],
            "suppliers": [dict(row) for row in db.execute(
                "SELECT id, name FROM suppliers ORDER BY name"
            ).fetchall()],
            "materials": [dict(row) for row in db.execute(
                "SELECT id, name, spec, supplier_id FROM materials ORDER BY name"
            ).fetchall()],
        }

    @staticmethod
    def list_standards(keyword="", status="", inspection_type="", page=1, limit=100, db=None):
        db = resolve_db(db)
        where = []
        params = []
        if keyword:
            where.append("(standard.standard_no LIKE ? OR standard.name LIKE ? OR standard.product_code LIKE ? OR process.name LIKE ?)")
            value = f"%{keyword}%"
            params.extend([value, value, value, value])
        if status:
            where.append("standard.status = ?")
            params.append(status)
        if inspection_type:
            where.append("standard.inspection_type = ?")
            params.append(inspection_type)
        clause = " AND ".join(where) if where else "1=1"
        total = db.execute(
            "SELECT COUNT(*) FROM quality_standards standard "
            "LEFT JOIN processes process ON process.id = standard.process_id WHERE " + clause,
            params,
        ).fetchone()[0]
        rows = db.execute(
            "SELECT standard.*, route.name AS route_name, process.name AS process_name, "
            "creator.name AS creator_name, COUNT(item.id) AS item_count "
            "FROM quality_standards standard "
            "LEFT JOIN process_routes route ON route.id = standard.route_id "
            "LEFT JOIN processes process ON process.id = standard.process_id "
            "LEFT JOIN users creator ON creator.id = standard.created_by "
            "LEFT JOIN quality_standard_items item ON item.standard_id = standard.id "
            "WHERE " + clause + " GROUP BY standard.id "
            "ORDER BY CASE standard.status WHEN 'active' THEN 0 ELSE 1 END, standard.updated_at DESC, standard.id DESC "
            "LIMIT ? OFFSET ?",
            params + [limit, (page - 1) * limit],
        ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total, "page": page, "limit": limit}

    @staticmethod
    def standard_by_id(standard_id, db=None):
        db = resolve_db(db)
        row = db.execute("SELECT * FROM quality_standards WHERE id = ?", (standard_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["items"] = [dict(item) for item in db.execute(
            "SELECT * FROM quality_standard_items WHERE standard_id = ? ORDER BY sort_order, id",
            (standard_id,),
        ).fetchall()]
        return result

    @staticmethod
    def default_standard(inspection_type, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM quality_standards WHERE inspection_type=? AND status='active' "
            "ORDER BY CASE WHEN product_code='' AND route_id IS NULL AND process_id IS NULL THEN 0 ELSE 1 END,id LIMIT 1",
            (inspection_type,),
        ).fetchone()

    @staticmethod
    def standard_no_exists(standard_no, exclude_id=None, db=None):
        db = resolve_db(db)
        if exclude_id:
            return db.execute(
                "SELECT id FROM quality_standards WHERE standard_no = ? AND id != ?",
                (standard_no, exclude_id),
            ).fetchone()
        return db.execute("SELECT id FROM quality_standards WHERE standard_no = ?", (standard_no,)).fetchone()

    @staticmethod
    def insert_standard(data, user_id, db):
        cursor = db.execute(
            "INSERT INTO quality_standards "
            "(standard_no, name, product_code, route_id, process_id, inspection_type, version, status, "
            "gate_mode, sampling_mode, sample_value, min_score, acceptance_rule, notes, created_by) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                data["standard_no"], data["name"], data.get("product_code", ""), data.get("route_id"),
                data.get("process_id"), data["inspection_type"], data.get("version", 1),
                data.get("status", "active"), data.get("gate_mode", "soft"),
                data.get("sampling_mode", "fixed"), data.get("sample_value", 1),
                data.get("min_score", 85), data.get("acceptance_rule", "all_required_pass"),
                data.get("notes", ""), user_id,
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def update_standard(standard_id, data, db):
        db.execute(
            "UPDATE quality_standards SET standard_no=?, name=?, product_code=?, route_id=?, process_id=?, "
            "inspection_type=?, version=?, status=?, gate_mode=?, sampling_mode=?, sample_value=?, "
            "min_score=?, acceptance_rule=?, notes=?, updated_at=datetime('now','localtime') WHERE id=?",
            (
                data["standard_no"], data["name"], data.get("product_code", ""), data.get("route_id"),
                data.get("process_id"), data["inspection_type"], data.get("version", 1),
                data.get("status", "active"), data.get("gate_mode", "soft"),
                data.get("sampling_mode", "fixed"), data.get("sample_value", 1),
                data.get("min_score", 85), data.get("acceptance_rule", "all_required_pass"),
                data.get("notes", ""), standard_id,
            ),
        )

    @staticmethod
    def replace_standard_items(standard_id, items, db):
        db.execute("DELETE FROM quality_standard_items WHERE standard_id = ?", (standard_id,))
        for index, item in enumerate(items):
            db.execute(
                "INSERT INTO quality_standard_items "
                "(standard_id, item_code, item_name, item_type, unit, nominal_value, lower_limit, upper_limit, "
                "required, weight, inspection_method, acceptance_criteria, sort_order) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    standard_id, item["item_code"], item["item_name"], item.get("item_type", "boolean"),
                    item.get("unit", ""), item.get("nominal_value", ""), item.get("lower_limit", ""),
                    item.get("upper_limit", ""), 1 if item.get("required", True) else 0,
                    item.get("weight", 0), item.get("inspection_method", ""),
                    item.get("acceptance_criteria", ""), item.get("sort_order", (index + 1) * 10),
                ),
            )

    @staticmethod
    def archive_standard(standard_id, db):
        db.execute(
            "UPDATE quality_standards SET status='inactive', updated_at=datetime('now','localtime') WHERE id=?",
            (standard_id,),
        )

    @staticmethod
    def list_plans(keyword="", status="", page=1, limit=100, db=None):
        db = resolve_db(db)
        where = []
        params = []
        if keyword:
            where.append("(plan.name LIKE ? OR standard.name LIKE ? OR plan.product_code LIKE ? OR process.name LIKE ?)")
            value = f"%{keyword}%"
            params.extend([value, value, value, value])
        if status:
            where.append("plan.status = ?")
            params.append(status)
        clause = " AND ".join(where) if where else "1=1"
        total = db.execute(
            "SELECT COUNT(*) FROM quality_inspection_plans plan "
            "LEFT JOIN quality_standards standard ON standard.id=plan.standard_id "
            "LEFT JOIN processes process ON process.id=plan.process_id WHERE " + clause,
            params,
        ).fetchone()[0]
        rows = db.execute(
            "SELECT plan.*, standard.standard_no, standard.name AS standard_name, "
            "route.name AS route_name, process.name AS process_name "
            "FROM quality_inspection_plans plan "
            "LEFT JOIN quality_standards standard ON standard.id=plan.standard_id "
            "LEFT JOIN process_routes route ON route.id=plan.route_id "
            "LEFT JOIN processes process ON process.id=plan.process_id "
            "WHERE " + clause + " ORDER BY CASE plan.status WHEN 'active' THEN 0 ELSE 1 END, plan.id DESC "
            "LIMIT ? OFFSET ?",
            params + [limit, (page - 1) * limit],
        ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total, "page": page, "limit": limit}

    @staticmethod
    def plan_by_id(plan_id, db=None):
        db = resolve_db(db)
        return db.execute("SELECT * FROM quality_inspection_plans WHERE id=?", (plan_id,)).fetchone()

    @staticmethod
    def insert_plan(data, user_id, db):
        cursor = db.execute(
            "INSERT INTO quality_inspection_plans "
            "(name, standard_id, product_code, route_id, process_id, trigger_type, inspection_type, "
            "gate_mode, sampling_mode, sample_value, frequency_qty, due_minutes, status, created_by) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                data["name"], data.get("standard_id"), data.get("product_code", ""), data.get("route_id"),
                data.get("process_id"), data["trigger_type"], data["inspection_type"],
                data.get("gate_mode", "soft"), data.get("sampling_mode", "fixed"),
                data.get("sample_value", 1), data.get("frequency_qty", 0), data.get("due_minutes", 120),
                data.get("status", "active"), user_id,
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def update_plan(plan_id, data, db):
        db.execute(
            "UPDATE quality_inspection_plans SET name=?, standard_id=?, product_code=?, route_id=?, process_id=?, "
            "trigger_type=?, inspection_type=?, gate_mode=?, sampling_mode=?, sample_value=?, frequency_qty=?, "
            "due_minutes=?, status=?, updated_at=datetime('now','localtime') WHERE id=?",
            (
                data["name"], data.get("standard_id"), data.get("product_code", ""), data.get("route_id"),
                data.get("process_id"), data["trigger_type"], data["inspection_type"],
                data.get("gate_mode", "soft"), data.get("sampling_mode", "fixed"),
                data.get("sample_value", 1), data.get("frequency_qty", 0), data.get("due_minutes", 120),
                data.get("status", "active"), plan_id,
            ),
        )

    @staticmethod
    def archive_plan(plan_id, db):
        db.execute(
            "UPDATE quality_inspection_plans SET status='inactive', updated_at=datetime('now','localtime') WHERE id=?",
            (plan_id,),
        )

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

    @staticmethod
    def insert_inspection(data, user_id, db):
        cursor = db.execute(
            "INSERT INTO quality_inspections "
            "(order_id, process_id, inspection_type, inspector_id, quantity_checked, quantity_passed, "
            "quantity_failed, result, defect_category, defect_quantity, notes, inspected_at, order_no, "
            "product_code, process_name, inspector_name, serial_no, score_total, score_detail_json, "
            "defect_level, defect_items_json, suggested_result, final_result, override_reason, task_id, "
            "standard_id, standard_version, measurements_json, quality_status, batch_no, scope_type, "
            "reviewed_by, reviewed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                data.get("order_id"), data.get("process_id"), data["inspection_type"], user_id,
                data.get("quantity_checked", 0), data.get("quantity_passed", 0), data.get("quantity_failed", 0),
                data["result"], data.get("defect_category", ""), data.get("defect_quantity", 0),
                data.get("notes", ""), data.get("inspected_at"), data.get("order_no", ""),
                data.get("product_code", ""), data.get("process_name", ""), data.get("inspector_name", ""),
                data.get("serial_no", ""), data.get("score_total", 0), data.get("score_detail_json", "{}"),
                data.get("defect_level", ""), data.get("defect_items_json", "[]"), data.get("suggested_result", ""),
                data.get("final_result", ""), data.get("override_reason", ""), data.get("task_id"),
                data.get("standard_id"), data.get("standard_version", 1), data.get("measurements_json", "[]"),
                data.get("quality_status", "pending"), data.get("batch_no", ""), data.get("scope_type", "production"),
                user_id, data.get("inspected_at"),
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def list_inspections(keyword="", result="", inspection_type="", page=1, limit=100, db=None):
        db = resolve_db(db)
        where = []
        params = []
        if keyword:
            where.append("(o.order_no LIKE ? OR o.product_name LIKE ? OR process.name LIKE ? OR qi.serial_no LIKE ?)")
            value = f"%{keyword}%"; params.extend([value, value, value, value])
        if result:
            where.append("qi.result=?"); params.append(result)
        if inspection_type:
            where.append("qi.inspection_type=?"); params.append(inspection_type)
        clause = " AND ".join(where) if where else "1=1"
        total = db.execute(
            "SELECT COUNT(*) FROM quality_inspections qi LEFT JOIN orders o ON o.id=qi.order_id "
            "LEFT JOIN processes process ON process.id=qi.process_id WHERE " + clause,
            params,
        ).fetchone()[0]
        rows = db.execute(
            "SELECT qi.*, o.order_no, o.product_name, o.product_code, process.name AS process_name, "
            "inspector.name AS inspector_name, task.task_no, standard.standard_no, ncr.id AS ncr_id, ncr.ncr_no, ncr.status AS ncr_status "
            "FROM quality_inspections qi LEFT JOIN orders o ON o.id=qi.order_id "
            "LEFT JOIN processes process ON process.id=qi.process_id LEFT JOIN users inspector ON inspector.id=qi.inspector_id "
            "LEFT JOIN quality_inspection_tasks task ON task.id=qi.task_id "
            "LEFT JOIN quality_standards standard ON standard.id=qi.standard_id "
            "LEFT JOIN quality_nonconformances ncr ON ncr.inspection_id=qi.id "
            "WHERE " + clause + " ORDER BY COALESCE(qi.inspected_at,qi.created_at) DESC, qi.id DESC LIMIT ? OFFSET ?",
            params + [limit, (page - 1) * limit],
        ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total, "page": page, "limit": limit}

    @staticmethod
    def inspection_by_id(inspection_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT qi.*, o.order_no, o.product_name, o.product_code, "
            "process.name AS process_name, inspector.name AS inspector_name, "
            "reviewer.name AS reviewer_name, task.task_no, standard.standard_no "
            "FROM quality_inspections qi LEFT JOIN orders o ON o.id=qi.order_id "
            "LEFT JOIN processes process ON process.id=qi.process_id "
            "LEFT JOIN users inspector ON inspector.id=qi.inspector_id "
            "LEFT JOIN users reviewer ON reviewer.id=qi.reviewed_by "
            "LEFT JOIN quality_inspection_tasks task ON task.id=qi.task_id "
            "LEFT JOIN quality_standards standard ON standard.id=qi.standard_id "
            "WHERE qi.id=?",
            (inspection_id,),
        ).fetchone()

    @staticmethod
    def review_inspection(inspection_id, status, note, reviewer_id, quality_status, db):
        db.execute(
            "UPDATE quality_inspections SET review_status=?, review_note=?, reviewed_by=?, "
            "reviewed_at=datetime('now','localtime'), quality_status=?, updated_at=datetime('now','localtime') "
            "WHERE id=?",
            (status, note, reviewer_id, quality_status, inspection_id),
        )

    @staticmethod
    def reject_task_for_review(task_id, db):
        if task_id:
            db.execute(
                "UPDATE quality_inspection_tasks SET status='failed', "
                "updated_at=datetime('now','localtime') WHERE id=?",
                (task_id,),
            )

    @staticmethod
    def insert_ncr(data, user_id, db):
        cursor = db.execute(
            "INSERT INTO quality_nonconformances "
            "(ncr_no, task_id, inspection_id, order_id, process_id, serial_no, supplier_id, material_id, "
            "defect_category, defect_level, defect_quantity, description, disposition, status, "
            "responsible_user_id, responsible_process_id, owner_id, due_at, source_type, created_by) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                data["ncr_no"], data.get("task_id"), data.get("inspection_id"), data.get("order_id"),
                data.get("process_id"), data.get("serial_no", ""), data.get("supplier_id"), data.get("material_id"),
                data.get("defect_category", ""), data.get("defect_level", ""), data.get("defect_quantity", 0),
                data.get("description", ""), data.get("disposition", "pending"), data.get("status", "open"),
                data.get("responsible_user_id"), data.get("responsible_process_id"), data.get("owner_id"),
                data.get("due_at", ""), data.get("source_type", "inspection"), user_id,
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def list_ncr(status="", disposition="", keyword="", page=1, limit=100, db=None):
        db = resolve_db(db)
        where = []
        params = []
        if status:
            where.append("ncr.status=?"); params.append(status)
        if disposition:
            where.append("ncr.disposition=?"); params.append(disposition)
        if keyword:
            where.append("(ncr.ncr_no LIKE ? OR o.order_no LIKE ? OR process.name LIKE ? OR ncr.description LIKE ?)")
            value = f"%{keyword}%"; params.extend([value, value, value, value])
        clause = " AND ".join(where) if where else "1=1"
        total = db.execute(
            "SELECT COUNT(*) FROM quality_nonconformances ncr LEFT JOIN orders o ON o.id=ncr.order_id "
            "LEFT JOIN processes process ON process.id=ncr.process_id WHERE " + clause,
            params,
        ).fetchone()[0]
        rows = db.execute(
            "SELECT ncr.*, o.order_no, o.product_name, process.name AS process_name, "
            "responsible.name AS responsible_user_name, owner.name AS owner_name, supplier.name AS supplier_name, "
            "material.name AS material_name, task.task_no "
            "FROM quality_nonconformances ncr LEFT JOIN orders o ON o.id=ncr.order_id "
            "LEFT JOIN processes process ON process.id=ncr.process_id "
            "LEFT JOIN users responsible ON responsible.id=ncr.responsible_user_id "
            "LEFT JOIN users owner ON owner.id=ncr.owner_id LEFT JOIN suppliers supplier ON supplier.id=ncr.supplier_id "
            "LEFT JOIN materials material ON material.id=ncr.material_id "
            "LEFT JOIN quality_inspection_tasks task ON task.id=ncr.task_id "
            "WHERE " + clause + " ORDER BY CASE ncr.status WHEN 'open' THEN 0 WHEN 'processing' THEN 1 "
            "WHEN 'pending_reinspection' THEN 2 ELSE 3 END, ncr.id DESC LIMIT ? OFFSET ?",
            params + [limit, (page - 1) * limit],
        ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total, "page": page, "limit": limit}

    @staticmethod
    def ncr_by_id(ncr_id, db=None):
        db = resolve_db(db)
        return db.execute("SELECT * FROM quality_nonconformances WHERE id=?", (ncr_id,)).fetchone()

    @staticmethod
    def ncr_by_inspection(inspection_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM quality_nonconformances WHERE inspection_id=? ORDER BY id DESC LIMIT 1",
            (inspection_id,),
        ).fetchone()

    @staticmethod
    def ncr_detail(ncr_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT ncr.*, o.order_no, o.product_name, o.product_code, process.name AS process_name, "
            "responsible.name AS responsible_user_name, owner.name AS owner_name, "
            "supplier.name AS supplier_name, material.name AS material_name "
            "FROM quality_nonconformances ncr LEFT JOIN orders o ON o.id=ncr.order_id "
            "LEFT JOIN processes process ON process.id=ncr.process_id "
            "LEFT JOIN users responsible ON responsible.id=ncr.responsible_user_id "
            "LEFT JOIN users owner ON owner.id=ncr.owner_id "
            "LEFT JOIN suppliers supplier ON supplier.id=ncr.supplier_id "
            "LEFT JOIN materials material ON material.id=ncr.material_id "
            "WHERE ncr.id=?",
            (ncr_id,),
        ).fetchone()
        if not row:
            return None
        actions = db.execute(
            "SELECT action_log.action, action_log.from_status, action_log.to_status, action_log.note, "
            "action_log.actor_id, actor.name AS actor_name, action_log.created_at AS created_at "
            "FROM quality_nonconformance_actions action_log "
            "LEFT JOIN users actor ON actor.id=action_log.actor_id "
            "WHERE ncr_id=? ORDER BY action_log.id DESC",
            (ncr_id,),
        ).fetchall()
        result = dict(row)
        result["actions"] = [dict(action) for action in actions]
        return result

    @staticmethod
    def update_ncr(ncr_id, data, db):
        db.execute(
            "UPDATE quality_nonconformances SET disposition=?, status=?, responsible_user_id=?, "
            "responsible_process_id=?, owner_id=?, due_at=?, root_cause=?, corrective_action=?, "
            "verification_result=?, closed_by=?, closed_at=?, updated_at=datetime('now','localtime') WHERE id=?",
            (
                data.get("disposition", "pending"), data.get("status", "open"), data.get("responsible_user_id"),
                data.get("responsible_process_id"), data.get("owner_id"), data.get("due_at", ""),
                data.get("root_cause", ""), data.get("corrective_action", ""),
                data.get("verification_result", ""), data.get("closed_by"), data.get("closed_at", ""), ncr_id,
            ),
        )

    @staticmethod
    def add_ncr_action(ncr_id, action, from_status, to_status, note, actor_id, db):
        db.execute(
            "INSERT INTO quality_nonconformance_actions (ncr_id,action,from_status,to_status,note,actor_id) "
            "VALUES (?,?,?,?,?,?)",
            (ncr_id, action, from_status, to_status, note, actor_id),
        )

    @staticmethod
    def insert_rework_for_ncr(ncr, user_id, db):
        cursor = db.execute(
            "INSERT INTO rework_records (order_id,process_id,user_id,quantity,reason,status,source_ncr_id) VALUES (?,?,?,?,?,'pending',?)",
            (
                ncr["order_id"], ncr["process_id"], ncr.get("responsible_user_id") or user_id,
                max(int(ncr.get("defect_quantity") or 1), 1), f"质量不合格单 {ncr['ncr_no']} 返修", ncr["id"],
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def list_capa(status="", keyword="", page=1, limit=100, db=None):
        db = resolve_db(db)
        where = []
        params = []
        if status:
            where.append("capa.status=?"); params.append(status)
        if keyword:
            where.append("(capa.capa_no LIKE ? OR capa.title LIKE ? OR ncr.ncr_no LIKE ?)")
            value = f"%{keyword}%"; params.extend([value, value, value])
        clause = " AND ".join(where) if where else "1=1"
        total = db.execute(
            "SELECT COUNT(*) FROM quality_capa_records capa LEFT JOIN quality_nonconformances ncr ON ncr.id=capa.ncr_id WHERE " + clause,
            params,
        ).fetchone()[0]
        rows = db.execute(
            "SELECT capa.*, ncr.ncr_no, owner.name AS owner_name, verifier.name AS verifier_name, "
            "CASE WHEN capa.status NOT IN ('closed','verified') AND capa.due_at != '' "
            "AND capa.due_at < date('now','localtime') THEN 1 ELSE 0 END AS overdue "
            "FROM quality_capa_records capa LEFT JOIN quality_nonconformances ncr ON ncr.id=capa.ncr_id "
            "LEFT JOIN users owner ON owner.id=capa.owner_id LEFT JOIN users verifier ON verifier.id=capa.verified_by "
            "WHERE " + clause + " ORDER BY overdue DESC, capa.id DESC LIMIT ? OFFSET ?",
            params + [limit, (page - 1) * limit],
        ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total, "page": page, "limit": limit}

    @staticmethod
    def capa_by_id(capa_id, db=None):
        db = resolve_db(db)
        return db.execute("SELECT * FROM quality_capa_records WHERE id=?", (capa_id,)).fetchone()

    @staticmethod
    def insert_capa(data, user_id, db):
        cursor = db.execute(
            "INSERT INTO quality_capa_records "
            "(capa_no,ncr_id,title,problem_description,root_cause,corrective_action,preventive_action,owner_id,due_at,status,created_by) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                data["capa_no"], data.get("ncr_id"), data["title"], data.get("problem_description", ""),
                data.get("root_cause", ""), data.get("corrective_action", ""), data.get("preventive_action", ""),
                data.get("owner_id"), data.get("due_at", ""), data.get("status", "open"), user_id,
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def update_capa(capa_id, data, user_id, db):
        db.execute(
            "UPDATE quality_capa_records SET ncr_id=?,title=?,problem_description=?,root_cause=?,corrective_action=?, "
            "preventive_action=?,owner_id=?,due_at=?,status=?,effectiveness_result=?,verified_by=?,"
            "verified_at=CASE WHEN ? IN ('verified','closed') "
            "THEN COALESCE(NULLIF(verified_at,''),datetime('now','localtime')) ELSE '' END, "
            "updated_at=datetime('now','localtime') WHERE id=?",
            (
                data.get("ncr_id"), data["title"], data.get("problem_description", ""), data.get("root_cause", ""),
                data.get("corrective_action", ""), data.get("preventive_action", ""), data.get("owner_id"),
                data.get("due_at", ""), data.get("status", "open"), data.get("effectiveness_result", ""),
                user_id if data.get("status") in {"verified", "closed"} else data.get("verified_by"),
                data.get("status", "open"), capa_id,
            ),
        )

    @staticmethod
    def list_supplier_inspections(keyword="", result="", page=1, limit=100, db=None):
        db = resolve_db(db)
        where = []
        params = []
        if keyword:
            where.append("(supplier.name LIKE ? OR material.name LIKE ? OR inspection.batch_no LIKE ? OR inspection.delivery_no LIKE ?)")
            value = f"%{keyword}%"; params.extend([value, value, value, value])
        if result:
            where.append("inspection.result=?"); params.append(result)
        clause = " AND ".join(where) if where else "1=1"
        total = db.execute(
            "SELECT COUNT(*) FROM quality_supplier_inspections inspection "
            "JOIN suppliers supplier ON supplier.id=inspection.supplier_id "
            "LEFT JOIN materials material ON material.id=inspection.material_id WHERE " + clause,
            params,
        ).fetchone()[0]
        rows = db.execute(
            "SELECT inspection.*, supplier.name AS supplier_name, material.name AS material_name, "
            "material.spec AS material_spec, inspector.name AS inspector_name, ncr.ncr_no "
            "FROM quality_supplier_inspections inspection JOIN suppliers supplier ON supplier.id=inspection.supplier_id "
            "LEFT JOIN materials material ON material.id=inspection.material_id "
            "LEFT JOIN users inspector ON inspector.id=inspection.inspector_id "
            "LEFT JOIN quality_nonconformances ncr ON ncr.id=inspection.ncr_id "
            "WHERE " + clause + " ORDER BY inspection.inspected_at DESC, inspection.id DESC LIMIT ? OFFSET ?",
            params + [limit, (page - 1) * limit],
        ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total, "page": page, "limit": limit}

    @staticmethod
    def insert_supplier_inspection(data, user_id, db):
        cursor = db.execute(
            "INSERT INTO quality_supplier_inspections "
            "(supplier_id,material_id,batch_no,delivery_no,quantity_checked,quantity_passed,quantity_failed,"
            "result,score_total,defect_category,defect_level,notes,inspector_id,inspected_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,COALESCE(NULLIF(?,''),datetime('now','localtime')))",
            (
                data["supplier_id"], data.get("material_id"), data.get("batch_no", ""), data.get("delivery_no", ""),
                data.get("quantity_checked", 0), data.get("quantity_passed", 0), data.get("quantity_failed", 0),
                data["result"], data.get("score_total", 0), data.get("defect_category", ""),
                data.get("defect_level", ""), data.get("notes", ""), user_id, data.get("inspected_at", ""),
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def attach_supplier_ncr(inspection_id, ncr_id, db):
        db.execute("UPDATE quality_supplier_inspections SET ncr_id=? WHERE id=?", (ncr_id, inspection_id))

    @staticmethod
    def supplier_quality_stats(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT supplier.id AS supplier_id, supplier.name AS supplier_name, COUNT(inspection.id) AS inspection_count, "
            "COALESCE(SUM(inspection.quantity_checked),0) AS checked_qty, "
            "COALESCE(SUM(inspection.quantity_failed),0) AS failed_qty, "
            "COALESCE(SUM(CASE WHEN inspection.result='pass' THEN 1 ELSE 0 END),0) AS pass_count, "
            "ROUND(AVG(NULLIF(inspection.score_total,0)),1) AS avg_score "
            "FROM suppliers supplier LEFT JOIN quality_supplier_inspections inspection ON inspection.supplier_id=supplier.id "
            "GROUP BY supplier.id ORDER BY failed_qty DESC, inspection_count DESC, supplier.name"
        ).fetchall()

    @staticmethod
    def list_gauges(keyword="", status="", page=1, limit=100, db=None):
        db = resolve_db(db)
        where = []
        params = []
        if keyword:
            where.append("(gauge.gauge_no LIKE ? OR gauge.name LIKE ? OR gauge.model LIKE ?)")
            value = f"%{keyword}%"; params.extend([value, value, value])
        if status:
            where.append("gauge.status=?"); params.append(status)
        clause = " AND ".join(where) if where else "1=1"
        total = db.execute("SELECT COUNT(*) FROM quality_gauges gauge WHERE " + clause, params).fetchone()[0]
        rows = db.execute(
            "SELECT gauge.*, owner.name AS owner_name, CASE WHEN gauge.status='active' AND gauge.next_calibration_at!='' "
            "AND gauge.next_calibration_at < date('now','localtime') THEN 1 ELSE 0 END AS overdue "
            "FROM quality_gauges gauge LEFT JOIN users owner ON owner.id=gauge.owner_id WHERE " + clause +
            " ORDER BY overdue DESC, gauge.next_calibration_at, gauge.id DESC LIMIT ? OFFSET ?",
            params + [limit, (page - 1) * limit],
        ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total, "page": page, "limit": limit}

    @staticmethod
    def gauge_by_id(gauge_id, db=None):
        db = resolve_db(db)
        return db.execute("SELECT * FROM quality_gauges WHERE id=?", (gauge_id,)).fetchone()

    @staticmethod
    def insert_gauge(data, user_id, db):
        cursor = db.execute(
            "INSERT INTO quality_gauges "
            "(gauge_no,name,model,measurement_range,accuracy,location,calibration_cycle_days,last_calibrated_at,"
            "next_calibration_at,status,owner_id,certificate_no,remark,created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                data["gauge_no"], data["name"], data.get("model", ""), data.get("measurement_range", ""),
                data.get("accuracy", ""), data.get("location", ""), data.get("calibration_cycle_days", 365),
                data.get("last_calibrated_at", ""), data.get("next_calibration_at", ""), data.get("status", "active"),
                data.get("owner_id"), data.get("certificate_no", ""), data.get("remark", ""), user_id,
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def update_gauge(gauge_id, data, db):
        db.execute(
            "UPDATE quality_gauges SET gauge_no=?,name=?,model=?,measurement_range=?,accuracy=?,location=?,"
            "calibration_cycle_days=?,status=?,owner_id=?,remark=?,updated_at=datetime('now','localtime') WHERE id=?",
            (
                data["gauge_no"], data["name"], data.get("model", ""), data.get("measurement_range", ""),
                data.get("accuracy", ""), data.get("location", ""), data.get("calibration_cycle_days", 365),
                data.get("status", "active"), data.get("owner_id"), data.get("remark", ""), gauge_id,
            ),
        )

    @staticmethod
    def insert_calibration(gauge_id, data, user_id, db):
        cursor = db.execute(
            "INSERT INTO quality_gauge_calibrations "
            "(gauge_id,calibrated_at,next_calibration_at,result,certificate_no,organization,notes,operator_id) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                gauge_id, data["calibrated_at"], data["next_calibration_at"], data["result"],
                data.get("certificate_no", ""), data.get("organization", ""), data.get("notes", ""), user_id,
            ),
        )
        status = "active" if data["result"] == "pass" else "suspended"
        db.execute(
            "UPDATE quality_gauges SET last_calibrated_at=?,next_calibration_at=?,status=?,certificate_no=?,"
            "updated_at=datetime('now','localtime') WHERE id=?",
            (data["calibrated_at"], data["next_calibration_at"], status, data.get("certificate_no", ""), gauge_id),
        )
        return cursor.lastrowid

    @staticmethod
    def dashboard(db=None):
        db = resolve_db(db)
        task = db.execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END),0) AS pending, "
            "COALESCE(SUM(CASE WHEN status='in_progress' THEN 1 ELSE 0 END),0) AS in_progress, "
            "COALESCE(SUM(CASE WHEN status IN ('pending','in_progress') AND due_at!='' "
            "AND due_at<datetime('now','localtime') THEN 1 ELSE 0 END),0) AS overdue "
            "FROM quality_inspection_tasks"
        ).fetchone()
        inspection = db.execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(CASE WHEN result='pass' THEN 1 ELSE 0 END),0) AS passed, "
            "COALESCE(SUM(quantity_checked),0) AS checked, COALESCE(SUM(quantity_failed),0) AS failed, "
            "COALESCE(ROUND(AVG(NULLIF(score_total,0)),1),0) AS avg_score FROM quality_inspections"
        ).fetchone()
        ncr = db.execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(CASE WHEN status NOT IN ('closed','cancelled') THEN 1 ELSE 0 END),0) AS open, "
            "COALESCE(SUM(CASE WHEN status='pending_reinspection' THEN 1 ELSE 0 END),0) AS pending_reinspection, "
            "COALESCE(SUM(CASE WHEN status NOT IN ('closed','cancelled') AND due_at!='' "
            "AND DATE(due_at)<DATE('now','localtime') THEN 1 ELSE 0 END),0) AS overdue "
            "FROM quality_nonconformances"
        ).fetchone()
        review_pending = db.execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(CASE WHEN result='pass' THEN 1 ELSE 0 END),0) AS passed, "
            "COALESCE(SUM(CASE WHEN result!='pass' THEN 1 ELSE 0 END),0) AS nonconforming "
            "FROM quality_inspections WHERE COALESCE(review_status,'unreviewed')='unreviewed'"
        ).fetchone()
        quality_holds = db.execute(
            "SELECT COUNT(*) AS total, "
            "COALESCE(SUM(CASE WHEN quality_status='quarantined' THEN 1 ELSE 0 END),0) AS quarantined, "
            "COALESCE(SUM(CASE WHEN quality_status='nonconforming' THEN 1 ELSE 0 END),0) AS nonconforming "
            "FROM inventory WHERE quality_status IN ('quarantined','nonconforming')"
        ).fetchone()
        capa = db.execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(CASE WHEN status NOT IN ('closed','verified') THEN 1 ELSE 0 END),0) AS open, "
            "COALESCE(SUM(CASE WHEN status NOT IN ('closed','verified') AND due_at!='' "
            "AND due_at<date('now','localtime') THEN 1 ELSE 0 END),0) AS overdue "
            "FROM quality_capa_records"
        ).fetchone()
        gauges = db.execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(CASE WHEN status='active' AND next_calibration_at!='' "
            "AND next_calibration_at<date('now','localtime') THEN 1 ELSE 0 END),0) AS overdue FROM quality_gauges"
        ).fetchone()
        recent_tasks = db.execute(
            "SELECT task.task_no,task.inspection_type,task.status,task.due_at,o.order_no,process.name AS process_name "
            "FROM quality_inspection_tasks task LEFT JOIN orders o ON o.id=task.order_id "
            "LEFT JOIN processes process ON process.id=task.process_id "
            "WHERE task.status IN ('pending','in_progress') ORDER BY CASE WHEN task.due_at!='' AND task.due_at<datetime('now','localtime') THEN 0 ELSE 1 END,task.id DESC LIMIT 10"
        ).fetchall()
        open_ncr = db.execute(
            "SELECT ncr.ncr_no,ncr.defect_level,ncr.status,ncr.due_at,o.order_no,process.name AS process_name, "
            "CASE WHEN ncr.due_at!='' AND DATE(ncr.due_at)<DATE('now','localtime') THEN 1 ELSE 0 END AS overdue "
            "FROM quality_nonconformances ncr LEFT JOIN orders o ON o.id=ncr.order_id "
            "LEFT JOIN processes process ON process.id=ncr.process_id WHERE ncr.status NOT IN ('closed','cancelled') "
            "ORDER BY ncr.id DESC LIMIT 10"
        ).fetchall()
        pending_reviews = db.execute(
            "SELECT qi.id,qi.result,qi.score_total,qi.inspected_at,task.task_no,o.order_no, "
            "process.name AS process_name,inspector.name AS inspector_name "
            "FROM quality_inspections qi LEFT JOIN quality_inspection_tasks task ON task.id=qi.task_id "
            "LEFT JOIN orders o ON o.id=qi.order_id LEFT JOIN processes process ON process.id=qi.process_id "
            "LEFT JOIN users inspector ON inspector.id=qi.inspector_id "
            "WHERE COALESCE(qi.review_status,'unreviewed')='unreviewed' "
            "ORDER BY qi.inspected_at DESC,qi.id DESC LIMIT 10"
        ).fetchall()
        checked = int(inspection["checked"] or 0)
        failed = int(inspection["failed"] or 0)
        return {
            "tasks": dict(task), "inspections": dict(inspection), "ncr": dict(ncr),
            "review_pending": dict(review_pending), "quality_holds": dict(quality_holds),
            "capa": dict(capa), "gauges": dict(gauges),
            "pass_rate": round((checked - failed) / checked * 100, 1) if checked else 0,
            "recent_tasks": [dict(row) for row in recent_tasks],
            "open_ncr": [dict(row) for row in open_ncr],
            "pending_reviews": [dict(row) for row in pending_reviews],
        }

    @staticmethod
    def analytics(date_from="", date_to="", db=None):
        db = resolve_db(db)
        where = []
        params = []
        if date_from:
            where.append("DATE(qi.inspected_at)>=?"); params.append(date_from)
        if date_to:
            where.append("DATE(qi.inspected_at)<=?"); params.append(date_to)
        clause = " AND ".join(where) if where else "1=1"
        trend = db.execute(
            "SELECT DATE(qi.inspected_at) AS date,COALESCE(SUM(qi.quantity_checked),0) AS checked,"
            "COALESCE(SUM(qi.quantity_failed),0) AS failed,ROUND(AVG(NULLIF(qi.score_total,0)),1) AS avg_score "
            "FROM quality_inspections qi WHERE " + clause + " GROUP BY DATE(qi.inspected_at) ORDER BY date",
            params,
        ).fetchall()
        pareto = db.execute(
            "SELECT COALESCE(NULLIF(qi.defect_category,''),'其他') AS category,COUNT(*) AS records,"
            "COALESCE(SUM(qi.defect_quantity),0) AS quantity FROM quality_inspections qi WHERE " + clause +
            " AND qi.result!='pass' GROUP BY category ORDER BY quantity DESC,records DESC LIMIT 10",
            params,
        ).fetchall()
        processes = db.execute(
            "SELECT process.id AS process_id,process.name AS process_name,COUNT(qi.id) AS inspections,"
            "COALESCE(SUM(qi.quantity_checked),0) AS checked,COALESCE(SUM(qi.quantity_failed),0) AS failed,"
            "ROUND(AVG(NULLIF(qi.score_total,0)),1) AS avg_score FROM quality_inspections qi "
            "JOIN processes process ON process.id=qi.process_id WHERE " + clause +
            " GROUP BY process.id ORDER BY failed DESC,inspections DESC LIMIT 20",
            params,
        ).fetchall()
        return {
            "trend": [dict(row) for row in trend],
            "pareto": [dict(row) for row in pareto],
            "processes": [dict(row) for row in processes],
            "suppliers": [dict(row) for row in QualityManagementRepository.supplier_quality_stats(db=db)],
        }
