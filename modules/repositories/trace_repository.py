"""
qr-system ? TraceRepository???????

???????? ? product_items / work_records / rework_records / shipments ???????
"""
from modules.db_unit_of_work import BaseService

class TraceRepository:
    """?????????"""

    @staticmethod
    def find_product_item_by_serial(serial_no, db=None):
        """?????????????+??????"""
        db = db or BaseService.db()
        return db.execute('''
            SELECT pi.*,
                   o.order_no, o.product_name, o.quantity as order_quantity,
                   o.completed, o.status as order_status, o.created_at as order_created,
                   COALESCE(c.name, o.customer) as customer
            FROM product_items pi
            LEFT JOIN orders o ON pi.order_id = o.id AND o.deleted_at IS NULL
            LEFT JOIN customers c ON o.customer_id = c.id
            WHERE pi.serial_no = ?
        ''', (serial_no,)).fetchone()

    @staticmethod
    def find_work_records_by_order(order_id, db=None):
        """???ID??????????+???????"""
        db = db or BaseService.db()
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
        """???ID??????????+???????"""
        db = db or BaseService.db()
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
        db = db or BaseService.db()
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
        db = db or BaseService.db()
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
        db = db or BaseService.db()
        return db.execute("""
            SELECT o.*, COALESCE(c.name, o.customer) as customer
            FROM orders o
            LEFT JOIN customers c ON o.customer_id = c.id
            WHERE o.order_no = ? AND o.deleted_at IS NULL
        """, (order_no,)).fetchone()

    @staticmethod
    def find_product_items_by_order(order_id, db=None):
        """查订单下全部产品项"""
        db = db or BaseService.db()
        return db.execute("""
            SELECT * FROM product_items
            WHERE order_id = ?
            ORDER BY position_no, id
        """, (order_id,)).fetchall()

    @staticmethod
    def find_material_consumptions_by_order(order_id, db=None):
        """查订单物料消耗"""
        db = db or BaseService.db()
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
        db = db or BaseService.db()
        return db.execute("""
            SELECT qi.id, qi.inspection_type, qi.quantity_checked, qi.quantity_passed,
                   qi.quantity_failed, qi.result, qi.notes, qi.inspected_at, qi.created_at,
                   qi.defect_category, qi.defect_quantity,
                   p.name as process_name, u.name as inspector_name
            FROM quality_inspections qi
            LEFT JOIN processes p ON qi.process_id = p.id
            LEFT JOIN users u ON qi.inspector_id = u.id
            WHERE qi.order_id = ?
            ORDER BY qi.created_at ASC
        """, (order_id,)).fetchall()

    @staticmethod
    def find_inventory_logs_by_order(order_id, db=None):
        """查订单入库记录"""
        db = db or BaseService.db()
        return db.execute("""
            SELECT il.id, il.type, il.quantity, il.remark, il.operator_name, il.created_at
            FROM inventory_logs il
            WHERE il.order_id = ?
            ORDER BY il.created_at ASC
        """, (order_id,)).fetchall()
