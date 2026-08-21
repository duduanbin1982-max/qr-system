"""Pure access policy calculations shared by middleware and services."""
import json
import logging
from typing import Iterable, List, Optional, Sequence, Set

from modules.permission_catalog import PERMISSION_IMPLICATIONS, infer_page_permissions


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
        raw_value = _row_value(row, "role_perms")
        if not raw_value:
            continue
        try:
            parsed = json.loads(raw_value)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning(
                "access_policy: invalid role_perms JSON for user %s: %s",
                user_id,
                exc,
            )
            continue
        if isinstance(parsed, list):
            permissions.update(str(item) for item in parsed if item)
    if "*" in permissions:
        return ["*"]
    # Materialize the same transitive permission closure used by middleware
    # and the browser so API consumers cannot observe a weaker policy.
    changed = True
    while changed:
        changed = False
        for granted, implied in PERMISSION_IMPLICATIONS.items():
            if granted not in permissions:
                continue
            for code in implied:
                if code not in permissions:
                    permissions.add(code)
                    changed = True
    permissions.update(infer_page_permissions(permissions))
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


def has_global_data_scope(
    permissions: Sequence[str], global_data_scope_permissions: Set[str]
) -> bool:
    permission_set = set(permissions or [])
    return bool(
        permission_set
        and (
            "*" in permission_set
            or permission_set & set(global_data_scope_permissions)
        )
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
