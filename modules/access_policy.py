"""Shared access policy helpers used by middleware and services."""
import json
import logging
from typing import List, Optional

from modules.config import GLOBAL_DATA_SCOPE_PERMS
from modules.repositories.access_policy_repository import AccessPolicyRepository


def get_user_permissions(user: Optional[dict]) -> List[str]:
    if not user:
        return []
    cached = user.get('_permissions')
    if cached is not None:
        return sorted(cached)
    rows = AccessPolicyRepository.get_permission_rows(user['id'])
    all_perms = set()
    for row in rows:
        for column in ('role_perms', 'group_perms'):
            if row[column]:
                try:
                    all_perms.update(json.loads(row[column]))
                except (json.JSONDecodeError, TypeError) as exc:
                    logging.getLogger('qr').warning(
                        'access_policy: invalid %s JSON for user %s: %s',
                        column, user.get('id'), exc
                    )
    return sorted(all_perms)


def has_permission(user: Optional[dict], perm: str) -> bool:
    if not user:
        return False
    perms = set(get_user_permissions(user))
    return '*' in perms or perm in perms


def get_user_process_ids(user: Optional[dict]) -> Optional[List[int]]:
    if not user:
        return None

    allowed = set()
    position_id = user.get('position_id')
    if position_id:
        for row in AccessPolicyRepository.list_position_process_ids(position_id):
            allowed.add(row['process_id'])

    process_ids_text = (user.get('process_ids') or '').strip()
    if process_ids_text:
        try:
            process_ids = [int(item.strip()) for item in process_ids_text.split(',') if item.strip()]
            for row in AccessPolicyRepository.list_existing_process_ids(process_ids):
                allowed.add(row['id'])
        except (ValueError, TypeError):
            pass

    if allowed:
        return sorted(allowed)
    if position_id or process_ids_text:
        return []

    perms = set(get_user_permissions(user))
    if perms and (perms & GLOBAL_DATA_SCOPE_PERMS or '*' in perms):
        return None
    return []
