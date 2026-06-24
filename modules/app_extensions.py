"""Flask application extension registration.

This module is the composition boundary for cross-cutting web concerns so the
core app instance does not directly depend on middleware implementations.
"""
import secrets

from flask import g, request


ALLOWED_ORIGINS = {
    "https://192.168.1.75:3000",
    "http://192.168.1.75:3000",
    "http://localhost:3000",
    "https://192.168.1.8",
    "http://192.168.1.8",
}


def register_app_extensions(app):
    from modules.middleware.error_handler import register_error_handlers
    from modules.middleware.rate_limit import apply_global_rate_limit
    from modules.middleware.request_tracker import RequestTracker

    register_error_handlers(app)
    RequestTracker(app)
    _register_request_hooks(app)
    _register_security_headers(app, apply_global_rate_limit)


def _register_request_hooks(app):
    @app.before_request
    def generate_csp_nonce():
        g.csp_nonce = secrets.token_hex(16)

    @app.before_request
    def api_version_prefix():
        if request.path.startswith("/api/v1/"):
            request.environ["PATH_INFO"] = request.path.replace("/api/v1/", "/api/", 1)


def _register_security_headers(app, apply_global_rate_limit):
    @app.after_request
    def add_security_headers(response):
        limit_resp = apply_global_rate_limit()
        if limit_resp is not None:
            return limit_resp

        origin = request.headers.get("Origin", "")
        if origin in ALLOWED_ORIGINS:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"

        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        response.headers["Access-Control-Max-Age"] = "86400"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        if request.is_secure or request.headers.get("X-Forwarded-Proto", "") == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"

        csp_nonce = getattr(g, "csp_nonce", "fallback")
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{csp_nonce}' cdn.jsdelivr.net unpkg.com; "
            "style-src 'self' 'unsafe-inline' unpkg.com; "
            "img-src 'self' data: blob:; "
            "connect-src 'self' cdn.jsdelivr.net unpkg.com; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"

        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"

        return response
