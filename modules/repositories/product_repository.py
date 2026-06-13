"""
qr-system — ProductRepository（数据访问层）

Brooks R6 fix: 将所有 products / product_attachments 表 SQL 集中到此文件。
Service 层只保留业务逻辑，不再直接写 SQL。
"""
from modules.services import BaseService

class ProductRepository:
    """产品数据访问 — 所有 products / product_attachments 表 CRUD 集中管理。"""

    # ============================================================
    # 查询 — 单条
    # ============================================================

    @staticmethod
    def find_by_id(pid, db=None):
        """按 ID 查询产品。"""
        db = db or BaseService.db()
        return db.execute(
            "SELECT * FROM products WHERE id = ?", (pid,)
        ).fetchone()

    @staticmethod
    def find_by_code(product_code, db=None):
        """按 product_code 查询产品（含 deleted_at 状态）。"""
        db = db or BaseService.db()
        return db.execute(
            "SELECT id, deleted_at FROM products WHERE product_code = ?", (product_code,)
        ).fetchone()

    @staticmethod
    def find_by_code_exclude(product_code, exclude_id, db=None):
        """按 product_code 查询，排除指定 ID（用于更新时的唯一性检查）。"""
        db = db or BaseService.db()
        return db.execute(
            "SELECT id FROM products WHERE product_code = ? AND id != ? AND deleted_at IS NULL",
            (product_code, exclude_id)
        ).fetchone()

    @staticmethod
    def exists_by_code(product_code, db=None):
        """检查 product_code 是否存在（用于导入去重，排除已软删除产品）。"""
        db = db or BaseService.db()
        return db.execute(
            "SELECT id FROM products WHERE product_code = ? AND deleted_at IS NULL", (product_code,)
        ).fetchone() is not None

    @staticmethod
    def get_product_code(pid, db=None):
        """获取产品的 product_code。"""
        db = db or BaseService.db()
        row = db.execute(
            "SELECT product_code FROM products WHERE id = ?", (pid,)
        ).fetchone()
        return row["product_code"] if row else ""

    # ============================================================
    # 查询 — 列表
    # ============================================================

    @staticmethod
    def list_with_attachments(where_sql, params, page, limit, db=None):
        """分页列表（含附件计数和缩略图），where_sql 不含 WHERE 关键字。"""
        db = db or BaseService.db()
        total = db.execute(
            f"SELECT COUNT(*) FROM products WHERE {where_sql}", params
        ).fetchone()[0]
        offset = (page - 1) * limit
        rows = db.execute(
            f"SELECT p.*,"
            f" COALESCE(pa.attachment_count, 0) as attachment_count,"
            f" pa_img.id as thumbnail_id"
            f" FROM products p"
            f" LEFT JOIN ("
            f"  SELECT product_id, COUNT(*) as attachment_count"
            f"  FROM product_attachments GROUP BY product_id"
            f" ) pa ON pa.product_id = p.id"
            f" LEFT JOIN ("
            f"  SELECT product_id, MIN(id) as id"
            f"  FROM product_attachments WHERE file_type LIKE '%image%'"
            f"  GROUP BY product_id"
            f" ) pa_img ON pa_img.product_id = p.id"
            f" WHERE {where_sql} ORDER BY p.id DESC LIMIT ? OFFSET ?",
            params + [limit, offset]
        ).fetchall()
        return rows, total

    @staticmethod
    def list_search(q, limit, db=None):
        """快速搜索产品，返回 id/product_name/product_code/category 等。"""
        db = db or BaseService.db()
        if q:
            return db.execute(
                "SELECT id, product_name, product_code, category, model, spec, style, "
                "upper_opening, plate_thickness, weight, price, route_id FROM products "
                "WHERE deleted_at IS NULL AND (product_name LIKE ? OR product_code LIKE ?) "
                "ORDER BY product_code LIMIT ?",
                (f"%{q}%", f"%{q}%", limit)
            ).fetchall()
        else:
            return db.execute(
                "SELECT id, product_name, product_code, category, model, spec, style, "
                "upper_opening, plate_thickness, weight, price, route_id FROM products "
                "WHERE deleted_at IS NULL ORDER BY product_code LIMIT ?",
                (limit,)
            ).fetchall()

    @staticmethod
    def count_by_product_code_in_orders(product_code, db=None):
        """统计该 product_code 在 orders 表中的使用次数。"""
        db = db or BaseService.db()
        return db.execute(
            "SELECT COUNT(*) FROM orders WHERE product_code = ?", (product_code,)
        ).fetchone()[0]

    @staticmethod
    def find_with_fields(pid, db=None):
        """按 ID 查询产品（仅关键字段，用于更新前获取旧值）。"""
        db = db or BaseService.db()
        return db.execute(
            "SELECT id, product_name, IFNULL(model,'') as model, "
            "IFNULL(spec,'') as spec, IFNULL(style,'') as style, "
            "IFNULL(upper_opening,'') as upper_opening, "
            "IFNULL(plate_thickness,'') as plate_thickness "
            "FROM products WHERE id = ?", (pid,)
        ).fetchone()

    # ============================================================
    # 写操作 — 产品
    # ============================================================

    @staticmethod
    def insert(data, db=None):
        """插入新产品，返回 product_id。需要外层事务管理。"""
        db = db or BaseService.db()
        cur = db.execute("""
            INSERT INTO products (product_name, model, product_code, spec, style,
                upper_opening, lower_opening, plate_thickness, category, weight, price,
                description, route_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            data["product_name"],
            data["model"],
            data["product_code"],
            data.get("spec", ""),
            data.get("style", ""),
            data.get("upper_opening", ""),
            data.get("lower_opening", ""),
            data.get("plate_thickness", ""),
            data.get("category", "结构件"),
            float(data.get("weight") or 0),
            float(data.get("price") or 0),
            data.get("description", ""),
            data.get("route_id") or None
        ))
        return cur.lastrowid


    @staticmethod
    def update(pid, set_clauses, params, db=None):
        """UPDATE products SET ... WHERE id = ?。调用方自行构建 set_clauses 和 params。"""
        db = db or BaseService.db()
        params.append(pid)
        db.execute(
            f"UPDATE products SET {', '.join(set_clauses)} WHERE id = ?", params
        )

    @staticmethod
    def update_product_code(pid, product_code, db=None):
        """单独更新 product_code。"""
        db = db or BaseService.db()
        db.execute(
            "UPDATE products SET product_code = ? WHERE id = ?", (product_code, pid)
        )

    @staticmethod
    def soft_delete(pid, db=None):
        """软删除产品。"""
        db = db or BaseService.db()
        db.execute(
            "UPDATE products SET deleted_at = datetime('now','localtime') WHERE id = ?", (pid,)
        )

    # ============================================================
    # 附件
    # ============================================================

    @staticmethod
    def list_attachments(product_id, db=None):
        """获取产品附件列表（含上传者姓名）。"""
        db = db or BaseService.db()
        return db.execute("""
            SELECT a.id, a.product_id, a.file_name, a.file_type, a.file_size,
                   a.created_at, u.name as uploaded_by_name
            FROM product_attachments a
            LEFT JOIN users u ON a.uploaded_by = u.id
            WHERE a.product_id = ?
            ORDER BY a.created_at DESC
        """, (product_id,)).fetchall()

    @staticmethod
    def insert_attachment(product_id, file_name, file_type, file_size, file_data, uploaded_by, db=None):
        """插入附件记录。"""
        db = db or BaseService.db()
        db.execute("""
            INSERT INTO product_attachments
                (product_id, file_name, file_type, file_size, file_data, uploaded_by)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (product_id, file_name, file_type, file_size, file_data, uploaded_by))

    @staticmethod
    def find_attachment(attachment_id, db=None):
        """按 ID 查询附件。"""
        db = db or BaseService.db()
        return db.execute(
            "SELECT * FROM product_attachments WHERE id = ?", (attachment_id,)
        ).fetchone()

    @staticmethod
    def delete_attachment(attachment_id, db=None):
        """删除附件记录。"""
        db = db or BaseService.db()
        db.execute(
            "DELETE FROM product_attachments WHERE id = ?", (attachment_id,)
        )

