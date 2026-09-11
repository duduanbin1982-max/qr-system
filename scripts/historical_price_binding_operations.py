#!/usr/bin/env python3
"""Preflight and apply controlled historical exact-price repairs."""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any

from scripts.production_operations import (
    ProductionOperationError,
    open_read_only_sqlite,
    write_evidence_json,
)


SCHEMA = "qr-system-historical-price-binding-repair/v1"
INFINITY = "9999-12-31 23:59:59"
SETTLEMENT_DECISIONS = {"settle", "zero_price", "no_settlement"}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


def _table_exists(db: sqlite3.Connection, table: str) -> bool:
    return bool(
        db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
    )


def _required_schema(db: sqlite3.Connection) -> None:
    required = {
        "orders": {"id", "order_no", "route_id", "route_version_id"},
        "work_records": {
            "id", "order_id", "route_id", "route_version_id", "process_id",
            "process_version_id", "quantity", "status", "type", "created_at",
        },
        "route_price_versions": {
            "id", "route_id", "route_version_id", "process_id", "process_version_id",
            "normal_unit_price_micros", "rework_rate_basis_points",
            "rework_rate_configured", "valid_from", "valid_to", "status",
        },
        "process_route_versions": {"id", "process_route_id", "status", "content_digest"},
        "process_route_version_items": {
            "route_version_id", "process_id", "process_version_id",
        },
        "process_versions": {"id", "process_id", "status", "content_digest"},
    }
    for table, expected in required.items():
        actual = _columns(db, table)
        missing = expected - actual
        if missing:
            raise ProductionOperationError(
                "schema", f"{table} missing required columns: {','.join(sorted(missing))}"
            )


def _missing_facts(db: sqlite3.Connection) -> list[dict[str, Any]]:
    settlement_exclusion = ""
    if _table_exists(db, "historical_price_binding_settlement_facts"):
        settlement_exclusion = """
          AND NOT EXISTS (
            SELECT 1
            FROM historical_price_binding_settlement_facts settlement_fact
            JOIN historical_price_binding_settlements settlement
              ON settlement.id=settlement_fact.settlement_id
            WHERE settlement_fact.work_record_id=wr.id
              AND settlement.decision='no_settlement'
          )
        """
    rows = db.execute(
        """
        SELECT wr.id AS work_record_id,o.id AS order_id,o.order_no,
               COALESCE(o.product_code,'') AS product_code,
               COALESCE(o.product_name,'') AS product_name,
               COALESCE(wr.route_id,o.route_id) AS route_id,wr.route_version_id,
               wr.process_id,wr.process_version_id,wr.quantity,wr.created_at,
               route_version.name AS route_name,
               route_version.content_digest AS route_content_digest,
               process_version.name AS process_name,
               process_version.content_digest AS process_content_digest
        FROM work_records wr
        JOIN orders o ON o.id=wr.order_id
        JOIN process_route_versions route_version ON route_version.id=wr.route_version_id
        JOIN process_versions process_version ON process_version.id=wr.process_version_id
        WHERE wr.status='approved' AND wr.type='normal'
          AND wr.route_version_id IS NOT NULL AND wr.process_version_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM route_price_versions price
            WHERE price.route_version_id=wr.route_version_id
              AND price.process_version_id=wr.process_version_id
              AND price.status='approved'
              AND price.valid_from<=wr.created_at
              AND (COALESCE(price.valid_to,'')='' OR price.valid_to>wr.created_at)
          )
        """ + settlement_exclusion + """
        ORDER BY wr.id
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _root_candidates(db: sqlite3.Connection, fact: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in db.execute(
            """
            SELECT * FROM route_price_versions
            WHERE route_id=? AND process_id=? AND status='approved'
              AND valid_from<=?
              AND (COALESCE(valid_to,'')='' OR valid_to>?)
            ORDER BY valid_from DESC,id DESC
            """,
            (fact["route_id"], fact["process_id"], fact["created_at"], fact["created_at"]),
        ).fetchall()
    ]


def _other_root_candidates(db: sqlite3.Connection, fact: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in db.execute(
            """
            SELECT price.id,price.route_version_id,price.process_version_id,
                   price.normal_unit_price_micros,price.rework_rate_basis_points,
                   price.rework_rate_configured,price.valid_from,price.valid_to,price.status,
                   COALESCE(route_version.name,route.name,'') AS route_name,
                   route_version.version AS route_version,
                   COALESCE(process_version.name,process.name,'') AS process_name,
                   process_version.version AS process_version
            FROM route_price_versions price
            LEFT JOIN process_routes route ON route.id=price.route_id
            LEFT JOIN process_route_versions route_version
              ON route_version.id=price.route_version_id
            LEFT JOIN processes process ON process.id=price.process_id
            LEFT JOIN process_versions process_version
              ON process_version.id=price.process_version_id
            WHERE price.route_id=? AND price.process_id=? AND price.status='approved'
            ORDER BY price.valid_from,price.id
            """,
            (fact["route_id"], fact["process_id"]),
        ).fetchall()
    ]


def _target_intervals(db: sqlite3.Connection, fact: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in db.execute(
            """
            SELECT id,valid_from,valid_to FROM route_price_versions
            WHERE route_version_id=? AND process_version_id=? AND status='approved'
            ORDER BY valid_from,id
            """,
            (fact["route_version_id"], fact["process_version_id"]),
        ).fetchall()
    ]


def _available_segment(
    source: dict[str, Any], intervals: list[dict[str, Any]], timestamp: str
) -> tuple[str, str | None]:
    lower = source["valid_from"]
    upper = source.get("valid_to") or INFINITY
    for interval in intervals:
        start = interval["valid_from"]
        end = interval.get("valid_to") or INFINITY
        if end <= timestamp and end > lower:
            lower = end
        elif start > timestamp and start < upper:
            upper = start
    if not (lower <= timestamp < upper):
        raise ProductionOperationError(
            "integrity", f"cannot derive non-overlapping interval for work at {timestamp}"
        )
    return lower, None if upper == INFINITY else upper


def _fact_evidence(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [
        {
            "id": int(row["work_record_id"]),
            "order_id": int(row["order_id"]),
            "order_no": str(row["order_no"]),
            "quantity": int(row["quantity"] or 0),
            "created_at": row["created_at"],
            "route_id": int(row["route_id"] or 0),
            "route_version_id": int(row["route_version_id"] or 0),
            "process_id": int(row["process_id"] or 0),
            "process_version_id": int(row["process_version_id"] or 0),
        }
        for row in sorted(rows, key=lambda item: int(item["work_record_id"]))
    ]
    return {
        "work_record_ids": [item["id"] for item in values],
        "work_record_digest": _digest(values),
        "work_record_count": len(values),
        "quantity": sum(item["quantity"] for item in values),
        "order_ids": sorted({item["order_id"] for item in values}),
        "order_nos": sorted({item["order_no"] for item in values}),
        "first_work_at": min(item["created_at"] for item in values),
        "last_work_at": max(item["created_at"] for item in values),
    }


def business_order_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return business-readable affected-order rows; never expose manual keys."""
    grouped: dict[tuple[int, str], dict[str, Any]] = {}
    for row in sorted(rows, key=lambda item: (str(item["order_no"]), int(item["work_record_id"]))):
        key = (int(row["order_id"]), str(row["order_no"]))
        item = grouped.setdefault(key, {
            "order_id": key[0],
            "order_no": key[1],
            "product_code": str(row.get("product_code") or ""),
            "product_name": str(row.get("product_name") or ""),
            "work_record_count": 0,
            "quantity": 0,
            "first_work_at": row["created_at"],
            "last_work_at": row["created_at"],
        })
        item["work_record_count"] += 1
        item["quantity"] += int(row.get("quantity") or 0)
        item["first_work_at"] = min(item["first_work_at"], row["created_at"])
        item["last_work_at"] = max(item["last_work_at"], row["created_at"])
    return list(grouped.values())


def build_preflight(db: sqlite3.Connection) -> dict[str, Any]:
    _required_schema(db)
    user_version = int(db.execute("PRAGMA user_version").fetchone()[0])
    facts = _missing_facts(db)
    clone_groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    manual_groups: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    manual_candidates: dict[tuple[int, int], list[dict[str, Any]]] = {}

    for fact in facts:
        candidates = _root_candidates(db, fact)
        if len(candidates) == 1:
            source = candidates[0]
            segment = _available_segment(source, _target_intervals(db, fact), fact["created_at"])
            key = (
                int(source["id"]), int(fact["route_version_id"]),
                int(fact["process_version_id"]), segment[0], segment[1],
            )
            clone_groups[key].append(fact)
        else:
            key = (int(fact["route_version_id"]), int(fact["process_version_id"]))
            manual_groups[key].append(fact)
            candidates_for_review = _other_root_candidates(db, fact)
            if key not in manual_candidates:
                manual_candidates[key] = candidates_for_review
            elif manual_candidates[key] != candidates_for_review:
                raise ProductionOperationError(
                    "integrity", "manual candidate set changed within one exact binding"
                )

    items: list[dict[str, Any]] = []
    for key, rows in sorted(clone_groups.items()):
        source_id, route_version_id, process_version_id, valid_from, valid_to = key
        source = dict(
            db.execute("SELECT * FROM route_price_versions WHERE id=?", (source_id,)).fetchone()
        )
        sample = rows[0]
        evidence = _fact_evidence(rows)
        item = {
            "action": "clone",
            "source_price_version_id": source_id,
            "target_route_id": int(sample["route_id"]),
            "target_route_version_id": route_version_id,
            "target_process_id": int(sample["process_id"]),
            "target_process_version_id": process_version_id,
            "target_route_name": sample["route_name"],
            "target_process_name": sample["process_name"],
            "target_route_content_digest": sample["route_content_digest"],
            "target_process_content_digest": sample["process_content_digest"],
            "normal_unit_price_micros": int(source["normal_unit_price_micros"]),
            "rework_rate_basis_points": int(source["rework_rate_basis_points"] or 0),
            "rework_rate_configured": int(source["rework_rate_configured"] or 0),
            "valid_from": valid_from,
            "valid_to": valid_to,
            "source_route_version_id": source.get("route_version_id"),
            "source_process_version_id": source.get("process_version_id"),
            **evidence,
        }
        item["item_key"] = (
            f"clone:{source_id}:{route_version_id}:{process_version_id}:"
            f"{_digest({'from': valid_from, 'to': valid_to})[:16]}"
        )
        item["price_idempotency_key"] = "historical-price:" + item["item_key"]
        item["item_digest"] = _digest(item)
        items.append(item)

    for key, rows in sorted(manual_groups.items()):
        route_version_id, process_version_id = key
        sample = rows[0]
        evidence = _fact_evidence(rows)
        candidates = manual_candidates[key]
        item = {
            "action": "manual",
            "source_price_version_id": None,
            "target_route_id": int(sample["route_id"]),
            "target_route_version_id": route_version_id,
            "target_process_id": int(sample["process_id"]),
            "target_process_version_id": process_version_id,
            "target_route_name": sample["route_name"],
            "target_process_name": sample["process_name"],
            "target_route_content_digest": sample["route_content_digest"],
            "target_process_content_digest": sample["process_content_digest"],
            "normal_unit_price_micros": None,
            "rework_rate_basis_points": None,
            "rework_rate_configured": None,
            "valid_from": None,
            "valid_to": None,
            "candidate_source_prices": candidates,
            "manual_reason": (
                "no approved root price covers the affected work timestamps"
                if candidates else "no approved root price exists"
            ),
            "manual_decision_reason": "",
            "manual_decision_by": None,
            "manual_decision_at": "",
            "manual_parent_item_key": "",
            **evidence,
        }
        item["affected_orders"] = business_order_summary(rows)
        item["item_key"] = f"manual:{route_version_id}:{process_version_id}"
        item["price_idempotency_key"] = "historical-price:" + item["item_key"]
        item["item_digest"] = _digest(item)
        items.append(item)

    snapshot = [
        {
            "id": int(row["work_record_id"]),
            "route_version_id": int(row["route_version_id"]),
            "process_version_id": int(row["process_version_id"]),
            "quantity": int(row["quantity"] or 0),
            "created_at": row["created_at"],
        }
        for row in facts
    ]
    result = {
        "schema": SCHEMA,
        "status": "draft",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "database_user_version": user_version,
        "missing_fact_digest": _digest(snapshot),
        "approval": {
            "operator_id": None,
            "operator_name": "",
            "approver_id": None,
            "approver_name": "",
            "approved_at": "",
            "reason": "",
            "idempotency_key": "",
        },
        "summary": {
            "missing_work_record_count": len(facts),
            "missing_quantity": sum(int(row["quantity"] or 0) for row in facts),
            "affected_order_count": len({int(row["order_id"]) for row in facts}),
            "affected_route_version_count": len(
                {int(row["route_version_id"]) for row in facts}
            ),
            "clone_item_count": sum(item["action"] == "clone" for item in items),
            "manual_item_count": sum(item["action"] == "manual" for item in items),
        },
        "items": items,
    }
    result["draft_digest"] = _digest(result)
    return result


def _load_manifest(path: str | Path) -> dict[str, Any]:
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    if manifest.get("schema") != SCHEMA:
        raise ProductionOperationError("argument", "unsupported repair manifest schema")
    return manifest


def _manifest_digest(manifest: dict[str, Any]) -> str:
    payload = dict(manifest)
    payload.pop("manifest_digest", None)
    payload.pop("draft_digest", None)
    return _digest(payload)


def _settlement_decision(item: dict[str, Any]) -> str:
    explicit = str(item.get("settlement_decision") or "").strip()
    if explicit:
        return explicit
    if item.get("action") == "clone":
        return "settle"
    required = (
        "normal_unit_price_micros", "rework_rate_basis_points",
        "rework_rate_configured", "valid_from",
    )
    return "settle" if all(item.get(key) is not None for key in required) else ""


def _validate_approval(manifest: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("status") != "approved":
        raise ProductionOperationError("authorization", "manifest status must be approved")
    approval = manifest.get("approval") or {}
    required = (
        "operator_id", "operator_name", "approver_id", "approver_name",
        "approved_at", "reason", "idempotency_key",
    )
    if any(approval.get(key) in (None, "") for key in required):
        raise ProductionOperationError("authorization", "manifest approval is incomplete")
    if int(approval["operator_id"]) == int(approval["approver_id"]):
        raise ProductionOperationError("authorization", "operator and approver must differ")
    if not manifest.get("items"):
        raise ProductionOperationError("argument", "manifest contains no repair items")
    for item in manifest["items"]:
        if item.get("action") not in ("clone", "manual"):
            raise ProductionOperationError("argument", f"unsupported repair action: {item.get('item_key')}")
        decision = _settlement_decision(item)
        if decision not in SETTLEMENT_DECISIONS and decision != "":
            raise ProductionOperationError(
                "authorization", f"unsupported settlement decision: {item.get('item_key')}"
            )
        if item.get("action") == "clone" and decision != "settle":
            raise ProductionOperationError(
                "authorization", f"clone item cannot use {decision}: {item.get('item_key')}"
            )
        required_price = (
            "normal_unit_price_micros", "rework_rate_basis_points",
            "rework_rate_configured", "valid_from",
        )
        if item.get("action") == "clone" and any(item.get(key) is None for key in required_price):
            raise ProductionOperationError(
                "authorization", f"clone price data incomplete: {item.get('item_key')}"
            )
        if item.get("action") == "manual":
            if decision == "no_settlement":
                if any(item.get(key) is not None for key in required_price):
                    raise ProductionOperationError(
                        "authorization", f"no-settlement item must not carry price data: {item.get('item_key')}"
                    )
                if not str(item.get("manual_decision_reason") or "").strip():
                    raise ProductionOperationError(
                        "authorization", f"no-settlement reason is required: {item.get('item_key')}"
                    )
                if item.get("manual_decision_by") in (None, ""):
                    raise ProductionOperationError(
                        "authorization", f"no-settlement decision actor is required: {item.get('item_key')}"
                    )
                if not str(item.get("manual_decision_by_name") or "").strip():
                    raise ProductionOperationError(
                        "authorization", f"no-settlement decision actor name is required: {item.get('item_key')}"
                    )
                if not str(item.get("manual_decision_at") or "").strip():
                    raise ProductionOperationError(
                        "authorization", f"no-settlement decision time is required: {item.get('item_key')}"
                    )
                continue
            supplied = [item.get(key) is not None for key in required_price]
            if any(supplied) and not all(supplied):
                raise ProductionOperationError(
                    "authorization", f"manual decision price data incomplete: {item.get('item_key')}"
                )
            if all(supplied):
                if not str(item.get("manual_decision_reason") or "").strip():
                    raise ProductionOperationError(
                        "authorization", f"manual decision reason is required: {item.get('item_key')}"
                    )
                if item.get("manual_decision_by") in (None, "") or not str(item.get("manual_decision_at") or "").strip():
                    raise ProductionOperationError(
                        "authorization", f"manual decision actor/time is required: {item.get('item_key')}"
                    )
                if not str(item.get("manual_parent_item_key") or "").strip():
                    raise ProductionOperationError(
                        "authorization", f"manual parent item key is required: {item.get('item_key')}"
                    )
                if decision == "settle" and int(item.get("normal_unit_price_micros") or 0) <= 0:
                    raise ProductionOperationError(
                        "authorization", f"settle item price must be positive: {item.get('item_key')}"
                    )
                if decision == "zero_price" and (
                    item.get("normal_unit_price_micros") is None
                    or int(item["normal_unit_price_micros"]) != 0
                ):
                    raise ProductionOperationError(
                        "authorization", f"zero-price item must use zero unit price: {item.get('item_key')}"
                    )
    return approval


def _validate_actor_identity(
    db: sqlite3.Connection,
    actor_id: int,
    actor_name: str,
    label: str,
) -> sqlite3.Row:
    """Resolve an approval actor against the database before opening a write transaction.

    Approval manifests store the database user primary key, not the login username.
    Production has historically used numeric usernames whose values differ from the
    internal user IDs, so relying on a foreign-key failure would be both opaque and
    too late.  Fail closed on missing, inactive, deleted, or mismatched identities.
    """
    try:
        normalized_id = int(actor_id)
    except (TypeError, ValueError) as exc:
        raise ProductionOperationError(
            "authorization", f"{label} database user id is invalid: {actor_id}"
        ) from exc
    normalized_name = str(actor_name or "").strip()
    row = db.execute(
        "SELECT id,username,name,status,deleted_at FROM users WHERE id=?",
        (normalized_id,),
    ).fetchone()
    if not row:
        raise ProductionOperationError(
            "authorization",
            f"{label} database user does not exist: {normalized_id}",
        )
    if row["status"] != "active" or row["deleted_at"] not in (None, ""):
        raise ProductionOperationError(
            "authorization",
            f"{label} database user is not active: {row['username']}",
        )
    if str(row["name"] or "").strip() != normalized_name:
        raise ProductionOperationError(
            "authorization",
            f"{label} name does not match database identity: {normalized_name}",
        )
    return row


def _work_rows(db: sqlite3.Connection, ids: list[int]) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in ids)
    return [
        dict(row)
        for row in db.execute(
            "SELECT wr.id AS work_record_id,wr.order_id,o.order_no,wr.quantity,wr.created_at,"
            "wr.route_id,wr.route_version_id,wr.process_id,wr.process_version_id "
            "FROM work_records wr JOIN orders o ON o.id=wr.order_id "
            f"WHERE wr.id IN ({placeholders}) ORDER BY wr.id",
            ids,
        ).fetchall()
    ]


def _validate_item(db: sqlite3.Connection, item: dict[str, Any]) -> list[dict[str, Any]]:
    route = db.execute(
        "SELECT * FROM process_route_versions WHERE id=? AND process_route_id=?",
        (item["target_route_version_id"], item["target_route_id"]),
    ).fetchone()
    process = db.execute(
        "SELECT * FROM process_versions WHERE id=? AND process_id=?",
        (item["target_process_version_id"], item["target_process_id"]),
    ).fetchone()
    node = db.execute(
        "SELECT 1 FROM process_route_version_items WHERE route_version_id=? "
        "AND process_id=? AND process_version_id=?",
        (
            item["target_route_version_id"], item["target_process_id"],
            item["target_process_version_id"],
        ),
    ).fetchone()
    if not route or not process or not node:
        raise ProductionOperationError("integrity", f"invalid exact target: {item['item_key']}")
    if route["content_digest"] != item["target_route_content_digest"]:
        raise ProductionOperationError("integrity", f"route digest changed: {item['item_key']}")
    if process["content_digest"] != item["target_process_content_digest"]:
        raise ProductionOperationError("integrity", f"process digest changed: {item['item_key']}")
    if item["action"] == "clone":
        source = db.execute(
            "SELECT * FROM route_price_versions WHERE id=?", (item["source_price_version_id"],)
        ).fetchone()
        if not source or source["status"] != "approved":
            raise ProductionOperationError("integrity", f"source price unavailable: {item['item_key']}")
        for key in (
            "normal_unit_price_micros", "rework_rate_basis_points", "rework_rate_configured",
        ):
            if int(source[key] or 0) != int(item[key] or 0):
                raise ProductionOperationError("integrity", f"source price changed: {item['item_key']}")
    rows = _work_rows(db, [int(value) for value in item["work_record_ids"]])
    evidence = _fact_evidence(rows)
    if evidence["work_record_digest"] != item["work_record_digest"]:
        raise ProductionOperationError("integrity", f"work evidence changed: {item['item_key']}")
    for row in rows:
        if (
            int(row["route_id"] or 0) != int(item["target_route_id"])
            or int(row["route_version_id"] or 0) != int(item["target_route_version_id"])
            or int(row["process_id"] or 0) != int(item["target_process_id"])
            or int(row["process_version_id"] or 0) != int(item["target_process_version_id"])
        ):
            raise ProductionOperationError(
                "integrity", f"work fact exact binding changed: {item['item_key']}"
            )
        if item.get("valid_from"):
            if not (item["valid_from"] <= row["created_at"] < (item.get("valid_to") or INFINITY)):
                raise ProductionOperationError("integrity", f"repair interval misses work: {item['item_key']}")
    return rows


def _insert_repair_item(
    db: sqlite3.Connection,
    run_id: int,
    item: dict[str, Any],
) -> int:
    existing = db.execute(
        "SELECT id,run_id,action,target_price_version_id FROM "
        "historical_price_binding_repair_items WHERE item_key=?",
        (item["item_key"],),
    ).fetchone()
    if existing:
        raise ProductionOperationError(
            "idempotency", f"repair item already exists and is immutable: {item['item_key']}"
        )
    if item.get("action") == "manual" and item.get("manual_parent_item_key"):
        parent = db.execute(
            "SELECT * FROM historical_price_binding_repair_items WHERE item_key=?",
            (item["manual_parent_item_key"],),
        ).fetchone()
        if not parent or parent["action"] != "manual" or parent["target_price_version_id"] is not None:
            raise ProductionOperationError(
                "integrity", f"manual parent item is invalid: {item['item_key']}"
            )
        for key in (
            "target_route_id", "target_route_version_id", "target_process_id",
            "target_process_version_id", "target_route_content_digest",
            "target_process_content_digest", "affected_work_record_digest",
        ):
            item_key = "work_record_digest" if key == "affected_work_record_digest" else key
            if parent[key] != item.get(item_key):
                raise ProductionOperationError(
                    "integrity", f"manual parent evidence mismatch: {item['item_key']}"
                )
    cursor = db.execute(
        """
        INSERT INTO historical_price_binding_repair_items (
            run_id,item_key,action,source_price_version_id,target_route_id,
            target_route_version_id,target_process_id,target_process_version_id,
            normal_unit_price_micros,rework_rate_basis_points,rework_rate_configured,
            valid_from,valid_to,target_route_content_digest,target_process_content_digest,
            affected_work_record_count,affected_quantity,affected_work_record_digest,
            manual_decision_reason,manual_decision_by,manual_decision_at,manual_parent_item_key,
            settlement_decision
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            run_id,item["item_key"],item["action"],item.get("source_price_version_id"),
            item["target_route_id"],item["target_route_version_id"],
            item["target_process_id"],item["target_process_version_id"],
            item.get("normal_unit_price_micros"),item.get("rework_rate_basis_points"),
            item.get("rework_rate_configured"),item.get("valid_from"),item.get("valid_to"),
            item["target_route_content_digest"],item["target_process_content_digest"],
            item["work_record_count"],item["quantity"],item["work_record_digest"],
            item.get("manual_decision_reason", ""),item.get("manual_decision_by"),
            item.get("manual_decision_at", ""),item.get("manual_parent_item_key", ""),
            _settlement_decision(item) or "settle",
        ),
    )
    return int(cursor.lastrowid)


def _insert_settlement_decision(
    db: sqlite3.Connection,
    repair_item_id: int,
    item: dict[str, Any],
    approval: dict[str, Any],
    price_version_id: int | None = None,
) -> int:
    """Persist a V083.1 zero-price or no-settlement decision and its facts."""
    decision = _settlement_decision(item)
    if decision not in {"zero_price", "no_settlement"}:
        return 0
    facts = _work_rows(db, [int(value) for value in item["work_record_ids"]])
    if not facts:
        raise ProductionOperationError(
            "integrity", f"settlement has no current work facts: {item['item_key']}"
        )
    evidence = _fact_evidence(facts)
    actor_id = int(item.get("manual_decision_by") or approval["operator_id"])
    actor_name = str(
        item.get("manual_decision_by_name")
        or item.get("manual_decision_name")
        or approval["operator_name"]
    )
    _validate_actor_identity(db, actor_id, actor_name, "settlement decision")
    decided_at = str(item.get("manual_decision_at") or approval["approved_at"])
    reason = str(item.get("manual_decision_reason") or approval["reason"]).strip()
    key = str(
        item.get("settlement_idempotency_key")
        or f"historical-price-settlement:{approval['idempotency_key']}:{item['item_key']}"
    )
    existing = db.execute(
        "SELECT id FROM historical_price_binding_settlements WHERE idempotency_key=?",
        (key,),
    ).fetchone()
    if existing:
        return int(existing[0])
    cursor = db.execute(
        """
        INSERT INTO historical_price_binding_settlements (
            repair_item_id,decision,price_version_id,reason,decided_by,decided_by_name,
            decided_at,idempotency_key,evidence_digest
        ) VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (
            repair_item_id, decision, price_version_id, reason, actor_id, actor_name,
            decided_at, key, evidence["work_record_digest"],
        ),
    )
    settlement_id = int(cursor.lastrowid)
    for row in facts:
        db.execute(
            """
            INSERT INTO historical_price_binding_settlement_facts (
                settlement_id,work_record_id,quantity,created_at,snapshot_json
            ) VALUES (?,?,?,?,?)
            """,
            (
                settlement_id, int(row["work_record_id"]), int(row["quantity"] or 0),
                row["created_at"], _json(row),
            ),
        )
    return settlement_id


def _insert_price(
    db: sqlite3.Connection,
    run_id: int,
    item: dict[str, Any],
    approval: dict[str, Any],
) -> int:
    repair_item_id = _insert_repair_item(db, run_id, item)
    remark = (
        "Controlled historical exact-price repair; "
        f"run={approval['idempotency_key']}; source={item.get('source_price_version_id') or 'manual'}"
    )
    price = db.execute(
        """
        INSERT INTO route_price_versions (
            route_id,process_id,normal_unit_price_micros,rework_rate_basis_points,
            rework_rate_configured,valid_from,valid_to,status,created_by,created_by_name,
            approved_by,approved_by_name,approved_at,remark,row_version,
            route_version_id,process_version_id,legacy_binding_unavailable,
            idempotency_key,request_digest,route_content_digest_snapshot,
            process_content_digest_snapshot,historical_price_repair_item_id
        ) VALUES (?,?,?,?,?,?,?,'approved',?,?,?,?,?,?,0,?,?,0,?,?,?,?,?)
        """,
        (
            item["target_route_id"],item["target_process_id"],
            item["normal_unit_price_micros"],item["rework_rate_basis_points"],
            item["rework_rate_configured"],item["valid_from"],item.get("valid_to"),
            approval["operator_id"],approval["operator_name"],
            approval["approver_id"],approval["approver_name"],approval["approved_at"],
            remark,item["target_route_version_id"],item["target_process_version_id"],
            item["price_idempotency_key"],item["item_digest"],
            item["target_route_content_digest"],item["target_process_content_digest"],
            repair_item_id,
        ),
    )
    price_id = int(price.lastrowid)
    db.execute(
        "UPDATE historical_price_binding_repair_items "
        "SET target_price_version_id=?,applied_at=datetime('now','localtime') WHERE id=?",
        (price_id, repair_item_id),
    )
    _insert_settlement_decision(db, repair_item_id, item, approval, price_id)
    return price_id


def _insert_no_settlement(
    db: sqlite3.Connection,
    run_id: int,
    item: dict[str, Any],
    approval: dict[str, Any],
) -> int:
    """Resolve a manual item without inventing a route-price row."""
    # A confirmation manifest may carry the original preflight item key, or
    # an explicit child item linked through manual_parent_item_key.  Reuse the
    # original pending evidence when present; never duplicate its unique key.
    existing = db.execute(
        "SELECT id,action,target_price_version_id FROM "
        "historical_price_binding_repair_items WHERE item_key=?",
        (item["item_key"],),
    ).fetchone()
    if existing:
        if existing["action"] != "manual" or existing["target_price_version_id"] is not None:
            raise ProductionOperationError(
                "integrity", f"no-settlement item is already resolved: {item['item_key']}"
            )
        repair_item_id = int(existing["id"])
        db.execute(
            "UPDATE historical_price_binding_repair_items "
            "SET settlement_decision='no_settlement' WHERE id=?",
            (repair_item_id,),
        )
    else:
        repair_item_id = _insert_repair_item(db, run_id, item)
    _insert_settlement_decision(db, repair_item_id, item, approval, None)
    return repair_item_id


def apply_manifest(database: str | Path, manifest: dict[str, Any]) -> dict[str, Any]:
    approval = _validate_approval(manifest)
    database_path = Path(database).expanduser().resolve()
    db = sqlite3.connect(str(database_path))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        if int(db.execute("PRAGMA user_version").fetchone()[0]) != 83:
            raise ProductionOperationError("schema", "historical price repair requires database v83")
        _validate_actor_identity(
            db, approval["operator_id"], approval["operator_name"], "operator"
        )
        _validate_actor_identity(
            db, approval["approver_id"], approval["approver_name"], "approver"
        )
        digest = _manifest_digest(manifest)
        declared_digest = manifest.get("manifest_digest")
        if declared_digest and declared_digest != digest:
            raise ProductionOperationError("integrity", "manifest digest does not match content")
        existing = db.execute(
            "SELECT * FROM historical_price_binding_repair_runs WHERE idempotency_key=?",
            (approval["idempotency_key"],),
        ).fetchone()
        if existing:
            if existing["manifest_digest"] != digest or existing["status"] not in ("partially_applied", "applied"):
                raise ProductionOperationError("idempotency", "repair key was used by another request")
            return {
                "status": "succeeded", "replayed": True, "run_id": existing["id"],
                "idempotency_key": approval["idempotency_key"],
            }
        db.execute("BEGIN IMMEDIATE")
        before = build_preflight(db)["summary"]
        cursor = db.execute(
            """
            INSERT INTO historical_price_binding_repair_runs (
                idempotency_key,manifest_digest,status,operator_id,operator_name,
                approver_id,approver_name,approved_at,reason,source_user_version,
                target_user_version,before_summary_json,manifest_json
            ) VALUES (?,?,'approved',?,?,?,?,?,?,?,?,?,?)
            """,
            (
                approval["idempotency_key"],digest,approval["operator_id"],
                approval["operator_name"],approval["approver_id"],approval["approver_name"],
                approval["approved_at"],approval["reason"],
                manifest["database_user_version"],83,_json(before),_json(manifest),
            ),
        )
        run_id = int(cursor.lastrowid)
        created = []
        deferred_manual = []
        for item in manifest["items"]:
            _validate_item(db, item)
            decision = _settlement_decision(item)
            if item.get("action") == "manual" and decision == "no_settlement":
                _insert_no_settlement(db, run_id, item, approval)
                created.append({"decision": decision, "item_key": item["item_key"]})
                continue
            complete_manual = item.get("action") == "manual" and all(
                item.get(key) is not None
                for key in ("normal_unit_price_micros", "rework_rate_basis_points", "rework_rate_configured", "valid_from")
            )
            if item.get("action") == "manual" and not complete_manual:
                _insert_repair_item(db, run_id, item)
                deferred_manual.append(item["item_key"])
            else:
                created.append(_insert_price(db, run_id, item, approval))
        after = build_preflight(db)["summary"]
        repaired_ids = {
            int(work_id)
            for item in manifest["items"]
            if item.get("action") == "clone"
            or _settlement_decision(item) == "no_settlement"
            or all(
                item.get(key) is not None
                for key in (
                    "normal_unit_price_micros", "rework_rate_basis_points",
                    "rework_rate_configured", "valid_from",
                )
            )
            for work_id in item["work_record_ids"]
        }
        remaining_ids = {int(row["work_record_id"]) for row in _missing_facts(db)}
        unresolved = sorted(repaired_ids & remaining_ids)
        if unresolved:
            raise ProductionOperationError(
                "integrity", f"repair left {len(unresolved)} authorized work records unresolved"
            )
        final_status = "partially_applied" if deferred_manual else "applied"
        db.execute(
            "UPDATE historical_price_binding_repair_runs "
            "SET status=?,after_summary_json=?,applied_at=CASE WHEN ?='applied' "
            "THEN datetime('now','localtime') ELSE applied_at END "
            "WHERE id=? AND status='approved'",
            (final_status, _json(after), final_status, run_id),
        )
        db.commit()
        return {
            "status": "succeeded", "replayed": False, "run_id": run_id,
            "idempotency_key": approval["idempotency_key"],
            "created_price_version_ids": created, "before": before, "after": after,
            "deferred_manual_item_keys": deferred_manual,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _preflight_command(args) -> dict[str, Any]:
    db = open_read_only_sqlite(args.database)
    try:
        report = build_preflight(db)
    finally:
        db.close()
    if args.output:
        write_evidence_json(args.output, report, overwrite=args.overwrite)
    return report


def _apply_command(args) -> dict[str, Any]:
    return apply_manifest(args.database, _load_manifest(args.manifest))


def _revise_payroll_command(args) -> dict[str, Any]:
    database = str(Path(args.database).expanduser().resolve())
    os.environ["DB_PATH"] = database
    os.environ.setdefault("SECRET_KEY", "historical-price-repair-operation")
    from modules.app import app
    from modules.db import get_db
    from modules.services.payroll_service import PayrollWorkflowService

    with app.app_context():
        db = get_db()
        run = db.execute(
            "SELECT * FROM historical_price_binding_repair_runs "
            "WHERE idempotency_key=? AND status='applied'",
            (args.repair_key,),
        ).fetchone()
        if not run:
            raise ProductionOperationError("argument", "applied repair run not found")
        # The manifest is authoritative; derive months from its explicit work ids
        # instead of relying on mutable batch contents.
        manifest = json.loads(run["manifest_json"])
        work_ids = sorted(
            {int(value) for item in manifest["items"] for value in item["work_record_ids"]}
        )
        placeholders = ",".join("?" for _ in work_ids)
        months = [
            row[0]
            for row in db.execute(
                "SELECT DISTINCT strftime('%Y-%m',datetime(created_at,'-7 hours')) month "
                f"FROM work_records WHERE id IN ({placeholders}) ORDER BY month",
                work_ids,
            ).fetchall()
        ]
        actor = {"id": run["operator_id"], "name": run["operator_name"]}
        created = []
        for month in months:
            previous = db.execute(
                "SELECT * FROM payroll_batches WHERE payroll_month=? "
                "AND superseded_by_batch_id IS NULL AND status<>'voided' "
                "ORDER BY version DESC,id DESC LIMIT 1",
                (month,),
            ).fetchone()
            key = f"{args.repair_key}:payroll:{month}"
            batch = PayrollWorkflowService.create_batch(
                month,
                actor,
                key,
                revision_reason="历史路线工价精确绑定修复后重新生成工资台账",
                supersedes_batch_id=previous["id"] if previous else None,
            )
            created.append(
                {
                    "month": month,
                    "batch_id": batch["id"],
                    "version": batch["version"],
                    "status": batch["status"],
                    "supersedes_batch_id": previous["id"] if previous else None,
                }
            )
        return {"status": "succeeded", "repair_key": args.repair_key, "batches": created}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--database", required=True)
    preflight.add_argument("--output")
    preflight.add_argument("--overwrite", action="store_true")
    preflight.set_defaults(handler=_preflight_command)
    apply = subparsers.add_parser("apply")
    apply.add_argument("--database", required=True)
    apply.add_argument("--manifest", required=True)
    apply.set_defaults(handler=_apply_command)
    payroll = subparsers.add_parser("revise-payroll")
    payroll.add_argument("--database", required=True)
    payroll.add_argument("--repair-key", required=True)
    payroll.set_defaults(handler=_revise_payroll_command)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.handler(args)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
