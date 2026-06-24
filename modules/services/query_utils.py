"""Backward-compatible import location for query utilities."""
from modules.query_utils import build_sort_clause, build_where_clause, paginate

__all__ = ["paginate", "build_sort_clause", "build_where_clause"]
