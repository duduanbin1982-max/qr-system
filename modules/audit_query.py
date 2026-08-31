"""Validation and normalization for the audit-log query boundary."""

from datetime import date


def parse_audit_query(page=1, limit=50, date_from="", date_to="", keyword="", max_limit=200):
    try:
        page = int(page)
        limit = int(limit)
    except (TypeError, ValueError):
        raise ValueError("page 和 limit 必须是整数")
    if page < 1:
        raise ValueError("page 必须大于等于 1")
    if limit < 1 or limit > max_limit:
        raise ValueError(f"limit 必须在 1-{max_limit} 之间")

    normalized_from = str(date_from or "").strip()
    normalized_to = str(date_to or "").strip()
    for value in (normalized_from, normalized_to):
        if value:
            try:
                date.fromisoformat(value)
            except ValueError as exc:
                raise ValueError("日期必须使用 YYYY-MM-DD 格式") from exc
    if normalized_from and normalized_to and normalized_from > normalized_to:
        raise ValueError("开始日期不能晚于结束日期")

    normalized_keyword = str(keyword or "").strip()
    if len(normalized_keyword) > 100:
        raise ValueError("keyword 长度不能超过 100 个字符")

    return {
        "page": page,
        "limit": limit,
        "date_from": normalized_from,
        "date_to": normalized_to,
        "keyword": normalized_keyword,
    }
