"""qr-system — Shared query utilities (pagination, filtering, sorting)."""
from modules.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_LIMIT


def paginate(sql, params, page=1, page_size=None, max_page_size=None):
    """Apply pagination to a SQL query string.
    
    Returns (paginated_sql, updated_params, page_size, offset).
    """
    page = max(1, int(page or 1))
    size = int(page_size or DEFAULT_PAGE_SIZE)
    max_sz = int(max_page_size or MAX_PAGE_LIMIT)
    size = min(size, max_sz)
    offset = (page - 1) * size
    return f"{sql} LIMIT ? OFFSET ?", params + [size, offset], size, offset


def build_sort_clause(sort_by, allowed_columns, default="updated_at"):
    """Build a safe ORDER BY clause from allowed columns."""
    if sort_by in allowed_columns:
        col = sort_by
    else:
        col = default
    direction = "DESC" if col in ("updated_at", "created_at", "id") else "ASC"
    return f"ORDER BY {col} {direction}"


def build_where_clause(filters, allowed_fields):
    """Build a WHERE clause from a dict of field:value pairs."""
    clauses = []
    vals = []
    for field, value in filters.items():
        if field in allowed_fields and value not in (None, "", []):
            clauses.append(f"{field} = ?")
            vals.append(value)
    if not clauses:
        return "1=1", []
    return " AND ".join(clauses), vals
