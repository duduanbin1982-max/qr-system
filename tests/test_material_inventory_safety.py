"""Inventory changes preserve balances, ledger history, and mandatory audits."""

import sqlite3
import uuid

import pytest

from factories import create_material
from modules.audit_writer import AuditCommand
from modules.db import get_db
from modules.db_unit_of_work import BaseService
from modules.domain.errors import ValidationError
from modules.repositories.audit_log_repository import AuditLogRepository
from modules.repositories.material_repository import MaterialRepository
from modules.services.material_service import MaterialService


def _material(client, *, quantity=10):
    with client.application.app_context():
        db = get_db()
        mid = create_material(db, quantity=quantity)
        db.commit()
        return mid


def _inventory_snapshot(client, mid):
    with client.application.app_context():
        db = get_db()
        return {
            "material": dict(db.execute(
                "SELECT * FROM materials WHERE id = ?", (mid,)
            ).fetchone()),
            "logs": [dict(row) for row in db.execute(
                "SELECT * FROM material_logs WHERE material_id = ? ORDER BY id", (mid,)
            )],
            "consumptions": [dict(row) for row in db.execute(
                "SELECT * FROM material_consumptions WHERE material_id = ? ORDER BY id",
                (mid,),
            )],
            "audits": [dict(row) for row in db.execute(
                "SELECT * FROM audit_logs WHERE target_type = 'material' "
                "AND target_id = ? ORDER BY id", (mid,)
            )],
        }


@pytest.mark.parametrize("quantity", [5, 0])
def test_material_delete_preserves_inventory_and_even_zero_balance_history(
    client, auth_headers, quantity,
):
    response = client.post(
        "/api/materials",
        json={"name": f"Protected Ledger {uuid.uuid4().hex}", "quantity": 5},
        headers=auth_headers,
    )
    mid = response.get_json()["id"]
    if quantity == 0:
        assert client.post(
            f"/api/materials/{mid}/stock",
            json={"type": "out", "quantity": 5},
            headers=auth_headers,
        ).status_code == 200
    before = _inventory_snapshot(client, mid)
    impact = client.get(
        f"/api/materials/{mid}/impact", headers=auth_headers,
    ).get_json()

    assert impact["refs"] == 0
    assert impact["can_delete"] is False
    assert impact["inventory_quantity"] == quantity
    assert impact["stock_log_count"] == len(before["logs"])
    assert "stock_history" in impact["blockers"]
    assert ("inventory" in impact["blockers"]) is (quantity != 0)
    deleted = client.delete(f"/api/materials/{mid}", headers=auth_headers)
    assert deleted.status_code == 409, deleted.get_json()
    assert deleted.get_json()["details"]["blockers"] == impact["blockers"]
    assert _inventory_snapshot(client, mid) == before


def test_material_delete_blocks_legacy_balance_without_ledger(client, auth_headers):
    mid = _material(client, quantity=2)
    before = _inventory_snapshot(client, mid)
    impact = client.get(
        f"/api/materials/{mid}/impact", headers=auth_headers,
    ).get_json()
    assert impact["can_delete"] is False
    assert impact["stock_log_count"] == 0
    assert impact["blockers"] == ["inventory"]
    assert client.delete(
        f"/api/materials/{mid}", headers=auth_headers,
    ).status_code == 409
    assert _inventory_snapshot(client, mid) == before


def test_material_delete_allows_empty_unused_record(client, auth_headers):
    mid = _material(client, quantity=0)
    impact = client.get(
        f"/api/materials/{mid}/impact", headers=auth_headers,
    ).get_json()
    assert impact["can_delete"] is True
    assert impact["blockers"] == []
    response = client.delete(f"/api/materials/{mid}", headers=auth_headers)
    assert response.status_code == 200, response.get_json()


@pytest.mark.parametrize("endpoint", ["stock", "consumptions"])
@pytest.mark.parametrize(
    "quantity", [float("nan"), float("inf"), "-inf", "1e309", True, None, {}, []],
)
def test_invalid_inventory_quantity_returns_400_without_any_writes(
    client, auth_headers, endpoint, quantity,
):
    mid = _material(client)
    before = _inventory_snapshot(client, mid)
    response = client.post(
        f"/api/materials/{mid}/{endpoint}",
        json={"type": "in", "quantity": quantity},
        headers=auth_headers,
    )
    assert response.status_code == 400, response.get_json()
    assert response.get_json()["code"] == "validation_error"
    assert _inventory_snapshot(client, mid) == before


@pytest.mark.parametrize("field", ["quantity", "unit_price", "safe_stock"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, -1])
def test_create_material_service_rejects_invalid_inventory_values(
    client, field, value,
):
    name = f"Invalid Material {uuid.uuid4().hex}"
    with client.application.app_context():
        db = get_db()
        with pytest.raises(ValidationError):
            MaterialService.create_material({"name": name, field: value})
        assert db.execute(
            "SELECT COUNT(*) FROM materials WHERE name = ?", (name,)
        ).fetchone()[0] == 0


@pytest.mark.parametrize("field", ["unit_price", "safe_stock"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, -1])
def test_update_material_service_rejects_invalid_inventory_values(
    client, field, value,
):
    mid = _material(client)
    before = _inventory_snapshot(client, mid)
    with client.application.app_context(), pytest.raises(ValidationError):
        MaterialService.update_material(mid, {field: value})
    assert _inventory_snapshot(client, mid) == before


@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.parametrize("field", ["unit_price", "safe_stock"])
@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_material_metadata_api_rejects_nonfinite_json_numbers(
    client, auth_headers, operation, field, value,
):
    mid = _material(client)
    before = _inventory_snapshot(client, mid)
    if operation == "create":
        response = client.post(
            "/api/materials",
            json={"name": f"Nonfinite {uuid.uuid4().hex}", field: value},
            headers=auth_headers,
        )
    else:
        response = client.put(
            f"/api/materials/{mid}", json={field: value}, headers=auth_headers,
        )
    assert response.status_code == 400, response.get_json()
    assert _inventory_snapshot(client, mid) == before


def test_stock_addition_overflow_rolls_back_without_ledger_or_audit(
    client, auth_headers,
):
    mid = _material(client, quantity=1e308)
    before = _inventory_snapshot(client, mid)
    response = client.post(
        f"/api/materials/{mid}/stock",
        json={"type": "in", "quantity": 1e308}, headers=auth_headers,
    )
    assert response.status_code == 400, response.get_json()
    assert response.get_json()["code"] == "validation_error"
    assert _inventory_snapshot(client, mid) == before


@pytest.mark.parametrize(
    ("balance", "delta"),
    [(float("inf"), 1), ("corrupt", 1), (10, float("inf")), (1e308, 1e308)],
)
def test_quantity_transition_rejects_nonfinite_or_corrupt_balance(
    client, balance, delta,
):
    mid = _material(client)
    with client.application.app_context():
        db = get_db()
        db.execute("UPDATE materials SET quantity = ? WHERE id = ?", (balance, mid))
        db.commit()
        with pytest.raises(ValidationError):
            with BaseService.transaction() as txn:
                MaterialRepository.apply_quantity_delta(mid, delta, db=txn)
        assert db.execute(
            "SELECT quantity FROM materials WHERE id = ?", (mid,)
        ).fetchone()[0] == balance
        assert db.execute(
            "SELECT COUNT(*) FROM material_logs WHERE material_id = ?", (mid,)
        ).fetchone()[0] == 0


def test_update_material_rejects_trimmed_empty_name(client, auth_headers):
    mid = _material(client)
    before = _inventory_snapshot(client, mid)
    response = client.put(
        f"/api/materials/{mid}", json={"name": " \t "}, headers=auth_headers,
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "物料名称不能为空"
    assert _inventory_snapshot(client, mid) == before


def test_consumption_audit_joins_inventory_transaction_once(
    client, auth_headers, monkeypatch,
):
    mid = _material(client)
    original_insert = AuditLogRepository.insert_command
    observed = []

    def record_transaction(command, *, db):
        if command.action == "consume":
            observed.append((db.in_transaction, BaseService.is_in_transaction(db)))
        return original_insert(command, db=db)

    monkeypatch.setattr(
        AuditLogRepository, "insert_command", staticmethod(record_transaction),
    )
    request_id = "consume-" + "r" * 140
    response = client.post(
        f"/api/materials/{mid}/consumptions",
        json={"quantity": 2},
        headers={**auth_headers, "X-Request-ID": request_id},
    )
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["new_quantity"] == 8
    assert observed == [(True, True)]
    audits = _inventory_snapshot(client, mid)["audits"]
    assert len(audits) == 1
    assert audits[0]["action"] == "consume"
    assert audits[0]["mandatory"] == 1
    assert audits[0]["request_id"] == request_id[:120]


@pytest.mark.parametrize(
    "failure", ["prepare", "runtime", "integrity", "storage", "after_insert"],
)
def test_consumption_audit_failure_rolls_back_all_inventory_writes(
    client, auth_headers, monkeypatch, failure,
):
    mid = _material(client)
    before = _inventory_snapshot(client, mid)
    original_insert = AuditLogRepository.insert_command
    original_prepare = AuditCommand.create
    monkeypatch.setitem(client.application.config, "PROPAGATE_EXCEPTIONS", False)

    def fail_prepare(cls, *args, **kwargs):
        if failure == "prepare" and len(args) > 1 and args[1] == "consume":
            raise RuntimeError("private command preparation failure")
        return original_prepare(*args, **kwargs)

    def fail_audit(command, *, db):
        if command.action != "consume":
            return original_insert(command, db=db)
        if failure == "after_insert":
            original_insert(command, db=db)
        error = {
            "integrity": sqlite3.IntegrityError,
            "storage": sqlite3.OperationalError,
        }.get(failure, RuntimeError)
        raise error("private audit storage failure")

    monkeypatch.setattr(AuditCommand, "create", classmethod(fail_prepare))
    monkeypatch.setattr(AuditLogRepository, "insert_command", staticmethod(fail_audit))
    response = client.post(
        f"/api/materials/{mid}/consumptions",
        json={"quantity": 2},
        headers=auth_headers,
    )
    assert response.status_code == 500, response.get_json()
    assert "private audit" not in response.get_data(as_text=True)
    assert _inventory_snapshot(client, mid) == before


@pytest.mark.parametrize(
    "source_type",
    ["consumption", "auto_consumption", "order_common_consumption", None],
)
def test_consumption_reversal_links_original_stock_log_for_each_source(
    client, auth_headers, source_type,
):
    mid = _material(client)
    with client.application.app_context():
        with BaseService.transaction() as txn:
            cid = MaterialRepository.insert_consumption(
                mid, None, None, 2, None, "系统", "历史领料", db=txn,
            )
            MaterialRepository.apply_quantity_delta(mid, -2, db=txn)
            original_id = None
            if source_type:
                original_id = MaterialRepository.insert_log(
                    mid, "out", 2, "领料", "系统",
                    balance_before=10, balance_after=8,
                    source_type=source_type, source_id=cid, db=txn,
                )
    response = client.delete(
        f"/api/material-consumptions/{cid}",
        json={"reason": "错误领料"}, headers=auth_headers,
    )
    assert response.status_code == 200, response.get_json()
    snapshot = _inventory_snapshot(client, mid)
    assert snapshot["material"]["quantity"] == 10
    assert snapshot["consumptions"][0]["status"] == "reversed"
    assert snapshot["logs"][-1]["reversal_of_log_id"] == original_id
    assert client.delete(
        f"/api/material-consumptions/{cid}",
        json={"reason": "重复撤销"}, headers=auth_headers,
    ).status_code == 409
