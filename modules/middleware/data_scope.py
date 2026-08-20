"""Data-scope helpers for process authorization and SQL filtering."""
from typing import List, Optional, Tuple
from modules.services.access_policy_service import get_user_process_ids as _get_user_process_ids


def get_user_process_ids(
    user: Optional[dict], order_id=None, db=None
) -> Optional[List[int]]:
    return _get_user_process_ids(user, order_id=order_id, db=db)


def check_order_data_scope(order_id: int, user: Optional[dict], db=None) -> bool:
    """Return whether a user may access an order and its child resources."""
    from modules.services.scan_helper_service import ScanHelperService

    return ScanHelperService.check_order_scope(
        order_id,
        get_user_process_ids(user, order_id=order_id, db=db),
        db=db,
    )



# Whitelist of allowed column names for process_filter_condition
_ALLOWED_FILTER_COLUMNS = {'process_id', 'id', 'wr.process_id', 'op.process_id'}

def process_filter_condition(user: Optional[dict], column: str = 'process_id') -> Tuple[str, List[int]]:
    """返回 (where_clause, params) 用于 SQL 过滤。
    - 管理员/全局角色：('1=1', [])
    - 无工序权限：('1=0', [])
    - 特定工序：('{column} IN (?,?,?)', [pids])
    
    Safety: column name is validated against _ALLOWED_FILTER_COLUMNS whitelist
    to prevent SQL injection through dynamic column names.
    """
    if column not in _ALLOWED_FILTER_COLUMNS:
        raise ValueError(f"Invalid filter column: {column}")
    pids = get_user_process_ids(user)
    if pids is None:
        return ('1=1', [])
    if not pids:
        return ('1=0', [])
    placeholders = ','.join('?' for _ in pids)
    return (f'{column} IN ({placeholders})', pids)


def filter_by_process(data_list: List[dict], process_id_field: str, user: Optional[dict]) -> List[dict]:

    """过滤列表数据，仅保留用户有权限的工序"""
    pids = get_user_process_ids(user)
    if pids is None:
        return data_list
    if not pids:
        return []
    return [d for d in data_list if d.get(process_id_field) in pids]
