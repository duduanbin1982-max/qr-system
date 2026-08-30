import sqlite3
import uuid
from io import BytesIO

import pytest

from factories import create_material, create_process_route, ensure_process
from modules.db import get_db
from modules.migration_helpers import MigrationInvariantError
from modules.migration_product_integrity import m064_harden_product_integrity
from scripts.product_integrity_v64 import inspect_product_integrity, rehearse_copy


def _product_payload(name=None, **overrides):
    payload = {
        "product_name": name or f"产品完整性-{uuid.uuid4().hex[:8]}",
        "model": f"MODEL-{uuid.uuid4().hex[:8]}",
        "category": "结构件",
        "weight": None,
        "price": None,
    }
    payload.update(overrides)
    return payload


def _create_product(client, auth_headers, **overrides):
    response = client.post(
        "/api/products",
        headers=auth_headers,
        json=_product_payload(**overrides),
    )
    assert response.status_code == 200, response.get_json()
    return response.get_json()["id"]


def test_blank_optional_numbers_round_trip_as_null(client, auth_headers):
    product_id = _create_product(client, auth_headers)
    response = client.put(
        f"/api/products/{product_id}",
        headers=auth_headers,
        json={"weight": None, "price": None},
    )
    assert response.status_code == 200, response.get_json()

    with client.application.app_context():
        row = get_db().execute(
            "SELECT weight, price FROM products WHERE id=?", (product_id,)
        ).fetchone()
        assert row["weight"] is None
        assert row["price"] is None


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"product_name": "   "}, "产品名称不能为空"),
        ({"category": "任意分类"}, "参数校验失败"),
    ],
)
def test_product_update_rejects_invalid_identity_fields(
    client, auth_headers, payload, expected
):
    product_id = _create_product(client, auth_headers)
    response = client.put(
        f"/api/products/{product_id}", headers=auth_headers, json=payload
    )
    assert response.status_code == 400
    assert expected in response.get_json()["error"]


def test_server_code_preview_matches_persisted_product(client, auth_headers):
    payload = _product_payload(
        product_name="编码预览产品",
        model="sb81",
        spec="三角型",
        style="标准",
        upper_opening="360",
        lower_opening="340",
        plate_thickness="18",
    )
    preview = client.post(
        "/api/products/code-preview", headers=auth_headers, json=payload
    )
    created = client.post("/api/products", headers=auth_headers, json=payload)
    assert preview.status_code == 200, preview.get_json()
    assert created.status_code == 200, created.get_json()
    assert preview.get_json()["product_code"] == created.get_json()["product_code"]


def test_bom_rejects_non_positive_quantity_and_duplicate_null_process(
    client, auth_headers
):
    product_id = _create_product(client, auth_headers)
    with client.application.app_context():
        db = get_db()
        material_id = create_material(db)
        db.commit()

    invalid = client.post(
        f"/api/products/{product_id}/bom",
        headers=auth_headers,
        json={"material_id": material_id, "quantity_per_unit": -2},
    )
    assert invalid.status_code == 400

    first = client.post(
        f"/api/products/{product_id}/bom",
        headers=auth_headers,
        json={"material_id": material_id, "quantity_per_unit": 1, "process_id": None},
    )
    duplicate = client.post(
        f"/api/products/{product_id}/bom",
        headers=auth_headers,
        json={"material_id": material_id, "quantity_per_unit": 2, "process_id": None},
    )
    assert first.status_code == 201, first.get_json()
    assert duplicate.status_code == 409, duplicate.get_json()

    with client.application.app_context():
        db = get_db()
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO product_bom "
                "(product_id, material_id, quantity_per_unit, process_id) "
                "VALUES (?, ?, -1, NULL)",
                (product_id, material_id),
            )


def test_missing_restore_and_purge_return_not_found(client, auth_headers):
    restore = client.put("/api/products/999999/restore", headers=auth_headers)
    purge = client.delete("/api/products/999999/purge", headers=auth_headers)
    assert restore.status_code == 404
    assert purge.status_code == 404
    assert restore.get_json()["code"] == "not_found"
    assert purge.get_json()["code"] == "not_found"


def test_historically_referenced_product_can_only_be_soft_deleted(client, auth_headers):
    product_id = _create_product(client, auth_headers)
    order = client.post(
        "/api/orders",
        headers=auth_headers,
        json={
            "order_no": f"PRODUCT-DELETE-{uuid.uuid4().hex[:8]}",
            "product_id": product_id,
            "quantity": 1,
        },
    )
    assert order.status_code == 200, order.get_json()

    deleted = client.delete(f"/api/products/{product_id}", headers=auth_headers)
    purged = client.delete(f"/api/products/{product_id}/purge", headers=auth_headers)
    assert deleted.status_code == 200, deleted.get_json()
    assert purged.status_code == 409
    assert "只能保留软删除状态" in purged.get_json()["error"]


def test_attachment_upload_requires_an_active_product(client, auth_headers):
    response = client.post(
        "/api/products/999999/attachments",
        headers=auth_headers,
        data={"file": (BytesIO(b"test"), "drawing.pdf")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 404
    assert response.get_json()["code"] == "not_found"


def test_legacy_product_import_delegates_to_canonical_policy(client, auth_headers):
    response = client.post(
        "/api/import/products",
        headers=auth_headers,
        json={
            "rows": [{
                "product_name": f"Legacy导入-{uuid.uuid4().hex[:8]}",
                "model": "LEGACY-01",
                "category": "结构件",
                "weight": "",
                "price": "",
                "lower_opening": "320",
            }]
        },
    )
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["success"] == 1
    assert response.get_json()["skipped"] == 0
    assert response.get_json()["deprecated"] is True


def test_product_import_preview_uses_product_validation(client, auth_headers):
    csv_data = "product_name,category,weight\n错误分类产品,未知分类,1\n".encode()
    response = client.post(
        "/api/import/preview",
        headers=auth_headers,
        data={"type": "products", "file": (BytesIO(csv_data), "products.csv")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["valid_rows"] == 0
    assert "产品分类仅支持" in response.get_json()["errors"][0]["error"]


def test_product_summary_is_independent_from_page_size(client, auth_headers):
    for index in range(7):
        _create_product(
            client,
            auth_headers,
            product_name=f"分页产品-{index}-{uuid.uuid4().hex[:6]}",
            category="结构件" if index < 4 else "机加工",
        )
    response = client.get(
        "/api/products?page=1&limit=3", headers=auth_headers
    )
    data = response.get_json()
    assert response.status_code == 200
    assert len(data["products"]) == 3
    assert data["total"] == 7
    assert data["summary"] == {"total": 7, "structural": 4, "machining": 3}


def test_product_route_root_resolves_current_version_for_new_order(
    client, auth_headers
):
    with client.application.app_context():
        db = get_db()
        process_id = ensure_process(db, name=f"产品默认路线工序-{uuid.uuid4().hex[:8]}")
        route_id = create_process_route(
            db, [process_id], name=f"产品默认路线-{uuid.uuid4().hex[:8]}"
        )
        route_version_id = db.execute(
            "SELECT current_effective_version_id FROM process_routes WHERE id=?",
            (route_id,),
        ).fetchone()[0]

    product_id = _create_product(
        client, auth_headers, process_route_id=route_id
    )
    order = client.post(
        "/api/orders",
        headers=auth_headers,
        json={
            "order_no": f"PRODUCT-ROUTE-{uuid.uuid4().hex[:8]}",
            "product_id": product_id,
            "quantity": 1,
        },
    )
    assert order.status_code == 200, order.get_json()
    with client.application.app_context():
        row = get_db().execute(
            "SELECT route_id, route_version_id FROM orders WHERE id=?",
            (order.get_json()["id"],),
        ).fetchone()
        assert tuple(row) == (route_id, route_version_id)


def test_v064_preflight_blocks_duplicate_null_process_rows():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        db.executescript(
            """
            CREATE TABLE products (id INTEGER PRIMARY KEY, route_id INTEGER);
            CREATE TABLE materials (id INTEGER PRIMARY KEY);
            CREATE TABLE processes (id INTEGER PRIMARY KEY, status TEXT);
            CREATE TABLE process_routes (id INTEGER PRIMARY KEY);
            CREATE TABLE product_bom (
                id INTEGER PRIMARY KEY,
                product_id INTEGER NOT NULL,
                material_id INTEGER NOT NULL,
                quantity_per_unit REAL,
                process_id INTEGER,
                created_at TEXT
            );
            INSERT INTO products VALUES (1, NULL);
            INSERT INTO materials VALUES (1);
            INSERT INTO product_bom VALUES (1, 1, 1, 1, NULL, '2026-08-15');
            INSERT INTO product_bom VALUES (2, 1, 1, 2, NULL, '2026-08-15');
            """
        )
        with pytest.raises(MigrationInvariantError, match="duplicate:1:1:-1:2"):
            m064_harden_product_integrity(db)
        assert db.execute(
            "SELECT COUNT(*) FROM product_bom"
        ).fetchone()[0] == 2
    finally:
        db.close()


def test_product_v64_read_only_preflight_passes_current_schema(client):
    from modules.migrations import LATEST_VERSION

    with client.application.app_context():
        report = inspect_product_integrity(get_db())
    assert report["status"] == "passed"
    assert report["schema_version"] == LATEST_VERSION
    assert report["blocking"] == {}


def test_product_v64_copy_rehearsal_migrates_without_touching_source(tmp_path):
    from modules.migrations import LATEST_VERSION, MIGRATIONS

    source = tmp_path / "source-v63.db"
    replica = tmp_path / "replica-v64.db"
    db = sqlite3.connect(source)
    db.row_factory = sqlite3.Row
    try:
        for version, _, migration in MIGRATIONS:
            if version > 63:
                break
            migration(db)
            db.execute(f"PRAGMA user_version={version}")
            db.commit()
    finally:
        db.close()

    report = rehearse_copy(source, replica)
    source_db = sqlite3.connect(source)
    replica_db = sqlite3.connect(replica)
    try:
        assert source_db.execute("PRAGMA user_version").fetchone()[0] == 63
        assert replica_db.execute("PRAGMA user_version").fetchone()[0] == LATEST_VERSION
        assert {
            row[1] for row in replica_db.execute("PRAGMA table_info(products)")
        } >= {"process_route_id"}
        assert report["status"] == "passed"
        assert report["integrity_check"] == "ok"
        assert report["foreign_key_issues"] == []
    finally:
        source_db.close()
        replica_db.close()
