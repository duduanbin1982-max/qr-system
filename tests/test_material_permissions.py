import json
import uuid

from factories import TEST_HASH, TEST_PASS, create_material
from modules.db import get_db


def _permission_headers(client, permissions):
    suffix = uuid.uuid4().hex[:8]
    username = f"material_perm_{suffix}"
    role_code = f"material_perm_{suffix}"
    with client.application.app_context():
        db = get_db()
        role_id = db.execute(
            "INSERT INTO roles (name, code, description, permissions, status, level) "
            "VALUES (?, ?, 'pytest material permission role', ?, 'active', 1)",
            (
                f"Material Permission {suffix}",
                role_code,
                json.dumps(permissions, ensure_ascii=False),
            ),
        ).lastrowid
        user_id = db.execute(
            "INSERT INTO users "
            "(username, password, name, role, status, password_version, employee_no) "
            "VALUES (?, ?, ?, ?, 'active', 2, ?)",
            (
                username,
                TEST_HASH,
                f"Material Permission {suffix}",
                role_code,
                f"TEST-MATERIAL-{suffix.upper()}",
            ),
        ).lastrowid
        db.execute(
            "INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)",
            (user_id, role_id),
        )
        db.commit()

    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": TEST_PASS},
    )
    assert response.status_code == 200, response.get_json()
    return {"Authorization": f"Bearer {response.get_json()['user']['token']}"}


def _seed_material(client, quantity=10):
    with client.application.app_context():
        db = get_db()
        material_id = create_material(db, quantity=quantity)
        db.commit()
        return material_id


def test_stock_permission_can_read_and_adjust_but_not_manage_material(client):
    material_id = _seed_material(client)
    headers = _permission_headers(client, ["materials:stock"])

    assert client.get("/api/materials", headers=headers).status_code == 200
    stock = client.post(
        f"/api/materials/{material_id}/stock",
        json={"type": "out", "quantity": 2, "remark": "权限测试"},
        headers=headers,
    )
    assert stock.status_code == 200, stock.get_json()
    assert stock.get_json()["new_quantity"] == 8
    assert client.post(
        "/api/materials",
        json={"name": f"Forbidden {uuid.uuid4().hex[:8]}"},
        headers=headers,
    ).status_code == 403
    assert client.put(
        f"/api/materials/{material_id}",
        json={"name": "Forbidden Update"},
        headers=headers,
    ).status_code == 403
    assert client.delete(f"/api/materials/{material_id}", headers=headers).status_code == 403
    assert client.post(
        f"/api/materials/{material_id}/consumptions",
        json={"quantity": 1},
        headers=headers,
    ).status_code == 403
    assert client.get("/api/suppliers", headers=headers).status_code == 403


def test_legacy_material_manage_permission_keeps_all_existing_operations(client):
    headers = _permission_headers(client, ["materials:manage"])

    supplier = client.post(
        "/api/suppliers",
        json={"name": f"Legacy Supplier {uuid.uuid4().hex[:8]}"},
        headers=headers,
    )
    assert supplier.status_code == 200, supplier.get_json()
    material = client.post(
        "/api/materials",
        json={
            "name": f"Legacy Material {uuid.uuid4().hex[:8]}",
            "quantity": 5,
            "supplier_id": supplier.get_json()["id"],
        },
        headers=headers,
    )
    assert material.status_code == 200, material.get_json()
    material_id = material.get_json()["id"]
    assert client.get("/api/materials", headers=headers).status_code == 200
    assert client.get("/api/suppliers", headers=headers).status_code == 200
    assert client.put(
        f"/api/materials/{material_id}",
        json={"location": "A-01"},
        headers=headers,
    ).status_code == 200
    assert client.post(
        f"/api/materials/{material_id}/consumptions",
        json={"quantity": 1},
        headers=headers,
    ).status_code == 200
