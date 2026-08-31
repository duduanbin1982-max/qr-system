"""Immutable actor identity shared by versioned service workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


class ActorContextParseError(ValueError):
    """Raised when an actor mapping has no usable identity."""


@dataclass(frozen=True, slots=True)
class ActorContext:
    id: int
    name: str
    role: str

    def to_legacy_mapping(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "role": self.role}


def parse_actor_context(actor: Mapping[str, Any] | None) -> ActorContext:
    """Normalize an existing route actor mapping without inferring identity."""

    source = actor or {}
    try:
        actor_id = int(source.get("id"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ActorContextParseError("actor id is required") from exc
    if actor_id <= 0:
        raise ActorContextParseError("actor id must be positive")
    return ActorContext(
        id=actor_id,
        name=str(source.get("name") or source.get("username") or "").strip(),
        role=str(source.get("role") or "").strip(),
    )
