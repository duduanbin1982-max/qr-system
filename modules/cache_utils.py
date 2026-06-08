"""Simple TTL cache for route responses."""
import time
from functools import wraps
from flask import jsonify, g

_cache_store = {}
MAX_CACHE_SIZE = 100

def _evict_oldest():
    """Remove oldest entries when cache exceeds max size."""
    if len(_cache_store) > MAX_CACHE_SIZE:
        sorted_keys = sorted(_cache_store.keys(), key=lambda k: _cache_store[k][1])
        for key in sorted_keys[:len(_cache_store) - MAX_CACHE_SIZE]:
            del _cache_store[key]

def _get_user_key():
    """Get a user-specific cache key suffix (0 for unauthenticated)."""
    try:
        return str(g.current_user.get('id', 0)) if hasattr(g, 'current_user') else '0'
    except Exception:
        return '0'

def ttl_cache(ttl_seconds=30):
    """Decorator: cache Flask JSON response for ttl_seconds.
    Only caches 2xx responses; error responses (4xx/5xx) are never cached.
    Cache key includes user ID for per-user isolation."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            uid = _get_user_key()
            cache_key = f"{func.__name__}:{uid}:{args}:{kwargs}"
            now = time.time()
            if cache_key in _cache_store:
                data, timestamp = _cache_store[cache_key]
                if now - timestamp < ttl_seconds:
                    return jsonify(data)
            result = func(*args, **kwargs)
            # Only cache successful (2xx) responses
            if isinstance(result, tuple) and len(result) == 2:
                resp, code = result
                if 200 <= code < 300:
                    data = resp.json if hasattr(resp, "json") else resp
                    _cache_store[cache_key] = (data, now)
                return resp, code
            # No status code = default 200
            data = result.json if hasattr(result, "json") else result
            _cache_store[cache_key] = (data, now)
            _evict_oldest()
            return result
        return wrapper
    return decorator

def invalidate_cache():
    """Clear all cached data."""
    _cache_store.clear()