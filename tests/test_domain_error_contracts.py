import ast
from pathlib import Path

import pytest

from modules.domain.errors import ConflictError, NotFoundError, ValidationError
from modules.services.approval_service import ApprovalService
from modules.services.material_service import MaterialService
from modules.services.order_service import OrderService
from modules.services.product_service import ProductService
from modules.services.trace_service import TraceService


PROJECT_ROOT = Path(__file__).resolve().parents[1]


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
