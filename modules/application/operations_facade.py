"""Stable entry point for operational scripts.

Adapters are loaded without initializing Flask, reading configuration, or
opening a database. Persistence, replica overrides and application lifecycle
details stay in application components; scripts receive detached values.
"""
from .operations_dto import PrecisionPreflightRequest
from .operations_deployment import DeploymentOperations
from .operations_migrations import MigrationOperations
from .operations_performance import PerformanceOperations
from .operations_runtime import RuntimeOperations
from .operations_schedule import ScheduleOperations


class OperationsFacade(MigrationOperations, RuntimeOperations, ScheduleOperations, PerformanceOperations, DeploymentOperations):
    @staticmethod
    def classify_work_time_operation(order, operation):
        from .operations_preflight import classify_work_time_operation

        return classify_work_time_operation(order, operation)

    @staticmethod
    def summarize_work_time_coverage(rows):
        from .operations_preflight import summarize_work_time_coverage

        return summarize_work_time_coverage(rows)

    @staticmethod
    def precision_preflight(database, limit=1000):
        from .operations_preflight import run_preflight

        request = PrecisionPreflightRequest(database, limit)
        return run_preflight(request.database, request.limit)


__all__ = ["OperationsFacade"]
