import json

import pytest

from modules import config
from modules.db import get_db
from modules.domain.price_versioning import PriceBindingStaleError
from modules.services.price_version_service import PriceVersionService
from modules.repositories.payroll_repository import PayrollRepository
from tests.test_pending_route_price_policy import _seed_versioned_reference


def _payload(ids, *, pending=True, key="pending-price-create", amount="1.25"):
    suffix = "v2" if pending else "v1"
    return {
        "route_id": ids["route_id"],
        "route_version_id": ids[f"route_{suffix}"],
        "process_id": ids["process_id"],
        "process_version_id": ids[f"process_{suffix}"],
        "expected_route_content_digest": f"route-{suffix}",
        "expected_process_content_digest": f"process-{suffix}",
        "normal_unit_price": amount,
        "valid_from": "2026-08-24 07:00:00",
        "idempotency_key": key,
    }


def _enable_pending(monkeypatch, *, write=False):
    monkeypatch.setattr(config, "ROUTE_PRICE_PENDING_REFERENCE_ENABLED", True)
    monkeypatch.setattr(config, "ROUTE_PRICE_PENDING_COMPAT_AUDIT_ENABLED", True)
    monkeypatch.setattr(config, "ROUTE_PRICE_PENDING_WRITE_ENABLED", write)


def test_pending_price_flags_are_fail_closed():
    assert config.get_pending_route_price_flags({}) == {
        "ROUTE_PRICE_PENDING_REFERENCE_ENABLED": False,
        "ROUTE_PRICE_PENDING_COMPAT_AUDIT_ENABLED": False,
        "ROUTE_PRICE_PENDING_WRITE_ENABLED": False,
    }


def test_pending_price_write_requires_reference_and_audit():
    with pytest.raises(RuntimeError, match="待发布路线工价功能开关组合无效"):
        config.validate_pending_route_price_flags({
            "ROUTE_PRICE_PENDING_REFERENCE_ENABLED": True,
            "ROUTE_PRICE_PENDING_COMPAT_AUDIT_ENABLED": False,
            "ROUTE_PRICE_PENDING_WRITE_ENABLED": True,
        })


def test_reference_api_defaults_to_published_and_requires_enabled_pending(
    client, auth_headers, monkeypatch
):
    with client.application.app_context():
        ids = _seed_versioned_reference(get_db())

    default = client.get(
        "/api/route-price-versions/reference?include_pending=true",
        headers=auth_headers,
    )
    default_ids = [
        row["route_version_id"] for row in default.get_json()["items"]
        if row["route_id"] == ids["route_id"]
    ]
    assert default_ids == [ids["route_v1"]]

    _enable_pending(monkeypatch)
    expanded = client.get(
        "/api/route-price-versions/reference?include_pending=true",
        headers=auth_headers,
    )
    expanded_ids = [
        row["route_version_id"] for row in expanded.get_json()["items"]
        if row["route_id"] == ids["route_id"]
    ]
    assert expanded_ids == [ids["route_v1"], ids["route_v2"]]


def test_pending_create_is_disabled_with_stable_domain_error(
    client, auth_headers
):
    with client.application.app_context():
        ids = _seed_versioned_reference(get_db())
    response = client.post(
        "/api/route-price-versions", json=_payload(ids), headers=auth_headers
    )
    assert response.status_code == 409
    assert response.get_json()["code"] == "PENDING_ROUTE_PRICE_WRITE_DISABLED"


def test_exact_create_is_idempotent_and_rejects_key_reuse(
    client, auth_headers, monkeypatch
):
    _enable_pending(monkeypatch, write=True)
    with client.application.app_context():
        ids = _seed_versioned_reference(get_db())
    payload = _payload(ids)
    first = client.post(
        "/api/route-price-versions", json=payload, headers=auth_headers
    )
    replay = client.post(
        "/api/route-price-versions", json=payload, headers=auth_headers
    )
    conflict = client.post(
        "/api/route-price-versions",
        json={**payload, "normal_unit_price": "1.50"},
        headers=auth_headers,
    )
    assert first.status_code == replay.status_code == 200
    assert replay.get_json()["id"] == first.get_json()["id"]
    assert first.get_json()["approval_mode"] == "grouped_release_only"
    assert conflict.status_code == 409
    assert conflict.get_json()["code"] == "IDEMPOTENCY_CONFLICT"


def test_create_rejects_stale_digest_and_unknown_properties(
    client, auth_headers, monkeypatch
):
    _enable_pending(monkeypatch, write=True)
    with client.application.app_context():
        ids = _seed_versioned_reference(get_db())
    stale = client.post(
        "/api/route-price-versions",
        json={**_payload(ids), "expected_route_content_digest": "old-route"},
        headers=auth_headers,
    )
    assert stale.status_code == 409
    assert stale.get_json()["code"] == PriceBindingStaleError.code
    invalid = client.post(
        "/api/route-price-versions",
        json={**_payload(ids, key="pending-price-extra"), "unexpected": "secret"},
        headers=auth_headers,
    )
    assert invalid.status_code == 400
    assert "不允许" in invalid.get_json()["error"]


def test_pending_price_cannot_be_approved_independently_and_creator_can_void(
    client, auth_headers, monkeypatch
):
    _enable_pending(monkeypatch, write=True)
    with client.application.app_context():
        ids = _seed_versioned_reference(get_db())
    created = client.post(
        "/api/route-price-versions", json=_payload(ids), headers=auth_headers
    ).get_json()
    approved = client.post(
        f"/api/route-price-versions/{created['id']}/approve",
        json={"row_version": created["row_version"]},
        headers=auth_headers,
    )
    assert approved.status_code == 409
    assert approved.get_json()["code"] == "GROUP_RELEASE_REQUIRED"

    voided = client.post(
        f"/api/route-price-versions/{created['id']}/void",
        json={
            "row_version": created["row_version"],
            "reason": "金额录入错误",
            "idempotency_key": "pending-price-void",
        },
        headers=auth_headers,
    )
    assert voided.status_code == 200
    assert voided.get_json()["status"] == "voided"
    assert voided.get_json()["void_reason"] == "金额录入错误"

    with client.application.app_context():
        with pytest.raises(ValueError, match="幂等键"):
            PriceVersionService.void(
                created["id"],
                {"row_version": created["row_version"], "reason": "重复作废"},
                {"id": created["created_by"], "name": created["created_by_name"]},
            )


def test_reference_compat_audit_ignores_pending_additions(
    client, auth_headers, monkeypatch
):
    _enable_pending(monkeypatch)
    with client.application.app_context():
        db = get_db()
        ids = _seed_versioned_reference(db)
        actor = {"id": 1, "name": "工价制单人"}
        price = PriceVersionService.create(
            _payload(ids, pending=False, key="published-price-audit"), actor
        )
    response = client.get(
        "/api/route-price-versions/reference?include_pending=true",
        headers=auth_headers,
    )
    assert response.status_code == 200
    with client.application.app_context():
        audit = get_db().execute(
            "SELECT * FROM route_price_reference_compat_audit "
            "WHERE price_version_id=? ORDER BY id DESC LIMIT 1", (price["id"],)
        ).fetchone()
        detail = json.loads(audit["detail_json"])
    assert audit["mismatch"] == 0
    assert detail["legacy_published_digest"] == detail["versioned_published_digest"]


def test_reference_compat_audit_detects_versioned_published_omission(
    client, auth_headers, monkeypatch
):
    _enable_pending(monkeypatch)
    with client.application.app_context():
        db = get_db()
        ids = _seed_versioned_reference(db)
        price = PriceVersionService.create(
            _payload(ids, pending=False, key="published-price-mismatch"),
            {"id": 1, "name": "工价制单人"},
        )
    original = PayrollRepository.list_route_process_references

    def omit_published(*args, **kwargs):
        return [
            row for row in original(*args, **kwargs)
            if row["route_version_id"] != ids["route_v1"]
        ]

    monkeypatch.setattr(
        PayrollRepository, "list_route_process_references", staticmethod(omit_published)
    )
    response = client.get(
        "/api/route-price-versions/reference?include_pending=true",
        headers=auth_headers,
    )
    assert response.status_code == 200
    with client.application.app_context():
        audit = get_db().execute(
            "SELECT mismatch,detail_json FROM route_price_reference_compat_audit "
            "WHERE price_version_id=? ORDER BY id DESC LIMIT 1", (price["id"],)
        ).fetchone()
    assert audit["mismatch"] == 1
    detail = json.loads(audit["detail_json"])
    assert detail["legacy_published_digest"] != detail["versioned_published_digest"]
