"""Production scheduling time semantics for the Asia/Shanghai boundary.

Scheduling code works with timezone-aware datetimes in the production zone.
Legacy SQLite values remain offset-free wall-clock strings, but parsing and
serialization of those values is confined to this module.  API timestamps are
always explicit instants and therefore must carry an offset.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo


PRODUCTION_TIMEZONE_NAME = "Asia/Shanghai"
PRODUCTION_TIMEZONE = ZoneInfo(PRODUCTION_TIMEZONE_NAME)
PRODUCTION_TIMESTAMP_KEYS = frozenset(
    {
        "start_at",
        "end_at",
        "planned_start_at",
        "planned_end_at",
        "segment_start_at",
        "segment_end_at",
        "allocation_start_at",
        "allocation_end_at",
        "actual_start_at",
        "actual_end_at",
        "actual_last_report_at",
        "priority_effective_at",
        "deadline_at",
        "projected_completion_at",
        "overlap_start_at",
        "overlap_end_at",
        "replanned_at",
        "assessed_at",
    }
)


def _parse_iso(value):
    if isinstance(value, datetime):
        return value
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text.replace(" ", "T"))


def production_now():
    """Return the current aware instant in the production timezone."""
    return datetime.now(PRODUCTION_TIMEZONE)


def production_midnight(value):
    """Return an aware production-zone midnight for a date or datetime."""
    if isinstance(value, datetime):
        work_date = value.astimezone(PRODUCTION_TIMEZONE).date() if value.tzinfo else value.date()
    elif isinstance(value, date):
        work_date = value
    else:
        work_date = datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    return datetime.combine(work_date, time.min, tzinfo=PRODUCTION_TIMEZONE)


def parse_production_date(value, label="生产日期"):
    """Parse a date-only production value as aware Shanghai midnight."""
    try:
        if isinstance(value, datetime):
            return production_midnight(value)
        if isinstance(value, date):
            return production_midnight(value)
        return production_midnight(datetime.strptime(str(value or "").strip(), "%Y-%m-%d").date())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}必须使用 YYYY-MM-DD 格式") from exc


def parse_api_timestamp(value, label="时间"):
    """Parse an API timestamp and require an explicit UTC offset."""
    try:
        parsed = _parse_iso(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}必须使用带明确 offset 的 ISO 8601 时间") from exc
    if parsed is None or parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label}必须使用带明确 offset 的 ISO 8601 时间")
    return parsed.astimezone(PRODUCTION_TIMEZONE)


def parse_database_timestamp(value):
    """Parse a legacy SQLite wall-clock value as production local time.

    Offset-bearing values are accepted for forward compatibility.  Naive
    values are interpreted as Asia/Shanghai wall-clock facts without deleting
    or replacing timezone information on an aware datetime.
    """
    if value in (None, ""):
        return None
    try:
        parsed = _parse_iso(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=PRODUCTION_TIMEZONE)
    return parsed.astimezone(PRODUCTION_TIMEZONE)


def ensure_production_datetime(value):
    """Normalize a datetime or compatible stored value to Asia/Shanghai."""
    parsed = parse_database_timestamp(value)
    if parsed is None:
        raise ValueError("无效的生产时间")
    return parsed


def format_database_timestamp(value):
    """Serialize an instant using the existing offset-free SQLite format."""
    if value in (None, ""):
        return ""
    parsed = ensure_production_datetime(value).astimezone(PRODUCTION_TIMEZONE)
    if parsed.second or parsed.microsecond:
        return parsed.strftime("%Y-%m-%d %H:%M:%S")
    return parsed.strftime("%Y-%m-%d %H:%M")


def format_api_timestamp(value):
    """Serialize a stored or aware time with an explicit Shanghai offset."""
    if value in (None, ""):
        return ""
    parsed = ensure_production_datetime(value).astimezone(PRODUCTION_TIMEZONE)
    timespec = "seconds" if parsed.second or parsed.microsecond else "minutes"
    return parsed.isoformat(timespec=timespec)


def format_api_date(value):
    """Serialize a date/datetime using the Asia/Shanghai production date."""
    if value in (None, ""):
        return ""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    return ensure_production_datetime(value).strftime("%Y-%m-%d")


def same_instant(first, second):
    """Return whether two timestamp expressions identify the same instant."""
    left = parse_database_timestamp(first)
    right = parse_database_timestamp(second)
    if left is None or right is None:
        return False
    return left.astimezone(timezone.utc) == right.astimezone(timezone.utc)


def api_time_payload(value, key=""):
    """Recursively attach offsets to timestamp fields at the HTTP boundary."""
    if isinstance(value, Mapping):
        return {
            item_key: api_time_payload(item_value, str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [api_time_payload(item, key) for item in value]
    if (key in PRODUCTION_TIMESTAMP_KEYS or key.endswith("_at")) and value not in (None, ""):
        parsed = parse_database_timestamp(value)
        return format_api_timestamp(parsed) if parsed is not None else value
    return value


__all__ = [
    "PRODUCTION_TIMEZONE",
    "PRODUCTION_TIMEZONE_NAME",
    "PRODUCTION_TIMESTAMP_KEYS",
    "api_time_payload",
    "ensure_production_datetime",
    "format_api_timestamp",
    "format_api_date",
    "format_database_timestamp",
    "parse_api_timestamp",
    "parse_database_timestamp",
    "parse_production_date",
    "production_midnight",
    "production_now",
    "same_instant",
]
