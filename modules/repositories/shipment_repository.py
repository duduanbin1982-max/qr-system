"""Shipment persistence with optimistic lifecycle and immutable ledgers."""

from modules.constants import MAX_PAGE_LIMIT
from modules.query_utils import paginate
from modules.repositories.context import resolve_db


class ShipmentRepository:
    @staticmethod
    def max_seq_for_date(prefix, today, prefix_len, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT MAX(CAST(SUBSTR(shipment_no, ?) AS INTEGER)) AS max_seq "
            "FROM shipments WHERE shipment_no LIKE ?",
            (prefix_len, prefix + today + "-%"),
        ).fetchone()

    @staticmethod
    def _filters(keyword="", status=""):
        where = ["1=1"]
        params = []
        if keyword:
            where.append("(s.shipment_no LIKE ? OR s.customer LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        if status:
            where.append("s.status = ?")
            params.append(status)
        return " AND ".join(where), params

    @staticmethod
    def _list_sql(where_sql, sort_by, sort_dir):
        allowed_sort = {
            "created_at": "s.created_at",
            "customer": "s.customer",
            "status": "s.status",
            "total_quantity": "s.total_quantity",
        }
        sort_column = allowed_sort.get(sort_by, "s.created_at")
        direction = "ASC" if str(sort_dir).lower() == "asc" else "DESC"
        return (
            "SELECT s.*, COALESCE(si.item_count,0) AS item_count, "
            "COALESCE(si.product_codes,'') AS product_codes FROM shipments s "
            "LEFT JOIN (SELECT shipment_id, COUNT(*) AS item_count, "
            "GROUP_CONCAT(DISTINCT NULLIF(product_code,'')) AS product_codes "
            "FROM shipment_items GROUP BY shipment_id) si ON si.shipment_id=s.id "
            f"WHERE {where_sql} ORDER BY {sort_column} {direction}, s.id {direction}"
        )

    @classmethod
    def list_shipments(
        cls, keyword="", status="", page=1, limit=20,
        sort_by="created_at", sort_dir="desc", db=None,
    ):
        db = resolve_db(db)
        where_sql, params = cls._filters(keyword, status)
        total = db.execute(
            "SELECT COUNT(*) FROM shipments s WHERE " + where_sql, params
        ).fetchone()[0]
        sql = cls._list_sql(where_sql, sort_by, sort_dir)
        paginated_sql, all_params, size, _ = paginate(
            sql, params, page=page, page_size=limit, max_page_size=MAX_PAGE_LIMIT
        )
        return db.execute(paginated_sql, all_params).fetchall(), total, size

    @classmethod
    def list_all_shipments(
        cls, keyword="", status="", sort_by="created_at", sort_dir="desc", db=None,
    ):
        db = resolve_db(db)
        where_sql, params = cls._filters(keyword, status)
        return db.execute(cls._list_sql(where_sql, sort_by, sort_dir), params).fetchall()

    @classmethod
    def fetch_list_summary(cls, keyword="", status="", db=None):
        db = resolve_db(db)
        where_sql, params = cls._filters(keyword, status)
        return db.execute(
            "SELECT COUNT(*) AS total, "
            "COALESCE(SUM(CASE WHEN s.status='pending' THEN 1 ELSE 0 END),0) AS pending_count, "
            "COALESCE(SUM(CASE WHEN s.status IN ('completed','received') THEN 1 ELSE 0 END),0) "
            "AS completed_count, COALESCE(SUM(s.receivable_amount),0) AS receivable_total, "
            "COALESCE(SUM(s.paid_amount),0) AS paid_total "
            "FROM shipments s WHERE " + where_sql,
            params,
        ).fetchone()

    @staticmethod
    def insert_shipment_txn(
        shipment_no, customer, contact_person, contact_phone, address, total_qty,
        remark, created_by_id, created_by_name, deduction_mode, material_bill_no,
        receivable_amount, db,
    ):
        cursor = db.execute(
            "INSERT INTO shipments (shipment_no,customer,contact_person,contact_phone,address,"
            "status,total_quantity,remark,created_by,created_by_id,created_by_name,deduction_mode,"
            "material_bill_no,receivable_amount,updated_at) "
            "VALUES (?,?,?,?,?,'pending',?,?,?,?,?,?,?,?,datetime('now','localtime'))",
            (
                shipment_no, customer, contact_person, contact_phone, address, total_qty,
                remark, created_by_name, created_by_id, created_by_name, deduction_mode,
                material_bill_no, receivable_amount,
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def insert_shipment_item_txn(
        shipment_id, inventory_id, product_model, product_name, quantity, unit,
        remark, order_id, product_code, order_no, db,
    ):
        cursor = db.execute(
            "INSERT INTO shipment_items (shipment_id,inventory_id,product_model,product_name,"
            "quantity,unit,remark,order_id,product_code,order_no) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                shipment_id, inventory_id, product_model, product_name, quantity, unit,
                remark, order_id, product_code, order_no,
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def mark_reserved_txn(shipment_id, db):
        return db.execute(
            "UPDATE shipments SET reserved_at=datetime('now','localtime') WHERE id=?",
            (shipment_id,),
        ).rowcount

    @staticmethod
    def find_shipment_by_id(shipment_id, db=None):
        db = resolve_db(db)
        return db.execute("SELECT * FROM shipments WHERE id=?", (shipment_id,)).fetchone()

    @staticmethod
    def find_shipment_items(shipment_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM shipment_items WHERE shipment_id=? ORDER BY id", (shipment_id,)
        ).fetchall()

    @staticmethod
    def update_shipment_fields_txn(shipment_id, changes, expected_version, db):
        allowed = {
            "customer", "contact_person", "contact_phone", "address", "remark",
            "receivable_amount",
        }
        fields = [field for field in changes if field in allowed]
        if not fields:
            return 0
        assignments = [f"{field}=?" for field in fields]
        assignments.extend(["updated_at=datetime('now','localtime')", "version=version+1"])
        params = [changes[field] for field in fields]
        cursor = db.execute(
            "UPDATE shipments SET " + ",".join(assignments)
            + " WHERE id=? AND status='pending' AND version=?",
            params + [shipment_id, expected_version],
        )
        return cursor.rowcount

    @staticmethod
    def transition_status_txn(
        shipment_id, from_statuses, to_status, expected_version, fields, db,
    ):
        allowed = {
            "completed_at", "completed_by_id", "completed_by_name", "cancelled_at",
            "cancelled_by_id", "cancelled_by_name", "cancel_reason", "reversed_at",
            "reversed_by_id", "reversed_by_name", "reverse_reason", "received_at",
            "received_by_id", "received_by_name", "receiver_name", "receive_date",
        }
        safe_fields = [field for field in fields if field in allowed]
        assignments = ["status=?"] + [f"{field}=?" for field in safe_fields]
        assignments.extend(["updated_at=datetime('now','localtime')", "version=version+1"])
        placeholders = ",".join("?" for _ in from_statuses)
        params = [to_status] + [fields[field] for field in safe_fields]
        params.extend([shipment_id, expected_version, *from_statuses])
        cursor = db.execute(
            "UPDATE shipments SET " + ",".join(assignments)
            + f" WHERE id=? AND version=? AND status IN ({placeholders})",
            params,
        )
        return cursor.rowcount

    @staticmethod
    def update_logistics_txn(
        shipment_id, logistics_company, tracking_no, expected_version, db,
    ):
        cursor = db.execute(
            "UPDATE shipments SET logistics_company=?,tracking_no=?,"
            "updated_at=datetime('now','localtime'),version=version+1 "
            "WHERE id=? AND version=? AND status IN ('pending','completed')",
            (logistics_company, tracking_no, shipment_id, expected_version),
        )
        return cursor.rowcount

    @staticmethod
    def insert_event_txn(
        event_no, shipment_id, event_type, from_status, to_status, payload,
        operator_id, operator_name, idempotency_key, db,
    ):
        cursor = db.execute(
            "INSERT INTO shipment_events (event_no,shipment_id,event_type,from_status,to_status,"
            "payload,operator_id,operator_name,idempotency_key) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                event_no, shipment_id, event_type, from_status, to_status, payload,
                operator_id, operator_name, idempotency_key,
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def find_events(shipment_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM shipment_events WHERE shipment_id=? ORDER BY id DESC",
            (shipment_id,),
        ).fetchall()

    @staticmethod
    def insert_payment_txn(
        payment_no, shipment_id, payment_type, amount, payment_date, method, remark,
        operator_id, operator_name, idempotency_key, reversal_of_id, db,
    ):
        cursor = db.execute(
            "INSERT INTO shipment_payments (payment_no,shipment_id,type,amount,payment_date,"
            "method,remark,operator_id,operator_name,idempotency_key,reversal_of_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                payment_no, shipment_id, payment_type, amount, payment_date, method, remark,
                operator_id, operator_name, idempotency_key, reversal_of_id,
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def find_payment_by_idempotency_key(idempotency_key, db=None):
        if not idempotency_key:
            return None
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM shipment_payments WHERE idempotency_key=?", (idempotency_key,)
        ).fetchone()

    @staticmethod
    def find_payment_by_id(payment_id, db=None):
        db = resolve_db(db)
        return db.execute("SELECT * FROM shipment_payments WHERE id=?", (payment_id,)).fetchone()

    @staticmethod
    def find_payments(shipment_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM shipment_payments WHERE shipment_id=? ORDER BY payment_date DESC,id DESC",
            (shipment_id,),
        ).fetchall()

    @staticmethod
    def fetch_shipment_stats(today, month_start, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) AS total, "
            "COALESCE(SUM(status='pending'),0) AS pending, "
            "COALESCE(SUM(status='received'),0) AS received, "
            "COALESCE(SUM(status='completed'),0) AS completed, "
            "COALESCE(SUM(status='cancelled'),0) AS cancelled, "
            "COALESCE(SUM(status='reversed'),0) AS reversed, "
            "COALESCE(SUM(date(created_at)=?),0) AS today_count, "
            "COALESCE(SUM(date(created_at)>=?),0) AS month_count, "
            "COALESCE(SUM(date(completed_at)=?),0) AS today_completed, "
            "COALESCE(SUM(CASE WHEN status IN ('completed','received') "
            "THEN total_quantity ELSE 0 END),0) AS total_shipped_qty, "
            "COALESCE(SUM(receivable_amount),0) AS total_receivable, "
            "COALESCE(SUM(paid_amount),0) AS total_paid, "
            "COALESCE(SUM(payment_status='paid'),0) AS paid_count, "
            "COALESCE(SUM(payment_status='partial'),0) AS partial_paid FROM shipments",
            (today, month_start, today),
        ).fetchone()

    @staticmethod
    def find_shipment_for_impact(shipment_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id,shipment_no,status,customer,total_quantity FROM shipments WHERE id=?",
            (shipment_id,),
        ).fetchone()

    @staticmethod
    def count_shipment_items_impact(shipment_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) AS cnt,COALESCE(SUM(quantity),0) AS qty "
            "FROM shipment_items WHERE shipment_id=?", (shipment_id,),
        ).fetchone()

    @staticmethod
    def count_distinct_inventory(shipment_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(DISTINCT inventory_id) FROM shipment_items WHERE shipment_id=?",
            (shipment_id,),
        ).fetchone()[0]

    @staticmethod
    def find_shipments_by_customer(customer, limit, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT s.*,COALESCE(si.item_count,0) AS item_count FROM shipments s "
            "LEFT JOIN (SELECT shipment_id,COUNT(*) AS item_count FROM shipment_items "
            "GROUP BY shipment_id) si ON si.shipment_id=s.id "
            "WHERE s.customer=? ORDER BY s.created_at DESC,s.id DESC LIMIT ?",
            (customer, limit),
        ).fetchall()

    @staticmethod
    def find_order_ids_for_shipment_txn(shipment_id, db):
        return db.execute(
            "SELECT DISTINCT order_id FROM shipment_items "
            "WHERE shipment_id=? AND order_id IS NOT NULL", (shipment_id,),
        ).fetchall()

    @staticmethod
    def sum_shipped_qty_txn(order_id, db):
        row = db.execute(
            "SELECT COALESCE(SUM(si.quantity),0) AS shipped_qty FROM shipment_items si "
            "JOIN shipments s ON s.id=si.shipment_id "
            "WHERE si.order_id=? AND s.status IN ('completed','received')", (order_id,),
        ).fetchone()
        return row["shipped_qty"] if row else 0

    @staticmethod
    def shipment_exists(shipment_id, db=None):
        db = resolve_db(db)
        return db.execute("SELECT id FROM shipments WHERE id=?", (shipment_id,)).fetchone()

    @staticmethod
    def shipment_items_exist(shipment_id, db=None):
        return ShipmentRepository.find_shipment_items(shipment_id, db=db)
