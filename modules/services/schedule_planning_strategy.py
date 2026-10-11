"""Shared planning primitives used by generation, replan, and revision flows.

The strategy is the stable public seam for reusable planning behavior.  The
legacy capacity service remains the compatibility owner of the underlying
allocation implementation for now, but callers no longer reach through its
private methods or inject a service object into another service.
"""

import importlib


class SchedulePlanningStrategy:
    """Public planning seam retained while allocation code is migrated."""

    _provider = None

    @classmethod
    def bind(cls, provider):
        """Bind the legacy implementation without creating an import cycle."""
        cls._provider = provider

    @classmethod
    def _capacity_service(cls):
        if cls._provider is None:
            module = importlib.import_module(
                "modules.services.schedule_capacity_service"
            )
            cls._provider = module.ScheduleCapacityService
        return cls._provider

    @classmethod
    def transaction(cls, db=None):
        return cls._capacity_service()._transaction(db)

    @classmethod
    def read_transaction(cls, db=None):
        return cls._capacity_service()._read_transaction(db)

    @classmethod
    def persist_operation_payload(cls, payload, txn, *, persist=True):
        return cls._capacity_service().persist_operation_payload(
            payload, txn, persist=persist
        )

    @classmethod
    def parse_timestamp(cls, value):
        return cls._capacity_service()._parse_timestamp(value)

    @classmethod
    def format_timestamp(cls, value):
        return cls._capacity_service()._format_timestamp(value)

    @classmethod
    def find_standard(cls, *args, **kwargs):
        return cls._capacity_service()._find_standard(*args, **kwargs)

    @classmethod
    def calendar_snapshot(cls, *args, **kwargs):
        return cls._capacity_service()._calendar_snapshot(*args, **kwargs)

    @classmethod
    def allocate_on_line(cls, *args, **kwargs):
        return cls._capacity_service()._allocate_on_line(*args, **kwargs)

    @classmethod
    def allocate_split_on_nodes(cls, *args, **kwargs):
        return cls._capacity_service()._allocate_split_on_nodes(*args, **kwargs)

    @classmethod
    def allocate_split_on_lines(cls, *args, **kwargs):
        return cls._capacity_service()._allocate_split_on_lines(*args, **kwargs)

    @classmethod
    def assess_revision_conflicts(cls, *args, **kwargs):
        return cls._capacity_service()._assess_revision_conflicts(*args, **kwargs)

    @classmethod
    def assert_revision_conflict_gate(cls, *args, **kwargs):
        return cls._capacity_service()._assert_revision_conflict_gate(*args, **kwargs)
