"""qr-system — Audit logging middleware."""
import logging
import uuid

from flask import g, request
from modules.db import get_db
from modules.audit_action_catalog import describe_action
from modules.audit_policy import sanitize_audit_detail

def audit_log(action: str, target_type: str = '', target_id: int = 0, detail: str = '') -> None:
    try:
        db = get_db()
        uid = g.current_user.get('id') if hasattr(g, 'current_user') else None
        metadata = describe_action(action)
        detail = sanitize_audit_detail(detail)
        request_id = request.headers.get("X-Request-ID", "")[:120]
        db.execute(
            'INSERT INTO audit_logs '
            '(event_id, user_id, action, target_type, target_id, detail, category, '
            'severity, mandatory, schema_version, redaction_version, request_id) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            (
                uuid.uuid4().hex,
                uid,
                action,
                target_type,
                target_id,
                detail,
                metadata.category,
                metadata.severity,
                int(metadata.mandatory),
                1,
                1,
                request_id,
            ),
        )
        # Only commit if NOT inside an active transaction (avoid breaking caller's atomicity)
        from modules.db_unit_of_work import BaseService
        if not BaseService.is_in_transaction(db):
            db.commit()
    except Exception as ex:
        logging.getLogger("qr-system").warning(f"audit_log failed: {ex}")


def safe_audit_log(action: str, target_type: str = '', target_id: int = 0, detail: str = '') -> None:
    """Best-effort audit logging helper for route handlers."""
    audit_log(action, target_type, target_id, detail)


def required_audit_log(
    action: str,
    target_type: str = '',
    target_id: int = 0,
    detail='',
    db=None,
):
    """Write a mandatory audit event and propagate failures to the transaction."""

    from modules.repositories.audit_log_repository import AuditLogRepository
    from modules.db_unit_of_work import BaseService

    connection = db or get_db()
    event_id = AuditLogRepository.insert_log(
        g.current_user.get('id') if hasattr(g, 'current_user') else None,
        action,
        target_type,
        target_id,
        detail,
        db=connection,
        request_id=request.headers.get("X-Request-ID", "")[:120],
    )
    if db is None and not BaseService.is_in_transaction(connection):
        connection.commit()
    return event_id
