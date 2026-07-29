"""Persistence queries for product and order traceability."""
from contextlib import contextmanager

from modules.repositories.context import resolve_db

class TraceRepository:
    """Traceability persistence gateway."""

    @staticmethod
    @contextmanager
    def read_snapshot(db=None):
        """Pin all trace reads to one SQLite snapshot."""
        db = resolve_db(db)
        owns_transaction = not db.in_transaction
        if owns_transaction:
            db.execute("BEGIN")
        try:
            snapshot_at = db.execute(
                "SELECT datetime('now','localtime') AS snapshot_at"
            ).fetchone()["snapshot_at"]
            yield db, snapshot_at
        finally:
            if owns_transaction and db.in_transaction:
                db.rollback()

    @staticmethod
    def find_product_item_by_serial(serial_no, db=None):
        """Find a product item and its joined order summary by serial number."""
        db = resolve_db(db)
        return db.execute('''
            SELECT pi.serial_no, pi.position_no, pi.status, pi.weight,
                   pi.production_date, pi.completed_at, pi.created_at,
                   current_process.name AS current_process_name,
                   o.id AS trace_order_id,
                   o.order_no AS trace_order_no,
                   o.product_name AS trace_product_name,
                   o.product_code AS trace_product_code,
                   o.quantity AS trace_order_quantity,
                   o.completed AS trace_completed,
                   o.scrapped AS trace_scrapped,
                   o.rework AS trace_rework,
                   o.status AS trace_order_status,
                   o.plan_start AS trace_plan_start,
                   o.plan_end AS trace_plan_end,
                   o.deadline AS trace_deadline,
                   o.remark AS trace_remark,
                   o.qr_mode AS trace_qr_mode,
                   o.delivery_status AS trace_delivery_status,
                   o.created_at AS trace_order_created,
                   o.updated_at AS trace_order_updated,
                   COALESCE(c.name, o.customer) AS trace_customer
            FROM product_items pi
            LEFT JOIN orders o ON pi.order_id = o.id AND o.deleted_at IS NULL
            LEFT JOIN customers c ON o.customer_id = c.id
            LEFT JOIN processes current_process ON current_process.id = pi.current_process_id
            WHERE pi.serial_no = ?
        ''', (serial_no,)).fetchone()

    @staticmethod
    def find_work_records_by_order(order_id, limit=100, offset=0, db=None):
        """Return work reports for an order with process and user names."""
        db = resolve_db(db)
        return db.execute('''
            SELECT wr.id, wr.serial_no, wr.quantity, wr.status, wr.type, wr.remark, wr.created_at,
                   p.name as process_name, u.name as worker_name
            FROM work_records wr
            LEFT JOIN processes p ON wr.process_id = p.id
            LEFT JOIN users u ON wr.user_id = u.id
            WHERE wr.order_id = ?
            ORDER BY wr.created_at ASC, wr.id ASC
            LIMIT ? OFFSET ?
        ''', (order_id, limit, offset)).fetchall()

    @staticmethod
    def find_rework_records_by_order(order_id, limit=100, offset=0, db=None):
        """Return rework records for an order with process and user names."""
        db = resolve_db(db)
        return db.execute('''
            SELECT rr.id, rr.quantity, rr.reason, rr.status, rr.created_at,
                   rr.completed_at,
                   p.name as process_name, u.name as worker_name
            FROM rework_records rr
            LEFT JOIN processes p ON rr.process_id = p.id
            LEFT JOIN users u ON rr.user_id = u.id
            WHERE rr.order_id = ?
            ORDER BY rr.created_at ASC, rr.id ASC
            LIMIT ? OFFSET ?
        ''', (order_id, limit, offset)).fetchall()

    @staticmethod
    def find_work_records_by_serial(serial_no, order_id, db=None):
        db = resolve_db(db)
        return db.execute('''
            SELECT wr.id, wr.serial_no, wr.quantity, wr.status, wr.type, wr.remark, wr.created_at,
                   p.name as process_name, u.name as worker_name
            FROM work_records wr
            LEFT JOIN processes p ON wr.process_id = p.id
            LEFT JOIN users u ON wr.user_id = u.id
            WHERE wr.order_id = ? AND wr.serial_no = ?
            ORDER BY wr.created_at ASC
        ''', (order_id, serial_no)).fetchall()

    @staticmethod
    def find_shipments_by_order_id(order_id, limit=100, offset=0, db=None):
        db = resolve_db(db)
        return db.execute("""
            SELECT s.id, s.shipment_no, s.customer, s.status,
                   s.total_quantity, SUM(si.quantity) AS order_quantity,
                   s.created_at, s.completed_at
            FROM shipments s
            JOIN shipment_items si ON si.shipment_id = s.id
            WHERE si.order_id = ?
            GROUP BY s.id, s.shipment_no, s.customer, s.status,
                     s.total_quantity, s.created_at, s.completed_at
            ORDER BY s.created_at DESC, s.id DESC
            LIMIT ? OFFSET ?
        """, (order_id, limit, offset)).fetchall()

    @staticmethod
    def find_order_by_no(order_no, db=None):
        """按订单号查订单"""
        db = resolve_db(db)
        return db.execute("""
            SELECT o.id AS trace_order_id, o.order_no,
                   COALESCE(c.name, o.customer) AS customer,
                   o.product_name, o.product_code, o.quantity, o.completed,
                   o.scrapped, o.rework, o.status, o.plan_start, o.plan_end,
                   o.deadline, o.remark, o.qr_mode, o.delivery_status,
                   o.created_at, o.updated_at
            FROM orders o
            LEFT JOIN customers c ON o.customer_id = c.id
            WHERE o.order_no = ? AND o.deleted_at IS NULL
        """, (order_no,)).fetchone()

    @staticmethod
    def find_product_items_by_order(order_id, limit=100, offset=0, db=None):
        """查订单下全部产品项"""
        db = resolve_db(db)
        return db.execute("""
            SELECT item.serial_no, item.position_no, item.status, item.weight,
                   item.production_date, item.completed_at, item.created_at,
                   process.name AS current_process_name
            FROM product_items item
            LEFT JOIN processes process ON process.id = item.current_process_id
            WHERE item.order_id = ?
            ORDER BY item.position_no, item.id
            LIMIT ? OFFSET ?
        """, (order_id, limit, offset)).fetchall()

    @staticmethod
    def find_material_consumptions_by_order(order_id, limit=100, offset=0, db=None):
        """查订单物料消耗"""
        db = resolve_db(db)
        return db.execute("""
            SELECT mc.id, mc.quantity, mc.notes, mc.operator_name, mc.created_at,
                   mc.source_work_record_id,
                   m.name as material_name, m.spec as material_spec,
                   p.name as process_name
            FROM material_consumptions mc
            LEFT JOIN materials m ON mc.material_id = m.id
            LEFT JOIN processes p ON mc.process_id = p.id
            WHERE mc.order_id = ?
            ORDER BY mc.created_at ASC, mc.id ASC
            LIMIT ? OFFSET ?
        """, (order_id, limit, offset)).fetchall()

    @staticmethod
    def find_quality_inspections_by_order(order_id, limit=100, offset=0, db=None):
        """查订单质检记录"""
        db = resolve_db(db)
        return db.execute("""
            SELECT qi.id, qi.inspection_type, qi.quantity_checked, qi.quantity_passed,
                   qi.quantity_failed, qi.result, qi.notes, qi.inspected_at, qi.created_at,
                   qi.defect_category, qi.defect_quantity, qi.defect_level, qi.score_total,
                   qi.serial_no,
                   task.task_no, ncr.ncr_no,
                   p.name as process_name, u.name as inspector_name
            FROM quality_inspections qi
            LEFT JOIN processes p ON qi.process_id = p.id
            LEFT JOIN users u ON qi.inspector_id = u.id
            LEFT JOIN quality_inspection_tasks task ON task.id = qi.task_id
            LEFT JOIN quality_nonconformances ncr ON ncr.inspection_id = qi.id
            WHERE qi.order_id = ?
            ORDER BY qi.created_at ASC, qi.id ASC
            LIMIT ? OFFSET ?
        """, (order_id, limit, offset)).fetchall()

    @staticmethod
    def find_quality_tasks_by_order(order_id, limit=100, offset=0, db=None):
        db = resolve_db(db)
        return db.execute("""
            SELECT task.id, task.task_no, task.inspection_type, task.trigger_type,
                   task.gate_mode, task.sample_qty, task.priority, task.status,
                   task.serial_no, task.due_at, task.started_at, task.completed_at,
                   task.created_at, process.name AS process_name,
                   standard.standard_no, standard.name AS standard_name,
                   assignee.name AS assigned_name
            FROM quality_inspection_tasks task
            LEFT JOIN processes process ON process.id = task.process_id
            LEFT JOIN quality_standards standard ON standard.id = task.standard_id
            LEFT JOIN users assignee ON assignee.id = task.assigned_to
            WHERE task.order_id = ?
            ORDER BY task.created_at, task.id
            LIMIT ? OFFSET ?
        """, (order_id, limit, offset)).fetchall()

    @staticmethod
    def find_quality_nonconformances_by_order(order_id, limit=100, offset=0, db=None):
        db = resolve_db(db)
        return db.execute("""
            SELECT ncr.id, ncr.ncr_no, ncr.defect_category, ncr.defect_level,
                   ncr.defect_quantity, ncr.description, ncr.disposition, ncr.status,
                   ncr.root_cause, ncr.corrective_action, ncr.verification_result,
                   ncr.due_at, ncr.closed_at, ncr.created_at, ncr.serial_no,
                   process.name AS process_name, owner.name AS owner_name,
                   task.task_no,
                   (SELECT COUNT(*) FROM quality_nonconformance_actions action
                    WHERE action.ncr_id = ncr.id) AS action_count
            FROM quality_nonconformances ncr
            LEFT JOIN processes process ON process.id = ncr.process_id
            LEFT JOIN users owner ON owner.id = ncr.owner_id
            LEFT JOIN quality_inspection_tasks task ON task.id = ncr.task_id
            WHERE ncr.order_id = ?
            ORDER BY ncr.created_at, ncr.id
            LIMIT ? OFFSET ?
        """, (order_id, limit, offset)).fetchall()

    @staticmethod
    def find_quality_capa_by_order(order_id, limit=100, offset=0, db=None):
        db = resolve_db(db)
        return db.execute("""
            SELECT capa.id, capa.capa_no, capa.title, capa.problem_description,
                   capa.root_cause, capa.corrective_action, capa.preventive_action,
                   capa.due_at, capa.status, capa.effectiveness_result,
                   capa.verified_at, capa.created_at, ncr.ncr_no,
                   owner.name AS owner_name, verifier.name AS verifier_name
            FROM quality_capa_records capa
            JOIN quality_nonconformances ncr ON ncr.id = capa.ncr_id
            LEFT JOIN users owner ON owner.id = capa.owner_id
            LEFT JOIN users verifier ON verifier.id = capa.verified_by
            WHERE ncr.order_id = ?
            ORDER BY capa.created_at, capa.id
            LIMIT ? OFFSET ?
        """, (order_id, limit, offset)).fetchall()

    @staticmethod
    def find_inventory_logs_by_order(order_id, limit=100, offset=0, db=None):
        """查订单入库记录"""
        db = resolve_db(db)
        return db.execute("""
            SELECT il.id, il.type, il.quantity, il.remark, il.operator_name, il.created_at,
                   inventory.product_model, inventory.product_name
            FROM inventory_logs il
            LEFT JOIN inventory ON inventory.id = il.inventory_id
            WHERE il.order_id = ?
            ORDER BY il.created_at ASC, il.id ASC
            LIMIT ? OFFSET ?
        """, (order_id, limit, offset)).fetchall()

    @staticmethod
    def find_quality_inspections_by_serial(serial_no, order_id, db=None):
        db = resolve_db(db)
        return db.execute("""
            SELECT qi.id, qi.inspection_type, qi.quantity_checked, qi.quantity_passed,
                   qi.quantity_failed, qi.result, qi.notes, qi.inspected_at, qi.created_at,
                   qi.defect_category, qi.defect_quantity, qi.defect_level, qi.score_total,
                   qi.serial_no, task.task_no, ncr.ncr_no,
                   p.name AS process_name, u.name AS inspector_name
            FROM quality_inspections qi
            LEFT JOIN processes p ON qi.process_id = p.id
            LEFT JOIN users u ON qi.inspector_id = u.id
            LEFT JOIN quality_inspection_tasks task ON task.id = qi.task_id
            LEFT JOIN quality_nonconformances ncr ON ncr.inspection_id = qi.id
            WHERE qi.order_id = ? AND qi.serial_no = ?
            ORDER BY qi.created_at, qi.id
        """, (order_id, serial_no)).fetchall()

    @staticmethod
    def find_quality_tasks_by_serial(serial_no, order_id, db=None):
        db = resolve_db(db)
        return db.execute("""
            SELECT task.id, task.task_no, task.inspection_type, task.trigger_type,
                   task.gate_mode, task.sample_qty, task.priority, task.status,
                   task.serial_no, task.due_at, task.started_at, task.completed_at,
                   task.created_at, process.name AS process_name,
                   standard.standard_no, standard.name AS standard_name,
                   assignee.name AS assigned_name
            FROM quality_inspection_tasks task
            LEFT JOIN processes process ON process.id = task.process_id
            LEFT JOIN quality_standards standard ON standard.id = task.standard_id
            LEFT JOIN users assignee ON assignee.id = task.assigned_to
            WHERE task.order_id = ? AND task.serial_no = ?
            ORDER BY task.created_at, task.id
        """, (order_id, serial_no)).fetchall()

    @staticmethod
    def find_quality_nonconformances_by_serial(serial_no, order_id, db=None):
        db = resolve_db(db)
        return db.execute("""
            SELECT ncr.id, ncr.ncr_no, ncr.defect_category, ncr.defect_level,
                   ncr.defect_quantity, ncr.description, ncr.disposition, ncr.status,
                   ncr.root_cause, ncr.corrective_action, ncr.verification_result,
                   ncr.due_at, ncr.closed_at, ncr.created_at, ncr.serial_no,
                   process.name AS process_name, owner.name AS owner_name,
                   task.task_no,
                   (SELECT COUNT(*) FROM quality_nonconformance_actions action
                    WHERE action.ncr_id = ncr.id) AS action_count
            FROM quality_nonconformances ncr
            LEFT JOIN processes process ON process.id = ncr.process_id
            LEFT JOIN users owner ON owner.id = ncr.owner_id
            LEFT JOIN quality_inspection_tasks task ON task.id = ncr.task_id
            WHERE ncr.order_id = ? AND ncr.serial_no = ?
            ORDER BY ncr.created_at, ncr.id
        """, (order_id, serial_no)).fetchall()

    @staticmethod
    def find_quality_capa_by_serial(serial_no, order_id, db=None):
        db = resolve_db(db)
        return db.execute("""
            SELECT capa.id, capa.capa_no, capa.title, capa.problem_description,
                   capa.root_cause, capa.corrective_action, capa.preventive_action,
                   capa.due_at, capa.status, capa.effectiveness_result,
                   capa.verified_at, capa.created_at, ncr.ncr_no,
                   owner.name AS owner_name, verifier.name AS verifier_name
            FROM quality_capa_records capa
            JOIN quality_nonconformances ncr ON ncr.id = capa.ncr_id
            LEFT JOIN users owner ON owner.id = capa.owner_id
            LEFT JOIN users verifier ON verifier.id = capa.verified_by
            WHERE ncr.order_id = ? AND ncr.serial_no = ?
            ORDER BY capa.created_at, capa.id
        """, (order_id, serial_no)).fetchall()

    @staticmethod
    def find_material_consumptions_by_serial(serial_no, order_id, db=None):
        """Return automatic material deductions attributable to one serial number."""
        db = resolve_db(db)
        return db.execute("""
            SELECT mc.id, mc.quantity, mc.notes, mc.operator_name, mc.created_at,
                   mc.source_work_record_id,
                   m.name AS material_name, m.spec AS material_spec,
                   p.name AS process_name
            FROM material_consumptions mc
            JOIN work_records wr ON wr.id = mc.source_work_record_id
            LEFT JOIN materials m ON mc.material_id = m.id
            LEFT JOIN processes p ON mc.process_id = p.id
            WHERE mc.order_id = ? AND wr.serial_no = ?
            ORDER BY mc.created_at, mc.id
        """, (order_id, serial_no)).fetchall()

    @staticmethod
    def find_order_scope_material_consumptions(order_id, db=None):
        """Return material consumption records that cannot be assigned to one item."""
        db = resolve_db(db)
        return db.execute("""
            SELECT mc.id, mc.quantity, mc.notes, mc.operator_name, mc.created_at,
                   mc.source_work_record_id,
                   m.name AS material_name, m.spec AS material_spec,
                   p.name AS process_name
            FROM material_consumptions mc
            LEFT JOIN work_records wr ON wr.id = mc.source_work_record_id
            LEFT JOIN materials m ON mc.material_id = m.id
            LEFT JOIN processes p ON mc.process_id = p.id
            WHERE mc.order_id = ?
              AND (mc.source_work_record_id IS NULL OR COALESCE(wr.serial_no, '') = '')
            ORDER BY mc.created_at, mc.id
        """, (order_id,)).fetchall()

    @staticmethod
    def count_order_trace_collections(order_id, db=None):
        """Return collection totals used by the order trace paginator."""
        db = resolve_db(db)
        row = db.execute("""
            SELECT
                (SELECT COUNT(*) FROM product_items WHERE order_id = ?) AS items,
                (SELECT COUNT(*) FROM work_records WHERE order_id = ?) AS work_records,
                (SELECT COUNT(*) FROM rework_records WHERE order_id = ?) AS rework_records,
                (SELECT COUNT(*) FROM quality_inspections WHERE order_id = ?) AS quality_inspections,
                (SELECT COUNT(*) FROM quality_inspection_tasks WHERE order_id = ?) AS quality_tasks,
                (SELECT COUNT(*) FROM quality_nonconformances WHERE order_id = ?) AS quality_nonconformances,
                (SELECT COUNT(*) FROM quality_capa_records capa
                 JOIN quality_nonconformances ncr ON ncr.id = capa.ncr_id
                 WHERE ncr.order_id = ?) AS quality_capa,
                (SELECT COUNT(*) FROM material_consumptions WHERE order_id = ?) AS material_consumptions,
                (SELECT COUNT(*) FROM inventory_logs WHERE order_id = ?) AS inventory_logs,
                (SELECT COUNT(DISTINCT shipment_id) FROM shipment_items WHERE order_id = ?) AS shipments
        """, (order_id,) * 10).fetchone()
        return dict(row)
