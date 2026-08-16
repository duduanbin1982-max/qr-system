"""qr-system — RouteRepository（工序路线数据访问层）"""
from modules.master_data_references import ROUTE_REFERENCES
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
            route_id: {
                "used_orders": 0,
                "used_products": 0,
                "is_locked": False,
                "reference_counts": [],
            }
            for route_id in normalized_ids
        }
        if not normalized_ids:
            return usage

        placeholders = ",".join("?" for _ in normalized_ids)
        table_cache = {}
        for reference in ROUTE_REFERENCES:
            table_exists = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (reference.table,),
            ).fetchone()
            if not table_exists:
                continue
            available_columns = table_cache.setdefault(
                reference.table,
                {
                    row[1]
                    for row in db.execute(f'PRAGMA table_info("{reference.table}")')
                },
            )
            scalar_columns = [
                column
                for column in reference.root_columns
                if column in available_columns
            ]
            if not scalar_columns:
                continue
            predicate = " OR ".join(
                f'"{column}" IN ({placeholders})' for column in scalar_columns
            )
            select_value = f'"{scalar_columns[0]}"'
            if len(scalar_columns) > 1:
                select_value = "COALESCE(" + ",".join(
                    f'"{column}"' for column in scalar_columns
                ) + ")"
            params = normalized_ids * len(scalar_columns)
            rows = db.execute(
                f'SELECT {select_value} AS reference_id, COUNT(*) AS cnt '
                f'FROM "{reference.table}" WHERE {predicate} GROUP BY reference_id',
                params,
            ).fetchall()
            by_id = {row["reference_id"]: row["cnt"] for row in rows}
            for route_id in normalized_ids:
                count = by_id.get(route_id, 0)
                usage[route_id]["reference_counts"].append((reference, count))

        for route_id, counts in usage.items():
            for reference, count in counts["reference_counts"]:
                if reference.business_key == "orders":
                    counts["used_orders"] = count
                elif reference.business_key == "products":
                    counts["used_products"] = count
            counts["is_locked"] = any(
                count and reference.impact_level != "internal"
                for reference, count in counts["reference_counts"]
            )
        return usage

    @staticmethod
    def get_route_usage(rid, db=None):
        return RouteRepository.get_route_usage_counts([rid], db=db)[int(rid)]

    @staticmethod
    def reference_counts(rid, db=None):
        return RouteRepository.get_route_usage(rid, db=db)["reference_counts"]

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
