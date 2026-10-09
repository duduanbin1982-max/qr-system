"""Fail-closed deployment write fence shared by runtime and release tooling.

The fence is a small, atomically-written JSON file outside the SQLite database.  It
allows a deployment to start the new process, run health checks, and keep all business
mutations blocked until the release has been explicitly accepted.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


WRITE_FENCE_SCHEMA = "qr-system-write-fence/v1"
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_fence_path(root: str | Path | None = None) -> Path:
    configured = os.environ.get("DEPLOYMENT_WRITE_FENCE_PATH", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    base = Path(root).expanduser().resolve() if root else project_root()
    return base / "data" / "deployments" / "write-fence.json"


def read_fence(path: str | Path | None = None) -> dict[str, Any] | None:
    fence_path = Path(path).expanduser().resolve() if path else resolve_fence_path()
    if not fence_path.exists():
        return None
    try:
        payload = json.loads(fence_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # A malformed fence is safer as an active fence than as an open write gate.
        return {
            "schema": WRITE_FENCE_SCHEMA,
            "active": True,
            "invalid": True,
            "path": str(fence_path),
        }
    if not isinstance(payload, dict) or payload.get("schema") != WRITE_FENCE_SCHEMA:
        return {
            "schema": WRITE_FENCE_SCHEMA,
            "active": True,
            "invalid": True,
            "path": str(fence_path),
        }
    return {**payload, "path": str(fence_path), "active": True}


def write_fenced(path: str | Path | None = None) -> bool:
    return read_fence(path) is not None


def fence_status(path: str | Path | None = None) -> dict[str, Any]:
    fence = read_fence(path)
    if fence is None:
        fence_path = Path(path).expanduser().resolve() if path else resolve_fence_path()
        return {"active": False, "path": str(fence_path)}
    return {
        "active": True,
        "path": fence.get("path"),
        "deployment_key": fence.get("deployment_key"),
        "target_commit": fence.get("target_commit"),
        "invalid": bool(fence.get("invalid")),
    }
