"""
qr-system — InventoryRepository（库存数据访问层）
"""
from modules.services import BaseService


class InventoryRepository:
    """库存数据访问 — 集中管理库存 CRUD、出入库、日志查询。"""

    @staticmethod
    def list_paged(where_sql, params, limit, offset, db=None):
        """分页查询库存列表（含低库存标记）。"""
        db = db or BaseService.db()
        total = db.execute(
            "SELECT COUNT(*) FROM inventory WHERE " + where_sql, params
        ).fetchone()[0]
        rows = db.execute(
            """SELECT *, CASE WHEN quantity <= safe_stock AND safe_stock > 0
               THEN 1 ELSE 0 END as low_stock_flag
               FROM inventory WHERE """ + where_sql + """
               ORDER BY id DESC LIMIT ? OFFSET ?""",
            params + [limit, offset]
        ).fetchall()
        return rows, total

    @staticmethod
    def find_by_id(item_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT id FROM inventory WHERE id = ?", (item_id,)
        ).fetchone()

    @staticmethod
    def find_by_model(model, exclude_id=None, db=None):
        db = db or BaseService.db()
        if exclude_id:
            return db.execute(
                "SELECT id FROM inventory WHERE product_model = ? AND id != ?",
                (model, exclude_id)
            ).fetchone()
        return db.execute(
            "SELECT id FROM inventory WHERE product_model = ?", (model,)
        ).fetchone()

    @staticmethod
    def stock_in(inv_id, quantity, operator, order_no, db=None):
        """入库：增加库存 + 记录日志。"""
        db = db or BaseService.db()
        db.execute(
            "UPDATE inventory SET quantity = quantity + ?, updated_at = datetime('now','localtime') WHERE id = ?",
            (quantity, inv_id)
        )
        db.execute(
            """INSERT INTO inventory_logs (inventory_id, type, quantity, operator_name, order_no, created_at)
               VALUES (?, 'stock_in', ?, ?, ?, datetime('now','localtime'))""",
            (inv_id, quantity, operator, order_no)
        )

    @staticmethod
    def stock_out(inv_id, quantity, operator, order_no, db=None):
        """出库：减少库存 + 记录日志 + 校验库存充足。"""
        db = db or BaseService.db()
        current = db.execute(
            "SELECT quantity FROM inventory WHERE id = ?", (inv_id,)
        ).fetchone()
        if not current or current['quantity'] < quantity:
            raise ValueError('库存不足')
        db.execute(
            "UPDATE inventory SET quantity = quantity - ?, updated_at = datetime('now','localtime') WHERE id = ?",
            (quantity, inv_id)
        )
        db.execute(
            """INSERT INTO inventory_logs (inventory_id, type, quantity, operator_name, order_no, created_at)
               VALUES (?, 'stock_out', ?, ?, ?, datetime('now','localtime'))""",
            (inv_id, quantity, operator, order_no)
        )

    @staticmethod
    def get_logs_paged(where_sql, params, limit, offset, db=None):
        """分页查询出入库日志。"""
        db = db or BaseService.db()
        total = db.execute(
            "SELECT COUNT(*) FROM inventory_logs il WHERE " + where_sql, params
        ).fetchone()[0]
        rows = db.execute(
            """SELECT il.*, i.product_model, i.product_name
               FROM inventory_logs il
               LEFT JOIN inventory i ON il.inventory_id = i.id
               WHERE """ + where_sql + """
               ORDER BY il.created_at DESC LIMIT ? OFFSET ?""",
            params + [limit, offset]
        ).fetchall()
        return rows, total

