"""
qr-system — 数据库层：连接管理、初始化、设置缓存
"""
import os
import sqlite3
import hashlib
from typing import Any, Optional, Tuple
import bcrypt
import json
import time
from flask import g

from modules.config import DB_PATH, PREDEFINED_ROLES
from modules.migrations import run_migrations, LATEST_VERSION

# 缓存系统设置（避免每次查询）
_settings_cache = None
_settings_cache_time = 0

def get_db() -> sqlite3.Connection:
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA busy_timeout=5000")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

def close_db(exception: Optional[Exception] = None) -> None:
    """关闭数据库连接。作为 app.teardown_appcontext 回调使用。"""
    db = g.pop('db', None)
    if db is not None:
        db.close()

_CACHE_STAMP_FILE = os.path.join(os.path.dirname(DB_PATH), '.settings_cache_stamp')

def _get_cache_stamp():
    try:
        return os.path.getmtime(_CACHE_STAMP_FILE)
    except OSError:
        return 0

def _touch_cache_stamp():
    with open(_CACHE_STAMP_FILE, 'w') as f:
        f.write(str(time.time()))

def get_setting(key: str, default: str = '') -> str:
    global _settings_cache, _settings_cache_time
    stamp = _get_cache_stamp()
    if _settings_cache is None or stamp > _settings_cache_time:
        # Prefer Flask's per-request connection when in app context,
        # fall back to a direct connection for startup/CLI usage
        db = None
        own_conn = False
        try:
            from flask import g as _flask_g
            db = _flask_g.db if hasattr(_flask_g, 'db') else None
        except Exception:
            pass
        if db is None:
            db = sqlite3.connect(DB_PATH)
            db.row_factory = sqlite3.Row
            own_conn = True
        rows = db.execute('SELECT key, value FROM system_settings').fetchall()
        if own_conn:
            db.close()
        _settings_cache = {r['key']: r['value'] for r in rows}
        _settings_cache_time = stamp
    return _settings_cache.get(key, default)

def clear_settings_cache() -> None:
    global _settings_cache, _settings_cache_time
    _settings_cache = None
    _settings_cache_time = 0
    _touch_cache_stamp()

def get_page_size(default: int = 20) -> int:
    """从系统设置读取分页条数"""
    try:
        v = get_setting('page_size', '')
        if v:
            return int(v)
    except (ValueError, TypeError):
        pass
    return default

def init_db() -> None:
    """Initialize database by running pending migrations (Migration Framework v3)."""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA journal_mode=WAL")
        current_version = db.execute("PRAGMA user_version").fetchone()[0]
        if current_version >= LATEST_VERSION:
            db.close()
            return
        run_migrations(db)
    finally:
        db.close()
