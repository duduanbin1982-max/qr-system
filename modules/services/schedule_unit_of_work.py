"""Shared transaction ownership for scheduling use cases."""

from contextlib import contextmanager
from modules.services import BaseService
from modules.repositories.schedule_revision_repository import ScheduleRevisionRepository


class ScheduleUnitOfWork:
    @staticmethod
    @contextmanager
    def transaction(db=None):
        """Use the request UoW in production or an explicit clone connection in preflight."""
        if db is None:
            with BaseService.transaction() as txn:
                yield txn
            return
        started = False
        if not db.in_transaction:
            db.execute("BEGIN IMMEDIATE")
            started = True
        try:
            yield db
            if started:
                db.commit()
        except Exception:
            if started:
                db.rollback()
            raise

    @staticmethod
    @contextmanager
    def read_transaction(db=None):
        """Open a deferred snapshot transaction for planning-only work."""
        if db is None:
            db = BaseService.db()
        started = False
        if not db.in_transaction:
            db.execute("BEGIN")
            started = True
        try:
            yield db
            if started:
                db.commit()
        except Exception:
            if started:
                db.rollback()
            raise

    @staticmethod
    def persist_operation_payload(payload, txn, *, persist=True):
        """Persist one operation only in the short write phase."""
        if not persist:
            result = dict(payload)
            result.pop("id", None)
            return result
        result = dict(payload)
        result["id"] = ScheduleRevisionRepository.insert_operation_schedule(
            result, txn
        )
        return result
