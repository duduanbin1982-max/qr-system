import hashlib

import pytest

from modules.domain.position_versioning import canonical_json as position_json
from modules.domain.position_versioning import stable_digest as position_digest
from modules.domain.process_versioning import canonical_json as process_json
from modules.domain.process_versioning import payload_sha256 as process_digest
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
from scripts.export_performance_v2_review_diff import _canonical as export_json
from scripts.pending_route_price_v074_operations import canonical_sha256
from scripts.production_performance_v2_apply import _canonical as apply_json
from scripts.production_performance_v2_approve import _canonical as approve_json
from scripts.production_performance_v2_post_cutover_smoke import (
    _canonical as smoke_json,
)
from scripts.production_performance_v2_preflight import _canonical as preflight_json
from scripts.production_performance_v2_supervisor_review import (
    _canonical as review_json,
)
from scripts.validate_performance_v57_replica import _canonical as replica_json
from scripts.validate_position_v070_replica import _canonical as position_replica_json


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
EXPECTED_UTF8_HEX = (
    "7b22616d6f756e74223a312e32352c226e6573746564223a7b2261223a5b332c7b22"
    "e590afe794a8223a747275657d5d2c2262223a327d2c226e756c6c223a6e756c6c2c"
    "22e4b8ade69687223a22e5b7a5e5ba8fe8b7afe7babf227d"
)
EXPECTED_SHA256 = "b684ca625660639998b74c8d97a06487a7c62f3755a93e590de9b8153a20f1cf"

SERIALIZERS = (
    ("process-domain", process_json),
    ("position-domain", position_json),
    ("performance-configuration", PerformanceConfigurationService._canonical),
    ("performance-fact", PerformanceFactCollector._canonical),
    ("performance-history", PerformanceHistoryMigrationService._canonical),
    ("performance-improvement", PerformanceImprovementService._canonical),
    ("performance-ledger", PerformanceLedgerService._canonical),
    ("performance-quality", PerformanceQualityEventService._canonical),
    ("performance-scoring", PerformanceScoringPolicy.canonical_json),
    ("performance-export", export_json),
    ("performance-apply", apply_json),
    ("performance-approve", approve_json),
    ("performance-smoke", smoke_json),
    ("performance-preflight", preflight_json),
    ("performance-review", review_json),
    ("performance-replica", replica_json),
    ("position-replica", position_replica_json),
)

DIGESTERS = (
    ("process-domain", process_digest),
    ("position-domain", position_digest),
    ("performance-fact", PerformanceFactCollector._digest),
    ("performance-history", PerformanceHistoryMigrationService._digest),
    ("pending-route-price-operations", canonical_sha256),
)


@pytest.mark.parametrize(
    "name,serializer",
    SERIALIZERS,
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_existing_canonical_serializers_emit_exact_v1_bytes(name, serializer):
    actual = serializer(VALUE)

    assert actual == EXPECTED_CANONICAL, name
    assert actual.encode("utf-8").hex() == EXPECTED_UTF8_HEX, name
    assert hashlib.sha256(actual.encode("utf-8")).hexdigest() == EXPECTED_SHA256


@pytest.mark.parametrize(
    "name,digester",
    DIGESTERS,
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_existing_digest_helpers_emit_exact_sha256(name, digester):
    assert digester(VALUE) == EXPECTED_SHA256, name


@pytest.mark.parametrize(
    "name,serializer",
    SERIALIZERS,
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_existing_canonical_serializers_reject_nan(name, serializer):
    with pytest.raises(ValueError):
        serializer({"value": float("nan")})


@pytest.mark.parametrize("serializer", (process_json, position_json))
def test_domain_normalizers_sort_sets_before_serialization(serializer):
    assert serializer({"values": {"乙", "甲"}}) == '{"values":["乙","甲"]}'
