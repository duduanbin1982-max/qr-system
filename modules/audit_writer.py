"""Unified audit command and write boundary."""

import logging
import uuid
from dataclasses import dataclass
from typing import Protocol

from modules.audit_action_catalog import describe_action
from modules.audit_policy import sanitize_audit_detail


LOGGER = logging.getLogger("qr-system")


@dataclass(frozen=True, slots=True)
class AuditCommand:
    """Immutable audit event ready for persistence."""

    event_id: str
    user_id: int | None
    action: str
    target_type: str
    target_id: int
    detail: str
    category: str
    severity: str
    mandatory: int
    schema_version: int
    redaction_version: int
    request_id: str

    @classmethod
    def create(
        cls,
        user_id,
        action,
        target_type="",
        target_id=0,
        detail="",
        *,
        event_id=None,
        request_id="",
    ):
        metadata = describe_action(action)
        return cls(
            event_id=str(event_id or uuid.uuid4().hex),
            user_id=int(user_id) if user_id is not None else None,
            action=str(action or ""),
            target_type=str(target_type or ""),
            target_id=int(target_id or 0),
            detail=sanitize_audit_detail(detail),
            category=metadata.category,
            severity=metadata.severity,
            mandatory=int(metadata.mandatory),
            schema_version=1,
            redaction_version=1,
            request_id=str(request_id or ""),
        )

    def to_payload(self):
        return {
            "event_id": self.event_id,
            "user_id": self.user_id,
            "action": self.action,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "detail": self.detail,
            "category": self.category,
            "severity": self.severity,
            "mandatory": self.mandatory,
            "schema_version": self.schema_version,
            "redaction_version": self.redaction_version,
            "request_id": self.request_id,
        }


class AuditPort(Protocol):
    """Persistence port implemented by the audit repository."""

    @staticmethod
    def insert_command(command: AuditCommand, *, db) -> int: ...


class AuditWriter:
    """Apply required or best-effort transaction semantics to audit commands."""

    @staticmethod
    def _port():
        from modules.repositories.audit_log_repository import AuditLogRepository

        return AuditLogRepository

    @classmethod
    def required(cls, command: AuditCommand, *, db, port: AuditPort | None = None):
        """Join the caller's transaction and propagate every persistence failure."""

        if db is None:
            raise ValueError("required audit writes need a caller-owned transaction")
        return (port or cls._port()).insert_command(command, db=db)

    @classmethod
    def best_effort(
        cls,
        command: AuditCommand,
        *,
        db=None,
        port: AuditPort | None = None,
    ):
        """Isolate an audit attempt and never alter the caller's failure outcome."""

        if db is None:
            from modules.db import get_db

            db = get_db()
        savepoint = "audit_" + uuid.uuid4().hex
        savepoint_created = False
        try:
            db.execute(f"SAVEPOINT {savepoint}")
            savepoint_created = True
            event_id = (port or cls._port()).insert_command(command, db=db)
            db.execute(f"RELEASE SAVEPOINT {savepoint}")
            return event_id
        except Exception as exc:
            if savepoint_created:
                try:
                    db.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    db.execute(f"RELEASE SAVEPOINT {savepoint}")
                except Exception:
                    LOGGER.exception(
                        "audit savepoint cleanup failed event_id=%s",
                        command.event_id,
                    )
            LOGGER.warning(
                "best-effort audit write failed action=%s event_id=%s: %s",
                command.action,
                command.event_id,
                exc,
            )
            return None


def insert_audit_log(
    db,
    user_id,
    action,
    target_type="",
    target_id=0,
    detail="",
    *,
    event_id=None,
    request_id="",
):
    """Compatibility entry point for existing transactional audit producers."""

    command = AuditCommand.create(
        user_id,
        action,
        target_type,
        target_id,
        detail,
        event_id=event_id,
        request_id=request_id,
    )
    return AuditWriter.required(command, db=db)
