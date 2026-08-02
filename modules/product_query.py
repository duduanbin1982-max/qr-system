"""Canonical product identity filters for persistence queries."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProductQueryFilter:
    """Resolve a product code once and reuse stable-ID query semantics."""

    product_code: str
    product_id: int | None

    @classmethod
    def resolve(cls, db, product_code):
        code = (product_code or "").strip()
        if not code:
            return cls("", None)
        row = db.execute(
            "SELECT product_id FROM product_code_aliases WHERE product_code = ?",
            (code,),
        ).fetchone()
        if not row:
            row = db.execute(
                "SELECT id AS product_id FROM products WHERE product_code = ?",
                (code,),
            ).fetchone()
        return cls(code, int(row["product_id"]) if row else None)

    def order_clause(self, order_alias="o"):
        if self.product_id is not None:
            return (
                "EXISTS (SELECT 1 FROM order_product_links product_link "
                f"WHERE product_link.order_id = {order_alias}.id "
                "AND product_link.product_id = ?)",
                [self.product_id],
            )
        return f"COALESCE({order_alias}.product_code, '') = ?", [self.product_code]

    def product_clause(self, product_alias="p"):
        if self.product_id is not None:
            return f"{product_alias}.id = ?", [self.product_id]
        return f"COALESCE({product_alias}.product_code, '') = ?", [self.product_code]

    def snapshot_clause(self, code_expression):
        if self.product_id is not None:
            return (
                f"({code_expression} = ? OR EXISTS ("
                "SELECT 1 FROM product_code_aliases snapshot_alias "
                f"WHERE snapshot_alias.product_code = {code_expression} "
                "AND snapshot_alias.product_id = ?))",
                [self.product_code, self.product_id],
            )
        return f"COALESCE({code_expression}, '') = ?", [self.product_code]

    def order_or_snapshot_clause(self, order_alias, *code_expressions):
        clauses = []
        params = []
        order_clause, order_params = self.order_clause(order_alias)
        clauses.append(order_clause)
        params.extend(order_params)
        for expression in code_expressions:
            snapshot_clause, snapshot_params = self.snapshot_clause(expression)
            clauses.append(snapshot_clause)
            params.extend(snapshot_params)
        return "(" + " OR ".join(clauses) + ")", params
