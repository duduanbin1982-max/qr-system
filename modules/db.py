"""
qr-system — 数据库层：连接管理、初始化、设置缓存
"""
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

def get_setting(key: str, default: str = '') -> str:
    """读取系统设置项，带 10 秒缓存"""
    global _settings_cache, _settings_cache_time
    now = time.time()
    if _settings_cache is None or now - _settings_cache_time > 10:
        db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
        rows = db.execute('SELECT key, value FROM system_settings').fetchall()
        db.close()
        _settings_cache = {r['key']: r['value'] for r in rows}
        _settings_cache_time = now
    return _settings_cache.get(key, default)

def clear_settings_cache() -> None:
    global _settings_cache, _settings_cache_time
    _settings_cache = None
    _settings_cache_time = 0

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
