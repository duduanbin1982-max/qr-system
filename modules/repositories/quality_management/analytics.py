"""QualityAnalyticsRepository quality persistence subdomain."""

from modules.repositories.context import resolve_db
from modules.repositories.quality_management.partners import QualityPartnerRepository


class QualityAnalyticsRepository(QualityPartnerRepository):
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

    @classmethod
    def analytics(cls, date_from="", date_to="", db=None):
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
            "suppliers": [dict(row) for row in cls.supplier_quality_stats(db=db)],
        }
