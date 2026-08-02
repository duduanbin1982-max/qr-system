"""Immutable inputs and outputs for process-reporting decisions."""

from dataclasses import dataclass
from typing import Any, Mapping


SEQUENTIAL = "sequential"
OUT_OF_ORDER = "out_of_order"


@dataclass(frozen=True)
class ProcessReportingRequest:
    order_data: Mapping[str, Any]
    policy: Mapping[str, Any]
    item_info: Mapping[str, Any] | None = None
    serial_no: str | None = None
    user_process_ids: set[int] | frozenset[int] | None = None
    preferred_process_ids: set[int] | frozenset[int] | None = None
    serial_backfill_available: bool = False
    serial_report_states: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]] | None = None


@dataclass(frozen=True)
class ReportingContext:
    order_quantity: int
    mode: str
    effective_previous_limit: bool
    serial_mode: bool
    item_process_id: int | None
    user_process_ids: frozenset[int] | None
    preferred_scope_supplied: bool
    preferred_process_ids: frozenset[int]
    serial_backfill_available: bool
    serial_states: tuple[tuple[int, str], ...]

    @classmethod
    def from_request(cls, request):
        serial_states = {}
        if request.serial_no or request.item_info:
            for row in request.serial_report_states or ():
                serial_states.setdefault(int(row["process_id"]), row["status"])
        return cls(
            order_quantity=int(request.order_data.get("quantity") or 0),
            mode=request.policy["mode"],
            effective_previous_limit=bool(
                request.policy["effective_previous_limit"]
            ),
            serial_mode=bool(request.serial_no or request.item_info),
            item_process_id=(
                request.item_info.get("current_process_id")
                if request.item_info
                else None
            ),
            user_process_ids=(
                None
                if request.user_process_ids is None
                else frozenset(request.user_process_ids)
            ),
            preferred_scope_supplied=request.preferred_process_ids is not None,
            preferred_process_ids=frozenset(request.preferred_process_ids or ()),
            serial_backfill_available=bool(request.serial_backfill_available),
            serial_states=tuple(serial_states.items()),
        )

    def serial_status(self, process_id):
        states = dict(self.serial_states)
        return states.get(int(process_id or 0), "unreported")


@dataclass(frozen=True)
class EligibilityResult:
    processes: tuple[dict[str, Any], ...]
    reportable: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class BackfillSelection:
    candidates: tuple[dict[str, Any], ...]
    source: str
    message_key: str


@dataclass(frozen=True)
class ProcessSelection:
    selected: dict[str, Any] | None
    pool: tuple[dict[str, Any], ...]
    source: str
    position_match: bool | None
    position_candidates: tuple[dict[str, Any], ...]
    message_key: str


@dataclass(frozen=True)
class ProcessReportingResult:
    processes: tuple[dict[str, Any], ...]
    current_process: dict[str, Any] | None
    context: ReportingContext
    backfill: BackfillSelection
    selection: ProcessSelection

    def attach_to(self, order_data):
        order_data["processes"] = [dict(process) for process in self.processes]
        order_data["current_process"] = self.current_process
        order_data["process_order_mode"] = self.context.mode
        order_data["process_order_scope"] = (
            "serial_sequential" if self.context.serial_mode else "order"
        )
        order_data["serial_backfill_available"] = bool(
            self.context.serial_mode and self.context.serial_backfill_available
        )
        order_data["serial_backfill_selection_source"] = self.backfill.source
        order_data["serial_backfill_candidate_count"] = len(
            self.backfill.candidates
        )
        order_data["serial_backfill_message"] = ""
        order_data["limit_by_prev_process_effective"] = (
            self.context.effective_previous_limit
        )
        order_data["requires_process_selection"] = bool(
            not self.context.serial_mode and len(self.selection.pool) > 1
        )
        order_data["process_selection_source"] = self.selection.source
        order_data["position_process_match"] = self.selection.position_match
        order_data["position_candidate_count"] = len(
            self.selection.position_candidates
        )
        order_data["process_selection_message"] = ""
        return order_data
