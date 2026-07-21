"""Authentication session policy and lifecycle operations."""
from datetime import datetime, timedelta

from modules.config import SESSION_IDLE_MINUTES, SESSION_TIMEOUT_HOURS
from modules.db import get_setting
from modules.repositories.auth_repository import AuthRepository
from modules.services import BaseService


class AuthSessionService:
    """Validate and maintain request sessions behind a service boundary."""

    TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
    MAX_TOUCH_INTERVAL = timedelta(minutes=5)
    MIN_TOUCH_INTERVAL = timedelta(seconds=30)

    @staticmethod
    def _setting_int(key, default):
        try:
            raw_value = get_setting(key, "")
            if raw_value in (None, ""):
                return default
            value = int(raw_value)
            return value if value >= 0 else default
        except Exception:
            return default

    @classmethod
    def _parse_timestamp(cls, value):
        if not value:
            return None
        try:
            return datetime.strptime(value, cls.TIMESTAMP_FORMAT)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _is_older_than(cls, value, now, limit):
        timestamp = cls._parse_timestamp(value)
        return bool(timestamp and now - timestamp > limit)

    @classmethod
    def _touch_interval(cls, idle_minutes):
        if idle_minutes <= 0:
            return cls.MAX_TOUCH_INTERVAL
        idle_half = timedelta(minutes=idle_minutes / 2)
        return max(cls.MIN_TOUCH_INTERVAL, min(cls.MAX_TOUCH_INTERVAL, idle_half))

    @classmethod
    def _should_touch(cls, last_active, now, idle_minutes):
        timestamp = cls._parse_timestamp(last_active)
        if timestamp is None:
            return True
        return now - timestamp >= cls._touch_interval(idle_minutes)

    @classmethod
    def authenticate(cls, token, now=None):
        row = AuthRepository.find_active_user_by_token(token)
        if not row:
            return None, "登录已过期"

        user = dict(row)
        session_created_at = user.pop("_session_created_at", None)
        session_last_active = user.pop("_session_last_active", None)
        now = now or datetime.now()
        timeout_hours = cls._setting_int("session_timeout_hours", SESSION_TIMEOUT_HOURS)
        idle_minutes = cls._setting_int("session_idle_minutes", SESSION_IDLE_MINUTES)

        session_started_at = session_created_at or user.get("last_active") or user.get("created_at")
        last_active = session_last_active or user.get("last_active") or session_started_at
        absolute_expired = timeout_hours > 0 and cls._is_older_than(
            session_started_at,
            now,
            timedelta(hours=timeout_hours),
        )
        idle_expired = idle_minutes > 0 and cls._is_older_than(
            last_active,
            now,
            timedelta(minutes=idle_minutes),
        )

        if absolute_expired or idle_expired:
            with BaseService.transaction() as transaction:
                AuthRepository.expire_session(user["id"], token, db=transaction)
            return None, "登录已过期，请重新登录"

        if cls._should_touch(last_active, now, idle_minutes):
            active_at = now.strftime(cls.TIMESTAMP_FORMAT)
            with BaseService.transaction() as transaction:
                AuthRepository.touch_session(user["id"], token, active_at, db=transaction)
            user["last_active"] = active_at

        return user, None
