"""Stable, detached values passed across the operations application boundary."""
from dataclasses import dataclass
from pathlib import Path
import sqlite3


@dataclass(frozen=True, slots=True)
class MigrationStep:
    version: int
    description: str


@dataclass(frozen=True, slots=True)
class MasterDataReference:
    entity_type: str
    table: str
    root_columns: tuple[str, ...]
    version_columns: tuple[str, ...]
    csv_columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PrecisionPreflightRequest:
    database: str | Path
    limit: int = 1000

    def __post_init__(self):
        if type(self.limit) is not int or not 1 <= self.limit <= 1000:
            raise ValueError("limit must be an integer from 1 to 1000")
        object.__setattr__(self, "database", str(Path(self.database).resolve()))


class ScheduleOperationError(ValueError):
    """Stable error shape for schedule replica and acceptance tools."""

    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


def detach_result(value):
    """Do not leak SQLite rows or caller-owned repository collections."""
    if isinstance(value, sqlite3.Row):
        return {key: detach_result(value[key]) for key in value.keys()}
    if isinstance(value, dict):
        return {key: detach_result(item) for key, item in value.items()}
    if isinstance(value, list):
        return [detach_result(item) for item in value]
    if isinstance(value, tuple):
        return tuple(detach_result(item) for item in value)
    return value
