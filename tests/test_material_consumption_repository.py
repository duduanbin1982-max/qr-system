import pytest

from factories import (
    TEST_USER,
    add_order_material,
    add_product_bom,
    create_material,
    create_order,
    ensure_process,
    ensure_product,
)
from modules.db import get_db
from modules.domain.errors import ConflictError
from modules.process_fact_projection import capture_process_fact_binding
from modules.services.material_service import MaterialService
from modules.services.order_material_state_service import OrderMaterialStateService


@pytest.fixture
def deduction_case(client):
    with client.application.app_context():
        db = get_db()
        process_id = ensure_process(db, name="Material deduction process")
        other_process_id = ensure_process(db, name="Other material process")
        product_id = ensure_product(db, product_code="MATERIAL-DEDUCTION-PRODUCT")
        order_id = create_order(
            db,
            [process_id],
            quantity=10,
            product_code="MATERIAL-DEDUCTION-PRODUCT",
        )
        db.execute("UPDATE orders SET product_id=? WHERE id=?", (product_id, order_id))
        steel_id = create_material(db, quantity=20, name="Deduction Steel")
        wire_id = create_material(db, quantity=20, name="Deduction Wire")
        db.execute("UPDATE materials SET unit='kg' WHERE id=?", (steel_id,))
        db.execute("UPDATE materials SET unit='m' WHERE id=?", (wire_id,))
        actor = dict(
            db.execute(
                "SELECT id,name FROM users WHERE username=?", (TEST_USER,)
            ).fetchone()
        )
        db.execute(
            "INSERT OR REPLACE INTO system_settings(key,value) "
            "VALUES ('auto_deduct_material','1')"
        )
        db.commit()
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        db.execute("BEGIN IMMEDIATE")
        try:
            yield {
                "db": db,
                "order_id": order_id,
                "product_id": product_id,
                "process_id": process_id,
                "other_process_id": other_process_id,
                "steel_id": steel_id,
                "wire_id": wire_id,
                "actor": actor,
            }
        finally:
            db.rollback()


def _snapshot(case, *rows):
    for material_id, quantity_per_unit in rows:
        add_order_material(
            case["db"],
            case["order_id"],
            material_id,
            case["process_id"],
            quantity_per_unit,
        )
    OrderMaterialStateService.mark_initialized(
        case["order_id"], case["product_id"], len(rows), case["db"]
    )


def _deduct(case, quantity=3, *, work_record_id=None):
    return MaterialService.deduct_for_process(
        case["order_id"],
        case["process_id"],
        quantity,
        case["actor"]["id"],
        case["actor"]["name"],
        db=case["db"],
        work_record_id=work_record_id,
    )


def _evidence(case):
    db = case["db"]
    return {
        "balances": [
            tuple(row)
            for row in db.execute("SELECT id,quantity FROM materials ORDER BY id")
        ],
        **{
            table: [
                dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY id")
            ]
            for table in ("material_consumptions", "material_logs", "audit_logs")
        },
    }


def _work_record(case, quantity):
    db = case["db"]
    binding = capture_process_fact_binding(
        db, order_id=case["order_id"], process_id=case["process_id"]
    )
    values = {
        "order_id": case["order_id"],
        "user_id": case["actor"]["id"],
        "type": "normal",
        "status": "approved",
        "quantity": quantity,
        **binding,
    }
    columns = ",".join(values)
    placeholders = ",".join("?" for _ in values)
    return db.execute(
        f"INSERT INTO work_records({columns}) VALUES ({placeholders})",
        tuple(values.values()),
    ).lastrowid


def test_deduct_for_process_prefers_order_material_snapshot(deduction_case):
    case = deduction_case
    db = case["db"]
    _snapshot(case, (case["steel_id"], 2))
    add_product_bom(
        db, case["product_id"], case["wire_id"], case["process_id"], 5
    )

    _deduct(case)

    assert db.execute(
        "SELECT quantity FROM materials WHERE id=?", (case["steel_id"],)
    ).fetchone()[0] == 14
    assert db.execute(
        "SELECT quantity FROM materials WHERE id=?", (case["wire_id"],)
    ).fetchone()[0] == 20
    consumption = db.execute(
        "SELECT material_id,order_id,process_id,quantity,operator_id,operator_name,"
        "notes,source_work_record_id,status,process_version_id "
        "FROM material_consumptions"
    ).fetchone()
    process_version_id = db.execute(
        "SELECT process_version_id FROM order_processes "
        "WHERE order_id=? AND process_id=?",
        (case["order_id"], case["process_id"]),
    ).fetchone()[0]
    assert dict(consumption) == {
        "material_id": case["steel_id"],
        "order_id": case["order_id"],
        "process_id": case["process_id"],
        "quantity": 6.0,
        "operator_id": case["actor"]["id"],
        "operator_name": case["actor"]["name"],
        "notes": "auto-deduct from order BOM",
        "source_work_record_id": None,
        "status": "active",
        "process_version_id": process_version_id,
    }
    consumption_id = db.execute("SELECT id FROM material_consumptions").fetchone()[0]
    log = db.execute(
        "SELECT type,quantity,balance_before,balance_after,source_type,source_id "
        "FROM material_logs"
    ).fetchone()
    assert dict(log) == {
        "type": "out",
        "quantity": 6.0,
        "balance_before": 20.0,
        "balance_after": 14.0,
        "source_type": "auto_consumption",
        "source_id": consumption_id,
    }
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_deduct_for_process_rejects_unknown_snapshot_without_live_bom_fallback(
    deduction_case,
):
    case = deduction_case
    db = case["db"]
    db.execute(
        "UPDATE orders SET product_code='MATERIAL-HISTORIC-CODE' WHERE id=?",
        (case["order_id"],),
    )
    add_product_bom(db, case["product_id"], case["steel_id"], None, 1.5)
    add_product_bom(
        db, case["product_id"], case["wire_id"], case["other_process_id"], 2
    )
    before = _evidence(case)

    with pytest.raises(ConflictError, match="禁止回退实时产品配方") as error:
        _deduct(case, 2)

    assert error.value.details == {
        "code": "MATERIAL_SNAPSHOT_UNKNOWN",
        "order_id": case["order_id"],
    }
    assert _evidence(case) == before


def test_deduct_for_process_is_disabled_by_setting_even_with_order_snapshot(
    deduction_case,
):
    case = deduction_case
    _snapshot(case, (case["steel_id"], 2))
    case["db"].execute(
        "UPDATE system_settings SET value='0' WHERE key='auto_deduct_material'"
    )
    before = _evidence(case)

    assert _deduct(case) == []

    assert _evidence(case) == before


def test_deduct_for_process_blocks_all_materials_when_any_stock_is_short(
    deduction_case,
):
    case = deduction_case
    case["db"].execute(
        "UPDATE materials SET quantity=2 WHERE id=?", (case["wire_id"],)
    )
    _snapshot(case, (case["steel_id"], 2), (case["wire_id"], 1))
    before = _evidence(case)

    with pytest.raises(ConflictError, match="物料库存不足，报工未提交") as error:
        _deduct(case)

    assert error.value.details == {
        "shortages": [
            {
                "material_id": case["wire_id"],
                "material_name": "Deduction Wire",
                "unit": "m",
                "required_quantity": 3.0,
                "available_quantity": 2.0,
            }
        ]
    }
    assert _evidence(case) == before


def test_deduct_for_process_rejects_duplicate_work_record_source(deduction_case):
    case = deduction_case
    db = case["db"]
    db.execute(
        "UPDATE materials SET quantity=10 WHERE id=?", (case["steel_id"],)
    )
    _snapshot(case, (case["steel_id"], 2))
    work_record_id = _work_record(case, 2)

    _deduct(case, 2, work_record_id=work_record_id)
    consumption_id = db.execute("SELECT id FROM material_consumptions").fetchone()[0]
    before = _evidence(case)

    with pytest.raises(ConflictError, match="物料已经扣减") as error:
        _deduct(case, 2, work_record_id=work_record_id)

    assert error.value.details == {
        "work_record_id": work_record_id,
        "consumption_ids": [consumption_id],
    }
    assert db.execute(
        "SELECT source_work_record_id FROM material_consumptions"
    ).fetchone()[0] == work_record_id
    assert db.execute(
        "SELECT quantity FROM materials WHERE id=?", (case["steel_id"],)
    ).fetchone()[0] == 6
    assert db.execute(
        "SELECT quantity FROM materials WHERE id=?", (case["wire_id"],)
    ).fetchone()[0] == 20
    assert db.execute("SELECT COUNT(*) FROM material_consumptions").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM material_logs").fetchone()[0] == 1
    assert _evidence(case) == before
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
