"""
qr-system — 数据权限中间件：基于岗位+角色的数据范围控制
"""
from typing import Any, List, Optional, Tuple, Union
from modules.db import get_db
from modules.middleware.auth import get_user_permissions

def get_user_process_ids(user: Optional[dict]) -> Optional[List[int]]:
    """返回用户可访问的工序ID列表。None=全部, [] =无权限"""
    if not user:
        return None
    perms = get_user_permissions(user)
    # 拥有全局权限则返回 None（全部数据）
    global_perms = {'orders:view', 'stats:view', 'inventory:view', '*',
                    'shipments:view', 'reports:view', 'dashboard:view'}
    if perms and (set(perms) & global_perms or '*' in perms):
        return None
    # 从岗位获取工序范围（通过 position_processes 关联表）
    pid = user.get('position_id')
    if pid:
        db = get_db()
        rows = db.execute('SELECT process_id FROM position_processes WHERE position_id = ?', (pid,)).fetchall()
        if rows:
            return [r['process_id'] for r in rows]
    # 有 position_id 但无工序关联 → 全无
    if pid is not None:
        return []
    return None


def process_filter_condition(user: Optional[dict], column: str = 'process_id') -> Tuple[str, List[int]]:
    """返回 (where_clause, params) 用于 SQL 过滤。
    - 管理员/全局角色：('1=1', [])
    - 无工序权限：('1=0', [])  
    - 特定工序：('{column} IN (?,?,?)', [pids])
    """
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
