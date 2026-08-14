import uuid


def ensure_process_version(db, process_id):
    root = db.execute(
        "SELECT * FROM processes WHERE id=?", (process_id,)
    ).fetchone()
    if root is None:
        raise ValueError(f"missing fixture process {process_id}")
    if root["current_effective_version_id"] is not None:
        return root["current_effective_version_id"]
    version_id = db.execute(
        "INSERT INTO process_versions "
        "(process_id,version,process_code_snapshot,name,category,description,"
        "seq_order,status) VALUES (?,1,?,?,?,?,?,'draft')",
        (
            process_id,
            root["process_code"],
            root["name"],
            root["category"],
            root["description"],
            root["seq_order"],
        ),
    ).lastrowid
    db.execute(
        "UPDATE process_versions SET status='published',"
        "published_at=datetime('now','localtime') WHERE id=?",
        (version_id,),
    )
    db.execute(
        "UPDATE processes SET current_effective_version_id=?,status='active' WHERE id=?",
        (version_id, process_id),
    )
    return version_id


def ensure_route_version(db, route_id):
    root = db.execute(
        "SELECT * FROM process_routes WHERE id=?", (route_id,)
    ).fetchone()
    if root is None:
        raise ValueError(f"missing fixture route {route_id}")
    if root["current_effective_version_id"] is not None:
        return root["current_effective_version_id"]
    version_id = db.execute(
        "INSERT INTO process_route_versions "
        "(process_route_id,version,route_code_snapshot,name,category,description,status) "
        "VALUES (?,1,?,?,?,?,'draft')",
        (
            route_id,
            root["route_code"],
            root["name"],
            root["category"],
            root["description"],
        ),
    ).lastrowid
    items = db.execute(
        "SELECT process_id,seq_order,required_audit FROM process_route_items "
        "WHERE route_id=? ORDER BY seq_order,id",
        (route_id,),
    ).fetchall()
    for item in items:
        process_version_id = ensure_process_version(db, item["process_id"])
        db.execute(
            "INSERT INTO process_route_version_items "
            "(route_version_id,process_id,process_version_id,seq_order,required_audit) "
            "VALUES (?,?,?,?,?)",
            (
                version_id,
                item["process_id"],
                process_version_id,
                item["seq_order"],
                item["required_audit"],
            ),
        )
    db.execute(
        "UPDATE process_route_versions SET status='published',"
        "published_at=datetime('now','localtime') WHERE id=?",
        (version_id,),
    )
    db.execute(
        "UPDATE process_routes SET current_effective_version_id=?,status='active' WHERE id=?",
        (version_id, route_id),
    )
    return version_id


def bind_order_process_versions(db, order_id):
    order = db.execute(
        "SELECT route_id FROM orders WHERE id=?", (order_id,)
    ).fetchone()
    route_version_id = None
    if order["route_id"] is not None:
        route_version_id = ensure_route_version(db, order["route_id"])
        route_version = db.execute(
            "SELECT name FROM process_route_versions WHERE id=?", (route_version_id,)
        ).fetchone()
        db.execute(
            "UPDATE orders SET route_version_id=?,route_name_snapshot=? WHERE id=?",
            (route_version_id, route_version["name"], order_id),
        )
    rows = db.execute(
        "SELECT process_id FROM order_processes WHERE order_id=?", (order_id,)
    ).fetchall()
    for row in rows:
        if route_version_id is not None:
            item = db.execute(
                "SELECT process_version_id FROM process_route_version_items "
                "WHERE route_version_id=? AND process_id=?",
                (route_version_id, row["process_id"]),
            ).fetchone()
            process_version_id = item["process_version_id"]
        else:
            process_version_id = ensure_process_version(db, row["process_id"])
        version = db.execute(
            "SELECT process_code_snapshot,name,category FROM process_versions WHERE id=?",
            (process_version_id,),
        ).fetchone()
        db.execute(
            "UPDATE order_processes SET process_version_id=?,process_code_snapshot=?,"
            "process_name_snapshot=?,process_category_snapshot=? "
            "WHERE order_id=? AND process_id=?",
            (
                process_version_id,
                version["process_code_snapshot"],
                version["name"],
                version["category"],
                order_id,
                row["process_id"],
            ),
        )


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
        ensure_process_version(db, row["id"])
        return row["id"]
    cursor = db.execute(
        "INSERT INTO processes (name, description, category, seq_order, status, updated_at) "
        "VALUES (?, 'pytest fixture process', 'fixture', ?, 'active', datetime('now','localtime'))",
        (name, seq_order),
    )
    process_id = cursor.lastrowid
    ensure_process_version(db, process_id)
    db.commit()
    return process_id


def create_process_route(db, process_ids, name=None, category="fixture"):
    route_name = name or f"Fixture Route {uuid.uuid4().hex[:8]}"
    route_id = db.execute(
        "INSERT INTO process_routes (name, description, status, category) "
        "VALUES (?, 'pytest fixture route', 'active', ?)",
        (route_name, category),
    ).lastrowid
    for seq_order, process_id in enumerate(process_ids, start=1):
        db.execute(
            "INSERT INTO process_route_items (route_id, process_id, seq_order) "
            "VALUES (?, ?, ?)",
            (route_id, process_id, seq_order),
        )
    ensure_route_version(db, route_id)
    db.commit()
    return route_id


def create_inventory_item(
    db,
    quantity=10,
    order_id=None,
    product_model="INV-MODEL-001",
    product_name="Fixture Inventory Product",
):
    inventory_id = db.execute(
        "INSERT INTO inventory "
        "(product_model, product_name, quantity, unit, order_id, category) "
        "VALUES (?, ?, ?, '件', ?, 'finished')",
        (product_model, product_name, quantity, order_id),
    ).lastrowid
    db.commit()
    return inventory_id


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
    bind_order_process_versions(db, order_id)
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
