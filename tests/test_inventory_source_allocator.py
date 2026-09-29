from decimal import Decimal

import pytest

from modules.domain.inventory_allocation import AllocationShortage, InventoryCandidate, allocate_inventory_sources


def candidate(inventory_id, quantity, received_at, *, order_id=None, lot_no="", manual_rank=None, key="group-a"):
    return InventoryCandidate(inventory_id, order_id, f"O-{order_id or 0}", Decimal(str(quantity)), received_at, lot_no, "", "A-01", key, manual_rank)


def test_fifo_uses_oldest_candidates_and_preserves_quantity():
    result = allocate_inventory_sources([candidate(2, 4, "2026-09-02"), candidate(1, 3, "2026-09-01")], Decimal("5"), compatibility_key="group-a")
    assert [(item.inventory_id, item.quantity) for item in result.items] == [(1, Decimal("3")), (2, Decimal("2"))]
    assert sum(item.quantity for item in result.items) == Decimal("5")


def test_manual_mode_respects_selected_source():
    result = allocate_inventory_sources([candidate(1, 4, "2026-09-01", order_id=10, manual_rank=2), candidate(2, 4, "2026-09-02", order_id=11, manual_rank=1)], Decimal("3"), mode="manual", compatibility_key="group-a", selected_inventory_ids=(2,))
    assert [(item.inventory_id, item.quantity) for item in result.items] == [(2, Decimal("3"))]


def test_shortage_is_explicit_and_never_returns_partial_success():
    with pytest.raises(AllocationShortage) as exc:
        allocate_inventory_sources([candidate(1, 2, "2026-09-01")], Decimal("5"), compatibility_key="group-a")
    assert exc.value.available == Decimal("2")
    assert exc.value.shortage == Decimal("3")
