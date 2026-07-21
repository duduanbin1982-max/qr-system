"""Order completion state migrations."""


def m032_remove_legacy_order_status_from_extra_fields(db):
    db.execute(
        "UPDATE orders SET extra_fields = json_remove(extra_fields, '$.status') "
        "WHERE json_valid(extra_fields) "
        "AND json_type(extra_fields, '$.status') IS NOT NULL"
    )
    db.commit()


MIGRATIONS = [
    (32, "Remove legacy duplicate order status from extra fields", m032_remove_legacy_order_status_from_extra_fields),
]
