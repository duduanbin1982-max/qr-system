"""
qr-system — 认证中间件：check_auth, check_permission, audit_log, has_permission, get_user_permissions
"""
from functools import wraps
from typing import Callable, List, Optional
from flask import request, jsonify, g

from modules.services.access_policy_service import get_user_permissions as _get_user_permissions, has_permission as _has_permission
from modules.services.auth_session_service import AuthSessionService

def has_permission(user: Optional[dict], perm: str) -> bool:
    """Return whether a user has the requested permission."""
    return _has_permission(user, perm)


def get_user_permissions(user: Optional[dict]) -> List[str]:
    """Return the effective permission codes for a user."""
    return _get_user_permissions(user)

def check_auth(f: Callable) -> Callable:
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        # Fallback: read from httpOnly cookie (XSS-safe)
        if not token:
            token = request.cookies.get('qr_token', '')
        if not token:
            return jsonify({'error': '未登录'}), 401
        user, error = AuthSessionService.authenticate(token)
        if not user:
            return jsonify({'error': error}), 401
        g.current_user = user
        g.current_user['_permissions'] = get_user_permissions(g.current_user)
        g.token = token

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
