"""QualityPartnerRepository quality persistence subdomain."""

from modules.repositories.context import resolve_db


class QualityPartnerRepository:
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
