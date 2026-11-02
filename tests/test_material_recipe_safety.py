"""Recipe writes reject invalid quantities before they can break work reports."""

import uuid

import pytest

from factories import create_material, create_order, ensure_process, ensure_product
from modules.db import get_db
from modules.domain.errors import ValidationError
from modules.domain.material_recipe import MaterialRecipePolicy


@pytest.fixture
def recipe_entities(client):
    with client.application.app_context():
        db = get_db()
        suffix = uuid.uuid4().hex[:8]
        process_id = ensure_process(db, name=f"Recipe {suffix}")
        product_id = ensure_product(db, product_code=f"RECIPE-{suffix}")
        order_id = create_order(db, [process_id], quantity=5)
        material_id = create_material(db, quantity=100)
        db.commit()
        return {
            "process_id": process_id, "product_id": product_id,
            "order_id": order_id, "material_id": material_id,
        }


@pytest.mark.parametrize("kind", ["order", "product"])
@pytest.mark.parametrize(
    "invalid", [0, -1, True, False, None, "", "text", "NaN", "Infinity", "1e309", [], {}]
)
def test_recipe_rejects_invalid_unit_quantity_without_persisting(
    client, auth_headers, recipe_entities, kind, invalid
):
    entities = recipe_entities
    if kind == "order":
        url = f"/api/orders/{entities['order_id']}/materials"
        table = "order_materials"
    else:
        url = f"/api/products/{entities['product_id']}/bom"
        table = "product_bom"
    response = client.post(
        url,
        json={"material_id": entities["material_id"], "quantity_per_unit": invalid},
        headers=auth_headers,
    )
    assert response.status_code == 400, response.get_json()
    with client.application.app_context():
        assert get_db().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize(
    "data",
    [
        {"material_id": True}, {"material_id": 1.5}, {"material_id": "1.5"},
        {"material_id": 1, "process_id": True},
        {"material_id": 1, "process_id": -1},
        {"material_id": 1, "process_id": 1.2},
    ],
)
def test_recipe_identity_rejects_coercion(data):
    with pytest.raises(ValidationError):
        MaterialRecipePolicy.normalize(data)


def test_quantity_field_precedence_uses_presence_instead_of_truthiness():
    with pytest.raises(ValidationError):
        MaterialRecipePolicy.normalize(
            {"material_id": 1, "quantity": 0, "quantity_per_unit": 8},
            quantity_field="quantity",
        )
    assert MaterialRecipePolicy.normalize(
        {"material_id": "1", "quantity": "2.5", "quantity_per_unit": 8},
        quantity_field="quantity",
    )["quantity_per_unit"] == 2.5


@pytest.mark.parametrize("field", ["material_id", "process_id"])
def test_order_recipe_rejects_missing_reference(
    client, auth_headers, recipe_entities, field
):
    payload = {
        "material_id": recipe_entities["material_id"],
        "process_id": recipe_entities["process_id"],
        "quantity": 2,
    }
    payload[field] = 999999
    response = client.post(
        f"/api/orders/{recipe_entities['order_id']}/materials",
        json=payload, headers=auth_headers,
    )
    assert response.status_code == 404, response.get_json()


def test_order_recipe_accepts_positive_decimal_and_explicit_common_scope(
    client, auth_headers, recipe_entities
):
    response = client.post(
        f"/api/orders/{recipe_entities['order_id']}/materials",
        json={
            "material_id": recipe_entities["material_id"],
            "quantity": "2.5", "process_id": None,
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.get_json()
    with client.application.app_context():
        row = get_db().execute("SELECT * FROM order_materials").fetchone()
        assert row["quantity_per_unit"] == 2.5
        assert row["process_id"] is None
