"""Request-context adapter for the unified audit writer."""

import logging

from flask import g, request

from modules.audit_writer import AuditCommand, AuditWriter


LOGGER = logging.getLogger("qr-system")


def _request_command(action, target_type="", target_id=0, detail=""):
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    request_id = request.headers.get("X-Request-ID", "")[:120]
    return AuditCommand.create(
        user_id,
        action,
        target_type,
        target_id,
        detail,
        request_id=request_id,
    )


def audit_log(action: str, target_type: str = "", target_id: int = 0, detail=""):
    """Backward-compatible name for a best-effort request audit."""

    return safe_audit_log(action, target_type, target_id, detail)


def safe_audit_log(
    action: str,
    target_type: str = "",
    target_id: int = 0,
    detail="",
):
    """Write an isolated audit event without changing the business outcome."""

    try:
        command = _request_command(action, target_type, target_id, detail)
        return AuditWriter.best_effort(command)
    except Exception as exc:
        LOGGER.warning(
            "best-effort request audit preparation failed action=%s: %s",
            action,
            exc,
        )
        return None


def required_audit_log(
    action: str,
    target_type: str = "",
    target_id: int = 0,
    detail="",
    db=None,
):
    """Join a caller-owned transaction and propagate audit failures."""

    return AuditWriter.required(
        _request_command(action, target_type, target_id, detail),
        db=db,
    )
