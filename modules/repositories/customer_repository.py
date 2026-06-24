"""
qr-system — CustomerRepository（数据访问层）

将所有 customers 表及相关 SQL 集中到此文件。
Service 层只保留业务逻辑，不再直接写 SQL。
"""
from modules.db_unit_of_work import BaseService


class CustomerRepository:
    """客户数据访问 — 所有 customers 表 CRUD 集中管理。"""

    # ============================================================
    # 查询
    # ============================================================

    @staticmethod
    def find_by_id(customer_id, db=None):
        """按 ID 查询客户。"""
        db = db or BaseService.db()
        return db.execute(
            "SELECT * FROM customers WHERE id = ?", (customer_id,)
        ).fetchone()

    @staticmethod
    def find_by_name(name, db=None):
        """按名称查询客户（用于重复检查）。"""
        db = db or BaseService.db()
        return db.execute(
            "SELECT id FROM customers WHERE name = ?", (name,)
        ).fetchone()

    @staticmethod
    def find_by_name_excluding(name, exclude_id, db=None):
        """按名称查询客户，排除指定 ID（用于更新时的重复检查）。"""
        db = db or BaseService.db()
        return db.execute(
            "SELECT id FROM customers WHERE name = ? AND id != ?", (name, exclude_id)
        ).fetchone()

    @staticmethod
    def count_all(where_sql, params, db=None):
        """按条件统计客户数。where_sql 不含 WHERE 关键字。"""
        db = db or BaseService.db()
        return db.execute(
            f"SELECT COUNT(*) FROM customers WHERE {where_sql}", params
        ).fetchone()[0]

    @staticmethod
    def list_all(where_sql, params, page, limit, db=None):
        """分页列表（where_sql 不含 WHERE 关键字，调用方负责拼接）。"""
        db = db or BaseService.db()
        total = CustomerRepository.count_all(where_sql, params, db=db)
        offset = (page - 1) * limit
        rows = db.execute(
            f"SELECT * FROM customers WHERE {where_sql} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [limit, offset]
        ).fetchall()
        return rows, total

    @staticmethod
    def count_active_orders(customer_id, db=None):
        """统计某客户的活跃（非软删除）订单数。"""
        db = db or BaseService.db()
        return db.execute(
            "SELECT COUNT(*) FROM orders WHERE customer_id = ? AND deleted_at IS NULL",
            (customer_id,)
        ).fetchone()[0]

    @staticmethod
    def get_orders(customer_id, page, limit, db=None):
        """获取客户的订单列表（含路线名）。"""
        db = db or BaseService.db()
        total = db.execute(
            "SELECT COUNT(*) FROM orders WHERE customer_id = ? AND deleted_at IS NULL",
            (customer_id,)
        ).fetchone()[0]
        offset = (page - 1) * limit
        rows = db.execute("""
            SELECT o.*, pr.name as route_name
            FROM orders o
            LEFT JOIN process_routes pr ON o.route_id = pr.id
            WHERE o.customer_id = ? AND o.deleted_at IS NULL
            ORDER BY o.created_at DESC LIMIT ? OFFSET ?
        """, (customer_id, limit, offset)).fetchall()
        return rows, total

    @staticmethod
    def get_order_processes(order_id, db=None):
        """获取订单的工序列表（含工序名）。"""
        db = db or BaseService.db()
        return db.execute("""
            SELECT op.*, p.name as process_name
            FROM order_processes op
            JOIN processes p ON op.process_id = p.id
            WHERE op.order_id = ?
            ORDER BY op.seq_order
        """, (order_id,)).fetchall()

    # ============================================================
    # 写操作
    # ============================================================

    @staticmethod
    def insert(data, db=None):
        """插入新客户，返回 customer_id。需要外层事务管理。"""
        db = db or BaseService.db()
        cur = db.execute("""
            INSERT INTO customers (name, contact, phone, email, address, remark, tags)
            VALUES (?,?,?,?,?,?,?)
        """, (data["name"], data.get("contact", ""),
              data.get("phone", ""), data.get("email", ""),
              data.get("address", ""), data.get("remark", ""),
              data.get("tags", "")))
        return cur.lastrowid

    @staticmethod
    def update(customer_id, set_clauses, params, db):
        """UPDATE customers SET ... WHERE id = ?。自动追加 updated_at 时间戳。"""
        set_clauses = list(set_clauses)  # Don't mutate caller's list
        if not any("updated_at" in c for c in set_clauses):
            set_clauses.append('updated_at = datetime("now","localtime")')
        params.append(customer_id)
        db.execute(
            f"UPDATE customers SET {', '.join(set_clauses)} WHERE id = ?", params
        )

    @staticmethod
    def delete(customer_id, db=None):
        """删除客户。"""
        db = db or BaseService.db()
        db.execute("DELETE FROM customers WHERE id = ?", (customer_id,))

    @staticmethod
    def dissociate_soft_deleted_orders(customer_id, db=None):
        """解除软删除订单的 customer_id 关联（保留 customer 字段以供审计）。"""
        db = db or BaseService.db()
        db.execute(
            "UPDATE orders SET customer_id = NULL WHERE customer_id = ? AND deleted_at IS NOT NULL",
            (customer_id,)
        )

    
    @staticmethod
    def get_active_order_nos(customer_id, limit=5, db=None):
        """获取活跃订单号列表（用于删除前的提示）。"""
        db = db or BaseService.db()
        rows = db.execute(
            "SELECT order_no FROM orders WHERE customer_id = ? AND deleted_at IS NULL LIMIT ?",
            (customer_id, limit)
        ).fetchall()
        return [r["order_no"] for r in rows]

    @staticmethod
    def cascade_name_to_orders(customer_id, new_name, db=None):
        """客户改名时同步更新 orders.customer 字段。"""
        db = db or BaseService.db()
        db.execute(
            "UPDATE orders SET customer = ? WHERE customer_id = ?",
            (new_name, customer_id)
        )
