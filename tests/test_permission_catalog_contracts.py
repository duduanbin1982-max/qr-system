from pathlib import Path

from modules.permission_catalog import (
    ACTION_PERMISSION_DEFS,
    PAGE_OPERATION_BINDINGS,
    PAGE_PERMISSION_CODES,
    SIDEBAR_ITEMS,
    build_permission_payload,
    infer_page_permissions,
)
from modules.access_policy import has_permission_code


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_permission_payload_contains_all_canonical_page_codes():
    payload = build_permission_payload()

    assert set(PAGE_PERMISSION_CODES).issubset(set(payload["codes"]))
    assert {item["code"] for item in SIDEBAR_ITEMS}.issubset(set(payload["codes"]))
    assert payload["pages"]
    assert payload["sidebar"]
    assert payload["mergedTree"]


def test_page_operation_bindings_reference_known_pages_and_resources():
    page_codes = set(PAGE_PERMISSION_CODES)
    resources = set(ACTION_PERMISSION_DEFS)
    violations = []

    for page_code, bound_resources in PAGE_OPERATION_BINDINGS.items():
        if page_code not in page_codes:
            violations.append(f"unknown page {page_code}")
        for resource in bound_resources:
            if resource not in resources:
                violations.append(f"unknown resource {resource} for {page_code}")

    assert violations == []


def test_business_permissions_infer_page_permissions():
    assert infer_page_permissions(["performance:view"]) == ["page:performance"]
    assert "page:settings.admin-users" in infer_page_permissions(["users:admin"])


def test_frontend_fallback_catalog_is_generated_from_backend_catalog():
    from scripts.export_permission_catalog import render_catalog

    generated = (
        PROJECT_ROOT / "frontend" / "src" / "lib" / "permissionFallback.generated.js"
    ).read_text(encoding="utf-8")

    assert generated == render_catalog()


def test_frontend_permissions_module_uses_generated_fallback_catalog():
    frontend_permissions = (
        PROJECT_ROOT / "frontend" / "src" / "lib" / "permissions.js"
    ).read_text(encoding="utf-8")

    assert "permissionFallback.generated.js" in frontend_permissions
    assert "export const SIDEBAR_ITEMS = [" not in frontend_permissions
    assert "export const ACTION_PAGE_MAP = {" not in frontend_permissions


def test_legacy_material_manage_permission_implies_granular_operations():
    expected = {
        "materials:view",
        "materials:create",
        "materials:edit",
        "materials:delete",
        "materials:stock",
        "materials:consume",
        "suppliers:view",
        "suppliers:create",
        "suppliers:edit",
        "suppliers:delete",
    }

    assert {"view", "create", "edit", "delete", "stock", "consume", "manage"}.issubset(
        set(ACTION_PERMISSION_DEFS["materials"][1])
    )
    assert ACTION_PERMISSION_DEFS["suppliers"][1] == ["view", "create", "edit", "delete"]
    assert all(has_permission_code(["materials:manage"], code) for code in expected)
    assert PAGE_OPERATION_BINDINGS["page:production.materials"] == ["materials", "suppliers"]
