"""qr-system — RouteRepository（工序路线数据访问层）"""
from modules.repositories.context import resolve_db


class RouteRepository:
    """工序路线数据访问 — 封装所有路线 SQL 查询。"""

    @staticmethod
    def list_routes(category="", search="", limit=None, offset=0, db=None):
        db = resolve_db(db)
        conditions = []
        params = []
        if category:
            conditions.append("category = ?")
            params.append(category)
        if search:
            conditions.append('name LIKE ? ESCAPE "\\"')
            safe_search = search.replace("%", "\\%").replace("_", "\\_")
            params.append(f"%{safe_search}%")
        where_sql = " WHERE " + " AND ".join(conditions) if conditions else ""
        total = db.execute(
            "SELECT COUNT(*) FROM process_routes" + where_sql, params
        ).fetchone()[0]
        sql = "SELECT * FROM process_routes" + where_sql + " ORDER BY created_at DESC"
        query_params = list(params)
        if limit:
            size = max(1, min(int(limit), 200))
            sql += " LIMIT ? OFFSET ?"
            query_params.extend([size, offset])
        return db.execute(sql, query_params).fetchall(), total

    @staticmethod
    def list_routes_query(sql, params, db=None):
        db = resolve_db(db)
        return db.execute(sql, params).fetchall()

    @staticmethod
    def list_route_items(route_ids, db=None):
        db = resolve_db(db)
        placeholders = ",".join("?" for _ in route_ids)
        return db.execute(
            "SELECT pri.*, p.name as process_name, p.category as category, "
            "p.status as process_status "
            "FROM process_route_items pri "
            "LEFT JOIN processes p ON pri.process_id = p.id "
            "WHERE pri.route_id IN (" + placeholders + ") "
            "ORDER BY pri.route_id, pri.seq_order",
            route_ids
        ).fetchall()

    @staticmethod
    def get_route_summary(db=None):
        db = resolve_db(db)
        category_counts = {
            row["category"]: row["cnt"]
            for row in db.execute(
                "SELECT category, COUNT(*) AS cnt FROM process_routes GROUP BY category"
            ).fetchall()
        }
        return {
            "total_routes": sum(category_counts.values()),
            "category_counts": category_counts,
            "process_nodes_total": db.execute(
                "SELECT COUNT(*) FROM process_route_items"
            ).fetchone()[0],
        }

    @staticmethod
    def get_route_usage_counts(route_ids, db=None):
        """批量统计路线引用；回收站记录仍可恢复，因此也计入引用。"""
        db = resolve_db(db)
        normalized_ids = list(dict.fromkeys(int(route_id) for route_id in route_ids))
        usage = {
            route_id: {"used_orders": 0, "used_products": 0, "is_locked": False}
            for route_id in normalized_ids
        }
        if not normalized_ids:
            return usage

        placeholders = ",".join("?" for _ in normalized_ids)
        for table, count_key in (("orders", "used_orders"), ("products", "used_products")):
            rows = db.execute(
                f"SELECT route_id, COUNT(*) AS cnt FROM {table} "
                f"WHERE route_id IN ({placeholders}) GROUP BY route_id",
                normalized_ids,
            ).fetchall()
            for row in rows:
                usage[row["route_id"]][count_key] = row["cnt"]

        for counts in usage.values():
            counts["is_locked"] = bool(counts["used_orders"] or counts["used_products"])
        return usage

    @staticmethod
    def get_route_usage(rid, db=None):
        return RouteRepository.get_route_usage_counts([rid], db=db)[int(rid)]

    @staticmethod
    def find_route_by_name(name, db=None):
        db = resolve_db(db)
        return db.execute("SELECT id FROM process_routes WHERE name = ?", (name,)).fetchone()

    @staticmethod
    def insert_route_txn(name, description, category, db):
        cur = db.execute(
            "INSERT INTO process_routes (name, description, category, updated_at) "
            "VALUES (?, ?, ?, datetime('now','localtime'))",
            (name, description, category)
        )
        return cur.lastrowid

    @staticmethod
    def insert_route_item_txn(route_id, process_id, seq_order, required_audit, db):
        db.execute(
            "INSERT INTO process_route_items "
            "(route_id, process_id, seq_order, required_audit) VALUES (?, ?, ?, ?)",
            (route_id, process_id, seq_order, required_audit)
        )

    @staticmethod
    def find_existing_process_ids(pids, db=None):
        db = resolve_db(db)
        placeholders = ",".join("?" for _ in pids)
        return db.execute(
            "SELECT id, name, category, status FROM processes WHERE id IN ("
            + placeholders + ")", pids
        ).fetchall()

    @staticmethod
    def find_route_by_id(rid, db=None):
        db = resolve_db(db)
        return db.execute("SELECT * FROM process_routes WHERE id = ?", (rid,)).fetchone()

    @staticmethod
    def update_route_txn(name, description, category, rid, db):
        db.execute(
            "UPDATE process_routes SET name=?, description=?, category=?, "
            "updated_at=datetime('now','localtime') WHERE id = ?",
            (name, description, category, rid)
        )

    @staticmethod
    def delete_route_items_txn(rid, db):
        db.execute("DELETE FROM process_route_items WHERE route_id = ?", (rid,))

    @staticmethod
    def delete_route_txn(rid, db):
        db.execute("DELETE FROM process_routes WHERE id = ?", (rid,))

    @staticmethod
    def count_orders_using_route(rid, db=None):
        usage = RouteRepository.get_route_usage(rid, db=db)
        return {"cnt": usage["used_orders"]}

    @staticmethod
    def find_orders_using_route_txn(rid, db):
        return db.execute(
            "SELECT id FROM orders WHERE deleted_at IS NULL AND route_id = ? ORDER BY id", (rid,)
        ).fetchall()

    @staticmethod
    def count_products_using_route(rid, db=None):
        usage = RouteRepository.get_route_usage(rid, db=db)
        return {"cnt": usage["used_products"]}

    @staticmethod
    def find_route_name(rid, db=None):
        db = resolve_db(db)
        return db.execute("SELECT id, name FROM process_routes WHERE id = ?", (rid,)).fetchone()

    @staticmethod
    def check_order_exists(order_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id FROM orders WHERE id = ? AND deleted_at IS NULL", (order_id,)
        ).fetchone()

    @staticmethod
    def find_route_items_ordered(rid, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM process_route_items WHERE route_id = ? ORDER BY seq_order", (rid,)
        ).fetchall()

    @staticmethod
    def find_route_items_with_processes(rid, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT pri.*, p.name AS process_name, p.category AS process_category, "
            "p.status AS process_status FROM process_route_items pri "
            "JOIN processes p ON p.id = pri.process_id "
            "WHERE pri.route_id = ? ORDER BY pri.seq_order, pri.id",
            (rid,),
        ).fetchall()

    @staticmethod
    def count_work_records_for_order_txn(order_id, db):
        row = db.execute(
            "SELECT COUNT(*) as cnt FROM work_records WHERE order_id = ?", (order_id,)
        ).fetchone()
        return row["cnt"] if row else 0

    @staticmethod
    def update_order_route_txn(rid, order_id, db):
        db.execute("UPDATE orders SET route_id = ? WHERE id = ?", (rid, order_id))

    @staticmethod
    def delete_order_processes_txn(order_id, db):
        db.execute("DELETE FROM order_processes WHERE order_id = ?", (order_id,))

    @staticmethod
    def insert_order_process_txn(order_id, process_id, seq_order, required_audit, db):
        db.execute(
            "INSERT INTO order_processes (order_id, process_id, seq_order, required_audit) "
            "VALUES (?, ?, ?, ?)",
            (order_id, process_id, seq_order, required_audit)
        )

    @staticmethod
    def replace_order_processes_txn(order_id, route_items, db):
        RouteRepository.delete_order_processes_txn(order_id, db=db)
        for item in route_items:
            RouteRepository.insert_order_process_txn(
                order_id, item["process_id"], item["seq_order"], item["required_audit"], db=db
            )
        return len(route_items)
