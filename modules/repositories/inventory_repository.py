"""qr-system - InventoryRepository"""
from modules.repositories.context import resolve_db
from modules.query_utils import paginate, build_sort_clause


class InventoryRepository:

    EMPTY_SPECIFICATION_FILTER = "__empty__"
    NORMALIZED_QUALITY_STATUS_SQL = (
        "COALESCE(NULLIF(TRIM(COALESCE(i.quality_status,'')),''),'qualified')"
    )

    @staticmethod
    def find_log_by_id(log_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT inventory_id,serial_no,qty_delta FROM inventory_logs WHERE id=?",
            (log_id,),
        ).fetchone()

    @staticmethod
    def find_allocation_run_by_idempotency(idempotency_key, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM inventory_allocation_runs WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()

    @staticmethod
    def find_allocation_run(run_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM inventory_allocation_runs WHERE id=?", (run_id,)
        ).fetchone()

    @staticmethod
    def find_reversal_run(original_run_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM inventory_allocation_runs WHERE reversal_of_run_id=?",
            (original_run_id,),
        ).fetchone()

    @staticmethod
    def list_allocation_items(run_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM inventory_allocation_items WHERE run_id=? ORDER BY sequence_no",
            (run_id,),
        ).fetchall()

    @staticmethod
    def list_allocation_runs(product_id=None, page=1, limit=50, db=None):
        db = resolve_db(db)
        page = max(int(page), 1)
        limit = max(1, min(int(limit), 200))
        clauses, params = ["1=1"], []
        if product_id is not None:
            clauses.append("r.product_id=?")
            params.append(product_id)
        where = " AND ".join(clauses)
        total = db.execute(
            "SELECT COUNT(*) FROM inventory_allocation_runs r WHERE " + where,
            params,
        ).fetchone()[0]
        rows = db.execute(
            "SELECT r.*,p.product_code,p.product_name "
            "FROM inventory_allocation_runs r JOIN products p ON p.id=r.product_id "
            "WHERE " + where + " ORDER BY r.created_at DESC,r.id DESC LIMIT ? OFFSET ?",
            [*params, limit, (page - 1) * limit],
        ).fetchall()
        return rows, int(total)

    @staticmethod
    def insert_allocation_run_txn(payload, db):
        cursor = db.execute(
            "INSERT INTO inventory_allocation_runs "
            "(idempotency_key,request_digest,preview_digest,result_digest,product_id,"
            "compatibility_key,mode,requested_quantity,reason,operator_id,operator_name,"
            "reversal_of_run_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                payload["idempotency_key"], payload["request_digest"],
                payload["preview_digest"], payload["result_digest"],
                payload["product_id"], payload["compatibility_key"], payload["mode"],
                payload["requested_quantity"], payload.get("reason", ""),
                payload.get("operator_id"), payload.get("operator_name", ""),
                payload.get("reversal_of_run_id"),
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def insert_allocation_item_txn(payload, db):
        cursor = db.execute(
            "INSERT INTO inventory_allocation_items "
            "(run_id,sequence_no,inventory_id,source_order_id,order_no_snapshot,"
            "lot_no,serial_no,location_snapshot,allocated_quantity,movement_id,"
            "balance_before,balance_after) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                payload["run_id"], payload["sequence_no"], payload["inventory_id"],
                payload.get("source_order_id"), payload.get("order_no", ""),
                payload.get("lot_no", ""), payload.get("serial_no", ""),
                payload.get("location", ""), payload["allocated_quantity"],
                payload["movement_id"], payload["balance_before"],
                payload["balance_after"],
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def build_item_filters(keyword="", low_stock=False, location="", specifications=None,
                           quality_status=""):
        clauses = ["i.deleted_at IS NULL"]
        params = []
        if keyword:
            clauses.append(
                "(i.product_model LIKE ? OR i.product_name LIKE ? OR i.specification LIKE ? "
                "OR i.location LIKE ? OR i.unit LIKE ? OR i.remark LIKE ? "
                "OR o.order_no LIKE ? OR o.customer LIKE ?)"
            )
            params.extend([f"%{keyword}%"] * 8)
        if low_stock:
            clauses.append(
                "i.quantity - COALESCE(i.reserved,0) - COALESCE(i.frozen_quantity,0) "
                "<= i.safe_stock AND i.safe_stock > 0"
            )
        if location:
            clauses.append("i.location = ?")
            params.append(location)
        specifications = tuple(specifications or ())
        if specifications:
            spec_clauses = []
            for specification in specifications:
                if specification == InventoryRepository.EMPTY_SPECIFICATION_FILTER:
                    spec_clauses.append("TRIM(COALESCE(i.specification, '')) = ''")
                else:
                    spec_clauses.append("TRIM(COALESCE(i.specification, '')) = ?")
                    params.append(specification)
            clauses.append("(" + " OR ".join(spec_clauses) + ")")
        if quality_status:
            clauses.append(InventoryRepository.NORMALIZED_QUALITY_STATUS_SQL + " = ?")
            params.append(quality_status)
        return " AND ".join(clauses), params

    @staticmethod
    def count_items(where_clause, params, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) FROM inventory i LEFT JOIN orders o ON i.order_id = o.id "
            "LEFT JOIN product_code_aliases pca ON pca.product_code = i.product_model "
            "LEFT JOIN products p ON p.id = pca.product_id AND p.deleted_at IS NULL WHERE "
            + where_clause, params
        ).fetchone()[0]

    @staticmethod
    def list_items_paginated(where_clause, params, page, limit, db=None):
        db = resolve_db(db)
        base_sql = (
            "SELECT COALESCE(i.product_id,o.product_id,pca.product_id) AS product_id, "
            "COALESCE(NULLIF(i.product_code_snapshot,''),NULLIF(o.product_code,''),"
            "i.product_model) AS product_code_snapshot, "
            "COALESCE(NULLIF(i.product_name_snapshot,''),NULLIF(i.product_name,''),"
            "o.product_name,'') AS product_name_snapshot, "
            "i.*, COALESCE(i.frozen_quantity,0) AS frozen_quantity, "
            "MAX(i.quantity - COALESCE(i.reserved,0) - COALESCE(i.frozen_quantity,0), 0) "
            "AS available_quantity, "
            "o.order_no, o.customer, p.price, "
            "CASE WHEN i.quantity - COALESCE(i.reserved,0) - COALESCE(i.frozen_quantity,0) "
            "<= i.safe_stock AND i.safe_stock > 0 "
            "THEN 1 ELSE 0 END as is_low FROM inventory i "
            "LEFT JOIN orders o ON i.order_id = o.id "
            "LEFT JOIN product_code_aliases pca ON pca.product_code = i.product_model "
            "LEFT JOIN products p ON p.id = pca.product_id AND p.deleted_at IS NULL WHERE "
            + where_clause + " "
            + build_sort_clause("updated_at", {"updated_at": "i.updated_at"}, default="i.updated_at")
        )
        paginated_sql, all_params, size, offset = paginate(base_sql, params, page=page, page_size=limit)
        rows = db.execute(paginated_sql, all_params).fetchall()
        return rows, size

    @staticmethod
    def insert_txn(
        model, product_name, specification, safe_stock, location, unit, remark,
        category, unit_cost, order_id, product_id, product_code_snapshot,
        product_name_snapshot, route_version_id_snapshot, db
    ):
        db.execute(
            "INSERT INTO inventory (product_model, product_name, specification, "
            "quantity, safe_stock, location, unit, remark, category, unit_cost, order_id, "
            "product_id, product_code_snapshot, product_name_snapshot, "
            "route_version_id_snapshot) VALUES (?,?,?,0,?,?,?,?,?,?,?,?,?,?,?)",
            (
                model, product_name, specification, safe_stock, location, unit,
                remark, category, unit_cost, order_id, product_id,
                product_code_snapshot, product_name_snapshot, route_version_id_snapshot,
            )
        )
        return db.execute("SELECT last_insert_rowid()").fetchone()[0]

    @staticmethod
    def find_duplicate_model_txn(model, order_id, exclude_id, db):
        return db.execute(
            "SELECT id FROM inventory WHERE product_model = ? "
            "AND ((order_id IS NULL AND ? IS NULL) OR order_id = ?) "
            "AND id != ? AND deleted_at IS NULL",
            (model, order_id, order_id, exclude_id)
        ).fetchone()

    @staticmethod
    def update_item_txn(item_id, model, product_name, specification, safe_stock, location, unit, remark, category, unit_cost, db):
        return db.execute(
            "UPDATE inventory SET product_model = ?, product_name = ?, specification = ?, "
            "safe_stock = ?, location = ?, unit = ?, remark = ?, category = ?, unit_cost = ?, "
            "updated_at = datetime('now','localtime') WHERE id = ? AND deleted_at IS NULL",
            (model, product_name, specification, safe_stock, location, unit, remark, category, unit_cost, item_id)
        )

    @staticmethod
    def find_item_by_id(item_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM inventory WHERE id = ? AND deleted_at IS NULL",
            (item_id,),
        ).fetchone()

    @staticmethod
    def list_available_by_order(order_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id AS inventory_id, product_model, product_name, specification, "
            "quantity, reserved, "
            "MAX(quantity - COALESCE(reserved,0) - COALESCE(frozen_quantity,0),0) "
            "AS available_quantity, unit, order_id FROM inventory "
            "WHERE order_id = ? AND "
            "MAX(quantity - COALESCE(reserved,0) - COALESCE(frozen_quantity,0),0) > 0 "
            "AND deleted_at IS NULL",
            (order_id,),
        ).fetchall()

    @staticmethod
    def find_item_for_delete(item_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT product_model, product_name, quantity, reserved, deleted_at "
            "FROM inventory WHERE id = ?",
            (item_id,)
        ).fetchone()

    @staticmethod
    def archive_item_txn(item_id, db):
        return db.execute(
            "UPDATE inventory SET deleted_at = datetime('now','localtime'), "
            "updated_at = datetime('now','localtime') "
            "WHERE id = ? AND deleted_at IS NULL AND quantity = 0 AND reserved = 0",
            (item_id,),
        )

    @staticmethod
    def increase_stock_txn(item_id, quantity, db):
        return db.execute(
            'UPDATE inventory SET quantity = quantity + ?, '
            'updated_at = datetime("now","localtime") '
            'WHERE id = ? AND deleted_at IS NULL',
            (quantity, item_id),
        )

    @staticmethod
    def decrease_stock_if_available_txn(item_id, quantity, db):
        return db.execute(
            'UPDATE inventory SET quantity = quantity - ?, '
            'updated_at = datetime("now","localtime") '
            'WHERE id = ? AND quantity - reserved >= ? AND deleted_at IS NULL',
            (quantity, item_id, quantity),
        )

    @staticmethod
    def consume_stock_txn(item_id, quantity, reserved_quantity, db):
        if reserved_quantity:
            return db.execute(
                "UPDATE inventory SET quantity = quantity - ?, reserved = reserved - ?, "
                "updated_at = datetime('now','localtime') "
                "WHERE id = ? AND quantity >= ? AND reserved >= ? AND deleted_at IS NULL",
                (quantity, reserved_quantity, item_id, quantity, reserved_quantity),
            )
        return db.execute(
            "UPDATE inventory SET quantity = quantity - ?, "
            "updated_at = datetime('now','localtime') "
            "WHERE id = ? AND quantity - reserved >= ? AND deleted_at IS NULL",
            (quantity, item_id, quantity),
        )

    @staticmethod
    def reserve_stock_txn(item_id, quantity, db):
        return db.execute(
            "UPDATE inventory SET reserved = reserved + ?, "
            "updated_at = datetime('now','localtime') "
            "WHERE id = ? AND quantity - reserved >= ? AND deleted_at IS NULL",
            (quantity, item_id, quantity),
        )

    @staticmethod
    def release_reserved_stock_txn(item_id, quantity, db):
        return db.execute(
            "UPDATE inventory SET reserved = reserved - ?, "
            "updated_at = datetime('now','localtime') "
            "WHERE id = ? AND reserved >= ? AND deleted_at IS NULL",
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
        qty_delta=0,
        balance_before=None,
        balance_after=None,
        lot_no="",
        serial_no="",
        source_type="",
        source_id=None,
        idempotency_key="",
        movement_no="",
        reversal_of_id=None,
        db=None,
    ):
        cursor = db.execute(
            "INSERT INTO inventory_logs (inventory_id, type, quantity, "
            "order_id, order_no, remark, operator_id, operator_name, movement_no, qty_delta, "
            "balance_before, balance_after, lot_no, serial_no, source_type, source_id, "
            "idempotency_key, reversal_of_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                inventory_id, log_type, quantity, order_id, order_no, remark,
                operator_id, operator_name, movement_no, qty_delta,
                balance_before, balance_after, lot_no, serial_no, source_type,
                source_id, idempotency_key, reversal_of_id,
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def find_log_by_idempotency_key(idempotency_key, db=None):
        if not idempotency_key:
            return None
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM inventory_logs WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()

    @staticmethod
    def get_lot_balance(inventory_id, lot_no, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT COALESCE(SUM(qty_delta), 0) AS balance FROM inventory_logs "
            "WHERE inventory_id = ? AND lot_no = ?",
            (inventory_id, lot_no),
        ).fetchone()
        return float(row["balance"] or 0)

    @staticmethod
    def get_serial_balance(inventory_id, serial_no, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT COALESCE(SUM(qty_delta), 0) AS balance FROM inventory_logs "
            "WHERE inventory_id = ? AND serial_no = ?",
            (inventory_id, serial_no),
        ).fetchone()
        return float(row["balance"] or 0)

    @staticmethod
    def find_serial_inbound(serial_no, db=None):
        if not serial_no:
            return None
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM inventory_logs WHERE serial_no = ? AND qty_delta > 0 LIMIT 1",
            (serial_no,),
        ).fetchone()

    @staticmethod
    def get_item_quantity(item_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT quantity, reserved FROM inventory WHERE id = ? AND deleted_at IS NULL",
            (item_id,),
        ).fetchone()

    @staticmethod
    def find_adjustment_item(item_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id, quantity, reserved, product_model FROM inventory "
            "WHERE id=? AND deleted_at IS NULL",
            (item_id,),
        ).fetchone()

    @staticmethod
    def count_logs(inv_id, type_filter, date_from, date_to, db=None):
        db = resolve_db(db)
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
        db = resolve_db(db)
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
        db = resolve_db(db)
        return db.execute(
            "SELECT *, quantity - reserved AS available_quantity, "
            "(safe_stock - (quantity - reserved)) as shortage "
            "FROM inventory "
            "WHERE quantity - reserved <= safe_stock AND safe_stock > 0 AND deleted_at IS NULL "
            "ORDER BY shortage DESC"
        ).fetchall()

    @staticmethod
    def count_item_logs(item_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) FROM inventory_logs WHERE inventory_id = ?", (item_id,)
        ).fetchone()[0]

    @staticmethod
    def count_linked_orders(item_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) FROM orders o JOIN inventory i ON i.order_id = o.id "
            "WHERE i.id = ? AND o.deleted_at IS NULL", (item_id,)
        ).fetchone()[0]

    @staticmethod
    def count_linked_shipment_items(item_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) FROM shipment_items WHERE inventory_id = ?",
            (item_id,),
        ).fetchone()[0]

    @staticmethod
    def get_inventory_stats(where_clause=None, params=None, db=None):
        db = resolve_db(db)
        if where_clause is None:
            return db.execute(
                "SELECT COUNT(*) as total_items, COALESCE(SUM(quantity),0) as total_quantity, "
                "COALESCE(SUM(CASE WHEN quantity - COALESCE(reserved,0) "
                "- COALESCE(frozen_quantity,0) <= safe_stock "
                "AND safe_stock > 0 THEN 1 ELSE 0 END),0) as low_stock "
                "FROM inventory WHERE deleted_at IS NULL"
            ).fetchone()
        params = params or []
        return db.execute(
            "SELECT COUNT(DISTINCT i.id) as total_items, "
            "COALESCE(SUM(i.quantity),0) as total_quantity, "
            "COALESCE(SUM(CASE WHEN i.quantity - COALESCE(i.reserved,0) "
            "- COALESCE(i.frozen_quantity,0) <= i.safe_stock "
            "AND i.safe_stock > 0 THEN 1 ELSE 0 END),0) as low_stock "
            "FROM inventory i LEFT JOIN orders o ON i.order_id = o.id "
            "WHERE " + where_clause,
            params,
        ).fetchone()

    @staticmethod
    def get_today_stats(today, where_clause=None, params=None, db=None):
        db = resolve_db(db)
        if where_clause is None:
            return db.execute(
                "SELECT COALESCE(SUM(CASE WHEN qty_delta > 0 THEN qty_delta ELSE 0 END),0) as today_in, "
                "COALESCE(SUM(CASE WHEN qty_delta < 0 THEN -qty_delta ELSE 0 END),0) as today_out "
                "FROM inventory_logs WHERE date(created_at) = ?", (today,)
            ).fetchone()
        params = params or []
        return db.execute(
            "SELECT COALESCE(SUM(CASE WHEN il.qty_delta > 0 THEN il.qty_delta ELSE 0 END),0) as today_in, "
            "COALESCE(SUM(CASE WHEN il.qty_delta < 0 THEN -il.qty_delta ELSE 0 END),0) as today_out "
            "FROM inventory_logs il JOIN inventory i ON i.id = il.inventory_id "
            "LEFT JOIN orders o ON i.order_id = o.id "
            "WHERE date(il.created_at) = ? AND " + where_clause,
            [today, *params],
        ).fetchone()

    @staticmethod
    def list_filter_options(db=None):
        """Return distinct order-view filter values from active inventory facts."""
        db = resolve_db(db)
        specifications = db.execute(
            "SELECT TRIM(COALESCE(i.specification,'')) AS value, COUNT(*) AS inventory_count "
            "FROM inventory i WHERE i.deleted_at IS NULL "
            "GROUP BY TRIM(COALESCE(i.specification,'')) "
            "ORDER BY CASE WHEN value='' THEN 1 ELSE 0 END, value COLLATE NOCASE"
        ).fetchall()
        quality_statuses = db.execute(
            "SELECT COALESCE(NULLIF(TRIM(COALESCE(i.quality_status,'')),''),'qualified') AS value, "
            "COUNT(*) AS inventory_count FROM inventory i WHERE i.deleted_at IS NULL "
            "GROUP BY COALESCE(NULLIF(TRIM(COALESCE(i.quality_status,'')),''),'qualified') "
            "ORDER BY value COLLATE NOCASE"
        ).fetchall()
        locations = db.execute(
            "SELECT TRIM(COALESCE(i.location,'')) AS value, COUNT(*) AS inventory_count "
            "FROM inventory i WHERE i.deleted_at IS NULL AND TRIM(COALESCE(i.location,'')) != '' "
            "GROUP BY TRIM(COALESCE(i.location,'')) ORDER BY value COLLATE NOCASE"
        ).fetchall()
        return {
            "specifications": [dict(row) for row in specifications],
            "quality_statuses": [dict(row) for row in quality_statuses],
            "locations": [dict(row) for row in locations],
        }

    @staticmethod
    def list_abc_rows(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT inv.id, inv.product_model, "
            "COALESCE(SUM(CASE WHEN il.qty_delta < 0 THEN -il.qty_delta ELSE 0 END),0) as total_out, "
            "inv.unit_cost, "
            "COALESCE(SUM(CASE WHEN il.qty_delta < 0 THEN -il.qty_delta ELSE 0 END),0) * inv.unit_cost as out_value "
            "FROM inventory inv LEFT JOIN inventory_logs il ON il.inventory_id = inv.id "
            "WHERE inv.deleted_at IS NULL GROUP BY inv.id ORDER BY out_value DESC"
        ).fetchall()

    @staticmethod
    def update_category_txn(item_id, category, db):
        return db.execute("UPDATE inventory SET category=? WHERE id=? AND deleted_at IS NULL", (category, item_id))

    @staticmethod
    def list_turnover_rows(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT inv.id, inv.product_model, inv.product_name, inv.quantity as current_stock, "
            "COALESCE(SUM(CASE WHEN il.qty_delta < 0 THEN -il.qty_delta ELSE 0 END),0) as total_out, "
            "COALESCE(SUM(CASE WHEN il.qty_delta > 0 THEN il.qty_delta ELSE 0 END),0) as total_in, "
            "inv.unit_cost FROM inventory inv "
            "LEFT JOIN inventory_logs il ON il.inventory_id = inv.id "
            "WHERE inv.deleted_at IS NULL GROUP BY inv.id ORDER BY total_out DESC"
        ).fetchall()

    @staticmethod
    def list_safe_stock_suggestion_rows(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT inv.id, inv.product_model, inv.product_name, inv.safe_stock as current_safe, "
            "inv.quantity, "
            "COALESCE(SUM(CASE WHEN il.qty_delta < 0 "
            "AND il.created_at >= date('now','-30 days') "
            "THEN -il.qty_delta ELSE 0 END),0) as month_out "
            "FROM inventory inv LEFT JOIN inventory_logs il ON il.inventory_id = inv.id "
            "WHERE inv.deleted_at IS NULL GROUP BY inv.id"
        ).fetchall()

    @staticmethod
    def list_inbound_batches(item_id=None, lot_no=None, db=None):
        db = resolve_db(db)
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
    def list_batch_movements(item_id=None, db=None):
        db = resolve_db(db)
        params = []
        where = "WHERE i.deleted_at IS NULL"
        if item_id:
            where += " AND il.inventory_id = ?"
            params.append(item_id)
        return db.execute(
            "SELECT il.*, i.product_model, i.product_name FROM inventory_logs il "
            "JOIN inventory i ON i.id = il.inventory_id "
            + where + " ORDER BY il.inventory_id, il.created_at, il.id",
            params,
        ).fetchall()

    @staticmethod
    def list_locations(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT location, COUNT(*) as item_count, SUM(quantity) as total_qty, "
            "GROUP_CONCAT(product_model || '(' || quantity || ')', ', ') as items "
            "FROM inventory WHERE location != '' AND deleted_at IS NULL "
            "GROUP BY location ORDER BY location"
        ).fetchall()

    @staticmethod
    def update_location_txn(item_id, new_location, db):
        return db.execute(
            "UPDATE inventory SET location=?, updated_at=datetime('now','localtime') "
            "WHERE id=? AND deleted_at IS NULL",
            (new_location, item_id),
        )

    @staticmethod
    def count_inventory_items(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) as cnt FROM inventory WHERE deleted_at IS NULL"
        ).fetchone()["cnt"]

    @staticmethod
    def count_inventory_items_counted_today(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) as cnt FROM inventory "
            "WHERE last_count_date >= date('now') AND deleted_at IS NULL"
        ).fetchone()["cnt"]

    @staticmethod
    def get_count_item(item_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM inventory WHERE id = ? AND deleted_at IS NULL",
            (item_id,),
        ).fetchone()

    @staticmethod
    def create_count_task_txn(task_no, user_id, user_name, db):
        cursor = db.execute(
            "INSERT INTO inventory_count_tasks "
            "(task_no, status, created_by, created_by_name) VALUES (?, 'counting', ?, ?)",
            (task_no, user_id, user_name),
        )
        task_id = cursor.lastrowid
        db.execute(
            "INSERT INTO inventory_count_items "
            "(task_id, inventory_id, product_model, product_name, book_quantity) "
            "SELECT ?, id, product_model, product_name, quantity FROM inventory "
            "WHERE deleted_at IS NULL",
            (task_id,),
        )
        return task_id

    @staticmethod
    def find_latest_count_task(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM inventory_count_tasks ORDER BY id DESC LIMIT 1"
        ).fetchone()

    @staticmethod
    def find_open_count_task(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM inventory_count_tasks "
            "WHERE status IN ('counting', 'submitted') ORDER BY id DESC LIMIT 1"
        ).fetchone()

    @staticmethod
    def find_count_task(task_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM inventory_count_tasks WHERE id = ?",
            (task_id,),
        ).fetchone()

    @staticmethod
    def list_count_task_items(task_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM inventory_count_items WHERE task_id = ? ORDER BY id",
            (task_id,),
        ).fetchall()

    @staticmethod
    def update_count_item_txn(task_id, item_id, actual_qty, remark, user_id, user_name, db):
        cursor = db.execute(
            "UPDATE inventory_count_items SET actual_quantity = ?, "
            "difference = ? - book_quantity, status = 'counted', remark = ?, "
            "counted_by = ?, counted_by_name = ?, "
            "counted_at = datetime('now','localtime') "
            "WHERE task_id = ? AND inventory_id = ? AND status != 'posted' "
            "AND EXISTS (SELECT 1 FROM inventory_count_tasks t "
            "WHERE t.id = ? AND t.status = 'counting')",
            (actual_qty, actual_qty, remark, user_id, user_name, task_id, item_id, task_id),
        )
        db.execute(
            "UPDATE inventory_count_tasks SET status = CASE WHEN EXISTS ("
            "SELECT 1 FROM inventory_count_items WHERE task_id = ? AND status = 'pending'"
            ") THEN 'counting' ELSE 'submitted' END, "
            "submitted_at = CASE WHEN EXISTS ("
            "SELECT 1 FROM inventory_count_items WHERE task_id = ? AND status = 'pending'"
            ") THEN submitted_at ELSE datetime('now','localtime') END, "
            "updated_at = datetime('now','localtime') WHERE id = ?",
            (task_id, task_id, task_id),
        )
        return cursor

    @staticmethod
    def mark_count_item_posted_txn(count_item_id, movement_id, db):
        db.execute(
            "UPDATE inventory_count_items SET status = 'posted', posted_movement_id = ? "
            "WHERE id = ?",
            (movement_id, count_item_id),
        )

    @staticmethod
    def mark_inventory_counted_txn(inventory_id, db):
        db.execute(
            "UPDATE inventory SET last_count_date = date('now','localtime'), "
            "updated_at = datetime('now','localtime') "
            "WHERE id = ? AND deleted_at IS NULL",
            (inventory_id,),
        )

    @staticmethod
    def approve_count_task_txn(task_id, user_id, user_name, db):
        return db.execute(
            "UPDATE inventory_count_tasks SET status = 'posted', approved_by = ?, "
            "approved_by_name = ?, approved_at = datetime('now','localtime'), "
            "updated_at = datetime('now','localtime') "
            "WHERE id = ? AND status = 'submitted'",
            (user_id, user_name, task_id),
        )
