"""Persistence queries for product and order traceability."""
from modules.repositories.context import resolve_db

class TraceRepository:
    """Traceability persistence gateway."""

    @staticmethod
    def find_product_item_by_serial(serial_no, db=None):
        """Find a product item and its joined order summary by serial number."""
        db = resolve_db(db)
        return db.execute('''
            SELECT pi.*,
                   o.order_no AS trace_order_no,
                   o.product_name AS trace_product_name,
                   o.quantity AS trace_order_quantity,
                   o.completed AS trace_completed,
                   o.status AS trace_order_status,
                   o.created_at AS trace_order_created,
                   COALESCE(c.name, o.customer) AS trace_customer
            FROM product_items pi
            LEFT JOIN orders o ON pi.order_id = o.id AND o.deleted_at IS NULL
            LEFT JOIN customers c ON o.customer_id = c.id
            WHERE pi.serial_no = ?
        ''', (serial_no,)).fetchone()

    @staticmethod
    def find_work_records_by_order(order_id, db=None):
        """Return work reports for an order with process and user names."""
        db = resolve_db(db)
        return db.execute('''
            SELECT wr.id, wr.quantity, wr.status, wr.type, wr.remark, wr.created_at,
                   p.name as process_name, u.name as worker_name
            FROM work_records wr
            LEFT JOIN processes p ON wr.process_id = p.id
            LEFT JOIN users u ON wr.user_id = u.id
            WHERE wr.order_id = ?
            ORDER BY wr.created_at ASC
        ''', (order_id,)).fetchall()

    @staticmethod
    def find_rework_records_by_order(order_id, db=None):
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
            ORDER BY rr.created_at ASC
        ''', (order_id,)).fetchall()

    @staticmethod
    def find_work_records_by_serial(serial_no, order_id, db=None):
        db = resolve_db(db)
        return db.execute('''
            SELECT wr.id, wr.quantity, wr.status, wr.type, wr.remark, wr.created_at,
                   p.name as process_name, u.name as worker_name
            FROM work_records wr
            LEFT JOIN processes p ON wr.process_id = p.id
            LEFT JOIN users u ON wr.user_id = u.id
            WHERE wr.order_id = ? AND wr.serial_no = ?
            ORDER BY wr.created_at ASC
        ''', (order_id, serial_no)).fetchall()

    @staticmethod
    def find_shipments_by_order_id(order_id, db=None):
        db = resolve_db(db)
        return db.execute("""
            SELECT DISTINCT s.id, s.shipment_no, s.customer, s.status,
                   s.total_quantity, s.completed_at
            FROM shipments s
            JOIN shipment_items si ON si.shipment_id = s.id
            WHERE si.order_id = ?
            ORDER BY s.created_at DESC
            LIMIT 10
        """, (order_id,)).fetchall()

    @staticmethod
    def find_order_by_no(order_no, db=None):
        """按订单号查订单"""
        db = resolve_db(db)
        return db.execute("""
            SELECT o.*, COALESCE(c.name, o.customer) as customer
            FROM orders o
            LEFT JOIN customers c ON o.customer_id = c.id
            WHERE o.order_no = ? AND o.deleted_at IS NULL
        """, (order_no,)).fetchone()

    @staticmethod
    def find_product_items_by_order(order_id, db=None):
        """查订单下全部产品项"""
        db = resolve_db(db)
        return db.execute("""
            SELECT * FROM product_items
            WHERE order_id = ?
            ORDER BY position_no, id
        """, (order_id,)).fetchall()

    @staticmethod
    def find_material_consumptions_by_order(order_id, db=None):
        """查订单物料消耗"""
        db = resolve_db(db)
        return db.execute("""
            SELECT mc.id, mc.quantity, mc.notes, mc.operator_name, mc.created_at,
                   m.name as material_name, m.spec as material_spec,
                   p.name as process_name
            FROM material_consumptions mc
            LEFT JOIN materials m ON mc.material_id = m.id
            LEFT JOIN processes p ON mc.process_id = p.id
            WHERE mc.order_id = ?
            ORDER BY mc.created_at ASC
        """, (order_id,)).fetchall()

    @staticmethod
    def find_quality_inspections_by_order(order_id, db=None):
        """查订单质检记录"""
        db = resolve_db(db)
        return db.execute("""
            SELECT qi.id, qi.inspection_type, qi.quantity_checked, qi.quantity_passed,
                   qi.quantity_failed, qi.result, qi.notes, qi.inspected_at, qi.created_at,
                   qi.defect_category, qi.defect_quantity, qi.defect_level, qi.score_total,
                   task.task_no, ncr.ncr_no,
                   p.name as process_name, u.name as inspector_name
            FROM quality_inspections qi
            LEFT JOIN processes p ON qi.process_id = p.id
            LEFT JOIN users u ON qi.inspector_id = u.id
            LEFT JOIN quality_inspection_tasks task ON task.id = qi.task_id
            LEFT JOIN quality_nonconformances ncr ON ncr.inspection_id = qi.id
            WHERE qi.order_id = ?
            ORDER BY qi.created_at ASC
        """, (order_id,)).fetchall()

    @staticmethod
    def find_quality_tasks_by_order(order_id, db=None):
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
        """, (order_id,)).fetchall()

    @staticmethod
    def find_quality_nonconformances_by_order(order_id, db=None):
        db = resolve_db(db)
        return db.execute("""
            SELECT ncr.id, ncr.ncr_no, ncr.defect_category, ncr.defect_level,
                   ncr.defect_quantity, ncr.description, ncr.disposition, ncr.status,
                   ncr.root_cause, ncr.corrective_action, ncr.verification_result,
                   ncr.due_at, ncr.closed_at, ncr.created_at,
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
        """, (order_id,)).fetchall()

    @staticmethod
    def find_quality_capa_by_order(order_id, db=None):
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
        """, (order_id,)).fetchall()

    @staticmethod
    def find_inventory_logs_by_order(order_id, db=None):
        """查订单入库记录"""
        db = resolve_db(db)
        return db.execute("""
            SELECT il.id, il.type, il.quantity, il.remark, il.operator_name, il.created_at
            FROM inventory_logs il
            WHERE il.order_id = ?
            ORDER BY il.created_at ASC
        """, (order_id,)).fetchall()
