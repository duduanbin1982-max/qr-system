"""Real-schema evidence survives archives and rejects ambiguous stock deductions."""

import json
import math
import shutil
import sqlite3
from decimal import Decimal

import pytest

from conftest import TEST_TEMPLATE_DB
from factories import add_order_material, add_product_bom, create_material, ensure_product
from modules.audit_writer import AuditWriter
from modules.domain.errors import ConflictError, ValidationError
from modules.process_fact_projection import capture_process_fact_binding
from modules.repositories.audit_log_repository import AuditLogRepository
from modules.repositories.material_repository import MaterialRepository
from modules.services.order_material_snapshot_service import OrderMaterialSnapshotService
from modules.services.order_material_state_service import OrderMaterialStateService as State


@pytest.fixture
def state_db(tmp_path):
    path = tmp_path / "material-state.db"
    shutil.copy2(TEST_TEMPLATE_DB, path)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    order_id = db.execute(
        "INSERT INTO orders(order_no,quantity) VALUES ('MATERIAL-STATE-1',10)"
    ).lastrowid
    material_id = create_material(db, quantity=100)
    db.commit()
    db.execute("BEGIN IMMEDIATE")
    try:
        yield db, order_id, material_id
    finally:
        db.rollback()
        db.close()


def _rows(db, order_id):
    return [dict(row) for row in db.execute(
        "SELECT material_id,process_id,quantity_per_unit FROM order_materials "
        "WHERE order_id=? AND process_id IS NULL", (order_id,)
    )]


def _recipe(state_db, quantity_per_unit=2, *, initialized=True):
    db, order_id, material_id = state_db
    add_order_material(db, order_id, material_id, None, quantity_per_unit)
    if initialized:
        State.mark_initialized(order_id, None, 1, db)
    return _rows(db, order_id)


def _allocate(db, order_id, material_id, quantity, *, source=State.COMMON_SOURCE):
    consumption_id = MaterialRepository.insert_consumption(
        material_id, order_id, None, quantity, None, "state test", "state test", db=db
    )
    transition = MaterialRepository.apply_quantity_delta(material_id, -quantity, db=db)
    log_id = MaterialRepository.insert_log(
        material_id, "out", quantity, "state test", "state test",
        balance_before=transition["balance_before"],
        balance_after=transition["balance_after"], source_type=source,
        source_id=consumption_id, db=db,
    )
    return {
        "material_id": material_id, "quantity": quantity,
        "consumption_id": consumption_id, "log_id": log_id,
    }


def _freeze(state_db, work_record_id=101):
    db, order_id, _ = state_db
    rows = _recipe(state_db)
    basis = State.prepare_common_basis(order_id, rows, work_record_id, db)
    allocations = [
        _allocate(
            db, order_id, row["material_id"],
            float(Decimal(basis["order_quantity"]) * Decimal(row["quantity_per_unit"])),
        )
        for row in basis["common_rows"]
    ]
    State.record_common_basis(order_id, basis, allocations, None, db)
    return rows, allocations


def _event(db, action, order_id):
    return dict(db.execute(
        "SELECT * FROM audit_logs WHERE event_id=?",
        (f"{action}:v1:{order_id}",),
    ).fetchone())


def _archive(db, envelope, *, batch="batch-1", delete_live=False):
    db.execute(
        "INSERT INTO audit_log_archive(archive_batch_id,source_id,event_id,payload) "
        "VALUES (?,?,?,?)",
        (batch, envelope["id"], envelope["event_id"], json.dumps(envelope)),
    )
    if delete_live:
        db.execute("DELETE FROM audit_logs WHERE id=?", (envelope["id"],))


def _assert_code(code, operation):
    with pytest.raises(ConflictError) as error:
        operation()
    assert error.value.details["code"] == code


@pytest.mark.parametrize("with_product", [False, True])
def test_empty_snapshot_initialization_is_explicit_even_without_product(state_db, with_product):
    db, order_id, _ = state_db
    product_id = ensure_product(db) if with_product else None
    assert OrderMaterialSnapshotService.copy_product_bom(order_id, product_id, db) == 0
    State.assert_snapshot_known(order_id, [], db)
    detail = json.loads(_event(db, State.SNAPSHOT_ACTION, order_id)["detail"])
    assert detail["row_count"] == 0
    assert detail["product_id"] == product_id
    assert _event(db, State.SNAPSHOT_ACTION, order_id)["mandatory"] == 1


def test_empty_unmarked_legacy_is_unknown_but_nonempty_legacy_can_be_read(state_db):
    db, order_id, _ = state_db
    _assert_code(
        "MATERIAL_SNAPSHOT_UNKNOWN",
        lambda: State.assert_snapshot_known(order_id, [], db),
    )
    rows = _recipe(state_db, initialized=False)
    State.assert_snapshot_known(order_id, rows, db)
    assert State.prepare_common_basis(order_id, rows, 101, db)["order_quantity"] == "10"


def test_snapshot_bom_is_copied_once_and_validated_before_snapshot_is_marked(state_db):
    db, order_id, material_id = state_db
    product_id = ensure_product(db)
    add_product_bom(db, product_id, material_id, quantity_per_unit=1.5)
    assert OrderMaterialSnapshotService.copy_product_bom(order_id, product_id, db) == 1
    assert _rows(db, order_id)[0]["quantity_per_unit"] == 1.5
    _assert_code(
        "MATERIAL_SNAPSHOT_ALREADY_INITIALIZED",
        lambda: OrderMaterialSnapshotService.copy_product_bom(order_id, product_id, db),
    )


@pytest.mark.parametrize("invalid", [-1, "bad", 0])
def test_invalid_historical_bom_cannot_create_snapshot_completion(state_db, invalid):
    db, order_id, material_id = state_db
    product_id = ensure_product(db)
    # Model a legacy row imported before the quantity CHECK was introduced.
    db.execute("PRAGMA ignore_check_constraints=ON")
    add_product_bom(db, product_id, material_id, quantity_per_unit=invalid)
    db.execute("PRAGMA ignore_check_constraints=OFF")
    with pytest.raises(ValidationError):
        OrderMaterialSnapshotService.copy_product_bom(order_id, product_id, db)
    assert db.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE action=?", (State.SNAPSHOT_ACTION,)
    ).fetchone()[0] == 0


def test_snapshot_completion_is_not_a_permanent_recipe_digest(state_db):
    db, order_id, material_id = state_db
    _recipe(state_db)
    db.execute(
        "UPDATE order_materials SET quantity_per_unit=3 WHERE order_id=?", (order_id,)
    )
    assert State.prepare_common_basis(order_id, _rows(db, order_id), 101, db)["common_rows"] == [
        {"material_id": material_id, "scope": "order", "quantity_per_unit": "3"}
    ]
    db.execute("DELETE FROM order_materials WHERE order_id=?", (order_id,))
    State.mark_initialized(order_id, None, 0, db)
    State.assert_snapshot_known(order_id, [], db)


def test_order_common_basis_skips_other_reports_and_rejects_same_report(state_db):
    db, order_id, material_id = state_db
    rows, allocations = _freeze(state_db)
    assert State.prepare_common_basis(order_id, rows, 102, db) is None
    _assert_code(
        "COMMON_CONSUMPTION_ALREADY_RECORDED",
        lambda: State.prepare_common_basis(order_id, rows, 101, db),
    )
    assert db.execute(
        "SELECT quantity FROM materials WHERE id=?", (material_id,)
    ).fetchone()[0] == 80
    consumption = db.execute(
        "SELECT * FROM material_consumptions WHERE id=?", (allocations[0]["consumption_id"],)
    ).fetchone()
    assert consumption["process_id"] is None
    assert consumption["source_work_record_id"] is None


def test_empty_common_basis_is_frozen_and_later_quantity_or_recipe_changes_are_blocked(state_db):
    db, order_id, material_id = state_db
    State.mark_initialized(order_id, None, 0, db)
    basis = State.prepare_common_basis(order_id, [], 101, db)
    State.record_common_basis(order_id, basis, [], None, db)
    assert State.prepare_common_basis(order_id, [], 102, db) is None
    _assert_code("STALE_INPUT", lambda: State.assert_common_mutable(order_id, db))
    add_order_material(db, order_id, material_id, None, 1)
    _assert_code(
        "STALE_INPUT",
        lambda: State.prepare_common_basis(order_id, _rows(db, order_id), 102, db),
    )


@pytest.mark.parametrize("change", ["quantity", "recipe", "same_product", "delete_last"])
def test_frozen_basis_detects_whole_order_drift_even_if_total_requirement_stays_same(
    state_db, change,
):
    db, order_id, _ = state_db
    _freeze(state_db)
    if change in ("quantity", "same_product"):
        db.execute("UPDATE orders SET quantity=20 WHERE id=?", (order_id,))
    if change in ("recipe", "same_product"):
        per_unit = 1 if change == "same_product" else 3
        db.execute(
            "UPDATE order_materials SET quantity_per_unit=? WHERE order_id=?",
            (per_unit, order_id),
        )
    if change == "delete_last":
        db.execute("DELETE FROM order_materials WHERE order_id=?", (order_id,))
    _assert_code(
        "STALE_INPUT",
        lambda: State.prepare_common_basis(order_id, _rows(db, order_id), 102, db),
    )


def test_reversal_remains_visible_and_never_causes_automatic_rededuction(state_db):
    db, order_id, _ = state_db
    rows, allocations = _freeze(state_db)
    db.execute(
        "UPDATE material_consumptions SET status='reversed' WHERE id=?",
        (allocations[0]["consumption_id"],),
    )
    _assert_code(
        "COMMON_CONSUMPTION_REVERSED",
        lambda: State.prepare_common_basis(order_id, rows, 102, db),
    )


@pytest.mark.parametrize("damage", ["duplicate", "missing_log", "wrong_scope", "missing_consumption"])
def test_common_basis_checks_all_consumptions_and_original_ledger_links(state_db, damage):
    db, order_id, material_id = state_db
    rows, allocations = _freeze(state_db)
    allocation = allocations[0]
    if damage == "duplicate":
        _allocate(db, order_id, material_id, 20)
    elif damage == "missing_log":
        db.execute("DELETE FROM material_logs WHERE id=?", (allocation["log_id"],))
    elif damage == "missing_consumption":
        db.execute(
            "DELETE FROM material_consumptions WHERE id=?", (allocation["consumption_id"],)
        )
    else:
        process_id = db.execute("SELECT id FROM processes LIMIT 1").fetchone()[0]
        db.execute(
            "UPDATE material_consumptions SET process_id=? WHERE id=?",
            (process_id, allocation["consumption_id"]),
        )
    _assert_code(
        "MATERIAL_STATE_INVALID", lambda: State.prepare_common_basis(order_id, rows, 102, db)
    )


def test_old_auto_consumption_is_ambiguous_and_manual_consumption_is_not_common(state_db):
    db, order_id, material_id = state_db
    rows = _recipe(state_db, initialized=False)
    manual = _allocate(db, order_id, material_id, 1, source="consumption")
    assert State.prepare_common_basis(order_id, rows, 101, db) is not None
    db.execute(
        "UPDATE material_logs SET source_type='auto_consumption' WHERE id=?",
        (manual["log_id"],),
    )
    _assert_code(
        "LEGACY_AMBIGUOUS", lambda: State.prepare_common_basis(order_id, rows, 101, db)
    )


def test_prior_approved_report_without_basis_is_ambiguous_even_if_no_consumption_exists(state_db):
    db, order_id, _ = state_db
    rows = _recipe(state_db, initialized=False)
    user_id = db.execute(
        "INSERT INTO users(username,password,name) VALUES ('state-worker','unused','Worker')"
    ).lastrowid
    process_id = db.execute(
        "SELECT id FROM processes WHERE current_effective_version_id IS NOT NULL LIMIT 1"
    ).fetchone()[0]
    binding = capture_process_fact_binding(db, process_id=process_id)
    values = {
        "order_id": order_id, "process_id": process_id, "user_id": user_id,
        "type": "normal", "status": "approved", "quantity": 1,
        **{key: value for key, value in binding.items() if key != "process_id"},
    }
    columns = ",".join(values)
    placeholders = ",".join("?" for _ in values)
    report_id = db.execute(
        f"INSERT INTO work_records({columns}) VALUES ({placeholders})", tuple(values.values())
    ).lastrowid
    # The current first report is excluded; a previous report cannot be inferred unconsumed.
    assert State.prepare_common_basis(order_id, rows, report_id, db) is not None
    _assert_code(
        "LEGACY_AMBIGUOUS",
        lambda: State.prepare_common_basis(order_id, rows, report_id + 1, db),
    )


def test_real_audit_cleanup_preserves_snapshot_and_common_basis_readability(state_db):
    db, order_id, _ = state_db
    rows, _ = _freeze(state_db)
    request_id = db.execute(
        "INSERT INTO audit_log_cleanup_requests(before_at,reason,requested_by) "
        "VALUES ('9999-01-01','state archival test',1000)"
    ).lastrowid
    result = AuditLogRepository.execute_cleanup_request_txn(
        request_id, 1004, "independently approved", db
    )
    assert result["archived"] >= 2
    assert db.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE target_type='order' AND target_id=?",
        (order_id,),
    ).fetchone()[0] == 0
    State.assert_snapshot_known(order_id, rows, db)
    assert State.prepare_common_basis(order_id, rows, 102, db) is None
    State.mark_initialized(order_id, None, 1, db)
    assert db.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE action=?", (State.SNAPSHOT_ACTION,)
    ).fetchone()[0] == 0


def test_identical_archived_duplicates_are_accepted_alongside_live_event(state_db):
    db, order_id, _ = state_db
    rows, _ = _freeze(state_db)
    for action in (State.SNAPSHOT_ACTION, State.COMMON_ACTION):
        envelope = _event(db, action, order_id)
        _archive(db, envelope, batch=f"{action}-one")
        _archive(db, envelope, batch=f"{action}-two")
    assert State.prepare_common_basis(order_id, rows, 102, db) is None


@pytest.mark.parametrize("damage", ["invalid_json", "wrong_target", "wrong_digest", "conflict"])
def test_corrupt_or_conflicting_archive_fails_closed(state_db, damage):
    db, order_id, _ = state_db
    rows, _ = _freeze(state_db)
    envelope = _event(db, State.COMMON_ACTION, order_id)
    if damage == "invalid_json":
        envelope["detail"] = "{"
    elif damage == "wrong_target":
        envelope["target_id"] = order_id + 1
    elif damage == "wrong_digest":
        detail = json.loads(envelope["detail"])
        detail["order_quantity"] = "99"
        envelope["detail"] = json.dumps(detail)
    else:
        envelope["user_id"] = 999
    _archive(db, envelope)
    _assert_code(
        "MATERIAL_STATE_INVALID", lambda: State.prepare_common_basis(order_id, rows, 102, db)
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("order_id", True),
        ("common_rows", [None]),
        ("common_rows", {"material_id": 1}),
        ("allocations", [None]),
        ("allocations", [["material_id", []]]),
    ],
)
def test_malformed_sealed_archived_payload_returns_structured_conflict(state_db, field, value):
    db, order_id, _ = state_db
    rows, _ = _freeze(state_db)
    envelope = _event(db, State.COMMON_ACTION, order_id)
    payload = json.loads(envelope["detail"])
    payload[field] = value
    envelope["detail"] = json.dumps(State._seal(payload))
    _archive(db, envelope, delete_live=True)
    _assert_code(
        "MATERIAL_STATE_INVALID", lambda: State.prepare_common_basis(order_id, rows, 102, db)
    )


def test_malformed_basis_is_rejected_before_attempting_to_expand_recipe_rows(state_db):
    db, order_id, _ = state_db
    rows = _recipe(state_db)
    basis = State.prepare_common_basis(order_id, rows, 101, db)
    basis["common_rows"] = [None]
    basis = State._seal(basis)
    _assert_code(
        "MATERIAL_STATE_INVALID",
        lambda: State.record_common_basis(order_id, basis, [], None, db),
    )


def test_missing_basis_with_common_ledger_never_recreates_a_new_basis(state_db):
    db, order_id, _ = state_db
    rows, _ = _freeze(state_db)
    db.execute("DELETE FROM audit_logs WHERE action=?", (State.COMMON_ACTION,))
    _assert_code(
        "MATERIAL_STATE_INVALID", lambda: State.prepare_common_basis(order_id, rows, 102, db)
    )


def test_floating_aggregation_does_not_make_unchanged_recipe_stale(state_db):
    db, order_id, material_id = state_db
    add_order_material(db, order_id, material_id, None, 0.1)
    add_order_material(db, order_id, material_id, None, 0.2)
    State.mark_initialized(order_id, None, 2, db)
    supplied = [{"material_id": material_id, "process_id": None, "quantity_per_unit": 0.1 + 0.2}]
    basis = State.prepare_common_basis(order_id, supplied, 101, db)
    allocation = _allocate(db, order_id, material_id, 10 * (0.1 + 0.2))
    State.record_common_basis(order_id, basis, [allocation], None, db)
    assert State.prepare_common_basis(order_id, supplied, 102, db) is None


@pytest.mark.parametrize("changed", [9e-13, 1e-30])
def test_tiny_consumption_quantity_drift_cannot_hide_behind_absolute_epsilon(state_db, changed):
    db, order_id, material_id = state_db
    db.execute("UPDATE orders SET quantity=1 WHERE id=?", (order_id,))
    db.execute("UPDATE materials SET quantity=1e-12 WHERE id=?", (material_id,))
    rows = _recipe(state_db, quantity_per_unit=1e-13)
    basis = State.prepare_common_basis(order_id, rows, 101, db)
    allocation = _allocate(db, order_id, material_id, 1e-13)
    State.record_common_basis(order_id, basis, [allocation], None, db)
    db.execute(
        "UPDATE material_consumptions SET quantity=? WHERE id=?",
        (changed, allocation["consumption_id"]),
    )
    _assert_code(
        "MATERIAL_STATE_INVALID",
        lambda: State.prepare_common_basis(order_id, rows, 102, db),
    )


def test_candidate_positive_decimal_that_underflows_storage_is_rejected(state_db):
    db, order_id, material_id = state_db
    _recipe(state_db)
    candidate = [{
        "material_id": material_id, "process_id": None, "quantity_per_unit": "1e-1000"
    }]
    _assert_code(
        "MATERIAL_STATE_INVALID",
        lambda: State.prepare_common_basis(order_id, candidate, 101, db),
    )


def test_zero_process_legacy_snapshot_is_explicitly_rejected(state_db):
    db, order_id, material_id = state_db
    db.commit()
    db.execute("PRAGMA foreign_keys=OFF")
    db.execute("BEGIN IMMEDIATE")
    add_order_material(db, order_id, material_id, 0, 2)
    State.mark_initialized(order_id, None, 1, db)
    _assert_code(
        "MATERIAL_STATE_INVALID",
        lambda: State.prepare_common_basis(order_id, [], 101, db),
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("balance_before", None),
        ("balance_before", -1),
        ("balance_before", float("inf")),
        ("balance_after", "invalid"),
        ("balance_after", -1),
        ("balance_after", float("nan")),
        ("balance_after", 79),
    ],
)
def test_common_original_log_requires_finite_nonnegative_conserved_balances(
    state_db, field, value,
):
    db, order_id, _ = state_db
    rows, allocations = _freeze(state_db)
    db.execute(
        f"UPDATE material_logs SET {field}=? WHERE id=?",
        (value, allocations[0]["log_id"]),
    )
    _assert_code(
        "MATERIAL_STATE_INVALID",
        lambda: State.prepare_common_basis(order_id, rows, 102, db),
    )


def test_tiny_common_original_log_balance_drift_is_detected(state_db):
    db, order_id, material_id = state_db
    db.execute("UPDATE orders SET quantity=1 WHERE id=?", (order_id,))
    db.execute("UPDATE materials SET quantity=1e-12 WHERE id=?", (material_id,))
    rows = _recipe(state_db, quantity_per_unit=1e-13)
    basis = State.prepare_common_basis(order_id, rows, 101, db)
    allocation = _allocate(db, order_id, material_id, 1e-13)
    State.record_common_basis(order_id, basis, [allocation], None, db)
    db.execute(
        "UPDATE material_logs SET balance_after=8e-13 WHERE id=?", (allocation["log_id"],)
    )
    _assert_code(
        "MATERIAL_STATE_INVALID",
        lambda: State.prepare_common_basis(order_id, rows, 102, db),
    )


def test_original_log_balance_accepts_one_representable_rounding_step(state_db):
    db, order_id, _ = state_db
    rows, allocations = _freeze(state_db)
    db.execute(
        "UPDATE material_logs SET balance_after=? WHERE id=?",
        (math.nextafter(80, math.inf), allocations[0]["log_id"]),
    )
    assert State.prepare_common_basis(order_id, rows, 102, db) is None


@pytest.mark.parametrize("failure_action", [State.SNAPSHOT_ACTION, State.COMMON_ACTION])
def test_required_evidence_failure_rolls_back_snapshot_or_deduction_atomically(
    state_db, monkeypatch, failure_action,
):
    db, order_id, material_id = state_db
    db.commit()
    write = AuditWriter.required

    def fail(command, *, db, **kwargs):
        if command.action == failure_action:
            raise RuntimeError("evidence persistence failed")
        return write(command, db=db, **kwargs)

    monkeypatch.setattr(AuditWriter, "required", fail)
    with pytest.raises(RuntimeError, match="订单物料状态审计写入失败"):
        with db:
            db.execute("BEGIN IMMEDIATE")
            if failure_action == State.SNAPSHOT_ACTION:
                product_id = ensure_product(db)
                add_product_bom(db, product_id, material_id, quantity_per_unit=2)
                OrderMaterialSnapshotService.copy_product_bom(order_id, product_id, db)
            else:
                _freeze(state_db)
    assert db.execute(
        "SELECT COUNT(*) FROM order_materials WHERE order_id=?", (order_id,)
    ).fetchone()[0] == 0
    assert db.execute(
        "SELECT COUNT(*) FROM material_consumptions WHERE order_id=?", (order_id,)
    ).fetchone()[0] == 0
    assert db.execute(
        "SELECT quantity FROM materials WHERE id=?", (material_id,)
    ).fetchone()[0] == 100


def test_state_operations_require_existing_transaction(state_db):
    db, order_id, _ = state_db
    db.commit()
    with pytest.raises(ValueError, match="caller's transaction"):
        State.mark_initialized(order_id, None, 0, db)
