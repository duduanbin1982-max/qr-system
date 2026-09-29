"""Read model and creation identity access for product-group inventory."""
import hashlib

from modules.domain.errors import ConflictError
from modules.repositories.context import resolve_db


RESOLVED_PRODUCT_ID_SQL = """
CASE
  WHEN i.product_id IS NOT NULL AND o.product_id IS NOT NULL
       AND i.product_id <> o.product_id THEN NULL
  WHEN i.product_id IS NOT NULL AND pca.product_id IS NOT NULL
       AND i.product_id <> pca.product_id THEN NULL
  WHEN o.product_id IS NOT NULL AND pca.product_id IS NOT NULL
       AND o.product_id <> pca.product_id THEN NULL
  ELSE COALESCE(i.product_id,o.product_id,pca.product_id)
END
"""
IDENTITY_REASON_SQL = """
CASE
  WHEN (i.product_id IS NOT NULL AND o.product_id IS NOT NULL AND i.product_id <> o.product_id)
    OR (i.product_id IS NOT NULL AND pca.product_id IS NOT NULL AND i.product_id <> pca.product_id)
    OR (o.product_id IS NOT NULL AND pca.product_id IS NOT NULL AND o.product_id <> pca.product_id)
    THEN 'product_identity_conflict'
  WHEN COALESCE(i.product_id,o.product_id,pca.product_id) IS NULL
    THEN 'product_identity_unresolved'
  ELSE 'resolved'
END
"""
AVAILABLE_SQL = "MAX(i.quantity-COALESCE(i.reserved,0)-COALESCE(i.frozen_quantity,0),0)"


def compatibility_key(row):
    raw = "|".join((
        str(row["product_id"]),
        (row["specification"] or "").strip(),
        str(row["route_version_id_snapshot"] or 0),
        (row["quality_status"] or "qualified").strip(),
    ))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


_compatibility_key_for_row = compatibility_key


class InventoryProductRepository:
    """Product-level read model; all identity decisions live in this repository."""

    @staticmethod
    def _resolved_cte():
        return f"""
            WITH identity_rows AS (
                SELECT i.*, o.order_no, o.customer,
                       o.product_id AS order_product_id,
                       pca.product_id AS alias_product_id,
                       {RESOLVED_PRODUCT_ID_SQL} AS resolved_product_id,
                       {IDENTITY_REASON_SQL} AS identity_reason
                FROM inventory i
                LEFT JOIN orders o ON o.id=i.order_id
                LEFT JOIN product_code_aliases pca
                  ON pca.product_code=COALESCE(NULLIF(i.product_code_snapshot,''),i.product_model)
                WHERE i.deleted_at IS NULL
            ), resolved_inventory AS (
                SELECT ir.*, p.product_code AS canonical_product_code,
                       p.product_name AS canonical_product_name,
                       p.category AS canonical_category
                FROM identity_rows ir
                JOIN products p ON p.id=ir.resolved_product_id AND p.deleted_at IS NULL
                WHERE ir.identity_reason='resolved'
            )
        """

    @staticmethod
    def _group_filters(filters):
        clauses = []
        params = []
        keyword = filters.get("keyword", "")
        if keyword:
            clauses.append(
                "(i.canonical_product_code LIKE ? OR i.canonical_product_name LIKE ? "
                "OR i.product_model LIKE ? OR i.product_name LIKE ? "
                "OR i.specification LIKE ? OR i.order_no LIKE ? OR i.location LIKE ?)"
            )
            params.extend([f"%{keyword}%"] * 7)
        if filters.get("location"):
            clauses.append("i.location=?")
            params.append(filters["location"])
        if filters.get("quality_status"):
            clauses.append("i.quality_status=?")
            params.append(filters["quality_status"])
        if filters.get("identity_status") not in ("", "resolved"):
            clauses.append("1=0")
        where = " AND ".join(clauses) if clauses else "1=1"
        having = ""
        if filters.get("low_stock"):
            having = (
                f"HAVING SUM({AVAILABLE_SQL}) <= SUM(COALESCE(i.safe_stock,0)) "
                "AND SUM(COALESCE(i.safe_stock,0)) > 0"
            )
        return where, having, params

    @classmethod
    def count_groups(cls, filters, db=None):
        db = resolve_db(db)
        where, having, params = cls._group_filters(filters)
        row = db.execute(
            cls._resolved_cte()
            + "SELECT COUNT(*) FROM ("
              "SELECT i.resolved_product_id FROM resolved_inventory i "
              f"WHERE {where} GROUP BY i.resolved_product_id {having}) grouped",
            params,
        ).fetchone()
        return int(row[0] or 0)

    @classmethod
    def list_groups(cls, filters, page, limit, db=None):
        db = resolve_db(db)
        where, having, params = cls._group_filters(filters)
        offset = (page - 1) * limit
        return db.execute(
            cls._resolved_cte()
            + "SELECT i.resolved_product_id AS product_id, "
              "i.canonical_product_code AS product_code, "
              "i.canonical_product_name AS product_name, "
              "i.canonical_category AS category, "
              "SUM(i.quantity) AS quantity, "
              "SUM(COALESCE(i.reserved,0)) AS reserved_quantity, "
              "SUM(COALESCE(i.frozen_quantity,0)) AS frozen_quantity, "
              f"SUM({AVAILABLE_SQL}) AS available_quantity, "
              "SUM(COALESCE(i.safe_stock,0)) AS safe_stock, "
              "COUNT(DISTINCT i.order_id) AS order_count, "
              "COUNT(*) AS inventory_count, "
              f"CASE WHEN SUM({AVAILABLE_SQL}) <= SUM(COALESCE(i.safe_stock,0)) "
              "AND SUM(COALESCE(i.safe_stock,0)) > 0 THEN 1 ELSE 0 END AS is_low "
              "FROM resolved_inventory i "
              f"WHERE {where} GROUP BY i.resolved_product_id,i.canonical_product_code,"
              f"i.canonical_product_name,i.canonical_category {having} "
              "ORDER BY is_low DESC, "
              "(safe_stock-available_quantity) DESC, product_code COLLATE NOCASE, product_id "
              "LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()

    @staticmethod
    def get_product(product_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id AS product_id,product_code,product_name,model,spec,category "
            "FROM products WHERE id=? AND deleted_at IS NULL",
            (product_id,),
        ).fetchone()

    @staticmethod
    def list_aliases(product_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT product_code,source FROM product_code_aliases "
            "WHERE product_id=? ORDER BY CASE WHEN source='current' THEN 0 ELSE 1 END,"
            "product_code COLLATE NOCASE",
            (product_id,),
        ).fetchall()

    @classmethod
    def list_compatibility_groups(cls, product_id, db=None):
        db = resolve_db(db)
        rows = db.execute(
            cls._resolved_cte()
            + "SELECT i.resolved_product_id AS product_id, "
              "COALESCE(i.specification,'') AS specification, "
              "i.route_version_id_snapshot, "
              "COALESCE(NULLIF(i.quality_status,''),'qualified') AS quality_status, "
              "SUM(i.quantity) AS quantity, "
              "SUM(COALESCE(i.reserved,0)) AS reserved_quantity, "
              "SUM(COALESCE(i.frozen_quantity,0)) AS frozen_quantity, "
              f"SUM({AVAILABLE_SQL}) AS available_quantity, "
              "COUNT(DISTINCT i.order_id) AS order_count, COUNT(*) AS inventory_count "
              "FROM resolved_inventory i WHERE i.resolved_product_id=? "
              "GROUP BY i.resolved_product_id,COALESCE(i.specification,''),"
              "i.route_version_id_snapshot,COALESCE(NULLIF(i.quality_status,''),'qualified') "
              "ORDER BY specification COLLATE NOCASE,"
              "COALESCE(route_version_id_snapshot,0),quality_status",
            (product_id,),
        ).fetchall()
        groups = []
        for row in rows:
            item = dict(row)
            item["compatibility_key"] = compatibility_key(item)
            groups.append(item)
        return groups

    @classmethod
    def list_inventory_details(cls, product_id, compatibility_key="", db=None):
        db = resolve_db(db)
        rows = db.execute(
            cls._resolved_cte()
            + "SELECT i.id AS inventory_id,i.resolved_product_id AS product_id,i.product_model,"
              "i.product_name,i.product_code_snapshot,i.product_name_snapshot,i.specification,"
              "i.quantity,COALESCE(i.reserved,0) AS reserved_quantity,"
              "COALESCE(i.frozen_quantity,0) AS frozen_quantity,"
              f"{AVAILABLE_SQL} AS available_quantity,i.safe_stock,i.location,i.unit,"
              "i.order_id,i.order_no,i.customer,i.route_version_id_snapshot,"
              "COALESCE(NULLIF(i.quality_status,''),'qualified') "
              "AS quality_status,"
              "(SELECT GROUP_CONCAT(DISTINCT NULLIF(l.lot_no,'')) FROM inventory_logs l "
              "WHERE l.inventory_id=i.id) AS lot_no,"
              "(SELECT GROUP_CONCAT(DISTINCT NULLIF(l.serial_no,'')) FROM inventory_logs l "
              "WHERE l.inventory_id=i.id) AS serial_no,i.updated_at "
              "FROM resolved_inventory i WHERE i.resolved_product_id=? "
              "ORDER BY order_no COLLATE NOCASE,inventory_id",
            (product_id,),
        ).fetchall()
        details = []
        for row in rows:
            row_key = _compatibility_key_for_row(row)
            if not compatibility_key or row_key == compatibility_key:
                details.append(row)
        return details

    @classmethod
    def get_group_details(cls, product_id, compatibility_key="", db=None):
        """Return the complete read-only product-group detail payload pieces."""
        db = resolve_db(db)
        product = cls.get_product(product_id, db=db)
        if not product:
            return None
        warnings = []
        for row in cls.list_identity_exceptions(db=db):
            candidate_ids = {
                row["inventory_product_id"], row["order_product_id"], row["alias_product_id"]
            }
            if product_id in candidate_ids:
                warnings.append(dict(row))
        return {
            "product": product,
            "aliases": cls.list_aliases(product_id, db=db),
            "compatibility_groups": cls.list_compatibility_groups(product_id, db=db),
            "inventory_items": cls.list_inventory_details(
                product_id, compatibility_key=compatibility_key, db=db
            ),
            "identity_warnings": warnings,
        }

    @staticmethod
    def list_identity_exceptions(limit=100, db=None):
        db = resolve_db(db)
        return db.execute(
            f"SELECT i.id AS inventory_id,i.product_model,i.product_name,i.order_id,"
            f"o.order_no,i.location,i.quantity,i.product_id AS inventory_product_id,"
            f"o.product_id AS order_product_id,pca.product_id AS alias_product_id,"
            f"{IDENTITY_REASON_SQL} AS reason "
            "FROM inventory i LEFT JOIN orders o ON o.id=i.order_id "
            "LEFT JOIN product_code_aliases pca "
            "ON pca.product_code=COALESCE(NULLIF(i.product_code_snapshot,''),i.product_model) "
            "WHERE i.deleted_at IS NULL AND "
            f"({IDENTITY_REASON_SQL})<>'resolved' ORDER BY i.id LIMIT ?",
            (limit,),
        ).fetchall()

    @staticmethod
    def resolve_creation_identity(product_code, order_id, db):
        code = (product_code or "").strip()
        order = None
        if order_id is not None:
            order = db.execute(
                "SELECT o.product_id,o.product_code,o.product_name,o.route_version_id,"
                "opl.product_id AS linked_product_id FROM orders o "
                "LEFT JOIN order_product_links opl ON opl.order_id=o.id WHERE o.id=?",
                (order_id,),
            ).fetchone()
        order_product_id = None
        if order:
            order_product_id = order["linked_product_id"] or order["product_id"]
        alias = db.execute(
            "SELECT a.product_id,p.product_code,p.product_name FROM product_code_aliases a "
            "JOIN products p ON p.id=a.product_id WHERE a.product_code=?",
            (code,),
        ).fetchone() if code else None
        alias_product_id = alias["product_id"] if alias else None
        if (
            order_product_id is not None
            and alias_product_id is not None
            and order_product_id != alias_product_id
        ):
            raise ConflictError("订单产品与库存产品编码不一致")
        product_id = order_product_id or alias_product_id
        product = None
        if product_id is not None:
            product = db.execute(
                "SELECT product_code,product_name FROM products WHERE id=?",
                (product_id,),
            ).fetchone()
        return {
            "product_id": product_id,
            "product_code_snapshot": code or ((order and order["product_code"]) or ""),
            "product_name_snapshot": (
                (product and product["product_name"])
                or (order and order["product_name"])
                or ""
            ),
            "route_version_id_snapshot": order["route_version_id"] if order else None,
        }
