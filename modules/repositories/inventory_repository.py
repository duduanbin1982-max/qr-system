"""qr-system - InventoryRepository"""
from modules.db_unit_of_work import BaseService
from modules.query_utils import paginate, build_sort_clause


class InventoryRepository:

    @staticmethod
    def build_item_filters(keyword="", low_stock=False, location=""):
        clauses = ["1=1"]
        params = []
        if keyword:
            clauses.append(
                "(i.product_model LIKE ? OR i.product_name LIKE ? OR i.specification LIKE ? "
                "OR i.location LIKE ? OR i.unit LIKE ? OR i.remark LIKE ? "
                "OR o.order_no LIKE ? OR o.customer LIKE ?)"
            )
            params.extend([f"%{keyword}%"] * 8)
        if low_stock:
            clauses.append("i.quantity <= i.safe_stock AND i.safe_stock > 0")
        if location:
            clauses.append("i.location = ?")
            params.append(location)
        return " AND ".join(clauses), params

    @staticmethod
    def count_items(where_clause, params, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT COUNT(*) FROM inventory i LEFT JOIN orders o ON i.order_id = o.id "
            "LEFT JOIN products p ON i.product_model = p.product_code AND p.deleted_at IS NULL WHERE "
            + where_clause, params
        ).fetchone()[0]

    @staticmethod
    def list_items_paginated(where_clause, params, page, limit, db=None):
        db = db or BaseService.db()
        base_sql = (
            "SELECT i.*, o.order_no, o.customer, p.price, "
            "CASE WHEN i.quantity <= i.safe_stock AND i.safe_stock > 0 "
            "THEN 1 ELSE 0 END as is_low FROM inventory i "
            "LEFT JOIN orders o ON i.order_id = o.id "
            "LEFT JOIN products p ON i.product_model = p.product_code AND p.deleted_at IS NULL WHERE "
            + where_clause + " "
            + build_sort_clause("updated_at", {"updated_at": "i.updated_at"}, default="i.updated_at")
        )
        paginated_sql, all_params, size, offset = paginate(base_sql, params, page=page, page_size=limit)
        rows = db.execute(paginated_sql, all_params).fetchall()
        return rows, size

    @staticmethod
    def insert_txn(model, product_name, specification, quantity, safe_stock, location, unit, remark, category, unit_cost, last_count_date, order_id, db):
        db.execute(
            "INSERT INTO inventory (product_model, product_name, specification, "
            "quantity, safe_stock, location, unit, remark, category, unit_cost, last_count_date, order_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (model, product_name, specification, quantity, safe_stock, location, unit, remark, category, unit_cost, last_count_date, order_id)
        )
        return db.execute("SELECT last_insert_rowid()").fetchone()[0]

    @staticmethod
    def find_duplicate_model_txn(model, order_id, exclude_id, db):
        return db.execute(
            "SELECT id FROM inventory WHERE product_model = ? AND order_id = ? AND id != ?",
            (model, order_id, exclude_id)
        ).fetchone()

    @staticmethod
    def update_item_txn(item_id, model, product_name, specification, quantity, safe_stock, location, unit, remark, category, unit_cost, last_count_date, db):
        db.execute(
            "UPDATE inventory SET product_model = ?, product_name = ?, specification = ?, "
            "quantity = ?, safe_stock = ?, location = ?, unit = ?, remark = ?, "
            "category = ?, unit_cost = ?, last_count_date = ?, "
            "updated_at = datetime('now','localtime') WHERE id = ?",
            (model, product_name, specification, quantity, safe_stock, location, unit, remark, category, unit_cost, last_count_date, item_id)
        )

    @staticmethod
    def find_item_by_id(item_id, db=None):
        db = db or BaseService.db()
        return db.execute("SELECT * FROM inventory WHERE id = ?", (item_id,)).fetchone()

    @staticmethod
    def find_item_for_delete(item_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT product_model, product_name, quantity FROM inventory WHERE id = ?",
            (item_id,)
        ).fetchone()

    @staticmethod
    def delete_item_txn(item_id, db):
        db.execute("DELETE FROM inventory WHERE id = ?", (item_id,))

    @staticmethod
    def delete_logs_for_item_txn(item_id, db):
        db.execute("DELETE FROM inventory_logs WHERE inventory_id = ?", (item_id,))

    @staticmethod
    def increase_stock_txn(item_id, quantity, db):
        return db.execute(
            'UPDATE inventory SET quantity = quantity + ?, '
            'updated_at = datetime("now","localtime") WHERE id = ?',
            (quantity, item_id),
        )

    @staticmethod
    def decrease_stock_if_available_txn(item_id, quantity, db):
        return db.execute(
            'UPDATE inventory SET quantity = quantity - ?, '
            'updated_at = datetime("now","localtime") '
            'WHERE id = ? AND quantity >= ?',
            (quantity, item_id, quantity),
        )

    @staticmethod
    def insert_movement_log_txn(
        inventory_id,
        log_type,
        quantity,
        order_id=None,
        order_no="",
        remark="",
        operator_id=None,
        operator_name="",
        db=None,
    ):
        db.execute(
            "INSERT INTO inventory_logs (inventory_id, type, quantity, "
            "order_id, order_no, remark, operator_id, operator_name) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (inventory_id, log_type, quantity, order_id, order_no, remark, operator_id, operator_name),
        )

    @staticmethod
    def insert_log_txn(inventory_id, log_type, quantity, remark, operator_id, operator_name, db):
        db.execute(
            "INSERT INTO inventory_logs (inventory_id, type, quantity, remark, operator_id, operator_name) "
            "VALUES (?,?,?,?,?,?)",
            (inventory_id, log_type, quantity, remark, operator_id, operator_name)
        )

    @staticmethod
    def update_quantity_txn(item_id, new_quantity, db):
        db.execute(
            "UPDATE inventory SET quantity = ?, updated_at = datetime('now','localtime') WHERE id = ?",
            (new_quantity, item_id)
        )

    @staticmethod
    def get_item_quantity(item_id, db=None):
        db = db or BaseService.db()
        return db.execute("SELECT quantity FROM inventory WHERE id = ?", (item_id,)).fetchone()

    @staticmethod
    def find_adjustment_item(item_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT id, quantity, product_model FROM inventory WHERE id=?",
            (item_id,),
        ).fetchone()

    @staticmethod
    def count_logs(inv_id, type_filter, date_from, date_to, db=None):
        db = db or BaseService.db()
        where = ["1=1"]
        params = []
        if inv_id:
            where.append("il.inventory_id = ?"); params.append(inv_id)
        if type_filter:
            where.append("il.type = ?"); params.append(type_filter)
        if date_from:
            where.append("il.created_at >= ?"); params.append(date_from)
        if date_to:
            where.append("il.created_at <= ?"); params.append(date_to + " 23:59:59")
        w = " AND ".join(where)
        return db.execute(
            "SELECT COUNT(*) FROM inventory_logs il "
            "LEFT JOIN inventory i ON il.inventory_id = i.id "
            "LEFT JOIN orders o ON i.order_id = o.id WHERE " + w, params
        ).fetchone()[0]

    @staticmethod
    def list_logs(inv_id, type_filter, date_from, date_to, page, limit, db=None):
        db = db or BaseService.db()
        where = ["1=1"]
        params = []
        if inv_id:
            where.append("il.inventory_id = ?"); params.append(inv_id)
        if type_filter:
            where.append("il.type = ?"); params.append(type_filter)
        if date_from:
            where.append("il.created_at >= ?"); params.append(date_from)
        if date_to:
            where.append("il.created_at <= ?"); params.append(date_to + " 23:59:59")
        w = " AND ".join(where)
        offset = (page - 1) * limit
        rows = db.execute(
            "SELECT il.*, i.product_model, i.product_name, o.order_no, "
            "u.name as operator_name FROM inventory_logs il "
            "LEFT JOIN inventory i ON il.inventory_id = i.id "
            "LEFT JOIN orders o ON i.order_id = o.id "
            "LEFT JOIN users u ON il.operator_id = u.id WHERE " + w + " "
            "ORDER BY il.created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset]
        ).fetchall()
        return rows

    @staticmethod
    def list_alerts(db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT *, (safe_stock - quantity) as shortage "
            "FROM inventory "
            "WHERE quantity <= safe_stock AND safe_stock > 0 "
            "ORDER BY shortage DESC"
        ).fetchall()

    @staticmethod
    def count_item_logs(item_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT COUNT(*) FROM inventory_logs WHERE inventory_id = ?", (item_id,)
        ).fetchone()[0]

    @staticmethod
    def count_linked_orders(item_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT COUNT(*) FROM orders o JOIN inventory i ON i.order_id = o.id "
            "WHERE i.id = ? AND o.deleted_at IS NULL", (item_id,)
        ).fetchone()[0]

    @staticmethod
    def get_inventory_stats(db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT COUNT(*) as total_items, COALESCE(SUM(quantity),0) as total_quantity, "
            "COALESCE(SUM(CASE WHEN quantity <= safe_stock AND safe_stock > 0 THEN 1 ELSE 0 END),0) as low_stock "
            "FROM inventory"
        ).fetchone()

    @staticmethod
    def get_today_stats(today, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT COALESCE(SUM(CASE WHEN type='in' THEN quantity ELSE 0 END),0) as today_in, "
            "COALESCE(SUM(CASE WHEN type='out' THEN quantity ELSE 0 END),0) as today_out "
            "FROM inventory_logs WHERE date(created_at) = ?", (today,)
        ).fetchone()

    @staticmethod
    def submit_count_txn(item_id, actual_qty, diff, log_type, log_remark, db):
        db.execute(
            "UPDATE inventory SET quantity = ?, last_count_date = date('now'), "
            "updated_at = datetime('now','localtime') WHERE id = ?",
            (actual_qty, item_id)
        )
        db.execute(
            "INSERT INTO inventory_logs (inventory_id, type, quantity, remark, operator_id, operator_name) "
            "VALUES (?,?,?,?,?,?)",
            (item_id, log_type, diff, log_remark, None, "system")
        )

    @staticmethod
    def list_abc_rows(db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT inv.id, inv.product_model, "
            "COALESCE(SUM(CASE WHEN il.type='out' THEN il.quantity ELSE 0 END),0) as total_out, "
            "inv.unit_cost, "
            "COALESCE(SUM(CASE WHEN il.type='out' THEN il.quantity ELSE 0 END),0) * inv.unit_cost as out_value "
            "FROM inventory inv LEFT JOIN inventory_logs il ON il.inventory_id = inv.id "
            "GROUP BY inv.id ORDER BY out_value DESC"
        ).fetchall()

    @staticmethod
    def update_category_txn(item_id, category, db):
        db.execute("UPDATE inventory SET category=? WHERE id=?", (category, item_id))

    @staticmethod
    def list_turnover_rows(db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT inv.id, inv.product_model, inv.product_name, inv.quantity as current_stock, "
            "COALESCE(SUM(CASE WHEN il.type='out' THEN il.quantity ELSE 0 END),0) as total_out, "
            "COALESCE(SUM(CASE WHEN il.type='in' THEN il.quantity ELSE 0 END),0) as total_in, "
            "inv.unit_cost FROM inventory inv "
            "LEFT JOIN inventory_logs il ON il.inventory_id = inv.id "
            "GROUP BY inv.id ORDER BY total_out DESC"
        ).fetchall()

    @staticmethod
    def list_safe_stock_suggestion_rows(db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT inv.id, inv.product_model, inv.product_name, inv.safe_stock as current_safe, "
            "inv.quantity, "
            "COALESCE(SUM(CASE WHEN il.type='out' AND il.created_at >= date('now','-30 days') "
            "THEN il.quantity ELSE 0 END),0) as month_out "
            "FROM inventory inv LEFT JOIN inventory_logs il ON il.inventory_id = inv.id "
            "GROUP BY inv.id"
        ).fetchall()

    @staticmethod
    def list_inbound_batches(item_id=None, lot_no=None, db=None):
        db = db or BaseService.db()
        clauses = ["type='in'"]
        params = []
        if item_id:
            clauses.append("inventory_id = ?")
            params.append(item_id)
        if lot_no:
            clauses.append("lot_no = ?")
            params.append(lot_no)
        return db.execute(
            "SELECT * FROM inventory_logs WHERE "
            + " AND ".join(clauses)
            + " ORDER BY created_at DESC LIMIT 100",
            params,
        ).fetchall()

    @staticmethod
    def list_batch_outbound_after(inventory_id, created_at, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT * FROM inventory_logs WHERE inventory_id=? AND type='out' "
            "AND created_at >= ? ORDER BY created_at",
            (inventory_id, created_at),
        ).fetchall()

    @staticmethod
    def list_locations(db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT location, COUNT(*) as item_count, SUM(quantity) as total_qty, "
            "GROUP_CONCAT(product_model || '(' || quantity || ')', ', ') as items "
            "FROM inventory WHERE location != '' GROUP BY location ORDER BY location"
        ).fetchall()

    @staticmethod
    def update_location_txn(item_id, new_location, db):
        db.execute(
            "UPDATE inventory SET location=?, updated_at=datetime('now','localtime') WHERE id=?",
            (new_location, item_id),
        )

    @staticmethod
    def count_inventory_items(db=None):
        db = db or BaseService.db()
        return db.execute("SELECT COUNT(*) as cnt FROM inventory").fetchone()["cnt"]

    @staticmethod
    def count_inventory_items_counted_today(db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT COUNT(*) as cnt FROM inventory WHERE last_count_date >= date('now')"
        ).fetchone()["cnt"]

    @staticmethod
    def get_count_item(item_id, db=None):
        db = db or BaseService.db()
        return db.execute("SELECT * FROM inventory WHERE id = ?", (item_id,)).fetchone()
