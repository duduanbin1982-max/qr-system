"""QualityStandardRepository quality persistence subdomain."""

from modules.repositories.context import resolve_db


class QualityStandardRepository:
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
