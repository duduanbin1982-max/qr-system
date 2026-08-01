"""Order QR-code print status migration."""

from modules.migration_helpers import add_column_if_missing


def m045_order_qr_print_status(db):
    add_column_if_missing(db, "orders", "qr_printed_at", "TEXT")
    add_column_if_missing(db, "orders", "qr_print_count", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(db, "orders", "qr_printed_by", "INTEGER")
    add_column_if_missing(db, "orders", "qr_printed_by_name", "TEXT NOT NULL DEFAULT ''")


MIGRATIONS = [
    (45, "Add order QR-code print status", m045_order_qr_print_status),
]
