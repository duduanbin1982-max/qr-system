from dataclasses import FrozenInstanceError

import pytest

from modules.domain.actor_context import (
    ActorContextParseError,
    parse_actor_context,
)


def test_parse_actor_context_normalizes_existing_route_mapping():
    actor = parse_actor_context(
        {
            "id": " 1000 ",
            "name": " 杜斌 ",
            "username": "ignored",
            "role": " admin ",
        }
    )

    assert actor.to_legacy_mapping() == {
        "id": 1000,
        "name": "杜斌",
        "role": "admin",
    }


def test_parse_actor_context_preserves_username_fallback_and_boolean_id():
    actor = parse_actor_context(
        {"id": True, "name": "", "username": " 布尔来源 ", "role": None}
    )

    assert actor.to_legacy_mapping() == {
        "id": 1,
        "name": "布尔来源",
        "role": "",
    }


@pytest.mark.parametrize(
    "source",
    (None, {}, {"id": None}, {"id": "not-a-number"}, {"id": "0"}, {"id": -1}),
)
def test_parse_actor_context_rejects_missing_or_invalid_identity(source):
    with pytest.raises(ActorContextParseError):
        parse_actor_context(source)


def test_actor_context_is_immutable():
    actor = parse_actor_context({"id": 1000, "name": "杜斌", "role": "admin"})

    with pytest.raises(FrozenInstanceError):
        actor.name = "changed"
