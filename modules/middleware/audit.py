"""qr-system — Audit logging middleware."""
import logging

from flask import g, request
from modules.db import get_db

def audit_log(action: str, target_type: str = '', target_id: int = 0, detail: str = '') -> None:
    try:
        db = get_db()
        uid = g.current_user.get('id') if hasattr(g, 'current_user') else None
        db.execute('INSERT INTO audit_logs (user_id, action, target_type, target_id, detail) VALUES (?,?,?,?,?)',
                   (uid, action, target_type, target_id, detail))
        # Only commit if NOT inside an active transaction (avoid breaking caller's atomicity)
        from modules.db_unit_of_work import BaseService
        if not BaseService.is_in_transaction(db):
            db.commit()
    except Exception as ex:
        logging.getLogger("qr-system").warning(f"audit_log failed: {ex}")


def safe_audit_log(action: str, target_type: str = '', target_id: int = 0, detail: str = '') -> None:
    """Best-effort audit logging helper for route handlers."""
    audit_log(action, target_type, target_id, detail)
