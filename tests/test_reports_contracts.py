import uuid

from modules.db import get_db


def _ensure_process(db):
    row = db.execute(
        "SELECT id FROM processes WHERE status = 'active' ORDER BY seq_order, id LIMIT 1"
    ).fetchone()
    if row:
        return row["id"]

    cursor = db.execute(
        "INSERT INTO processes (name, description, category, seq_order, status, updated_at) "
        "VALUES (?, ?, ?, 1, 'active', datetime('now','localtime'))",
        ("Fixture Matrix Process", "pytest fixture process", "fixture"),
    )
    return cursor.lastrowid


def _insert_matrix_work_record(db, product_code, process_id, user_id, quantity):
    product_name = f"Matrix Product {product_code}"
    db.execute(
        "INSERT INTO products (product_name, product_code, model, spec, category) "
        "VALUES (?, ?, 'MATRIX', 'Standard', 'fixture')",
        (product_name, product_code),
    )
    cursor = db.execute(
        "INSERT INTO orders (order_no, customer, product_name, product_code, quantity, status, qr_mode) "
        "VALUES (?, 'Test Customer', ?, ?, 10, 'pending', '')",
        (f"TEST-MATRIX-{uuid.uuid4().hex[:8].upper()}", product_name, product_code),
    )
    order_id = cursor.lastrowid
    db.execute(
        "INSERT INTO order_processes (order_id, process_id, seq_order, status, completed, scrapped, rework) "
        "VALUES (?, ?, 1, 'pending', 0, 0, 0)",
        (order_id, process_id),
    )
    db.execute(
        "INSERT INTO work_records (order_id, process_id, user_id, type, quantity, remark, status, serial_no) "
        "VALUES (?, ?, ?, 'normal', ?, 'matrix contract', 'approved', ?)",
        (order_id, process_id, user_id, quantity, f"MX-{uuid.uuid4().hex[:8]}"),
    )


def test_product_process_matrix_matches_frontend_contract(client, auth_headers):
    target_code = f"MATRIX-{uuid.uuid4().hex[:8].upper()}"
    other_code = f"MATRIX-{uuid.uuid4().hex[:8].upper()}"

    with client.application.app_context():
        db = get_db()
        process_id = _ensure_process(db)
        user_id = db.execute(
            "SELECT id FROM users WHERE username = 'testrunner'"
        ).fetchone()["id"]
        _insert_matrix_work_record(db, target_code, process_id, user_id, 7)
        _insert_matrix_work_record(db, other_code, process_id, user_id, 3)
        db.commit()

    response = client.get(
        f"/api/reports/product-process-matrix?product_code={target_code}",
        headers=auth_headers,
    )

    assert response.status_code == 200, response.get_json()
    data = response.get_json()
    assert data["processes"]
    assert all({"id", "name"} <= set(process) for process in data["processes"])
    assert len(data["products"]) == 1

    product = data["products"][0]
    process_index = next(
        index for index, process in enumerate(data["processes"]) if process["id"] == process_id
    )
    assert product["product_code"] == target_code
    assert isinstance(product["data"], list)
    assert len(product["data"]) == len(data["processes"])
    assert product["data"][process_index] == 7
    assert product["total"] == 7
