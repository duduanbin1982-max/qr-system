import hashlib
import os
from pathlib import Path
import subprocess
import sys

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
from scripts import export_performance_v2_review_diff as review_export
from scripts import pending_route_price_v074_operations as pending_route_price
from scripts import production_performance_v2_apply as performance_apply
from scripts import production_performance_v2_approve as performance_approve
from scripts import production_performance_v2_post_cutover_smoke as performance_smoke
from scripts import production_performance_v2_preflight as performance_preflight
from scripts import production_performance_v2_supervisor_review as performance_review
from scripts import validate_performance_v57_replica as performance_replica
from scripts import validate_position_v070_replica as position_replica


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

# Characterization seam: these private delegates are intentionally centralized here
# to protect the shared Evidence Protocol while business tests use public workflows.
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

SCRIPT_SERIALIZERS = (
    review_export._canonical,
    performance_apply._canonical,
    performance_approve._canonical,
    performance_smoke._canonical,
    performance_preflight._canonical,
    performance_review._canonical,
    performance_replica._canonical,
    position_replica._canonical,
)

SCRIPT_DIGESTERS = (
    review_export._digest,
    pending_route_price.canonical_sha256,
    performance_apply._digest,
    performance_approve._digest,
    performance_preflight._digest,
    performance_review._digest,
    position_replica._digest,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ENTRYPOINTS = (
    "export_performance_v2_review_diff.py",
    "pending_route_price_v074_operations.py",
    "production_performance_v2_apply.py",
    "production_performance_v2_approve.py",
    "production_performance_v2_post_cutover_smoke.py",
    "production_performance_v2_preflight.py",
    "production_performance_v2_supervisor_review.py",
    "validate_performance_v57_replica.py",
    "validate_position_v070_replica.py",
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


@pytest.mark.parametrize("serializer", SCRIPT_SERIALIZERS)
def test_script_serializers_delegate_to_v1(monkeypatch, serializer):
    seen = []
    monkeypatch.setattr(
        evidence_protocol,
        "canonical_json_v1",
        lambda value: seen.append(value) or "shared",
    )
    value = {"source": "script"}

    assert serializer(value) == "shared"
    assert seen == [value]


@pytest.mark.parametrize("digester", SCRIPT_DIGESTERS)
def test_script_digesters_delegate_to_v1(monkeypatch, digester):
    seen = []
    monkeypatch.setattr(
        evidence_protocol,
        "sha256_digest_v1",
        lambda value: seen.append(value) or "shared-digest",
    )
    value = {"source": "script"}

    assert digester(value) == "shared-digest"
    assert seen == [value]


@pytest.mark.parametrize("script_name", SCRIPT_ENTRYPOINTS)
def test_migrated_scripts_keep_direct_help_entrypoint(tmp_path, script_name):
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / script_name), "--help"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    assert "usage:" in completed.stdout
