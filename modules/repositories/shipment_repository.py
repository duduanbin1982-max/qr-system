"""qr-system — ShipmentRepository（出库管理数据访问层）"""
from modules.constants import MAX_PAGE_LIMIT
from modules.query_utils import paginate
from modules.repositories.context import resolve_db


class ShipmentRepository:
    """出库管理数据访问 — 封装所有出库 SQL 查询。"""

    # ========== generate_no ==========
    @staticmethod
    def max_seq_for_date(prefix, today, prefix_len, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT MAX(CAST(SUBSTR(shipment_no, ?) AS INTEGER)) as max_seq FROM shipments WHERE shipment_no LIKE ?",
            (prefix_len, prefix + today + "-%")
        ).fetchone()

    # ========== list_shipments ==========
    @staticmethod
    def list_shipments(keyword="", status="", page=1, limit=20, sort_by="created_at", sort_dir="desc", db=None):
        db = resolve_db(db)
        where = ["1=1"]
        params = []
        if keyword:
            where.append("(s.shipment_no LIKE ? OR s.customer LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        if status:
            where.append("s.status = ?")
            params.append(status)
        where_sql = " AND ".join(where)
        total = db.execute(
            "SELECT COUNT(*) FROM shipments s WHERE " + where_sql, params
        ).fetchone()[0]
        allowed_sort = {
            "created_at": "s.created_at",
            "customer": "s.customer",
            "status": "s.status",
            "total_quantity": "s.total_quantity",
        }
        sort_column = allowed_sort.get(sort_by, "s.created_at")
        direction = "ASC" if str(sort_dir).lower() == "asc" else "DESC"
        sql = (
            "SELECT s.*, COALESCE(si.item_count, 0) AS item_count, "
            "COALESCE(si.product_codes, '') AS product_codes FROM shipments s "
            "LEFT JOIN (SELECT shipment_id, COUNT(*) AS item_count, "
            "GROUP_CONCAT(DISTINCT NULLIF(product_code, '')) AS product_codes "
            "FROM shipment_items GROUP BY shipment_id) si ON si.shipment_id = s.id "
            f"WHERE {where_sql} ORDER BY {sort_column} {direction}"
        )
        paginated_sql, all_params, size, _ = paginate(
            sql, params, page=page, page_size=limit, max_page_size=MAX_PAGE_LIMIT
        )
        rows = db.execute(paginated_sql, all_params).fetchall()
        return rows, total, size

    # ========== create_shipment (transaction) ==========
    @staticmethod
    def insert_shipment_txn(shipment_no, customer, contact_person, contact_phone, address,
                             total_qty, remark, created_by, deduction_mode, material_bill_no,
                             receivable_amount, db):
        cur = db.execute(
            "INSERT INTO shipments (shipment_no, customer, contact_person, contact_phone, address, "
            "status, total_quantity, remark, created_by, deduction_mode, material_bill_no, receivable_amount) "
            "VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)",
            (shipment_no, customer, contact_person, contact_phone, address,
             total_qty, remark, created_by, deduction_mode, material_bill_no, receivable_amount)
        )
        return cur.lastrowid

    @staticmethod
    def insert_shipment_item_txn(shipment_id, inventory_id, product_model, product_name,
                                  quantity, unit, remark, order_id, product_code, order_no, db):
        db.execute(
            "INSERT INTO shipment_items (shipment_id, inventory_id, product_model, "
            "product_name, quantity, unit, remark, order_id, product_code, order_no) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (shipment_id, inventory_id, product_model, product_name, quantity, unit, remark,
             order_id, product_code, order_no)
        )

    @staticmethod
    def mark_reserved_txn(shipment_id, db):
        db.execute(
            "UPDATE shipments SET reserved_at = datetime('now','localtime') WHERE id = ?",
            (shipment_id,)
        )

    @staticmethod
    # ========== get_shipment_detail ==========
    @staticmethod
    def find_shipment_by_id(shipment_id, db=None):
        db = resolve_db(db)
        return db.execute("SELECT * FROM shipments WHERE id = ?", (shipment_id,)).fetchone()

    @staticmethod
    def find_shipment_items(shipment_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT si.*, COALESCE(i.product_model, si.product_model) as product_model, "
            "COALESCE(i.product_name, si.product_name) as product_name "
            "FROM shipment_items si LEFT JOIN inventory i ON si.inventory_id = i.id "
            "WHERE si.shipment_id = ?",
            (shipment_id,)
        ).fetchall()

    # ========== update_shipment ==========
    @staticmethod
    def update_shipment_fields_txn(shipment_id, changes, db):
        allowed = {
            "customer", "contact_person", "contact_phone", "address", "remark",
            "status", "receivable_amount", "payment_status",
        }
        fields = [field for field in changes if field in allowed]
        if not fields:
            return 0
        params = [changes[field] for field in fields]
        cursor = db.execute(
            "UPDATE shipments SET " + ", ".join(f"{field} = ?" for field in fields) + " WHERE id = ?",
            params + [shipment_id],
        )
        return cursor.rowcount

    # ========== delete_shipment ==========
    @staticmethod
    def find_shipment_items_for_delete_txn(shipment_id, db):
        return db.execute("SELECT * FROM shipment_items WHERE shipment_id = ?", (shipment_id,)).fetchall()

    @staticmethod
    def delete_shipment_items_txn(shipment_id, db):
        db.execute("DELETE FROM shipment_items WHERE shipment_id = ?", (shipment_id,))

    @staticmethod
    def delete_shipment_txn(shipment_id, db):
        db.execute("DELETE FROM shipments WHERE id = ?", (shipment_id,))

    # ========== complete_shipment ==========
    @staticmethod
    def complete_shipment_txn(shipment_id, completed_at, db):
        db.execute(
            "UPDATE shipments SET status = 'completed', completed_at = ? WHERE id = ?",
            (completed_at, shipment_id)
        )

    # ========== update_logistics ==========
    @staticmethod
    def update_logistics_txn(shipment_id, logistics_company, tracking_no, db):
        db.execute(
            "UPDATE shipments SET logistics_company=?, tracking_no=? WHERE id=?",
            (logistics_company, tracking_no, shipment_id)
        )

    # ========== receive_shipment ==========
    @staticmethod
    def receive_shipment_txn(shipment_id, remark_append, db):
        db.execute(
            "UPDATE shipments SET status='received', remark = remark || ? WHERE id=?",
            (remark_append, shipment_id)
        )

    # ========== record_payment ==========
    @staticmethod
    def record_payment_txn(shipment_id, new_paid, payment_status, payment_date, method, remark, db):
        db.execute(
            "UPDATE shipments SET paid_amount = ?, payment_status = ?, payment_date = ?, "
            "payment_method = ?, payment_remark = ? WHERE id = ?",
            (new_paid, payment_status, payment_date, method, remark, shipment_id)
        )

    # ========== cancel_shipment ==========
    @staticmethod
    def release_reserved_for_shipment_txn(shipment_id, db):
        return db.execute("SELECT * FROM shipment_items WHERE shipment_id = ?", (shipment_id,)).fetchall()

    @staticmethod
    def cancel_shipment_txn(shipment_id, db):
        db.execute(
            "UPDATE shipments SET status='cancelled', cancelled_at=datetime('now','localtime') WHERE id=?",
            (shipment_id,)
        )

    # ========== get_stats ==========
    @staticmethod
    def fetch_shipment_stats(today, month_start, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) as total, "
            "COALESCE(SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END),0) as pending, "
            "COALESCE(SUM(CASE WHEN status='received' THEN 1 ELSE 0 END),0) as received, "
            "COALESCE(SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END),0) as completed, "
            "COALESCE(SUM(CASE WHEN status='cancelled' THEN 1 ELSE 0 END),0) as cancelled, "
            "COALESCE(SUM(CASE WHEN date(created_at)=? THEN 1 ELSE 0 END),0) as today_count, "
            "COALESCE(SUM(CASE WHEN date(created_at)>=? THEN 1 ELSE 0 END),0) as month_count, "
            "COALESCE(SUM(CASE WHEN date(completed_at)=? THEN 1 ELSE 0 END),0) as today_completed, "
            "COALESCE(SUM(CASE WHEN status='completed' THEN total_quantity ELSE 0 END),0) as total_shipped_qty, "
            "COALESCE(SUM(receivable_amount),0) as total_receivable, "
            "COALESCE(SUM(paid_amount),0) as total_paid, "
            "COALESCE(SUM(CASE WHEN payment_status='paid' THEN 1 ELSE 0 END),0) as paid_count, "
            "COALESCE(SUM(CASE WHEN payment_status='partial' THEN 1 ELSE 0 END),0) as partial_paid "
            "FROM shipments",
            (today, month_start, today)
        ).fetchone()

    # ========== get_impact ==========
    @staticmethod
    def find_shipment_for_impact(shipment_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id, shipment_no, status, customer, total_quantity FROM shipments WHERE id = ?",
            (shipment_id,)
        ).fetchone()

    @staticmethod
    def count_shipment_items_impact(shipment_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) as cnt, COALESCE(SUM(quantity),0) as qty FROM shipment_items WHERE shipment_id = ?",
            (shipment_id,)
        ).fetchone()

    @staticmethod
    def count_distinct_inventory(shipment_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(DISTINCT inventory_id) FROM shipment_items WHERE shipment_id = ?",
            (shipment_id,)
        ).fetchone()[0]

    # ========== get_customer_history ==========
    @staticmethod
    def find_shipments_by_customer(customer, limit, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT s.*, COALESCE(si.item_count,0) as item_count FROM shipments s "
            "LEFT JOIN (SELECT shipment_id, COUNT(*) as item_count FROM shipment_items GROUP BY shipment_id) si "
            "ON si.shipment_id = s.id WHERE s.customer = ? ORDER BY s.created_at DESC LIMIT ?",
            (customer, limit)
        ).fetchall()

    # ========== _update_order_delivery_status ==========
    @staticmethod
    def find_order_ids_for_shipment_txn(shipment_id, db):
        return db.execute(
            "SELECT DISTINCT order_id FROM shipment_items WHERE shipment_id = ? AND order_id IS NOT NULL",
            (shipment_id,)
        ).fetchall()

    @staticmethod
    def sum_shipped_qty_txn(order_id, db):
        row = db.execute(
            "SELECT COALESCE(SUM(si.quantity),0) as shipped_qty FROM shipment_items si "
            "JOIN shipments s ON s.id = si.shipment_id WHERE si.order_id = ? AND s.status = 'completed'",
            (order_id,)
        ).fetchone()
        return row["shipped_qty"] if row else 0

    @staticmethod
    # ========== existence check ==========
    @staticmethod
    def shipment_exists(shipment_id, db=None):
        db = resolve_db(db)
        return db.execute("SELECT id FROM shipments WHERE id = ?", (shipment_id,)).fetchone()

    @staticmethod
    def shipment_items_exist(shipment_id, db=None):
        db = resolve_db(db)
        return db.execute("SELECT * FROM shipment_items WHERE shipment_id = ?", (shipment_id,)).fetchall()
