"""Checked-in, explicitly authorized inputs for the production V2 migration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


MANIFEST_PATH = (
    Path(__file__).resolve().parents[1]
    / "deploy"
    / "process_v2_price_binding_resolutions.json"
)


def topology_sha256(route_id: int, nodes: list[dict]) -> str:
    payload = {
        "route_id": int(route_id),
        "nodes": [
            {
                "process_id": int(node["process_id"]),
                "is_required": int(node.get("is_required", 1)),
                "required_audit": int(node.get("required_audit", 0)),
            }
            for node in nodes
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_price_binding_resolution_manifest() -> dict:
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise RuntimeError("unsupported process V2 price resolution manifest")
    authorization = payload.get("authorization") or {}
    if not authorization.get("approved_by") or not authorization.get("approved_at"):
        raise RuntimeError("process V2 price resolution manifest is not authorized")
    for revision in payload.get("backup_route_revisions", []):
        actual = topology_sha256(revision["route_id"], revision["nodes"])
        if actual != revision["topology_sha256"]:
            raise RuntimeError(
                "process V2 backup route topology digest mismatch: "
                + str(revision["route_id"])
            )
    return payload
