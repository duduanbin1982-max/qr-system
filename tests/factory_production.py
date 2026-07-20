import uuid


def ensure_customer(db, name="Test Customer"):
    row = db.execute("SELECT id FROM customers WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    return db.execute("INSERT INTO customers (name) VALUES (?)", (name,)).lastrowid


def ensure_product(db, product_code="TEST-CODE-001", product_name="Test Product"):
    row = db.execute(
        "SELECT id FROM products WHERE product_code = ?", (product_code,)
    ).fetchone()
    if row:
        return row["id"]
    return db.execute(
        "INSERT INTO products (product_name, product_code, model, spec, category) "
        "VALUES (?, ?, 'TEST', 'Standard', 'fixture')",
        (product_name, product_code),
    ).lastrowid


def ensure_process(db, name="Fixture Process", seq_order=1):
    row = db.execute("SELECT id FROM processes WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    return db.execute(
        "INSERT INTO processes (name, description, category, seq_order, status, updated_at) "
        "VALUES (?, 'pytest fixture process', 'fixture', ?, 'active', datetime('now','localtime'))",
        (name, seq_order),
    ).lastrowid


def create_order(db, process_ids, quantity=10, product_code="TEST-CODE-001"):
    order_no = f"TEST-FIXTURE-{uuid.uuid4().hex[:8].upper()}"
    order_id = db.execute(
        "INSERT INTO orders (order_no, customer, product_name, product_code, quantity, status, qr_mode) "
        "VALUES (?, 'Test Customer', 'Test Product', ?, ?, 'pending', '')",
        (order_no, product_code, quantity),
    ).lastrowid
    for seq_order, process_id in enumerate(process_ids, start=1):
        db.execute(
            "INSERT INTO order_processes "
            "(order_id, process_id, seq_order, status, completed, scrapped, rework) "
            "VALUES (?, ?, ?, 'pending', 0, 0, 0)",
            (order_id, process_id, seq_order),
        )
    db.commit()
    return order_id


def ensure_test_order(db):
    ensure_customer(db)
    ensure_product(db)
    process = db.execute(
        "SELECT id FROM processes WHERE status = 'active' ORDER BY seq_order, id LIMIT 1"
    ).fetchone()
    process_id = process["id"] if process else ensure_process(db)
    return create_order(db, [process_id])
