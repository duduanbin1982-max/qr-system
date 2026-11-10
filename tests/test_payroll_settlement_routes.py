"""Permission and HTTP contracts for the payroll settlement API."""

from io import BytesIO

import pytest

from modules.middleware.auth import AuthSessionService
from modules.services.payroll_settlement_service import (
    MAX_RECEIPT_BYTES,
    PayrollSettlementService,
)
from modules.services.payroll_service import PayrollWorkflowService


def _authenticate(monkeypatch, permissions):
    actor = {
        "id": 17,
        "name": "财务操作员",
        "username": "payroll-finance",
        "_permissions": list(permissions),
    }
    monkeypatch.setattr(
        AuthSessionService, "authenticate", lambda _token: (dict(actor), None)
    )
    return {"Authorization": "Bearer payroll-settlement-route-test"}


@pytest.mark.parametrize(
    ("permission", "method", "path", "kwargs", "service_method"),
    [
        (
            "wages:export", "get", "/api/payroll/batches/31/settlement", {},
            "get_by_batch",
        ),
        (
            "wages:export", "post", "/api/payroll/batches/31/settlement/exports",
            {"json": {}, "headers": {"Idempotency-Key": "route-export"}},
            "create_export",
        ),
        (
            "wages:export", "get", "/api/payroll/settlement/exports/41/download", {},
            "download_export",
        ),
        (
            "wages:receipt", "post", "/api/payroll/settlement/exports/41/receipts",
            {
                "data": {"file": (BytesIO(b"receipt"), "receipt.csv")},
                "headers": {"Idempotency-Key": "route-receipt"},
                "content_type": "multipart/form-data",
            },
            "upload_receipt",
        ),
        (
            "wages:reconcile", "post", "/api/payroll/settlements/51/reconcile",
            {"json": {}, "headers": {"Idempotency-Key": "route-reconcile"}},
            "reconcile",
        ),
        (
            "wages:reconcile", "post",
            "/api/payroll/settlement/differences/61/resolve",
            {"json": {"resolution_code": "exclude_duplicate"}},
            "resolve_difference",
        ),
        (
            "wages:close", "post", "/api/payroll/settlements/51/close",
            {"json": {"close_reason": "已核对"}}, "close",
        ),
    ],
)
def test_settlement_routes_require_action_specific_permissions(
    client, monkeypatch, permission, method, path, kwargs, service_method
):
    denied_permissions = [] if service_method == "get_by_batch" else ["wages:view_all"]
    headers = _authenticate(monkeypatch, denied_permissions)
    called = []

    def unexpected_call(*_args, **_kwargs):
        called.append(True)
        raise AssertionError("unauthorized request reached service")

    monkeypatch.setattr(PayrollSettlementService, service_method, unexpected_call)
    request_kwargs = {**kwargs, "headers": {**kwargs.get("headers", {}), **headers}}
    response = getattr(client, method)(path, **request_kwargs)

    assert response.status_code == 403
    assert called == []


@pytest.mark.parametrize(
    ("permission", "method", "path", "kwargs", "service_method"),
    [
        ("wages:view_all", "get", "/api/payroll/batches/31/settlement", {}, "get_by_batch"),
        (
            "wages:export", "post", "/api/payroll/batches/31/settlement/exports",
            {"json": {}, "headers": {"Idempotency-Key": "route-export"}}, "create_export",
        ),
        (
            "wages:export", "get", "/api/payroll/settlement/exports/41/download", {},
            "download_export",
        ),
        (
            "wages:receipt", "post", "/api/payroll/settlement/exports/41/receipts",
            {
                "data": {"file": (BytesIO(b"receipt"), "receipt.csv")},
                "headers": {"Idempotency-Key": "route-receipt"},
                "content_type": "multipart/form-data",
            }, "upload_receipt",
        ),
        (
            "wages:reconcile", "post", "/api/payroll/settlements/51/reconcile",
            {"json": {}, "headers": {"Idempotency-Key": "route-reconcile"}},
            "reconcile",
        ),
        (
            "wages:reconcile", "post", "/api/payroll/settlement/differences/61/resolve",
            {"json": {"resolution_code": "exclude_duplicate"}}, "resolve_difference",
        ),
        (
            "wages:close", "post", "/api/payroll/settlements/51/close",
            {"json": {"close_reason": "已核对"}}, "close",
        ),
    ],
)
def test_settlement_routes_allow_the_matching_permission(
    client, monkeypatch, permission, method, path, kwargs, service_method
):
    headers = _authenticate(monkeypatch, [permission])
    monkeypatch.setattr(
        "modules.routes.payroll.safe_audit_log", lambda *_args, **_kwargs: None
    )
    called = []

    def accepted(*args, **service_kwargs):
        called.append((args, service_kwargs))
        if service_method == "download_export":
            return b"payment-list"
        return {"id": 71, "status": "ok"}

    monkeypatch.setattr(PayrollSettlementService, service_method, accepted)
    request_kwargs = {**kwargs, "headers": {**kwargs.get("headers", {}), **headers}}
    response = getattr(client, method)(path, **request_kwargs)

    assert response.status_code in (200, 201)
    assert called
    if service_method != "download_export":
        assert "no-store" in response.headers["Cache-Control"]


def test_legacy_payroll_export_is_labeled_preview(client, monkeypatch):
    headers = _authenticate(monkeypatch, ["wages:export"])
    monkeypatch.setattr(
        "modules.routes.payroll.safe_audit_log", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        PayrollWorkflowService,
        "export_data",
        lambda _batch_id: (
            {"payroll_month": "2026-07", "version": 2},
            [{
                "employee_name_snapshot": "员工",
                "employee_no_snapshot": "EMP-1",
                "normal_wage_cents": 100,
                "rework_wage_cents": 0,
                "bonus_cents": 0,
                "allowance_cents": 0,
                "deduction_cents": 0,
                "payable_wage_cents": 100,
            }],
        ),
    )

    response = client.get("/api/payroll/batches/31/export", headers=headers)

    assert response.status_code == 200
    assert response.headers["X-Payroll-Export-Mode"] == "preview"
    assert "Preview only" in response.headers["X-Payroll-Export-Notice"]
    assert "payroll_preview_2026-07_v2.csv" in response.headers["Content-Disposition"]
    assert "no-store" in response.headers["Cache-Control"]


def test_receipt_upload_rejects_missing_file_before_service(client, monkeypatch):
    headers = _authenticate(monkeypatch, ["wages:receipt"])
    monkeypatch.setattr(
        PayrollSettlementService,
        "upload_receipt",
        lambda *_args, **_kwargs: pytest.fail("service should not be called"),
    )

    response = client.post(
        "/api/payroll/settlement/exports/41/receipts", headers=headers, data={}
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "缺少回执 CSV 文件"


@pytest.mark.parametrize(
    ("permission", "path", "service_method"),
    [
        ("wages:export", "/api/payroll/batches/31/settlement/exports", "create_export"),
        ("wages:reconcile", "/api/payroll/settlements/51/reconcile", "reconcile"),
        ("wages:reconcile", "/api/payroll/settlement/differences/61/resolve", "resolve_difference"),
        ("wages:close", "/api/payroll/settlements/51/close", "close"),
    ],
)
def test_settlement_json_routes_reject_non_object_payloads(
    client, monkeypatch, permission, path, service_method
):
    headers = _authenticate(monkeypatch, [permission])
    monkeypatch.setattr(
        PayrollSettlementService,
        service_method,
        lambda *_args, **_kwargs: pytest.fail("service should not be called"),
    )

    response = client.post(path, headers=headers, json=[])

    assert response.status_code == 400
    assert response.get_json()["error"] == "请求内容必须是 JSON 对象"


def test_receipt_upload_rejects_oversized_request_before_service(client, monkeypatch):
    headers = _authenticate(monkeypatch, ["wages:receipt"])
    monkeypatch.setattr(
        PayrollSettlementService,
        "upload_receipt",
        lambda *_args, **_kwargs: pytest.fail("service should not be called"),
    )

    response = client.post(
        "/api/payroll/settlement/exports/41/receipts",
        headers=headers,
        data={"file": (BytesIO(b"x" * (MAX_RECEIPT_BYTES + 64 * 1024)), "large.csv")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 413
    assert response.get_json()["error"] == "回执文件不能超过 2 MB"
