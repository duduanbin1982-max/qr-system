"""Pure inventory source allocation rules.

This module deliberately has no database or Flask imports.  It receives a
stable candidate snapshot and returns immutable allocation items.
"""
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class InventoryCandidate:
    inventory_id: int
    order_id: int | None
    order_no: str
    available_quantity: Decimal
    received_at: str
    lot_no: str
    serial_no: str
    location: str
    compatibility_key: str
    manual_rank: int | None = None


@dataclass(frozen=True)
class AllocationItem:
    inventory_id: int
    order_id: int | None
    order_no: str
    lot_no: str
    serial_no: str
    location: str
    quantity: Decimal


@dataclass(frozen=True)
class AllocationResult:
    requested_quantity: Decimal
    available_quantity: Decimal
    items: tuple[AllocationItem, ...]


class AllocationShortage(ValueError):
    def __init__(self, requested, available):
        self.requested = requested
        self.available = available
        self.shortage = requested - available
        super().__init__(f"可用库存不足，缺少 {self.shortage}")


def allocate_inventory_sources(candidates, quantity, *, mode="fifo", compatibility_key="", selected_inventory_ids=()):
    requested = Decimal(str(quantity))
    if requested <= 0:
        raise ValueError("申请数量必须大于零")
    if mode not in {"fifo", "manual"}:
        raise ValueError("分配模式必须为 fifo 或 manual")
    selected = {int(item) for item in selected_inventory_ids}
    eligible = [
        item for item in candidates
        if item.compatibility_key == compatibility_key
        and item.available_quantity > 0
        and (mode != "manual" or item.inventory_id in selected)
    ]
    if mode == "manual" and not selected:
        raise ValueError("人工分配必须选择库存来源")
    if mode == "fifo":
        eligible.sort(key=lambda item: (item.received_at, item.lot_no, item.location, item.inventory_id, item.serial_no))
    else:
        eligible.sort(key=lambda item: (item.manual_rank if item.manual_rank is not None else 10**9, item.inventory_id))
    available = sum((item.available_quantity for item in eligible), Decimal("0"))
    if available < requested:
        raise AllocationShortage(requested, available)
    remaining = requested
    result = []
    for candidate in eligible:
        if remaining <= 0:
            break
        allocated = min(candidate.available_quantity, remaining)
        result.append(AllocationItem(candidate.inventory_id, candidate.order_id, candidate.order_no, candidate.lot_no, candidate.serial_no, candidate.location, allocated))
        remaining -= allocated
    return AllocationResult(requested, available, tuple(result))
