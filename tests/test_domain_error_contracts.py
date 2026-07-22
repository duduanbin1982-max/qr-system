import ast
from contextlib import nullcontext
from pathlib import Path

import pytest

from modules.domain.errors import ConflictError, NotFoundError, ValidationError
from modules.repositories.product_bom_repository import ProductBomRepository
from modules.services.approval_service import ApprovalService
from modules.services.material_service import MaterialService
from modules.services.order_service import OrderService
from modules.services.product_service import ProductService
from modules.services.trace_service import TraceService


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALLOWED_ROUTE_EXCEPTION_RECOVERY = {
    ("auth.py", "login"),
    ("email_reports.py", "_send_email"),
    ("imports.py", "import_preview"),
    ("imports.py", "bulk_import_orders"),
    ("imports.py", "bulk_import_products"),
    ("imports.py", "bulk_import_customers"),
    ("settings.py", "save_settings"),
    ("settings.py", "save_company_info"),
    ("system.py", "system_health"),
    ("system.py", "create_backup"),
}


@pytest.mark.contract
def test_python_sources_contain_no_corrupted_question_mark_text():
    offenders = []
    for path in (PROJECT_ROOT / "modules").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and "??" in node.value:
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}")
    assert offenders == []


@pytest.mark.contract
def test_route_exception_recovery_is_centralized_and_explicit():
    broad_handlers = set()
    for path in (PROJECT_ROOT / "modules" / "routes").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert " in str(e)" not in source
        assert " in str(exc)" not in source

        tree = ast.parse(source)
        parents = {
            child: node
            for node in ast.walk(tree)
            for child in ast.iter_child_nodes(node)
        }
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.ExceptHandler)
                and isinstance(node.type, ast.Name)
                and node.type.id == "Exception"
            ):
                continue
            parent = parents.get(node)
            while parent and not isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
                parent = parents.get(parent)
            broad_handlers.add((path.name, parent.name if parent else ""))

    assert broad_handlers == ALLOWED_ROUTE_EXCEPTION_RECOVERY


@pytest.mark.unit
def test_domain_errors_expose_stable_http_contracts():
    assert ValidationError("参数错误").status_code == 400
    assert NotFoundError("不存在").to_payload() == {"error": "不存在", "code": "not_found"}
    assert ConflictError("冲突").status_code == 409


@pytest.mark.unit
def test_services_raise_readable_domain_errors(monkeypatch):
    with pytest.raises(ValidationError, match="审批操作必须是通过或驳回"):
        ApprovalService.handle(1, "invalid", {"id": 1, "name": "admin"})

    with pytest.raises(ValidationError, match="序列号不能为空"):
        TraceService.trace(" ")

    monkeypatch.setattr("modules.services.material_service.MaterialRepository.find_by_id", lambda _mid: None)
    with pytest.raises(NotFoundError, match="物料不存在"):
        MaterialService.update_material(999999, {"name": "测试物料"})

    monkeypatch.setattr(OrderService, "get_order", lambda _order_id: None)
    with pytest.raises(NotFoundError, match="订单不存在"):
        OrderService.list_order_materials(999999)

    with pytest.raises(ValidationError, match="物料 ID 不能为空"):
        ProductService.add_product_bom(999999, {})


@pytest.mark.unit
def test_product_bom_unique_constraint_becomes_domain_conflict(monkeypatch):
    transaction = object()
    monkeypatch.setattr(
        "modules.services.product_service.BaseService.transaction",
        lambda: nullcontext(transaction),
    )
    monkeypatch.setattr(ProductBomRepository, "product_exists", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(ProductBomRepository, "insert_unique", lambda *_args, **_kwargs: None)

    with pytest.raises(ConflictError, match="该物料已存在于产品配方中"):
        ProductService.add_product_bom(1, {"material_id": 2, "quantity": 1})


@pytest.mark.integration
def test_domain_error_routes_return_chinese_messages_and_status_codes(client, auth_headers):
    material_response = client.put(
        "/api/materials/999999",
        json={"name": "测试物料"},
        headers=auth_headers,
    )
    assert material_response.status_code == 404
    assert material_response.get_json()["error"] == "物料不存在"

    order_response = client.get("/api/orders/999999/materials", headers=auth_headers)
    assert order_response.status_code == 404
    assert order_response.get_json()["code"] == "not_found"

    bom_response = client.post("/api/products/999999/bom", json={}, headers=auth_headers)
    assert bom_response.status_code == 400
    assert bom_response.get_json()["error"] == "物料 ID 不能为空"

    import_response = client.post("/api/users/import", headers=auth_headers)
    assert import_response.status_code == 400
    assert import_response.get_json()["error"] == "请上传 Excel 文件"


@pytest.mark.integration
def test_unexpected_route_errors_use_the_global_safe_response(client, auth_headers, monkeypatch):
    monkeypatch.setitem(client.application.config, "PROPAGATE_EXCEPTIONS", False)

    def fail_daily_records(*_args, **_kwargs):
        raise RuntimeError("sensitive database detail")

    monkeypatch.setattr(
        "modules.routes.stats.StatsService.get_daily_records",
        fail_daily_records,
    )
    response = client.get("/api/stats/daily?date=2026-07-21", headers=auth_headers)

    assert response.status_code == 500
    assert response.get_json() == {"error": "服务器内部错误，请稍后重试"}
