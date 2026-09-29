from uuid import uuid4


def seed_product_inventory_scenario(
    db,
    *,
    code="P-1001",
    specs=("标准", "标准"),
    quantities=(5, 7),
    reserved=(1, 2),
    frozen=(0, 1),
    safe_stocks=(2, 10),
):
    suffix = uuid4().hex[:8].upper()
    product_code = f"{code}-{suffix}"
    product_id = db.execute(
        "INSERT INTO products(product_code,product_name,model,spec,category) "
        "VALUES(?, '测试产品', '', '', '结构件')",
        (product_code,),
    ).lastrowid
    db.execute(
        "INSERT OR IGNORE INTO product_code_aliases(product_id,product_code,source) "
        "VALUES(?,?,'current')",
        (product_id, product_code),
    )
    order_ids = []
    inventory_ids = []
    for index, specification in enumerate(specs):
        order_no = f"INV-GROUP-{suffix}-{index + 1}"
        order_id = db.execute(
            "INSERT INTO orders(order_no,product_code,product_id,product_name,quantity,status) "
            "VALUES(?,?,?,'测试产品',20,'pending')",
            (order_no, product_code, product_id),
        ).lastrowid
        inventory_id = db.execute(
            "INSERT INTO inventory(product_model,product_name,specification,quantity,reserved,"
            "frozen_quantity,safe_stock,location,unit,order_id,product_id,"
            "product_code_snapshot,product_name_snapshot,quality_status) "
            "VALUES(?, '测试产品', ?, ?, ?, ?, ?, ?, '件', ?, ?, ?, '测试产品', 'qualified')",
            (
                product_code, specification, quantities[index], reserved[index],
                frozen[index], safe_stocks[index], f"A-{index + 1:02d}",
                order_id, product_id, product_code,
            ),
        ).lastrowid
        order_ids.append(order_id)
        inventory_ids.append(inventory_id)
    db.commit()
    return {
        "product_id": product_id,
        "product_code": product_code,
        "order_ids": tuple(order_ids),
        "inventory_ids": tuple(inventory_ids),
    }


def seed_unresolved_inventory(db):
    suffix = uuid4().hex[:8].upper()
    inventory_id = db.execute(
        "INSERT INTO inventory(product_model,product_name,quantity,reserved,frozen_quantity,"
        "safe_stock,location,unit,product_id,product_code_snapshot,product_name_snapshot) "
        "VALUES(?, '无法识别产品', 3, 0, 0, 0, 'U-01', '件', NULL, '', '无法识别产品')",
        (f"UNKNOWN-{suffix}",),
    ).lastrowid
    db.commit()
    return inventory_id
