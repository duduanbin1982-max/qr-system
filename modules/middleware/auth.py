"""
qr-system — 认证中间件：check_auth, check_permission, audit_log, has_permission, get_user_permissions
"""
import json
from functools import wraps
from typing import Any, Callable, Dict, List, Optional
import logging
from datetime import datetime, timedelta
from flask import request, jsonify, g

from modules.config import SESSION_TIMEOUT_HOURS, SESSION_IDLE_MINUTES
from modules.db import get_db, get_setting

def has_permission(user: Optional[dict], perm: str) -> bool:
    """检查用户是否拥有指定权限（含角色组权限继承）
    - user: g.current_user dict
    - perm: 如 'orders:edit' 或 '*' (星号需超级管理员)
    """
    if not user:
        return False
    cached = user.get('_permissions')
    if cached is not None:
        if '*' in cached:
            return True
        return perm in cached
    # Fallback: DB query
    db = get_db()
    rows = db.execute('''
        SELECT r.permissions, rg.permissions as group_permissions
        FROM user_roles ur
        JOIN roles r ON ur.role_id = r.id
        LEFT JOIN role_groups rg ON r.group_id = rg.id
        WHERE ur.user_id = ? AND r.status = 'active'
    ''', (user['id'],)).fetchall()
    all_perms = set()
    for row in rows:
        for col in ['permissions', 'group_permissions']:
            if row[col]:
                try:
                    perms = json.loads(row[col])
                    all_perms.update(perms)
                except (json.JSONDecodeError, TypeError):
                    pass
    if '*' in all_perms:
        return True
    return perm in all_perms

def get_user_permissions(user: Optional[dict]) -> List[str]:
    """获取用户所有权限列表（含角色组继承）"""
    if not user:
        return []
    db = get_db()
    rows = db.execute('''
        SELECT r.permissions, rg.permissions as group_permissions
        FROM user_roles ur
        JOIN roles r ON ur.role_id = r.id
        LEFT JOIN role_groups rg ON r.group_id = rg.id
        WHERE ur.user_id = ? AND r.status = 'active'
    ''', (user['id'],)).fetchall()
    all_perms = set()
    for row in rows:
        for col in ['permissions', 'group_permissions']:
            if row[col]:
                try:
                    perms = json.loads(row[col])
                    all_perms.update(perms)
                except (json.JSONDecodeError, TypeError):
                    pass
    return sorted(all_perms)

def check_auth(f: Callable) -> Callable:
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        # Also accept token via query param (for download links that can't set headers)
        if not token:
            token = request.args.get('token', '')
        # Fallback: read from httpOnly cookie (XSS-safe)
        if not token:
            token = request.cookies.get('qr_token', '')
        if not token:
            return jsonify({'error': '未登录'}), 401
        db = get_db()
        row = db.execute('SELECT * FROM users WHERE token = ? AND status = "active"', (token,)).fetchone()
        if not row:
            return jsonify({'error': '登录已过期'}), 401
        g.current_user = dict(row)
        g.current_user['_permissions'] = get_user_permissions(g.current_user)
        g.token = token

        # Check session timeout (if configured, override from settings)
        timeout_hours = SESSION_TIMEOUT_HOURS
        idle_minutes = SESSION_IDLE_MINUTES
        try:
            st = get_setting('session_timeout_hours', '')
            if st and st.isdigit():
                timeout_hours = int(st)
            si = get_setting('session_idle_minutes', '')
            if si and si.isdigit():
                idle_minutes = int(si)
        except Exception:
            pass

        now = datetime.now()
        expired = False
        idle_expired = False

        # Check absolute session timeout
        if timeout_hours > 0:
            last_active = g.current_user.get('last_active', '')
            if last_active:
                try:
                    last_dt = datetime.strptime(last_active, '%Y-%m-%d %H:%M:%S')
                    if now - last_dt > timedelta(hours=timeout_hours):
                        expired = True
                except Exception:
                    pass
            elif g.current_user.get('created_at'):
                try:
                    created_dt = datetime.strptime(g.current_user['created_at'], '%Y-%m-%d %H:%M:%S')
                    if now - created_dt > timedelta(hours=timeout_hours):
                        expired = True
                except Exception:
                    pass

        # Check idle timeout (shorter, only if user has last_active)
        if not expired and idle_minutes > 0:
            last_active = g.current_user.get('last_active', '')
            if last_active:
                try:
                    last_dt = datetime.strptime(last_active, '%Y-%m-%d %H:%M:%S')
                    if now - last_dt > timedelta(minutes=idle_minutes):
                        idle_expired = True
                except Exception:
                    pass

        if expired or idle_expired:
            db.execute('UPDATE users SET token = "" WHERE id = ?', (g.current_user['id'],))
            db.commit()
            return jsonify({'error': 'Login expired due to inactivity'}), 401

        # Update last_active
        db.execute('UPDATE users SET last_active = datetime("now","localtime") WHERE id = ?',
                   (g.current_user['id'],))
        db.commit()

        return f(*args, **kwargs)
    return decorated

def check_permission(perm: str) -> Callable:
    """权限检查装饰器 — 用法: @check_permission('orders:edit')
    自动包含 check_auth 逻辑（需配合 @check_auth 使用或内部调用 has_permission）
    注意：必须用在 @check_auth 之后（路由装饰器最内层）"""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not hasattr(g, 'current_user'):
                return jsonify({'error': '未登录'}), 401
            if not has_permission(g.current_user, perm):
                return jsonify({'error': '无权限'}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator

def audit_log(action: str, target_type: str = '', target_id: int = 0, detail: str = '') -> None:
    try:
        db = get_db()
        uid = g.current_user.get('id') if hasattr(g, 'current_user') else None
        db.execute('INSERT INTO audit_logs (user_id, action, target_type, target_id, detail) VALUES (?,?,?,?,?)',
                   (uid, action, target_type, target_id, detail))
        db.commit()
    except Exception as ex:
        logging.getLogger("qr-system").warning(f"audit_log failed: {ex}")
