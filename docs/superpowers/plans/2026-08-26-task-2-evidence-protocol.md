# Task 2 Evidence Protocol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce one versioned canonical JSON and SHA-256 evidence protocol, then migrate every Task 1 characterized provider without changing any serialized byte, digest, exception, CLI contract, or stored evidence.

**Architecture:** `modules/domain/evidence_protocol.py` owns raw JSON-compatible serialization and hashing through `canonical_json_v1(value) -> str` and `sha256_digest_v1(value) -> str`. Process and position domains keep their domain-specific normalization and public helper names, while performance services and production scripts keep their existing wrapper names and delegate mechanical serialization to the shared protocol. Directly executable scripts add a file-relative project-root bootstrap before importing the shared module so invocation remains independent of the caller's working directory.

**Tech Stack:** Python 3.12, standard-library `json` and `hashlib`, pytest, SQLite, Git Bash.

## Global Constraints

- Branch from merged Task 1 baseline `bb36472ad71cfe55ad8613ae0a1bb6a601be17a6` as `codex/task-2-evidence-protocol`.
- Run every command through Git Bash with working directory `C:\Users\dubin\Documents\生产管理系统升级版\qr-system-full-debt-design`.
- Preserve canonical UTF-8 bytes and SHA-256 `b684ca625660639998b74c8d97a06487a7c62f3755a93e590de9b8153a20f1cf`.
- Preserve process and position normalization, including sorted sets, normalized negative zero, and current Chinese `ValidationError` messages for unsupported values and non-finite floats.
- Preserve every existing public/private compatibility helper name used by services, scripts, and tests.
- Do not modify database migrations, schema, `user_version=75`, APIs, feature flags, permissions, CLI arguments, stdout, stderr, exit codes, or production data.
- Use red-green-refactor for every production-code change. Do not push, merge, deploy, restart, migrate, or change production flags without separate authorization.

---

### Task 1: Add the Versioned Evidence Protocol Primitive

**Files:**
- Create: `modules/domain/evidence_protocol.py`
- Create: `tests/test_evidence_protocol.py`

**Interfaces:**
- Consumes: any value accepted by `json.dumps` with `ensure_ascii=False`, `sort_keys=True`, `separators=(",", ":")`, and `allow_nan=False`.
- Produces: `canonical_json_v1(value: Any) -> str` and `sha256_digest_v1(value: Any) -> str`.

- [ ] **Step 1: Write the failing primitive contract**

Create `tests/test_evidence_protocol.py` with imports of the not-yet-existing functions and tests that assert the Task 1 canonical text, UTF-8 bytes, SHA-256, mapping-order independence, and `ValueError` rejection of NaN and Infinity:

```python
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
    assert canonical_json_v1({"b": 2, "a": 1}) == canonical_json_v1({"a": 1, "b": 2})


@pytest.mark.parametrize("value", (float("nan"), float("inf"), float("-inf")))
def test_v1_rejects_non_finite_numbers(value):
    with pytest.raises(ValueError):
        canonical_json_v1({"value": value})
```

- [ ] **Step 2: Run the primitive contract and verify RED**

Run: `python -m pytest -q tests/test_evidence_protocol.py`

Expected: collection fails with `ModuleNotFoundError: No module named 'modules.domain.evidence_protocol'`.

- [ ] **Step 3: Implement the minimal versioned primitive**

Create `modules/domain/evidence_protocol.py`:

```python
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
```

- [ ] **Step 4: Run the primitive and Task 1 evidence contracts**

Run: `python -m pytest -q tests/test_evidence_protocol.py tests/test_evidence_protocol_characterization.py`

Expected: PASS; the new primitive tests and all 41 existing characterization cases pass.

- [ ] **Step 5: Commit the primitive**

```bash
git add modules/domain/evidence_protocol.py tests/test_evidence_protocol.py
git commit -m "feat: add versioned evidence protocol"
```

### Task 2: Delegate Domain and Service Compatibility Helpers

**Files:**
- Modify: `tests/test_evidence_protocol.py`
- Modify: `modules/domain/process_versioning.py`
- Modify: `modules/domain/position_versioning.py`
- Modify: `modules/services/performance_configuration_service.py`
- Modify: `modules/services/performance_fact_collector.py`
- Modify: `modules/services/performance_history_migration_service.py`
- Modify: `modules/services/performance_improvement_service.py`
- Modify: `modules/services/performance_ledger_service.py`
- Modify: `modules/services/performance_quality_event_service.py`
- Modify: `modules/services/performance_scoring_policy.py`

**Interfaces:**
- Consumes: `evidence_protocol.canonical_json_v1(value)` and `evidence_protocol.sha256_digest_v1(value)`.
- Produces: unchanged `canonical_json`, `stable_digest`, `payload_sha256`, `_canonical`, `_digest`, and `PerformanceScoringPolicy.canonical_json` compatibility helpers.

- [ ] **Step 1: Write failing delegation tests**

Extend `tests/test_evidence_protocol.py` with the characterized domain/service provider matrices. Monkeypatch `evidence_protocol.canonical_json_v1` and `sha256_digest_v1` to return sentinels, assert raw service values reach the shared primitive unchanged, and assert process/position wrappers pass their existing `canonicalize(value)` result.

```python
from modules.domain import evidence_protocol, position_versioning, process_versioning
from modules.services.performance_configuration_service import PerformanceConfigurationService
from modules.services.performance_fact_collector import PerformanceFactCollector
from modules.services.performance_history_migration_service import PerformanceHistoryMigrationService
from modules.services.performance_improvement_service import PerformanceImprovementService
from modules.services.performance_ledger_service import PerformanceLedgerService
from modules.services.performance_quality_event_service import PerformanceQualityEventService
from modules.services.performance_scoring_policy import PerformanceScoringPolicy


SERVICE_SERIALIZERS = (
    PerformanceConfigurationService._canonical,
    PerformanceFactCollector._canonical,
    PerformanceHistoryMigrationService._canonical,
    PerformanceImprovementService._canonical,
    PerformanceLedgerService._canonical,
    PerformanceQualityEventService._canonical,
    PerformanceScoringPolicy.canonical_json,
)


@pytest.mark.parametrize("serializer", SERVICE_SERIALIZERS)
def test_service_serializers_delegate_to_v1(monkeypatch, serializer):
    seen = []
    monkeypatch.setattr(evidence_protocol, "canonical_json_v1", lambda value: seen.append(value) or "shared")
    value = {"source": "service"}
    assert serializer(value) == "shared"
    assert seen == [value]


@pytest.mark.parametrize("module", (process_versioning, position_versioning))
def test_domain_serializers_normalize_before_delegating(monkeypatch, module):
    seen = []
    monkeypatch.setattr(evidence_protocol, "canonical_json_v1", lambda value: seen.append(value) or "shared")
    assert module.canonical_json({"values": {"乙", "甲"}}) == "shared"
    assert seen == [{"values": ["乙", "甲"]}]
```

- [ ] **Step 2: Run the delegation tests and verify RED**

Run: `python -m pytest -q tests/test_evidence_protocol.py`

Expected: primitive tests pass and delegation tests fail because existing helpers still call local `json.dumps` and `hashlib.sha256`.

- [ ] **Step 3: Migrate domain wrappers without moving normalization**

Import `modules.domain.evidence_protocol` in both versioning modules. Replace only the mechanical calls:

```python
def canonical_json(value):
    return evidence_protocol.canonical_json_v1(canonicalize(value))


def payload_sha256(value):
    return evidence_protocol.sha256_digest_v1(canonicalize(value))
```

Use the same body for position `canonical_json`; position `stable_digest` delegates to `sha256_digest_v1(canonicalize(value))`. Leave `canonicalize`, `_canonical_scalar`, and their domain exceptions unchanged.

- [ ] **Step 4: Migrate service wrappers**

Import `from modules.domain import evidence_protocol` and replace each `_canonical` or `canonical_json` body with `return evidence_protocol.canonical_json_v1(value)`. Replace only `PerformanceFactCollector._digest` and `PerformanceHistoryMigrationService._digest` with `return evidence_protocol.sha256_digest_v1(value)`; retain other `hashlib` uses that hash files or already-canonical strings.

- [ ] **Step 5: Run domain/service tests and verify GREEN**

Run:

```bash
python -m pytest -q tests/test_evidence_protocol.py tests/test_evidence_protocol_characterization.py tests/test_process_versioning_policy.py tests/test_position_versioning_policy.py tests/test_performance_fact_collector.py tests/test_performance_history_migration.py tests/test_performance_scoring_policy.py
```

Expected: PASS with the frozen canonical digest and history manifest digests unchanged.

- [ ] **Step 6: Commit domain and service delegation**

```bash
git add tests/test_evidence_protocol.py modules/domain/process_versioning.py modules/domain/position_versioning.py modules/services/performance_configuration_service.py modules/services/performance_fact_collector.py modules/services/performance_history_migration_service.py modules/services/performance_improvement_service.py modules/services/performance_ledger_service.py modules/services/performance_quality_event_service.py modules/services/performance_scoring_policy.py
git commit -m "refactor: delegate evidence serialization"
```

### Task 3: Delegate Characterized Production Script Helpers

**Files:**
- Modify: `tests/test_evidence_protocol.py`
- Modify: `scripts/export_performance_v2_review_diff.py`
- Modify: `scripts/pending_route_price_v074_operations.py`
- Modify: `scripts/production_performance_v2_apply.py`
- Modify: `scripts/production_performance_v2_approve.py`
- Modify: `scripts/production_performance_v2_post_cutover_smoke.py`
- Modify: `scripts/production_performance_v2_preflight.py`
- Modify: `scripts/production_performance_v2_supervisor_review.py`
- Modify: `scripts/validate_performance_v57_replica.py`
- Modify: `scripts/validate_position_v070_replica.py`

**Interfaces:**
- Consumes: the same shared V1 functions and each script's file-relative repository root.
- Produces: unchanged `_canonical`, `_digest`, and `canonical_sha256` helpers plus direct `python <absolute-script-path> --help` compatibility from an unrelated working directory.

- [ ] **Step 1: Write failing script delegation and direct-entry tests**

Extend `tests/test_evidence_protocol.py` with the eight characterized script serializers and all in-scope digest wrappers. Monkeypatch the shared module to assert delegation. Add a subprocess test that invokes each migrated script with `--help` from `tmp_path` and asserts exit code 0 and empty stderr.

- [ ] **Step 2: Run the script tests and verify RED**

Run: `python -m pytest -q tests/test_evidence_protocol.py`

Expected: script delegation tests fail because the wrappers still implement serialization locally.

- [ ] **Step 3: Add safe script imports and delegate wrappers**

For scripts without an existing project-root bootstrap, add after standard-library imports:

```python
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.domain import evidence_protocol  # noqa: E402
```

For scripts with an existing bootstrap, add only the shared-module import after it. Replace canonical bodies with `evidence_protocol.canonical_json_v1(value)` and digest bodies with `evidence_protocol.sha256_digest_v1(value)`. Preserve file hashing helpers that consume bytes.

- [ ] **Step 4: Run script contracts and verify GREEN**

Run:

```bash
python -m pytest -q tests/test_evidence_protocol.py tests/test_evidence_protocol_characterization.py tests/test_production_operations_characterization.py tests/test_pending_route_price_v074_operations.py
```

Expected: PASS; canonical bytes, digest values, direct script entry, CLI output, and operational behavior remain unchanged.

- [ ] **Step 5: Commit script delegation**

```bash
git add tests/test_evidence_protocol.py scripts/export_performance_v2_review_diff.py scripts/pending_route_price_v074_operations.py scripts/production_performance_v2_apply.py scripts/production_performance_v2_approve.py scripts/production_performance_v2_post_cutover_smoke.py scripts/production_performance_v2_preflight.py scripts/production_performance_v2_supervisor_review.py scripts/validate_performance_v57_replica.py scripts/validate_position_v070_replica.py
git commit -m "refactor: share production evidence protocol"
```

### Task 4: Run Full Regression and Record Task 2 Evidence

**Files:**
- Create: `docs/superpowers/evidence/2026-08-26-task-2-evidence-protocol.md`

**Interfaces:**
- Consumes: all Task 1 behavior gates and Task 2 delegation tests.
- Produces: a reviewable Task 2 branch with no schema, API, CLI, flag, or digest changes.

- [ ] **Step 1: Verify scope and schema**

Run: `git diff --check github/master...HEAD`

Run: `SECRET_KEY=task-2-schema-check python -c "from modules.migrations import LATEST_VERSION; assert LATEST_VERSION == 75; print(LATEST_VERSION)"`

Expected: no whitespace errors and stdout `75`.

- [ ] **Step 2: Run focused and full backend regression**

Run: `python -m pytest -q tests/test_evidence_protocol.py tests/test_evidence_protocol_characterization.py tests/test_production_operations_characterization.py tests/test_performance_history_migration.py tests/test_process_versioning_policy.py tests/test_position_versioning_policy.py tests/test_pending_route_price_v074_operations.py`

Run: `python -m pytest -q`

Expected: all focused and complete backend tests pass.

- [ ] **Step 3: Run architecture, frontend, build, and E2E gates**

Run: `python -m pytest -q tests/test_architecture_imports.py tests/test_migrations.py`

Run: `npm run test:unit`

Run: `npm run check:architecture`

Run: `npm run build`

Run: `npm run test:e2e`

Expected: all gates pass, `user_version=75`, and all 19 E2E workflows pass.

- [ ] **Step 4: Record exact verification counts and the unchanged three SHA-256 values**

Create `docs/superpowers/evidence/2026-08-26-task-2-evidence-protocol.md` only after every gate passes. Record the tested source baseline, final commit, changed compatibility providers, exact test counts, schema version, canonical SHA-256, history plan SHA-256, history month SHA-256, and the Node version environment note.

- [ ] **Step 5: Commit the evidence and perform final branch review**

```bash
git add docs/superpowers/evidence/2026-08-26-task-2-evidence-protocol.md docs/superpowers/plans/2026-08-26-task-2-evidence-protocol.md
git commit -m "docs: record task 2 evidence protocol"
git status --short --branch
git log --oneline --decorate -6
```

Expected: clean `codex/task-2-evidence-protocol`; no database, migration, frontend source, generated bundle, or production evidence artifact changes.
