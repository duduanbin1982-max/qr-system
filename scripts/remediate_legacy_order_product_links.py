#!/usr/bin/env python3
"""Apply the manually confirmed legacy order-to-product mappings.

The mapping is deliberately explicit. It never performs fuzzy or similarity matching.
"""

import argparse
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from modules.config import DB_PATH


MAPPINGS = (
    (317, "26062902", "外壳-SB131-SJ-460-25-经济自用", 619, "SB131", "三角型", "460", "25", "historical_backup_exact"),
    (334, "26070201", "外壳-艾迪195三角外壳-SJ-500-440-35-经济自用", 10011, "艾迪195三角外壳", "三角型", "500", "35", "audit_log_manual_confirmation"),
    (341, "26070406", "外壳-30G-FT-440-25-经济自用", 10014, "30G", "分体直型", "440", "25", "historical_backup_exact"),
    (357, "26070806", "外壳-20G-FT-360-25-正坤", 10019, "20G", "分体直型", "360", "25", "historical_backup_exact"),
    (361, "26070810", "外壳-F款SB81-SJ-360-18-经济自用", 10021, "F款SB81", "三角型", "360", "18", "historical_backup_exact"),
    (363, "26070902", "外壳-F款SB81-SJ-360-18-经济自用", 10021, "F款SB81", "三角型", "360", "18", "historical_backup_exact"),
    (366, "26071301", "外壳-SB70-SJ-440-290-18-经济自用", 10023, "SB70", "三角型", "440", "18", "audit_log_manual_confirmation"),
    (371, "26071501", "外壳-F款SB81-SJ-360-18-经济自用", 10021, "F款SB81", "三角型", "360", "18", "historical_backup_exact"),
    (378, "26072202", "外壳-121-SJ-450-355-25-十条夹板丝", 10027, "SB121", "三角型", "450", "25", "historical_backup_exact"),
    (379, "26072301", "高仿贝利特-151L-SJ-510-440-30-经济自用", 10028, "高仿贝利特151L", "三角型", "510", "30", "audit_log_manual_confirmation"),
    (381, "26072501", "外壳-SB50-SJ-290-16-标准自用", 501, "SB50", "三角型", "290", "16", "historical_backup_exact"),
    (382, "26072502", "外壳-SB40-SJ-198-14-经济自用", 10029, "SB40", "三角型", "198", "14", "historical_backup_exact"),
    (383, "26072601", "外壳-仿水山195-JY-490-420-35", 10030, "仿水山195", "静音型", "490", "35", "historical_backup_exact"),
    (387, "26073001", "外壳-SB40-FT-210-175-12-包边款", 10034, "SB40", "分体直型", "210", "12", "historical_backup_exact"),
    (388, "26073002", "外壳-SB50-FT-290-240-16-包边款", 10035, "SB50", "分体直型", "290", "16", "historical_backup_exact"),
    (389, "26073003", "外壳-20G-FT-360-310-20-包边款", 10036, "20G", "分体直型", "360", "20", "historical_backup_exact"),
    (390, "26073004", "外壳-SB81-FT-360-309-20-包边", 10037, "SB81", "分体直型", "360", "20", "historical_backup_exact"),
    (391, "26073005", "外壳-30G-SJ-360-340-22-经济自用", 10038, "30G", "三角型", "360", "22", "historical_backup_exact"),
    (392, "26073006", "外壳-15G-FT-360-280-16-包边款", 10033, "HB15G", "分体直型", "360", "16", "historical_backup_exact"),
)


def _columns(db, table):
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


def _validate_schema(db):
    if "product_id" not in _columns(db, "orders"):
        raise RuntimeError("orders.product_id is missing; run database migration v50 first")
    if not db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='product_code_aliases'"
    ).fetchone():
        raise RuntimeError("product_code_aliases is missing; run database migration v50 first")


def _validate_mapping(db, mapping):
    order_id, order_no, legacy_code, product_id, model, spec, upper, thickness, _source = mapping
    order = db.execute(
        "SELECT id, order_no, product_code, product_id FROM orders WHERE id = ?",
        (order_id,),
    ).fetchone()
    if not order:
        raise RuntimeError(f"order {order_id}/{order_no} does not exist")
    if order["order_no"] != order_no or order["product_code"] != legacy_code:
        raise RuntimeError(f"order {order_id}/{order_no} no longer matches its audited snapshot")
    if order["product_id"] not in (None, product_id):
        raise RuntimeError(
            f"order {order_id}/{order_no} is already linked to product {order['product_id']}"
        )

    product = db.execute(
        "SELECT id, model, spec, upper_opening, plate_thickness FROM products WHERE id = ?",
        (product_id,),
    ).fetchone()
    expected = (product_id, model, spec, upper, thickness)
    actual = tuple(product) if product else None
    if actual != expected:
        raise RuntimeError(
            f"product {product_id} identity changed; expected {expected}, got {actual}"
        )

    alias = db.execute(
        "SELECT product_id FROM product_code_aliases WHERE product_code = ?",
        (legacy_code,),
    ).fetchone()
    if alias and alias["product_id"] != product_id:
        raise RuntimeError(
            f"legacy code {legacy_code} belongs to product {alias['product_id']}, not {product_id}"
        )


def remediate(db, apply=False):
    _validate_schema(db)
    for mapping in MAPPINGS:
        _validate_mapping(db, mapping)

    if not apply:
        return {"validated": len(MAPPINGS), "updated": 0, "aliases": 0}

    aliases_before = db.execute("SELECT COUNT(*) FROM product_code_aliases").fetchone()[0]
    updated = 0
    try:
        db.execute("BEGIN IMMEDIATE")
        for mapping in MAPPINGS:
            order_id, _order_no, legacy_code, product_id, *_rest = mapping
            db.execute(
                "INSERT INTO product_code_aliases (product_id, product_code, source) "
                "VALUES (?, ?, 'legacy_backfill') ON CONFLICT(product_code) DO NOTHING",
                (product_id, legacy_code),
            )
            cursor = db.execute(
                "UPDATE orders SET product_id = ? "
                "WHERE id = ? AND (product_id IS NULL OR product_id = ?)",
                (product_id, order_id, product_id),
            )
            updated += cursor.rowcount

        confirmed_codes = sorted({mapping[2] for mapping in MAPPINGS})
        placeholders = ",".join("?" for _ in confirmed_codes)
        db.execute(
            "UPDATE orders SET product_id = ("
            "SELECT a.product_id FROM product_code_aliases a "
            "WHERE a.product_code = orders.product_code"
            ") WHERE product_id IS NULL AND product_code IN (" + placeholders + ")",
            confirmed_codes,
        )

        for mapping in MAPPINGS:
            _validate_mapping(db, mapping)
        db.commit()
    except Exception:
        db.rollback()
        raise

    aliases_after = db.execute("SELECT COUNT(*) FROM product_code_aliases").fetchone()[0]
    return {
        "validated": len(MAPPINGS),
        "updated": updated,
        "aliases": aliases_after - aliases_before,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=DB_PATH)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try:
        result = remediate(db, apply=args.apply)
    finally:
        db.close()

    mode = "applied" if args.apply else "validated"
    print(
        f"legacy order product remediation {mode}: "
        f"validated={result['validated']} updated={result['updated']} aliases={result['aliases']}"
    )


if __name__ == "__main__":
    main()
