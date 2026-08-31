"""Shared route-layer imports for Flask handlers.

Route modules should import cross-cutting decorators and helpers from here instead
of depending on every middleware module directly. This keeps individual route
modules focused on HTTP orchestration while preserving the existing public API.
"""

from functools import wraps

from flask import jsonify, request

from modules import config
from modules.app import app
from modules.domain.process_versioning import (
    VersionedMasterDataWriteDisabledError,
    assert_legacy_master_data_write_allowed,
)
from modules.domain.position_versioning import (
    PositionLegacyWriteBlockedError,
    PositionVersionedWriteDisabledError,
)
from modules.domain.reporting_day import reporting_range_bounds
from modules.middleware.audit import required_audit_log, safe_audit_log
from modules.middleware.auth import check_auth, check_permission, has_permission
from modules.middleware.data_scope import check_order_data_scope, get_user_process_ids
from modules.middleware.error_handler import handle_unexpected_error
from modules.middleware.helpers import get_json_body, list_response, parse_pagination, safe_route
from modules.middleware.rate_limit import rate_limit
from modules.middleware.validate import validate_json


def validate_reporting_range(view):
    """Reject malformed or reversed start/end reporting-day query ranges."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        try:
            reporting_range_bounds(
                request.args.get("start", ""), request.args.get("end", "")
            )
        except ValueError:
            return jsonify({"error": "日期范围无效，请使用 YYYY-MM-DD 且开始日期不晚于结束日期"}), 400
        return view(*args, **kwargs)

    return wrapped


def require_versioned_master_data_write(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not config.PROCESS_VERSIONED_WRITE_ENABLED:
            raise VersionedMasterDataWriteDisabledError(
                "版本化工序和路线写入尚未启用"
            )
        return view(*args, **kwargs)

    return wrapped


def require_legacy_master_data_write(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        assert_legacy_master_data_write_allowed(
            not config.PROCESS_LEGACY_WRITE_BLOCKED
        )
        return view(*args, **kwargs)

    return wrapped


def require_position_versioned_write(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not config.POSITION_VERSIONED_WRITE_ENABLED:
            raise PositionVersionedWriteDisabledError(
                "岗位版本化写入尚未启用"
            )
        return view(*args, **kwargs)

    return wrapped


def require_legacy_position_write(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if config.POSITION_LEGACY_WRITE_BLOCKED:
            raise PositionLegacyWriteBlockedError(
                "Legacy 岗位写入已关闭，请使用岗位版本化接口"
            )
        return view(*args, **kwargs)

    return wrapped

__all__ = [
    "app",
    "check_auth",
    "check_permission",
    "check_order_data_scope",
    "get_json_body",
    "get_user_process_ids",
    "handle_unexpected_error",
    "has_permission",
    "list_response",
    "parse_pagination",
    "rate_limit",
    "require_legacy_master_data_write",
    "require_legacy_position_write",
    "require_position_versioned_write",
    "require_versioned_master_data_write",
    "required_audit_log",
    "safe_audit_log",
    "safe_route",
    "validate_json",
    "validate_reporting_range",
]
