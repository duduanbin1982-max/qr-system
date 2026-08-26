import hashlib

import pytest

from modules.domain.evidence_protocol import canonical_json_v1, sha256_digest_v1


VALUE = {
    "中文": "工序路线",
    "nested": {"b": 2, "a": [3, {"启用": True}]},
    "amount": 1.25,
    "null": None,
}
EXPECTED_CANONICAL = (
    '{"amount":1.25,"nested":{"a":[3,{"启用":true}],"b":2},'
    '"null":null,"中文":"工序路线"}'
)
EXPECTED_SHA256 = "b684ca625660639998b74c8d97a06487a7c62f3755a93e590de9b8153a20f1cf"


def test_v1_emits_the_frozen_utf8_bytes_and_digest():
    actual = canonical_json_v1(VALUE)

    assert actual == EXPECTED_CANONICAL
    assert sha256_digest_v1(VALUE) == EXPECTED_SHA256
    assert hashlib.sha256(actual.encode("utf-8")).hexdigest() == EXPECTED_SHA256


def test_v1_is_independent_of_mapping_insertion_order():
    assert canonical_json_v1({"b": 2, "a": 1}) == canonical_json_v1(
        {"a": 1, "b": 2}
    )


@pytest.mark.parametrize("value", (float("nan"), float("inf"), float("-inf")))
def test_v1_rejects_non_finite_numbers(value):
    with pytest.raises(ValueError):
        canonical_json_v1({"value": value})
