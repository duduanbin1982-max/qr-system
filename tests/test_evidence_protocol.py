import hashlib

import pytest

from modules.domain import evidence_protocol, position_versioning, process_versioning
from modules.domain.evidence_protocol import canonical_json_v1, sha256_digest_v1
from modules.services.performance_configuration_service import (
    PerformanceConfigurationService,
)
from modules.services.performance_fact_collector import PerformanceFactCollector
from modules.services.performance_history_migration_service import (
    PerformanceHistoryMigrationService,
)
from modules.services.performance_improvement_service import (
    PerformanceImprovementService,
)
from modules.services.performance_ledger_service import PerformanceLedgerService
from modules.services.performance_quality_event_service import (
    PerformanceQualityEventService,
)
from modules.services.performance_scoring_policy import PerformanceScoringPolicy


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

SERVICE_SERIALIZERS = (
    PerformanceConfigurationService._canonical,
    PerformanceFactCollector._canonical,
    PerformanceHistoryMigrationService._canonical,
    PerformanceImprovementService._canonical,
    PerformanceLedgerService._canonical,
    PerformanceQualityEventService._canonical,
    PerformanceScoringPolicy.canonical_json,
)

SERVICE_DIGESTERS = (
    PerformanceFactCollector._digest,
    PerformanceHistoryMigrationService._digest,
)


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


@pytest.mark.parametrize("serializer", SERVICE_SERIALIZERS)
def test_service_serializers_delegate_to_v1(monkeypatch, serializer):
    seen = []
    monkeypatch.setattr(
        evidence_protocol,
        "canonical_json_v1",
        lambda value: seen.append(value) or "shared",
    )
    value = {"source": "service"}

    assert serializer(value) == "shared"
    assert seen == [value]


@pytest.mark.parametrize("digester", SERVICE_DIGESTERS)
def test_service_digesters_delegate_to_v1(monkeypatch, digester):
    seen = []
    monkeypatch.setattr(
        evidence_protocol,
        "sha256_digest_v1",
        lambda value: seen.append(value) or "shared-digest",
    )
    value = {"source": "service"}

    assert digester(value) == "shared-digest"
    assert seen == [value]


@pytest.mark.parametrize("module", (process_versioning, position_versioning))
def test_domain_serializers_normalize_before_delegating(monkeypatch, module):
    seen = []

    def capture(value):
        seen.append(value)
        return value if isinstance(value, str) else "shared"

    monkeypatch.setattr(
        evidence_protocol,
        "canonical_json_v1",
        capture,
    )

    assert module.canonical_json({"values": {"乙", "甲"}}) == "shared"
    assert sorted(seen[:-1]) == ["乙", "甲"]
    assert seen[-1] == {"values": ["乙", "甲"]}


@pytest.mark.parametrize(
    "module,digester_name",
    (
        (process_versioning, "payload_sha256"),
        (position_versioning, "stable_digest"),
    ),
)
def test_domain_digesters_normalize_before_delegating(
    monkeypatch, module, digester_name
):
    seen = []
    monkeypatch.setattr(
        evidence_protocol,
        "sha256_digest_v1",
        lambda value: seen.append(value) or "shared-digest",
    )

    assert getattr(module, digester_name)({"values": {"乙", "甲"}}) == "shared-digest"
    assert seen == [{"values": ["乙", "甲"]}]
