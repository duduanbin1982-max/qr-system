"""Compatibility evidence payloads and deterministic conflict aggregation."""

import hashlib
import json

from modules.domain.production_time import format_database_timestamp


def conflict_identity(fact):
    return {
        "order_id": fact.get("order_id"),
        "order_process_id": fact.get("order_process_id"),
        "process_id": fact.get("process_id"),
        "process_name": fact.get("process_name") or "",
        "revision_item_id": fact.get("revision_item_id"),
        "schedule_id": fact.get("schedule_id"),
        "production_node_id": fact.get("production_node_id"),
        "process_line_id": fact.get("process_line_id"),
        "node_name": fact.get("node_name") or "",
    }


def build_conflict(conflict_type, reason, *, first=None, second=None,
                   overlap=None, severity="blocking", details=None):
    first, second = first or {}, second or {}
    payload = {
        "conflict_type": conflict_type, "severity": severity, "reason": reason,
        "first": conflict_identity(first), "second": conflict_identity(second),
        "overlap_start_at": format_database_timestamp(overlap[0]) if overlap else "",
        "overlap_end_at": format_database_timestamp(overlap[1]) if overlap else "",
        "overlap_minutes": overlap[2] if overlap else 0,
        "first_locked": bool(first.get("locked")),
        "second_locked": bool(second.get("locked")),
        "details": dict(details or {}),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["evidence_digest"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return payload


def merge_conflict_evidence(groups):
    unique = {}
    for group in groups:
        for conflict in group:
            unique.setdefault(conflict["evidence_digest"], conflict)
    return sorted(unique.values(), key=lambda item: (
        item["conflict_type"], item["overlap_start_at"],
        item["first"].get("order_process_id") or 0,
        item["second"].get("order_process_id") or 0, item["evidence_digest"],
    ))
