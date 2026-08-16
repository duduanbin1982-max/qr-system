"""
qr-system — ProductRepository（数据访问层）

Brooks R6 fix: 将所有 products / product_attachments 表 SQL 集中到此文件。
Service 层只保留业务逻辑，不再直接写 SQL。
"""
from modules.repositories.context import resolve_db

class ProductRepository:
    """产品数据访问 — 所有 products / product_attachments 表 CRUD 集中管理。"""

    # ============================================================
    # 查询 — 单条
    # ============================================================

    @staticmethod
    def find_by_id(pid, db=None):
        """按 ID 查询产品。"""
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM products WHERE id = ?", (pid,)
        ).fetchone()

    @staticmethod
    def find_active_identity(pid, db=None):
        """按 ID 查询未删除产品的删除影响检查字段。"""
        db = resolve_db(db)
        return db.execute(
            "SELECT id, product_name, product_code FROM products WHERE id = ? AND deleted_at IS NULL",
            (pid,)
        ).fetchone()

    @staticmethod
    def find_by_code(product_code, db=None):
        """按 product_code 查询产品（含 deleted_at 状态）。"""
        db = resolve_db(db)
        return db.execute(
            "SELECT id, deleted_at FROM products WHERE product_code = ?", (product_code,)
        ).fetchone()

    @staticmethod
    def find_active_id_by_code(product_code, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id FROM products WHERE product_code = ? AND deleted_at IS NULL",
            (product_code,)
        ).fetchone()

    @staticmethod
    def find_active_snapshot(pid, db=None):
        """Return the authoritative fields copied into a newly linked order."""
        db = resolve_db(db)
        return db.execute(
            "SELECT id, product_name, product_code, model, spec, style, "
            "upper_opening, lower_opening, plate_thickness, category, "
            "weight, price, COALESCE(process_route_id, route_id) AS process_route_id, "
            "COALESCE(process_route_id, route_id) AS route_id "
            "FROM products WHERE id = ? AND deleted_at IS NULL",
            (pid,),
        ).fetchone()

    @staticmethod
    def find_active_snapshot_by_code(product_code, db=None):
        """Resolve a current or historical code to one active product."""
        db = resolve_db(db)
        return db.execute(
            "SELECT p.id, p.product_name, p.product_code, p.model, p.spec, p.style, "
            "p.upper_opening, p.lower_opening, p.plate_thickness, p.category, "
            "p.weight, p.price, COALESCE(p.process_route_id, p.route_id) AS process_route_id, "
            "COALESCE(p.process_route_id, p.route_id) AS route_id "
            "FROM product_code_aliases a "
            "JOIN products p ON p.id = a.product_id "
            "WHERE a.product_code = ? AND p.deleted_at IS NULL",
            (product_code,),
        ).fetchone()

    @staticmethod
    def find_code_alias(product_code, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id, product_id, product_code, source, created_at "
            "FROM product_code_aliases WHERE product_code = ?",
            (product_code,),
        ).fetchone()

    @staticmethod
    def find_by_code_exclude(product_code, exclude_id, db=None):
        """按 product_code 查询，排除指定 ID（用于更新时的唯一性检查）。"""
        db = resolve_db(db)
        return db.execute(
            "SELECT id FROM products WHERE product_code = ? AND id != ? AND deleted_at IS NULL",
            (product_code, exclude_id)
        ).fetchone()

    @staticmethod
    def exists_by_code(product_code, db=None):
        """检查 product_code 是否存在（用于导入去重，排除已软删除产品）。"""
        db = resolve_db(db)
        return db.execute(
            "SELECT id FROM products WHERE product_code = ? AND deleted_at IS NULL", (product_code,)
        ).fetchone() is not None

    @staticmethod
    def get_product_code(pid, db=None):
        """获取产品的 product_code。"""
        db = resolve_db(db)
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
        db = resolve_db(db)
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
    def summary(deleted=False, db=None):
        """Return authoritative counts independent from list pagination."""
        db = resolve_db(db)
        predicate = "deleted_at IS NOT NULL" if deleted else "deleted_at IS NULL"
        row = db.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN category='结构件' THEN 1 ELSE 0 END) AS structural, "
            "SUM(CASE WHEN category='机加工' THEN 1 ELSE 0 END) AS machining "
            f"FROM products WHERE {predicate}"
        ).fetchone()
        return {
            "total": int(row["total"] or 0),
            "structural": int(row["structural"] or 0),
            "machining": int(row["machining"] or 0),
        }

    @staticmethod
    def list_search(q, limit, db=None):
        """快速搜索产品，返回 id/product_name/product_code/category 等。"""
        db = resolve_db(db)
        if q:
            return db.execute(
                "SELECT id, product_name, product_code, category, model, spec, style, "
                "upper_opening, plate_thickness, weight, price, "
                "COALESCE(process_route_id, route_id) AS process_route_id, "
                "COALESCE(process_route_id, route_id) AS route_id FROM products "
                "WHERE deleted_at IS NULL AND (product_name LIKE ? OR product_code LIKE ?) "
                "ORDER BY product_code LIMIT ?",
                (f"%{q}%", f"%{q}%", limit)
            ).fetchall()
        else:
            return db.execute(
                "SELECT id, product_name, product_code, category, model, spec, style, "
                "upper_opening, plate_thickness, weight, price, "
                "COALESCE(process_route_id, route_id) AS process_route_id, "
                "COALESCE(process_route_id, route_id) AS route_id FROM products "
                "WHERE deleted_at IS NULL ORDER BY product_code LIMIT ?",
                (limit,)
            ).fetchall()

    @staticmethod
    def count_orders_referencing_product(product_id, db=None):
        """Count stable and not-yet-backfilled order references to a product."""
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) FROM orders o "
            "LEFT JOIN product_code_aliases a "
            "ON o.product_id IS NULL AND a.product_code = o.product_code "
            "WHERE o.product_id = ? OR a.product_id = ?",
            (product_id, product_id),
        ).fetchone()[0]

    @staticmethod
    def reference_counts(product_id, db=None):
        """Return historical references that make physical deletion unsafe."""
        db = resolve_db(db)
        return {
            "orders": int(ProductRepository.count_orders_referencing_product(product_id, db=db)),
            "work_time_standards": int(db.execute(
                "SELECT COUNT(*) FROM work_time_standards WHERE product_id = ?",
                (product_id,),
            ).fetchone()[0]),
            "performance_source_facts": int(db.execute(
                "SELECT COUNT(*) FROM performance_source_facts WHERE product_id = ?",
                (product_id,),
            ).fetchone()[0]),
        }

    @staticmethod
    def route_exists(route_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT 1 FROM process_routes WHERE id = ?", (route_id,)
        ).fetchone() is not None

    @staticmethod
    def find_with_fields(pid, db=None):
        """按 ID 查询产品（仅关键字段，用于更新前获取旧值）。"""
        db = resolve_db(db)
        return db.execute(
            "SELECT id, product_name, product_code, IFNULL(model,'') as model, "
            "IFNULL(spec,'') as spec, IFNULL(style,'') as style, "
            "IFNULL(upper_opening,'') as upper_opening, "
            "IFNULL(lower_opening,'') as lower_opening, "
            "IFNULL(plate_thickness,'') as plate_thickness, "
            "IFNULL(category,'结构件') as category, weight, price, description, "
            "COALESCE(process_route_id, route_id) AS process_route_id "
            "FROM products WHERE id = ?", (pid,)
        ).fetchone()

    # ============================================================
    # 写操作 — 产品
    # ============================================================

    @staticmethod
    def insert(data, db=None):
        """插入新产品，返回 product_id。需要外层事务管理。"""
        db = resolve_db(db)
        cur = db.execute("""
            INSERT INTO products (product_name, model, product_code, spec, style,
                upper_opening, lower_opening, plate_thickness, category, weight, price,
                description, route_id, process_route_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
            data.get("weight"),
            data.get("price"),
            data.get("description", ""),
            data.get("process_route_id") or None,
            data.get("process_route_id") or None,
        ))
        return cur.lastrowid


    @staticmethod
    def update(pid, set_clauses, params, db=None):
        """UPDATE products SET ... WHERE id = ?。调用方自行构建 set_clauses 和 params。"""
        db = resolve_db(db)
        params.append(pid)
        db.execute(
            f"UPDATE products SET {', '.join(set_clauses)} WHERE id = ?", params
        )

    @staticmethod
    def update_product_code(pid, product_code, db=None):
        """单独更新 product_code。"""
        db = resolve_db(db)
        db.execute(
            "UPDATE products SET product_code = ? WHERE id = ?", (product_code, pid)
        )

    @staticmethod
    def insert_code_alias(product_id, product_code, source, db=None):
        """Insert one immutable code alias. Caller must validate ownership first."""
        db = resolve_db(db)
        db.execute(
            "INSERT INTO product_code_aliases (product_id, product_code, source) "
            "VALUES (?, ?, ?)",
            (product_id, product_code, source),
        )

    @staticmethod
    def link_unresolved_orders(product_id, db=None):
        """Bind legacy orders whose snapshot code is an alias of this product."""
        db = resolve_db(db)
        cursor = db.execute(
            "UPDATE orders SET product_id = ? "
            "WHERE product_id IS NULL AND product_code IN ("
            "SELECT product_code FROM product_code_aliases WHERE product_id = ?"
            ")",
            (product_id, product_id),
        )
        return cursor.rowcount

    @staticmethod
    def soft_delete(pid, db=None):
        """软删除产品。"""
        db = resolve_db(db)
        db.execute(
            "UPDATE products SET deleted_at = datetime('now','localtime') WHERE id = ?", (pid,)
        )
    @staticmethod
    def restore(pid, db=None):
        """恢复已软删除的产品。"""
        db = resolve_db(db)
        db.execute(
            "UPDATE products SET deleted_at = NULL WHERE id = ?", (pid,)
        )

    @staticmethod
    def hard_delete(pid, db=None):
        """物理删除产品（先删附件，再删产品）。仅用于回收站中已确认无引用的产品。"""
        db = resolve_db(db)
        db.execute("DELETE FROM product_attachments WHERE product_id = ?", (pid,))
        db.execute("DELETE FROM products WHERE id = ?", (pid,))

    # ============================================================
    # 附件
    # ============================================================

    @staticmethod
    def list_attachments(product_id, db=None):
        """获取产品附件列表（含上传者姓名）。"""
        db = resolve_db(db)
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
        db = resolve_db(db)
        db.execute("""
            INSERT INTO product_attachments
                (product_id, file_name, file_type, file_size, file_data, uploaded_by)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (product_id, file_name, file_type, file_size, file_data, uploaded_by))

    @staticmethod
    def find_attachment(attachment_id, db=None):
        """按 ID 查询附件。"""
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM product_attachments WHERE id = ?", (attachment_id,)
        ).fetchone()

    @staticmethod
    def delete_attachment(attachment_id, db=None):
        """删除附件记录。"""
        db = resolve_db(db)
        db.execute(
            "DELETE FROM product_attachments WHERE id = ?", (attachment_id,)
        )
