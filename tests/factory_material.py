import uuid


def create_material(db, quantity=100, name=None):
    material_name = name or f"Fixture Material {uuid.uuid4().hex[:8]}"
    return db.execute(
        "INSERT INTO materials (name, quantity, unit, material_type) "
        "VALUES (?, ?, '件', 'fixture')",
        (material_name, quantity),
    ).lastrowid


def add_order_material(db, order_id, material_id, process_id, quantity_per_unit=1):
    return db.execute(
        "INSERT INTO order_materials "
        "(order_id, material_id, quantity_per_unit, process_id, source) "
        "VALUES (?, ?, ?, ?, 'fixture')",
        (order_id, material_id, quantity_per_unit, process_id),
    ).lastrowid


def add_product_bom(db, product_id, material_id, process_id=None, quantity_per_unit=1):
    return db.execute(
        "INSERT INTO product_bom (product_id, material_id, quantity_per_unit, process_id) "
        "VALUES (?, ?, ?, ?)",
        (product_id, material_id, quantity_per_unit, process_id),
    ).lastrowid
