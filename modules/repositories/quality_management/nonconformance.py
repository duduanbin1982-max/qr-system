"""QualityNonconformanceRepository quality persistence subdomain."""

from modules.repositories.context import resolve_db
from modules.process_fact_projection import (
    capture_process_fact_binding,
    process_value_sql,
    process_version_join,
    warn_legacy_fact_rows,
)


class QualityNonconformanceRepository:
    @staticmethod
    def insert_ncr(data, user_id, db):
        binding = None
        source_table = None
        source_id = None
        if data.get("inspection_id"):
            source_table = "quality_inspections"
            source_id = data["inspection_id"]
        elif data.get("task_id"):
            source_table = "quality_inspection_tasks"
            source_id = data["task_id"]
        if source_table:
            source = db.execute(
                "SELECT process_id,process_version_id,process_code_snapshot,process_name_snapshot,"
                "process_category_snapshot,route_id,route_version_id,route_name_snapshot "
                f"FROM {source_table} WHERE id=?",
                (source_id,),
            ).fetchone()
            if source:
                binding = dict(source)
        if not binding or binding.get("process_version_id") is None:
            binding = capture_process_fact_binding(
                db,
                order_id=data.get("order_id"),
                process_id=data.get("process_id"),
            )
        responsible_binding = capture_process_fact_binding(
            db,
            order_id=data.get("order_id"),
            process_id=data.get("responsible_process_id"),
            route_id=binding.get("route_id"),
        )
        cursor = db.execute(
            "INSERT INTO quality_nonconformances "
            "(ncr_no, task_id, inspection_id, order_id, process_id, serial_no, supplier_id, material_id, "
            "defect_category, defect_level, defect_quantity, description, disposition, status, "
            "responsible_user_id, responsible_process_id, owner_id, due_at, source_type, created_by, "
            "process_version_id,process_code_snapshot,process_name_snapshot,process_category_snapshot,"
            "responsible_process_version_id,responsible_process_code_snapshot,responsible_process_name_snapshot,"
            "responsible_process_category_snapshot,route_id,route_version_id,route_name_snapshot,version_binding_source) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                data["ncr_no"], data.get("task_id"), data.get("inspection_id"), data.get("order_id"),
                data.get("process_id"), data.get("serial_no", ""), data.get("supplier_id"), data.get("material_id"),
                data.get("defect_category", ""), data.get("defect_level", ""), data.get("defect_quantity", 0),
                data.get("description", ""), data.get("disposition", "pending"), data.get("status", "open"),
                data.get("responsible_user_id"), data.get("responsible_process_id"), data.get("owner_id"),
                data.get("due_at", ""), data.get("source_type", "inspection"), user_id,
                binding.get("process_version_id"), binding.get("process_code_snapshot", ""),
                binding.get("process_name_snapshot", ""), binding.get("process_category_snapshot", ""),
                responsible_binding.get("process_version_id"), responsible_binding.get("process_code_snapshot", ""),
                responsible_binding.get("process_name_snapshot", ""), responsible_binding.get("process_category_snapshot", ""),
                binding.get("route_id") or responsible_binding.get("route_id"),
                binding.get("route_version_id") or responsible_binding.get("route_version_id"),
                binding.get("route_name_snapshot") or responsible_binding.get("route_name_snapshot", ""),
                "captured" if binding.get("process_version_id") or responsible_binding.get("process_version_id") else "",
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
            process_name = process_value_sql("ncr", "process_version", "process")
            where.append("(ncr.ncr_no LIKE ? OR o.order_no LIKE ? OR " + process_name + " LIKE ? OR ncr.description LIKE ?)")
            value = f"%{keyword}%"; params.extend([value, value, value, value])
        clause = " AND ".join(where) if where else "1=1"
        total = db.execute(
            "SELECT COUNT(*) FROM quality_nonconformances ncr LEFT JOIN orders o ON o.id=ncr.order_id "
            "LEFT JOIN processes process ON process.id=ncr.process_id "
            + process_version_join("ncr", "process_version") + "WHERE " + clause,
            params,
        ).fetchone()[0]
        process_name = process_value_sql("ncr", "process_version", "process")
        responsible_process_name = process_value_sql(
            "ncr", "responsible_process_version", "responsible_process", role="responsible_process"
        )
        rows = db.execute(
            "SELECT ncr.*, o.order_no, o.product_name, " + process_name + " AS process_name, "
            + responsible_process_name + " AS responsible_process_name, "
            + "responsible.name AS responsible_user_name, owner.name AS owner_name, supplier.name AS supplier_name, "
            "material.name AS material_name, task.task_no "
            "FROM quality_nonconformances ncr LEFT JOIN orders o ON o.id=ncr.order_id "
            "LEFT JOIN processes process ON process.id=ncr.process_id "
            + process_version_join("ncr", "process_version")
            + "LEFT JOIN processes responsible_process ON responsible_process.id=ncr.responsible_process_id "
            + process_version_join("ncr", "responsible_process_version", "responsible_process")
            + "LEFT JOIN users responsible ON responsible.id=ncr.responsible_user_id "
            "LEFT JOIN users owner ON owner.id=ncr.owner_id LEFT JOIN suppliers supplier ON supplier.id=ncr.supplier_id "
            "LEFT JOIN materials material ON material.id=ncr.material_id "
            "LEFT JOIN quality_inspection_tasks task ON task.id=ncr.task_id "
            "WHERE " + clause + " ORDER BY CASE ncr.status WHEN 'open' THEN 0 WHEN 'processing' THEN 1 "
            "WHEN 'pending_reinspection' THEN 2 ELSE 3 END, ncr.id DESC LIMIT ? OFFSET ?",
            params + [limit, (page - 1) * limit],
        ).fetchall()
        warn_legacy_fact_rows("quality_nonconformances", rows, roles=("process", "responsible_process"))
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
        process_name = process_value_sql("ncr", "process_version", "process")
        responsible_process_name = process_value_sql(
            "ncr", "responsible_process_version", "responsible_process", role="responsible_process"
        )
        row = db.execute(
            "SELECT ncr.*, o.order_no, o.product_name, o.product_code, " + process_name + " AS process_name, "
            + responsible_process_name + " AS responsible_process_name, "
            + "responsible.name AS responsible_user_name, owner.name AS owner_name, "
            "supplier.name AS supplier_name, material.name AS material_name "
            "FROM quality_nonconformances ncr LEFT JOIN orders o ON o.id=ncr.order_id "
            "LEFT JOIN processes process ON process.id=ncr.process_id "
            + process_version_join("ncr", "process_version")
            + "LEFT JOIN processes responsible_process ON responsible_process.id=ncr.responsible_process_id "
            + process_version_join("ncr", "responsible_process_version", "responsible_process")
            + "LEFT JOIN users responsible ON responsible.id=ncr.responsible_user_id "
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
        current = db.execute(
            "SELECT order_id,route_id FROM quality_nonconformances WHERE id=?", (ncr_id,)
        ).fetchone()
        responsible_binding = capture_process_fact_binding(
            db,
            order_id=current["order_id"] if current else None,
            process_id=data.get("responsible_process_id"),
            route_id=current["route_id"] if current else None,
        )
        db.execute(
            "UPDATE quality_nonconformances SET disposition=?, status=?, responsible_user_id=?, "
            "responsible_process_id=?, owner_id=?, due_at=?, root_cause=?, corrective_action=?, "
            "verification_result=?, closed_by=?, closed_at=?, responsible_process_version_id=?,"
            "responsible_process_code_snapshot=?,responsible_process_name_snapshot=?,"
            "responsible_process_category_snapshot=?,updated_at=datetime('now','localtime') WHERE id=?",
            (
                data.get("disposition", "pending"), data.get("status", "open"), data.get("responsible_user_id"),
                data.get("responsible_process_id"), data.get("owner_id"), data.get("due_at", ""),
                data.get("root_cause", ""), data.get("corrective_action", ""),
                data.get("verification_result", ""), data.get("closed_by"), data.get("closed_at", ""),
                responsible_binding.get("process_version_id"), responsible_binding.get("process_code_snapshot", ""),
                responsible_binding.get("process_name_snapshot", ""),
                responsible_binding.get("process_category_snapshot", ""), ncr_id,
            ),
        )

    @staticmethod
    def add_ncr_action(ncr_id, action, from_status, to_status, note, actor_id, db):
        db.execute(
            "INSERT INTO quality_nonconformance_actions (ncr_id,action,from_status,to_status,note,actor_id) "
            "VALUES (?,?,?,?,?,?)",
            (ncr_id, action, from_status, to_status, note, actor_id),
        )

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
