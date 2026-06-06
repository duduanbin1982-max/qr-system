"""
qr-system — 路由公共工具函数

消除 routes/*.py 间大量重复的样板代码：
  - 分页参数解析 (8 个文件重复)
  - JSON body 解析 (5 个文件重复)
  - 异常包装 (6 个文件重复)
"""
from flask import request, jsonify
from modules.db import get_page_size
from modules.middleware.error_handler import handle_unexpected_error


# ============================================================
# 分页参数
# ============================================================

def parse_pagination(max_limit: int = 200) -> dict:
    """从 query string 提取 page/limit/offset/search，返回统一 dict。

    Returns:
        {'page': int, 'limit': int, 'offset': int, 'search': str}
    """
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', get_page_size(), type=int)
    limit = max(1, min(limit, max_limit))
    offset = (page - 1) * limit
    search = request.args.get('search', '').strip()
    return {'page': page, 'limit': limit, 'offset': offset, 'search': search}


# ============================================================
# JSON Body
# ============================================================

def get_json_body() -> dict:
    """从 request body 解析 JSON，永远返回 dict（解析失败返回 {}）。"""
    return request.get_json(force=True, silent=True) or {}


# ============================================================
# 统一异常包装
# ============================================================

def safe_route(operation_name: str, func, *args, **kwargs):
    """安全执行路由逻辑，捕获所有异常并返回 500。

    Usage:
        return safe_route('创建订单', lambda: some_service.create(data))
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        return handle_unexpected_error(e, operation_name)


# ============================================================
# 标准列表响应
# ============================================================

def list_response(items: list, total: int, pagination: dict, **extra) -> tuple:
    """构建标准分页列表响应。

    Args:
        items: 数据列表
        total: 总数
        pagination: parse_pagination() 的返回值
        extra: 额外字段（如 pending/producing/completed 计数）

    Returns:
        (jsonify_response, 200)
    """
    result = {
        'items': items,
        'total': total,
        'page': pagination['page'],
        'limit': pagination['limit'],
    }
    result.update(extra)
    return jsonify(result), 200
