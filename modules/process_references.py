"""Authoritative registry of business data that refers to a process."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessReference:
    table: str
    columns: tuple[str, ...]
    csv_columns: tuple[str, ...] = ()


PROCESS_REFERENCES = (
    ProcessReference("approval_config", ("process_id",)),
    ProcessReference("material_consumptions", ("process_id",)),
    ProcessReference("order_completion_focus_events", ("process_id",)),
    ProcessReference("order_materials", ("process_id",)),
    ProcessReference("order_processes", ("process_id",)),
    ProcessReference("position_processes", ("process_id",)),
    ProcessReference("process_handoff_reviews", ("from_process_id", "to_process_id")),
    ProcessReference(
        "process_quality_evaluation_task_audits",
        ("target_process_id", "evaluator_process_id"),
    ),
    ProcessReference(
        "process_quality_evaluation_tasks",
        ("target_process_id", "evaluator_process_id"),
    ),
    ProcessReference("process_quality_evaluation_templates", ("process_id",)),
    ProcessReference(
        "process_quality_evaluations",
        ("target_process_id", "evaluator_process_id"),
    ),
    ProcessReference("process_route_items", ("process_id",)),
    ProcessReference("product_bom", ("process_id",)),
    ProcessReference("product_items", ("current_process_id",)),
    ProcessReference("quality_inspection_plans", ("process_id",)),
    ProcessReference("quality_inspection_tasks", ("process_id",)),
    ProcessReference("quality_inspections", ("process_id",)),
    ProcessReference(
        "quality_nonconformances",
        ("process_id", "responsible_process_id"),
    ),
    ProcessReference("quality_standards", ("process_id",)),
    ProcessReference("rework_records", ("process_id",)),
    ProcessReference("route_price_history", ("process_id",)),
    ProcessReference("route_prices", ("process_id",)),
    ProcessReference("scrap_records", ("process_id",)),
    ProcessReference("user_processes", ("process_id",)),
    ProcessReference("users", (), ("process_ids",)),
    ProcessReference("work_records", ("process_id",)),
    ProcessReference("work_time_records", ("process_id",)),
    ProcessReference("work_time_standards", ("process_id",)),
)


PROCESS_REFERENCE_TABLES = frozenset(reference.table for reference in PROCESS_REFERENCES)
