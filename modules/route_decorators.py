"""Shared route-layer imports for Flask handlers.

Route modules should import cross-cutting decorators and helpers from here instead
of depending on every middleware module directly. This keeps individual route
modules focused on HTTP orchestration while preserving the existing public API.
"""

from modules.app import app
from modules.middleware.audit import safe_audit_log
from modules.middleware.auth import check_auth, check_permission, has_permission
from modules.middleware.data_scope import get_user_process_ids
from modules.middleware.error_handler import handle_unexpected_error
from modules.middleware.helpers import get_json_body, list_response, parse_pagination, safe_route
from modules.middleware.rate_limit import rate_limit
from modules.middleware.validate import validate_json

__all__ = [
    "app",
    "check_auth",
    "check_permission",
    "get_json_body",
    "get_user_process_ids",
    "handle_unexpected_error",
    "has_permission",
    "list_response",
    "parse_pagination",
    "rate_limit",
    "safe_audit_log",
    "safe_route",
    "validate_json",
]
