"""Exercise order-scoped material deductions through the real report endpoint."""

import json
import sqlite3
import uuid

import pytest

from factories import (
    add_order_material,
    add_product_bom,
    create_material,
    create_order,
    ensure_process,
    ensure_product,
    ensure_user,
    WORKER_HASH,
    WORKER_PASS,
)
from modules.db import get_db
from modules.repositories.audit_log_repository import AuditLogRepository
from modules.services.order_material_state_service import OrderMaterialStateService as State


@pytest.fixture
def second_worker_headers(client):
    with client.application.app_context():
        ensure_user(
            get_db(), "material-second-worker", WORKER_HASH, "Second Worker",
            "worker", "MATERIAL-WORKER-002", "worker-group",
        )
    response = client.post(
        "/api/auth/login",
        json={"username": "material-second-worker", "password": WORKER_PASS},
    )
    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    token = payload.get("user", payload)["token"]
    return {"Authorization": f"Bearer {token}"}


def _setup(client, *, common=2, dedicated=1, stock=100, initialized=False):
    suffix = uuid.uuid4().hex[:8]
    with client.application.app_context():
        db = get_db()
        processes = [
            ensure_process(db, name=f"Common Material {suffix} {index}")
            for index in range(2)
        ]
        product_id = ensure_product(db, product_code=f"MATERIAL-{suffix}")
        order_id = create_order(
            db, processes, quantity=5, product_code=f"MATERIAL-{suffix}",
        )
        db.execute("UPDATE orders SET status='producing' WHERE id=?", (order_id,))
        material_id = create_material(db, quantity=stock)
        if common:
            add_order_material(db, order_id, material_id, None, common)
        if dedicated:
            for process_id in processes:
                add_order_material(db, order_id, material_id, process_id, dedicated)
        if initialized:
            State.mark_initialized(
                order_id, product_id, (1 if common else 0) + (2 if dedicated else 0), db,
            )
        db.execute(
            "INSERT OR REPLACE INTO system_settings(key,value) "
            "VALUES ('auto_deduct_material','1')"
        )
        # This fixture has no inspection plan execution between reporting batches.
        # Keep material integration independent of automatic quality task creation.
        db.execute(
            "INSERT OR REPLACE INTO system_settings(key,value) VALUES (?,?)",
            ("quality_management_rules", json.dumps({
                "auto_first_article": False, "auto_final_inspection": False,
            })),
        )
        db.commit()
    return order_id, processes, material_id, product_id


def _report(client, headers, order_id, process_id, quantity=1):
    return client.post(
        "/api/mobile/report",
        json={
            "order_id": order_id, "process_id": process_id,
            "quantity": quantity, "report_type": "normal",
        },
        headers=headers,
    )


def _facts(client, order_id, material_id):
    with client.application.app_context():
        db = get_db()
        result = {}
        for name, sql, args in [
            ("order", "SELECT * FROM orders WHERE id=?", (order_id,)),
            ("processes", "SELECT * FROM order_processes WHERE order_id=? ORDER BY id", (order_id,)),
            ("reports", "SELECT * FROM work_records WHERE order_id=? ORDER BY id", (order_id,)),
            ("material", "SELECT * FROM materials WHERE id=?", (material_id,)),
            ("consumptions", "SELECT * FROM material_consumptions WHERE order_id=? ORDER BY id", (order_id,)),
            ("logs", "SELECT * FROM material_logs WHERE material_id=? ORDER BY id", (material_id,)),
            ("evidence", "SELECT * FROM audit_logs WHERE target_type='order' AND target_id=? "
             "AND action LIKE 'material_order_%' ORDER BY id", (order_id,)),
        ]:
            result[name] = [dict(row) for row in db.execute(sql, args)]
        return result


def test_common_material_deducted_once_for_whole_order_across_batches_and_processes(
    client, worker_auth_headers, second_worker_headers,
):
    oid, processes, mid, _ = _setup(client)
    for process_id, quantity, headers in [
        (processes[0], 2, worker_auth_headers), (processes[0], 3, second_worker_headers),
        (processes[1], 2, worker_auth_headers), (processes[1], 3, second_worker_headers),
    ]:
        response = _report(client, headers, oid, process_id, quantity)
        assert response.status_code == 200, response.get_json()

    facts = _facts(client, oid, mid)
    assert facts["material"][0]["quantity"] == 80  # 5*2 common + 10*1 process
    common = [row for row in facts["consumptions"] if row["process_id"] is None]
    dedicated = [row for row in facts["consumptions"] if row["process_id"] is not None]
    assert len(common) == 1
    assert common[0]["quantity"] == 10
    assert common[0]["source_work_record_id"] is None
    assert len(dedicated) == 4
    assert {row["source_work_record_id"] for row in dedicated} == {
        row["id"] for row in facts["reports"]
    }
    assert [row["source_type"] for row in facts["logs"]].count(State.COMMON_SOURCE) == 1
    receipt = [row for row in facts["evidence"] if row["action"] == State.COMMON_ACTION]
    assert len(receipt) == 1
    payload = json.loads(receipt[0]["detail"])
    assert payload["order_quantity"] == "5"
    assert payload["allocations"][0]["consumption_id"] == common[0]["id"]
    assert payload["work_record_id"] == facts["reports"][0]["id"]


def test_same_material_common_and_process_demands_are_checked_together_before_writes(
    client, worker_auth_headers,
):
    oid, processes, mid, _ = _setup(client, stock=11)
    before = _facts(client, oid, mid)
    response = _report(client, worker_auth_headers, oid, processes[0], 2)
    assert response.status_code == 409, response.get_json()
    shortage = response.get_json()["details"]["shortages"]
    assert len(shortage) == 1
    assert shortage[0]["required_quantity"] == 12
    assert shortage[0]["available_quantity"] == 11
    assert _facts(client, oid, mid) == before


@pytest.mark.parametrize("after_insert", [False, True])
@pytest.mark.parametrize("storage_error", [sqlite3.OperationalError, sqlite3.IntegrityError])
def test_common_receipt_failure_rolls_back_report_stock_ledger_and_process_then_retry(
    client, worker_auth_headers, monkeypatch, after_insert, storage_error,
):
    oid, processes, mid, _ = _setup(client)
    before = _facts(client, oid, mid)
    original = AuditLogRepository.insert_command
    monkeypatch.setitem(client.application.config, "PROPAGATE_EXCEPTIONS", False)

    def fail_receipt(command, *, db):
        if command.action == State.COMMON_ACTION:
            assert db.in_transaction
            assert db.execute(
                "SELECT COUNT(*) FROM material_consumptions WHERE order_id=?", (oid,),
            ).fetchone()[0] == 2
            if after_insert:
                original(command, db=db)
            raise storage_error("private material evidence failure")
        return original(command, db=db)

    with monkeypatch.context() as scoped:
        scoped.setattr(AuditLogRepository, "insert_command", staticmethod(fail_receipt))
        response = _report(client, worker_auth_headers, oid, processes[0], 2)
    assert response.status_code == 500, response.get_json()
    assert "private material" not in response.get_data(as_text=True)
    assert _facts(client, oid, mid) == before
    retry = _report(client, worker_auth_headers, oid, processes[0], 2)
    assert retry.status_code == 200, retry.get_json()
    facts = _facts(client, oid, mid)
    assert facts["material"][0]["quantity"] == 88
    assert len(facts["reports"]) == 1
    assert len(facts["consumptions"]) == 2


@pytest.mark.parametrize("initialized", [False, True])
def test_empty_snapshot_uses_explicit_provenance_and_never_live_product_bom(
    client, worker_auth_headers, initialized,
):
    oid, processes, mid, pid = _setup(
        client, common=0, dedicated=0, initialized=initialized,
    )
    with client.application.app_context():
        db = get_db()
        add_product_bom(db, pid, mid, None, quantity_per_unit=999)
        db.commit()
    before = _facts(client, oid, mid)
    response = _report(client, worker_auth_headers, oid, processes[0], 1)
    if not initialized:
        assert response.status_code == 409, response.get_json()
        assert response.get_json()["details"]["code"] == "MATERIAL_SNAPSHOT_UNKNOWN"
        assert _facts(client, oid, mid) == before
    else:
        assert response.status_code == 200, response.get_json()
        facts = _facts(client, oid, mid)
        assert len(facts["reports"]) == 1
        assert facts["material"][0]["quantity"] == 100
        assert facts["consumptions"] == []
        assert facts["logs"] == []
        basis = next(row for row in facts["evidence"] if row["action"] == State.COMMON_ACTION)
        assert json.loads(basis["detail"])["common_rows"] == []


def test_existing_approved_legacy_report_prevents_guessed_common_backfill(
    client, worker_auth_headers, second_worker_headers,
):
    oid, processes, mid, _ = _setup(client)
    with client.application.app_context():
        db = get_db()
        db.execute("UPDATE system_settings SET value='0' WHERE key='auto_deduct_material'")
        db.commit()
    first = _report(client, worker_auth_headers, oid, processes[0], 1)
    assert first.status_code == 200, first.get_json()
    with client.application.app_context():
        db = get_db()
        db.execute("UPDATE system_settings SET value='1' WHERE key='auto_deduct_material'")
        db.commit()
    before = _facts(client, oid, mid)
    response = _report(client, second_worker_headers, oid, processes[0], 1)
    assert response.status_code == 409, response.get_json()
    assert response.get_json()["details"]["code"] == "LEGACY_AMBIGUOUS"
    assert _facts(client, oid, mid) == before


def test_archived_common_receipt_still_prevents_duplicate_order_deduction(
    client, worker_auth_headers, second_worker_headers,
):
    oid, processes, mid, _ = _setup(client, initialized=True)
    first = _report(client, worker_auth_headers, oid, processes[0], 1)
    assert first.status_code == 200, first.get_json()
    with client.application.app_context():
        db = get_db()
        rows = db.execute(
            "SELECT * FROM audit_logs WHERE target_type='order' AND target_id=? "
            "AND action LIKE 'material_order_%'", (oid,),
        ).fetchall()
        for row in rows:
            db.execute(
                "INSERT INTO audit_log_archive(archive_batch_id,source_id,event_id,payload) "
                "VALUES (?,?,?,?)",
                ("material-integration", row["id"], row["event_id"], json.dumps(dict(row))),
            )
            db.execute("DELETE FROM audit_logs WHERE id=?", (row["id"],))
        db.commit()
    second = _report(client, second_worker_headers, oid, processes[0], 1)
    assert second.status_code == 200, second.get_json()
    facts = _facts(client, oid, mid)
    assert facts["material"][0]["quantity"] == 88
    assert len(facts["consumptions"]) == 3
    assert len([row for row in facts["logs"] if row["source_type"] == State.COMMON_SOURCE]) == 1
    assert facts["evidence"] == []


def test_reversed_common_consumption_requires_explicit_resolution_without_rededuction(
    client, worker_auth_headers, auth_headers, second_worker_headers,
):
    oid, processes, mid, _ = _setup(client)
    first = _report(client, worker_auth_headers, oid, processes[0], 1)
    assert first.status_code == 200, first.get_json()
    common = next(
        row for row in _facts(client, oid, mid)["consumptions"] if row["process_id"] is None
    )
    reverse = client.delete(
        f"/api/material-consumptions/{common['id']}",
        json={"reason": "核对后撤销"}, headers=auth_headers,
    )
    assert reverse.status_code == 200, reverse.get_json()
    before = _facts(client, oid, mid)
    reversal = before["logs"][-1]
    assert reversal["reversal_of_log_id"] == before["logs"][0]["id"]
    response = _report(client, second_worker_headers, oid, processes[0], 1)
    assert response.status_code == 409, response.get_json()
    assert response.get_json()["details"]["code"] == "COMMON_CONSUMPTION_REVERSED"
    assert _facts(client, oid, mid) == before


def test_frozen_common_recipe_cannot_be_removed_but_process_recipe_remains_editable(
    client, worker_auth_headers, auth_headers,
):
    oid, processes, mid, _ = _setup(client)
    first = _report(client, worker_auth_headers, oid, processes[0], 1)
    assert first.status_code == 200, first.get_json()
    rows = client.get(f"/api/orders/{oid}/materials", headers=auth_headers).get_json()["materials"]
    common = next(row for row in rows if row["process_id"] is None)
    dedicated = next(row for row in rows if row["process_id"] == processes[1])
    deletion = client.delete(
        f"/api/orders/{oid}/materials/{common['id']}", headers=auth_headers,
    )
    assert deletion.status_code == 409, deletion.get_json()
    assert deletion.get_json()["details"]["code"] == "STALE_INPUT"
    process_delete = client.delete(
        f"/api/orders/{oid}/materials/{dedicated['id']}", headers=auth_headers,
    )
    assert process_delete.status_code == 200, process_delete.get_json()
    new_common = client.post(
        f"/api/orders/{oid}/materials",
        json={"material_id": mid, "quantity_per_unit": 1, "process_id": None},
        headers=auth_headers,
    )
    assert new_common.status_code == 409, new_common.get_json()
    assert new_common.get_json()["details"]["code"] == "STALE_INPUT"
