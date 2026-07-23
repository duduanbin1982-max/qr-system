"""Pure access policy calculations shared by middleware and services."""
import json
import logging
from typing import Iterable, List, Optional, Sequence, Set


PERMISSION_IMPLICATIONS = {
    "quality:edit": {"quality:review"},
}


def _row_value(row, key):
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        if hasattr(row, "get"):
            return row.get(key)
        return getattr(row, key, None)


def collect_permission_codes(permission_rows: Iterable, user_id=None, logger=None) -> List[str]:
    logger = logger or logging.getLogger("qr")
    permissions: Set[str] = set()
    for row in permission_rows or []:
        for column in ("role_perms", "group_perms"):
            raw_value = _row_value(row, column)
            if not raw_value:
                continue
            try:
                parsed = json.loads(raw_value)
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning(
                    "access_policy: invalid %s JSON for user %s: %s",
                    column,
                    user_id,
                    exc,
                )
                continue
            if isinstance(parsed, list):
                permissions.update(str(item) for item in parsed if item)
    return sorted(permissions)


def has_permission_code(permissions: Sequence[str], perm: str) -> bool:
    permission_set = set(permissions or [])
    if "*" in permission_set or perm in permission_set:
        return True
    return any(
        perm in implied
        for granted, implied in PERMISSION_IMPLICATIONS.items()
        if granted in permission_set
    )


def parse_process_ids(process_ids_text: str) -> List[int]:
    text = (process_ids_text or "").strip()
    if not text:
        return []
    return [int(item.strip()) for item in text.split(",") if item.strip()]


def resolve_process_scope(
    position_process_rows: Iterable,
    explicit_process_rows: Iterable,
    *,
    has_position_scope: bool,
    has_explicit_process_scope: bool,
    permissions: Sequence[str],
    global_data_scope_permissions: Set[str],
) -> Optional[List[int]]:
    allowed = set()
    for row in position_process_rows or []:
        process_id = _row_value(row, "process_id")
        if process_id is not None:
            allowed.add(process_id)
    for row in explicit_process_rows or []:
        process_id = _row_value(row, "id")
        if process_id is not None:
            allowed.add(process_id)

    if allowed:
        return sorted(allowed)
    if has_position_scope or has_explicit_process_scope:
        return []

    permission_set = set(permissions or [])
    if permission_set and (permission_set & set(global_data_scope_permissions) or "*" in permission_set):
        return None
    return []
