from pathlib import Path

from modules.permission_catalog import (
    ACTION_LABELS,
    ACTION_PERMISSION_DEFS,
    PAGE_OPERATION_BINDINGS,
    PAGE_PERMISSION_CODES,
    SIDEBAR_ITEMS,
    build_permission_payload,
    default_role_permission_additions,
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
    assert infer_page_permissions(["performance:view_self"]) == ["page:performance"]
    assert "page:settings.admin-users" in infer_page_permissions(["users:admin"])


def test_performance_permissions_are_granular_and_labels_are_resource_neutral():
    assert ACTION_PERMISSION_DEFS["performance"][1] == [
        "view_self",
        "view_department",
        "view_all",
        "review_department",
        "prepare",
        "approve",
        "plan_manage",
        "plan_reassess",
    ]
    assert ACTION_LABELS["view_self"] == "查看本人"
    assert ACTION_LABELS["view_all"] == "查看全部"
    assert ACTION_LABELS["prepare"] == "制单"
    assert ACTION_LABELS["approve"] == "批准"


def test_legacy_performance_permissions_never_imply_global_access():
    assert not has_permission_code(["performance:view"], "performance:view_all")
    assert not has_permission_code(["performance:create"], "performance:prepare")
    for role_code in ("qc_inspector", "warehouse_keeper"):
        additions = default_role_permission_additions(role_code)
        assert "performance:view_self" in additions
        assert "performance:view_all" not in additions
        assert "performance:view" not in additions


def test_performance_write_permissions_only_imply_required_read_scope():
    assert has_permission_code(
        ["performance:review_department"], "performance:view_department"
    )
    assert has_permission_code(["performance:prepare"], "performance:view_all")
    assert has_permission_code(["performance:approve"], "performance:view_all")
    assert not has_permission_code(["performance:view_all"], "performance:prepare")
    assert not has_permission_code(["performance:view_all"], "performance:approve")


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


def test_process_version_permissions_are_granular_and_resource_neutral():
    expected_version_actions = [
        "view",
        "create",
        "submit",
        "approve",
        "reject",
        "impact",
    ]

    assert ACTION_PERMISSION_DEFS["process_versions"][1] == expected_version_actions
    assert ACTION_PERMISSION_DEFS["route_versions"][1] == expected_version_actions
    assert ACTION_PERMISSION_DEFS["processes"][1][-2:] == ["retire", "reactivate"]
    assert ACTION_PERMISSION_DEFS["process_routes"][1] == ["retire", "reactivate"]
    assert ACTION_PERMISSION_DEFS["master_data_releases"][1] == [
        "view",
        "create",
        "submit",
        "approve",
        "reject",
    ]
    assert {"submit", "approve", "reject", "impact", "retire", "reactivate"}.issubset(
        ACTION_LABELS
    )
    assert ACTION_LABELS["submit"] == "提交"
    assert ACTION_LABELS["impact"] == "影响查询"


def test_legacy_process_permissions_only_imply_version_read_access():
    assert has_permission_code(["processes:view"], "process_versions:view")
    assert has_permission_code(["routes:view"], "route_versions:view")

    forbidden_migrations = {
        "process_versions:approve",
        "process_versions:reject",
        "processes:retire",
        "processes:reactivate",
        "route_versions:approve",
        "route_versions:reject",
        "process_routes:retire",
        "process_routes:reactivate",
        "master_data_releases:approve",
    }
    for legacy_permission in (
        "processes:create",
        "processes:edit",
        "processes:delete",
        "routes:create",
        "routes:edit",
        "routes:delete",
    ):
        assert all(
            not has_permission_code([legacy_permission], permission)
            for permission in forbidden_migrations
        )
