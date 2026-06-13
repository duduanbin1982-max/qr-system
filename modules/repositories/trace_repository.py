"""
qr-system ? TraceRepository???????

???????? ? product_items / work_records / rework_records / shipments ???????
"""
from modules.services import BaseService


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
        """???ID?????????
        ??shipment_items ? order_id ????? product_name ?????
        ????? product_name??? shipment_items?
        """
        db = db or BaseService.db()
        # ????????
        order = db.execute(
            'SELECT product_name FROM orders WHERE id = ? AND deleted_at IS NULL',
            (order_id,)
        ).fetchone()
        if not order or not order['product_name']:
            return []
        return db.execute('''
            SELECT DISTINCT s.id, s.shipment_no, s.customer, s.status,
                   s.total_quantity, s.completed_at
            FROM shipments s
            JOIN shipment_items si ON si.shipment_id = s.id
            WHERE si.product_name = ?
            ORDER BY s.created_at DESC
            LIMIT 10
        ''', (order['product_name'],)).fetchall()

    @staticmethod
    def find_shipments_by_product_name(product_name, db=None):
        """??????????????????? product_name ?????"""
        db = db or BaseService.db()
        return db.execute('''
            SELECT DISTINCT s.id, s.shipment_no, s.customer, s.status,
                   s.total_quantity, s.completed_at
            FROM shipments s
            JOIN shipment_items si ON si.shipment_id = s.id
            WHERE si.product_name = ?
            ORDER BY s.created_at DESC
            LIMIT 10
        ''', (product_name,)).fetchall()
