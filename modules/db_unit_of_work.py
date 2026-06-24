"""Database unit-of-work helpers for services and repositories."""
import sqlite3
import threading
from contextlib import contextmanager

from modules.db import get_db

_txn_connections = set()
_txn_lock = threading.Lock()
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
    """Shared database helpers used by services and repositories."""

    @staticmethod
    def db():
        """Get the current request database connection."""
        return get_db()

    @staticmethod
    @contextmanager
    def transaction():
        db = get_db()
        try:
            db.execute('BEGIN IMMEDIATE')
        except Exception as exc:
            raise RuntimeError(f'数据库锁定: {exc}')
        with _txn_lock:
            _txn_connections.add(id(db))
        try:
            yield db
            db.commit()
        except sqlite3.IntegrityError as exc:
            db.execute('ROLLBACK')
            msg = str(exc)
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
        """Check if a connection is inside an active transaction."""
        if db is not None:
            return id(db) in _txn_connections
        return len(_txn_connections) > 0
