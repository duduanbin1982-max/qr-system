"""
qr-system - Service 层基类

提供统一事务管理，消除路由中重复的 BEGIN/COMMIT/ROLLBACK 模板。
"""
import sqlite3
import threading
from contextlib import contextmanager
from modules.db import get_db

# Thread-safe set of connection IDs currently in active transactions
_txn_connections = set()
_txn_lock = threading.Lock()




# Testability seam: allow overriding DB path for testing
_test_db_path = None

def set_test_db_path(path):
    """Set an alternative database path for testing."""
    global _test_db_path
    _test_db_path = path

def get_db_path():
    """Return the configured database path."""
    if _test_db_path:
        return _test_db_path
    from modules.config import DB_PATH
    return DB_PATH


class BaseService:
    """所有 Service 的基类，提供事务管理。"""

    @staticmethod
    def db():
        """获取数据库连接（非事务场景）"""
        return get_db()

    @staticmethod
    @contextmanager
    def transaction():
        """
        事务上下文管理器。

        Usage:
            with BaseService.transaction() as db:
                db.execute('INSERT ...', params)

        Raises:
            RuntimeError: 数据库锁定
            ValueError: 数据完整性约束违反（含 FK）
        """
        db = get_db()
        try:
            db.execute('BEGIN IMMEDIATE')
        except Exception as e:
            raise RuntimeError(f'数据库锁定: {e}')
        with _txn_lock:
            _txn_connections.add(id(db))
        try:
            yield db
            db.commit()
        except sqlite3.IntegrityError as e:
            db.execute('ROLLBACK')
            msg = str(e)
            if 'FOREIGN KEY' in msg.upper():
                raise ValueError('无法删除：该记录被其他数据引用')
            raise ValueError(f'数据完整性约束违反: {msg}')
        except Exception:
            db.execute('ROLLBACK')
            raise
        finally:
            with _txn_lock:
                _txn_connections.discard(id(db))

    @staticmethod
    def is_in_transaction(db=None):
        """Check if the given connection (or any) is inside an active transaction."""
        if db is not None:
            return id(db) in _txn_connections
        return len(_txn_connections) > 0
