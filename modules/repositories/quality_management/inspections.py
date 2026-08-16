"""QualityInspectionRepository quality subdomain."""

from modules.repositories.context import resolve_db
from modules.process_fact_projection import (
    capture_process_fact_binding,
    process_value_sql,
    process_version_join,
    warn_legacy_fact_rows,
)
from modules.repositories.quality_management.tasks import QualityTaskRepository


class QualityInspectionRepository(QualityTaskRepository):
    @staticmethod
    def insert_inspection(data, user_id, db):
        binding = None
        if data.get("task_id"):
            task = db.execute(
                "SELECT process_id,process_version_id,process_code_snapshot,process_name_snapshot,"
                "process_category_snapshot,route_id,route_version_id,route_name_snapshot "
                "FROM quality_inspection_tasks WHERE id=?",
                (data["task_id"],),
            ).fetchone()
            if task:
                binding = dict(task)
        if not binding or binding.get("process_version_id") is None:
            binding = capture_process_fact_binding(
                db,
                order_id=data.get("order_id"),
                process_id=data.get("process_id"),
                source_work_record_id=data.get("work_record_id"),
            )
        cursor = db.execute(
            "INSERT INTO quality_inspections "
            "(order_id, process_id, inspection_type, inspector_id, quantity_checked, quantity_passed, "
            "quantity_failed, result, defect_category, defect_quantity, notes, inspected_at, order_no, "
            "product_code, process_name, inspector_name, serial_no, score_total, score_detail_json, "
            "defect_level, defect_items_json, suggested_result, final_result, override_reason, task_id, "
            "standard_id, standard_version, measurements_json, quality_status, batch_no, scope_type, "
            "reviewed_by, reviewed_at, process_version_id, process_code_snapshot, process_name_snapshot, "
            "process_category_snapshot, route_id, route_version_id, route_name_snapshot, version_binding_source) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                binding.get("process_version_id"), binding.get("process_code_snapshot", ""),
                binding.get("process_name_snapshot", ""), binding.get("process_category_snapshot", ""),
                binding.get("route_id"), binding.get("route_version_id"), binding.get("route_name_snapshot", ""),
                binding.get("version_binding_source", "captured" if binding.get("process_version_id") else ""),
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def list_inspections(keyword="", result="", inspection_type="", page=1, limit=100, db=None):
        db = resolve_db(db)
        where = []
        params = []
        if keyword:
            process_name = process_value_sql("qi", "process_version", "process")
            where.append("(o.order_no LIKE ? OR o.product_name LIKE ? OR " + process_name + " LIKE ? OR qi.serial_no LIKE ?)")
            value = f"%{keyword}%"; params.extend([value, value, value, value])
        if result:
            where.append("qi.result=?"); params.append(result)
        if inspection_type:
            where.append("qi.inspection_type=?"); params.append(inspection_type)
        clause = " AND ".join(where) if where else "1=1"
        total = db.execute(
            "SELECT COUNT(*) FROM quality_inspections qi LEFT JOIN orders o ON o.id=qi.order_id "
            "LEFT JOIN processes process ON process.id=qi.process_id "
            + process_version_join("qi", "process_version") + "WHERE " + clause,
            params,
        ).fetchone()[0]
        process_name = process_value_sql("qi", "process_version", "process")
        rows = db.execute(
            "SELECT qi.*, o.order_no, o.product_name, o.product_code, " + process_name + " AS process_name_display, "
            "inspector.name AS inspector_name, task.task_no, standard.standard_no, ncr.id AS ncr_id, ncr.ncr_no, ncr.status AS ncr_status "
            "FROM quality_inspections qi LEFT JOIN orders o ON o.id=qi.order_id "
            "LEFT JOIN processes process ON process.id=qi.process_id "
            + process_version_join("qi", "process_version")
            + "LEFT JOIN users inspector ON inspector.id=qi.inspector_id "
            + "LEFT JOIN quality_inspection_tasks task ON task.id=qi.task_id "
            "LEFT JOIN quality_standards standard ON standard.id=qi.standard_id "
            "LEFT JOIN quality_nonconformances ncr ON ncr.inspection_id=qi.id "
            "WHERE " + clause + " ORDER BY COALESCE(qi.inspected_at,qi.created_at) DESC, qi.id DESC LIMIT ? OFFSET ?",
            params + [limit, (page - 1) * limit],
        ).fetchall()
        warn_legacy_fact_rows("quality_inspections", rows)
        items = []
        for row in rows:
            item = dict(row)
            item["process_name"] = item.pop("process_name_display", item.get("process_name", ""))
            items.append(item)
        return {"items": items, "total": total, "page": page, "limit": limit}

    @staticmethod
    def inspection_by_id(inspection_id, db=None):
        db = resolve_db(db)
        process_name = process_value_sql("qi", "process_version", "process")
        row = db.execute(
            "SELECT qi.*, o.order_no, o.product_name, o.product_code, "
            + process_name + " AS process_name_display, inspector.name AS inspector_name, "
            + "reviewer.name AS reviewer_name, task.task_no, standard.standard_no "
            "FROM quality_inspections qi LEFT JOIN orders o ON o.id=qi.order_id "
            "LEFT JOIN processes process ON process.id=qi.process_id "
            + process_version_join("qi", "process_version")
            + "LEFT JOIN users inspector ON inspector.id=qi.inspector_id "
            "LEFT JOIN users reviewer ON reviewer.id=qi.reviewed_by "
            "LEFT JOIN quality_inspection_tasks task ON task.id=qi.task_id "
            "LEFT JOIN quality_standards standard ON standard.id=qi.standard_id "
            "WHERE qi.id=?",
            (inspection_id,),
        ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["process_name"] = item.pop("process_name_display", item.get("process_name", ""))
        return item

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
