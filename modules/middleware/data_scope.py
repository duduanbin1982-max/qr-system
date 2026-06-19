"""
qr-system — 数据权限中间件：基于岗位+角色的数据范围控制
"""
from typing import Any, List, Optional, Tuple, Union
from modules.db import get_db
from modules.middleware.auth import get_user_permissions
from modules.config import GLOBAL_DATA_SCOPE_PERMS

def get_user_process_ids(user: Optional[dict]) -> Optional[List[int]]:
    if not user:
        return None

    db = get_db()
    allowed = set()

    # 1. Collect position processes
    pid = user.get("position_id")
    if pid:
        rows = db.execute(
            "SELECT process_id FROM position_processes WHERE position_id = ?", (pid,)
        ).fetchall()
        for r in rows:
            allowed.add(r["process_id"])

    # 2. Collect employee processes (supplement / fill-in)
    pids_str = (user.get("process_ids") or "").strip()
    if pids_str:
        try:
            pids = [int(x.strip()) for x in pids_str.split(",") if x.strip()]
            if pids:
                ph = ",".join("?" for _ in pids)
                existing = db.execute(
                    f"SELECT id FROM processes WHERE id IN ({ph})", pids
                ).fetchall()
                for r in existing:
                    allowed.add(r["id"])
        except (ValueError, TypeError):
            pass

    # 3. Return merged result (position U employee)
    if allowed:
        return sorted(list(allowed))

    # 4. Has position or process_ids but merge empty => zero permission
    if pid or pids_str:
        return []

    # 5. Check global permissions (admin etc.)
    perms = get_user_permissions(user)
    global_perms = GLOBAL_DATA_SCOPE_PERMS
    if perms and (set(perms) & global_perms or "*" in perms):
        return None

    # 6. No position, no employee processes, no global perms => zero
    return []



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
