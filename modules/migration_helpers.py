"""Explicit, reusable primitives for SQLite schema migrations."""

import sqlite3


class MigrationInvariantError(RuntimeError):
    """Raised when existing data prevents a required schema invariant."""


def table_exists(db, table):
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone() is not None


def column_exists(db, table, column):
    if not table_exists(db, table):
        return False
    return any(row[1] == column for row in db.execute(f"PRAGMA table_info({table})"))


def add_column_if_missing(db, table, column, definition):
    if not table_exists(db, table) or column_exists(db, table, column):
        return False
    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    return True


def create_unique_index(db, index_name, table, columns):
    try:
        db.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} ON {table}({columns})"
        )
    except sqlite3.IntegrityError as exc:
        raise MigrationInvariantError(
            f"cannot create unique index {index_name}; duplicate {table}({columns}) data exists"
        ) from exc
