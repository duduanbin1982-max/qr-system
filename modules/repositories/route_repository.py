"""qr-system — RouteRepository（工序路线数据访问层）"""
from modules.db_unit_of_work import BaseService


class RouteRepository:
    """工序路线数据访问 — 封装所有路线 SQL 查询。"""

    @staticmethod
    def list_routes_query(sql, params, db=None):
        db = db or BaseService.db()
        return db.execute(sql, params).fetchall()

    @staticmethod
    def count_routes(conditions, params, db=None):
        db = db or BaseService.db()
        count_sql = "SELECT COUNT(*) FROM process_routes"
        if conditions:
            count_sql += " WHERE " + " AND ".join(conditions)
        return db.execute(count_sql, params).fetchone()[0]

    @staticmethod
    def list_route_items(route_ids, db=None):
        db = db or BaseService.db()
        placeholders = ",".join("?" for _ in route_ids)
        return db.execute(
            "SELECT pri.*, p.name as process_name, p.category as category "
            "FROM process_route_items pri "
            "LEFT JOIN processes p ON pri.process_id = p.id "
            "WHERE pri.route_id IN (" + placeholders + ") "
            "ORDER BY pri.route_id, pri.seq_order",
            route_ids
        ).fetchall()

    @staticmethod
    def find_route_by_name(name, db=None):
        db = db or BaseService.db()
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
        db = db or BaseService.db()
        placeholders = ",".join("?" for _ in pids)
        return db.execute(
            "SELECT id FROM processes WHERE id IN (" + placeholders + ")", pids
        ).fetchall()

    @staticmethod
    def find_route_by_id(rid, db=None):
        db = db or BaseService.db()
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
        db = db or BaseService.db()
        return db.execute(
            "SELECT COUNT(*) as cnt FROM orders WHERE deleted_at IS NULL AND route_id = ?", (rid,)
        ).fetchone()

    @staticmethod
    def find_orders_using_route_txn(rid, db):
        return db.execute(
            "SELECT id FROM orders WHERE deleted_at IS NULL AND route_id = ? ORDER BY id", (rid,)
        ).fetchall()

    @staticmethod
    def count_products_using_route(rid, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT COUNT(*) as cnt FROM products WHERE deleted_at IS NULL AND route_id = ?", (rid,)
        ).fetchone()

    @staticmethod
    def find_route_name(rid, db=None):
        db = db or BaseService.db()
        return db.execute("SELECT id, name FROM process_routes WHERE id = ?", (rid,)).fetchone()

    @staticmethod
    def check_order_exists(order_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT id FROM orders WHERE id = ? AND deleted_at IS NULL", (order_id,)
        ).fetchone()

    @staticmethod
    def find_route_items_ordered(rid, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT * FROM process_route_items WHERE route_id = ? ORDER BY seq_order", (rid,)
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
