#!/usr/bin/env python3
"""Read-only checks and copy-based rehearsal helpers for product v64."""

import hashlib
from pathlib import Path
import shutil
import sqlite3


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _scalar(db, sql, params=()):
    return int(db.execute(sql, params).fetchone()[0] or 0)


def inspect_product_integrity(db):
    version = int(db.execute("PRAGMA user_version").fetchone()[0])
    products = {
        "total": _scalar(db, "SELECT COUNT(*) FROM products"),
        "active": _scalar(db, "SELECT COUNT(*) FROM products WHERE deleted_at IS NULL"),
        "deleted": _scalar(db, "SELECT COUNT(*) FROM products WHERE deleted_at IS NOT NULL"),
        "blank_name": _scalar(db, "SELECT COUNT(*) FROM products WHERE TRIM(COALESCE(product_name,''))=''"),
        "blank_code": _scalar(db, "SELECT COUNT(*) FROM products WHERE TRIM(COALESCE(product_code,''))=''"),
        "duplicate_code": _scalar(
            db,
            "SELECT COUNT(*) FROM (SELECT product_code FROM products "
            "WHERE TRIM(COALESCE(product_code,''))!='' GROUP BY product_code HAVING COUNT(*)>1)",
        ),
        "invalid_category": _scalar(
            db,
            "SELECT COUNT(*) FROM products WHERE category NOT IN ('结构件','机加工')",
        ),
        "invalid_route_root": _scalar(
            db,
            "SELECT COUNT(*) FROM products p LEFT JOIN process_routes route "
            "ON route.id=p.route_id WHERE p.route_id IS NOT NULL AND route.id IS NULL",
        ),
    }
    bom = {
        "total": _scalar(db, "SELECT COUNT(*) FROM product_bom"),
        "invalid_quantity": _scalar(
            db,
            "SELECT COUNT(*) FROM product_bom WHERE quantity_per_unit IS NULL "
            "OR quantity_per_unit<=0 OR quantity_per_unit>1e308",
        ),
        "duplicate_identity": _scalar(
            db,
            "SELECT COUNT(*) FROM (SELECT product_id,material_id,COALESCE(process_id,-1) "
            "FROM product_bom GROUP BY product_id,material_id,COALESCE(process_id,-1) "
            "HAVING COUNT(*)>1)",
        ),
        "orphan_reference": _scalar(
            db,
            "SELECT COUNT(*) FROM product_bom pb "
            "LEFT JOIN products p ON p.id=pb.product_id "
            "LEFT JOIN materials m ON m.id=pb.material_id "
            "LEFT JOIN processes process ON process.id=pb.process_id "
            "WHERE p.id IS NULL OR m.id IS NULL "
            "OR (pb.process_id IS NOT NULL AND process.id IS NULL)",
        ),
    }
    aliases = {
        "total": _scalar(db, "SELECT COUNT(*) FROM product_code_aliases"),
        "ownership_conflict": _scalar(
            db,
            "SELECT COUNT(*) FROM product_code_aliases alias JOIN products product "
            "ON product.product_code=alias.product_code WHERE alias.product_id!=product.id",
        ),
        "missing_current_alias": _scalar(
            db,
            "SELECT COUNT(*) FROM products product WHERE TRIM(COALESCE(product.product_code,''))!='' "
            "AND NOT EXISTS (SELECT 1 FROM product_code_aliases alias "
            "WHERE alias.product_id=product.id AND alias.product_code=product.product_code)",
        ),
    }
    blocking = {
        "products.blank_name": products["blank_name"],
        "products.blank_code": products["blank_code"],
        "products.duplicate_code": products["duplicate_code"],
        "products.invalid_category": products["invalid_category"],
        "products.invalid_route_root": products["invalid_route_root"],
        "bom.invalid_quantity": bom["invalid_quantity"],
        "bom.duplicate_identity": bom["duplicate_identity"],
        "bom.orphan_reference": bom["orphan_reference"],
        "aliases.ownership_conflict": aliases["ownership_conflict"],
        "aliases.missing_current_alias": aliases["missing_current_alias"],
    }
    blocking = {key: value for key, value in blocking.items() if value}
    return {
        "status": "blocked" if blocking else "passed",
        "schema_version": version,
        "products": products,
        "bom": bom,
        "aliases": aliases,
        "blocking": blocking,
    }


def open_read_only(path):
    db_path = Path(path).resolve()
    db = sqlite3.connect("file:" + db_path.as_posix() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    return db


def rehearse_copy(source, destination):
    source_path = Path(source).resolve()
    destination_path = Path(destination).resolve()
    if source_path == destination_path:
        raise ValueError("演练数据库不能覆盖源数据库")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, destination_path)
    before_hash = file_sha256(source_path)
    before_size = source_path.stat().st_size

    from modules.migrations import LATEST_VERSION, run_migrations

    db = sqlite3.connect(destination_path)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA foreign_keys=ON")
        run_migrations(db)
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = [tuple(row) for row in db.execute("PRAGMA foreign_key_check")]
        report = inspect_product_integrity(db)
        report.update({
            "integrity_check": integrity,
            "foreign_key_issues": foreign_keys,
            "expected_schema_version": LATEST_VERSION,
        })
    finally:
        db.close()
    if source_path.stat().st_size != before_size or file_sha256(source_path) != before_hash:
        raise RuntimeError("演练过程中源数据库发生变化")
    if (
        report["status"] != "passed"
        or report["schema_version"] != report["expected_schema_version"]
        or report["integrity_check"] != "ok"
        or report["foreign_key_issues"]
    ):
        raise RuntimeError("产品 v64 副本演练未通过")
    report["source_sha256"] = before_hash
    report["rehearsal_sha256"] = file_sha256(destination_path)
    return report
