"""Versioned canonical serialization for immutable audit evidence."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json_v1(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_digest_v1(value: Any) -> str:
    return hashlib.sha256(canonical_json_v1(value).encode("utf-8")).hexdigest()
