"""
qr-system — API 速率限制中间件

内存滑动窗口限流，按 IP+端点 维度计数。
单 worker 部署适用，多 worker 需改用 Redis 后端。
"""
import time
import threading
from functools import wraps
from flask import request, jsonify, g


# ============================================================
# 滑动窗口计数器（线程安全）
# ============================================================
class SlidingWindow:
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._buckets: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _clean(self, key: str, now: float):
        if key in self._buckets:
            cutoff = now - self.window_seconds
            self._buckets[key] = [t for t in self._buckets[key] if t > cutoff]
            if not self._buckets[key]:
                del self._buckets[key]

    def is_allowed(self, key: str) -> tuple[bool, int]:
        """返回 (是否允许, 剩余请求数)"""
        now = time.time()
        with self._lock:
            self._clean(key, now)
            if key not in self._buckets:
                self._buckets[key] = []
            count = len(self._buckets[key])
            if count >= self.max_requests:
                return False, 0
            self._buckets[key].append(now)
            remaining = self.max_requests - count - 1
            return True, remaining


# ============================================================
# 预设限流策略
# ============================================================
_global_limiter = SlidingWindow(max_requests=300, window_seconds=60)   # 全局 300 req/min
_write_limiter  = SlidingWindow(max_requests=60,  window_seconds=60)   # 写操作 60 req/min
_scan_limiter   = SlidingWindow(max_requests=120, window_seconds=60)   # 扫码 120 req/min


def _get_key(prefix: str) -> str:
    """生成限流key：前缀 + IP（有登录态则加用户ID）"""
    ip = request.remote_addr or '127.0.0.1'
    uid = g.current_user.get('id') if hasattr(g, 'current_user') else ''
    return f"{prefix}:{ip}:{uid}"


def rate_limit(limiter=None, max_rpm=300):
    """
    API 限流装饰器。

    用法:
        @rate_limit()                          # 默认 300 req/min
        @rate_limit(limiter=_write_limiter)    # 写操作 60 req/min
    """
    rl = limiter or SlidingWindow(max_requests=max_rpm, window_seconds=60)

    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            key = _get_key(f.__name__)
            allowed, remaining = rl.is_allowed(key)
            if not allowed:
                return jsonify({
                    'error': '请求过于频繁，请稍后再试',
                    'retry_after': 60
                }), 429
            # 在响应头中注入限流信息
            resp = f(*args, **kwargs)
            if hasattr(resp, 'headers'):
                resp.headers['X-RateLimit-Remaining'] = str(remaining)
            return resp
        return decorated
    return decorator


# ============================================================
# 全局 after_request 限流（兜底所有 API）
# ============================================================
def apply_global_rate_limit():
    """应在 app.after_request 中调用的全局限流检查。
    仅对 /api/ 路径生效，健康检查等端点除外。
    """
    if not request.path.startswith('/api/'):
        return None  # 不限流
    if request.path in ('/api/health', '/api/auth/login'):
        return None  # 健康检查和登录不限流

    key = _get_key('global')
    allowed, remaining = _global_limiter.is_allowed(key)
    if not allowed:
        return jsonify({'error': '请求过于频繁，请稍后再试', 'retry_after': 60}), 429
    return None

