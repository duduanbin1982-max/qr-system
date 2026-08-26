# Task 1 Behavior Characterization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze the current evidence bytes, actor parsing, production command mechanics, performance-history manifests, and process-management UI workflows before any debt-remediation refactor begins.

**Architecture:** Add black-box and compatibility-focused tests around the existing production baseline; do not introduce shared production abstractions in this task. Each characterization test asserts the exact behavior observed at `cd6f999836de47a78f0b36f9b251c6f1faa47f49`, so an initial failure means the test misunderstood the baseline and must be corrected before later refactoring starts.

**Tech Stack:** Python 3.12, pytest, SQLite, Flask test fixtures, Vue 3, Vue Test Utils, Vitest, npm/Vite, Git Bash.

## Global Constraints

- Work on a dedicated `codex/task-1-behavior-characterization` branch based on production baseline `cd6f999836de47a78f0b36f9b251c6f1faa47f49` plus the approved design and this plan.
- Run every command through Git Bash using the displayed `& "C:\Program Files\Git\bin\bash.exe" -c 'python -m pytest -q'` pattern; set the command working directory to `C:\Users\dubin\Documents\生产管理系统升级版\qr-system-full-debt-design`.
- This task changes tests and characterization evidence only. Do not modify files under `modules/`, `scripts/`, or `frontend/src/`.
- Do not add or modify migrations, database objects, feature flags, APIs, response bodies, error codes, Chinese messages, permissions, state transitions, digest bytes, or `user_version`; `LATEST_VERSION` and test databases remain `75`.
- Preserve the existing production baseline of 1026 backend tests, 140 frontend unit tests, and 19 end-to-end tests; all newly added characterization tests must pass on the unrefactored baseline.
- If a newly written characterization test initially fails, stop and compare the assertion with current behavior. Correct the test; do not change production code to make it pass.
- Do not push, merge, deploy, stop, restart, migrate, or change production flags in this task without separate authorization.

---

## File Map

- `tests/test_evidence_protocol_characterization.py`: exact canonical JSON, UTF-8 bytes, SHA-256, ordering, and NaN rejection across every current evidence serializer in scope.
- `tests/test_actor_context_characterization.py`: exact valid, fallback, invalid, and observed boolean-ID behavior of all seven duplicated actor adapters.
- `tests/test_production_operations_characterization.py`: read-only SQLite, backup equivalence, payroll fingerprints, and CLI stdout/stderr/exit-code contracts for the performance production commands.
- `tests/test_performance_history_migration.py`: exact synthetic historical month manifest, classifications, user sets, record order, and digest baseline.
- `frontend/tests/unit/ProcessList.spec.js`: complete parent-page workflow contract for creation, draft update, submit, approve, reject, lifecycle commands, permissions, reloads, and errors.
- `docs/superpowers/evidence/2026-08-26-task-1-characterization-baseline.md`: immutable human-readable record of the commands and gates that passed.

### Task 1: Freeze Canonical Evidence Bytes and Digests

**Files:**
- Create: `tests/test_evidence_protocol_characterization.py`
- Read only: `modules/domain/process_versioning.py:292`
- Read only: `modules/domain/position_versioning.py:204`
- Read only: `modules/services/performance_configuration_service.py:41`
- Read only: `modules/services/performance_fact_collector.py:58`
- Read only: `modules/services/performance_history_migration_service.py:50`
- Read only: `modules/services/performance_improvement_service.py:54`
- Read only: `modules/services/performance_ledger_service.py:36`
- Read only: `modules/services/performance_quality_event_service.py:18`
- Read only: `modules/services/performance_scoring_policy.py:219`

**Interfaces:**
- Consumes: existing serializer callables accepting one JSON-compatible value and returning `str`; existing digest callables accepting one value and returning a lowercase 64-character hexadecimal string.
- Produces: a golden protocol contract with canonical text `EXPECTED_CANONICAL` and digest `EXPECTED_SHA256`; remediation Tasks 2 and 6 may refactor implementations only while this file remains unchanged and green.

- [ ] **Step 1: Create the serializer and digest provider matrix**

Create `tests/test_evidence_protocol_characterization.py` with these imports and constants:

```python
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
```

- [ ] **Step 2: Add exact byte, ordering, digest, and rejection assertions**

Append the complete tests:

```python
@pytest.mark.parametrize("name,serializer", SERIALIZERS, ids=lambda value: value if isinstance(value, str) else None)
def test_existing_canonical_serializers_emit_exact_v1_bytes(name, serializer):
    actual = serializer(VALUE)

    assert actual == EXPECTED_CANONICAL, name
    assert actual.encode("utf-8").hex() == EXPECTED_UTF8_HEX, name
    assert hashlib.sha256(actual.encode("utf-8")).hexdigest() == EXPECTED_SHA256


@pytest.mark.parametrize("name,digester", DIGESTERS, ids=lambda value: value if isinstance(value, str) else None)
def test_existing_digest_helpers_emit_exact_sha256(name, digester):
    assert digester(VALUE) == EXPECTED_SHA256, name


@pytest.mark.parametrize("name,serializer", SERIALIZERS, ids=lambda value: value if isinstance(value, str) else None)
def test_existing_canonical_serializers_reject_nan(name, serializer):
    with pytest.raises(ValueError):
        serializer({"value": float("nan")})


@pytest.mark.parametrize("serializer", (process_json, position_json))
def test_domain_normalizers_sort_sets_before_serialization(serializer):
    assert serializer({"values": {"乙", "甲"}}) == '{"values":["乙","甲"]}'
```

- [ ] **Step 3: Run the new characterization file on the untouched baseline**

Run: `& "C:\Program Files\Git\bin\bash.exe" -c 'python -m pytest -q tests/test_evidence_protocol_characterization.py'`

Expected: PASS. No source file changes are permitted. If any provider differs, inspect that provider and correct its expected row or remove it from the shared-protocol scope only with design review.

- [ ] **Step 4: Commit the evidence-byte contract**

```bash
git add tests/test_evidence_protocol_characterization.py
git commit -m "test: freeze canonical evidence bytes"
```

Expected: one test-only commit; `git diff HEAD^ --name-only` prints only `tests/test_evidence_protocol_characterization.py`.

### Task 2: Freeze Actor Adapter Inputs, Outputs, and Errors

**Files:**
- Create: `tests/test_actor_context_characterization.py`
- Read only: `modules/services/master_data_lifecycle_service.py:21`
- Read only: `modules/services/master_data_release_service.py:34`
- Read only: `modules/services/process_version_service.py:29`
- Read only: `modules/services/route_version_service.py:42`
- Read only: `modules/services/position_audit_service.py:14`
- Read only: `modules/services/position_lifecycle_service.py:30`
- Read only: `modules/services/position_version_service.py:39`

**Interfaces:**
- Consumes: each existing `Service._actor(actor: Mapping | None) -> dict` adapter.
- Produces: an exact compatibility contract for normalized `{"id": int, "name": str, "role": str}` and `ValidationError("操作人不能为空")`; remediation Task 3 must preserve it through compatibility adapters.

- [ ] **Step 1: Create the complete actor adapter matrix**

Create `tests/test_actor_context_characterization.py`:

```python
import pytest

from modules.domain.errors import ValidationError
from modules.services.master_data_lifecycle_service import (
    MasterDataLifecycleService,
)
from modules.services.master_data_release_service import MasterDataReleaseService
from modules.services.position_audit_service import PositionAuditService
from modules.services.position_lifecycle_service import PositionLifecycleService
from modules.services.position_version_service import PositionVersionService
from modules.services.process_version_service import ProcessVersionService
from modules.services.route_version_service import RouteVersionService


ACTOR_ADAPTERS = (
    ("master-data-lifecycle", MasterDataLifecycleService._actor),
    ("master-data-release", MasterDataReleaseService._actor),
    ("process-version", ProcessVersionService._actor),
    ("route-version", RouteVersionService._actor),
    ("position-audit", PositionAuditService._actor),
    ("position-lifecycle", PositionLifecycleService._actor),
    ("position-version", PositionVersionService._actor),
)

VALID_CASES = (
    (
        {"id": " 1000 ", "name": " 杜斌 ", "username": "ignored", "role": " admin "},
        {"id": 1000, "name": "杜斌", "role": "admin"},
    ),
    (
        {"id": 1004, "name": "", "username": " Dooley ", "role": None},
        {"id": 1004, "name": "Dooley", "role": ""},
    ),
)

INVALID_ACTORS = (
    None,
    {},
    {"id": None},
    {"id": "not-a-number"},
    {"id": "0"},
    {"id": -1},
)
```

- [ ] **Step 2: Add exact compatibility assertions, including the observed boolean quirk**

Append:

```python
@pytest.mark.parametrize("adapter_name,adapter", ACTOR_ADAPTERS)
@pytest.mark.parametrize("source,expected", VALID_CASES)
def test_actor_adapters_preserve_valid_normalization(
    adapter_name, adapter, source, expected
):
    assert adapter(source) == expected, adapter_name


@pytest.mark.parametrize("adapter_name,adapter", ACTOR_ADAPTERS)
@pytest.mark.parametrize("source", INVALID_ACTORS)
def test_actor_adapters_preserve_fail_closed_error(adapter_name, adapter, source):
    with pytest.raises(ValidationError) as error:
        adapter(source)

    assert str(error.value) == "操作人不能为空", adapter_name
    assert error.value.to_payload() == {
        "error": "操作人不能为空",
        "code": "validation_error",
    }


@pytest.mark.parametrize("adapter_name,adapter", ACTOR_ADAPTERS)
def test_actor_adapters_record_current_boolean_id_behavior(adapter_name, adapter):
    assert adapter({"id": True, "username": "布尔来源", "role": "worker"}) == {
        "id": 1,
        "name": "布尔来源",
        "role": "worker",
    }, adapter_name
```

The last test intentionally records a current Python `int(True) == 1` compatibility quirk. Remediation Task 3 may not silently change it; rejecting boolean IDs requires a separately approved behavior change and contract update.

- [ ] **Step 3: Run the actor characterization file**

Run: `& "C:\Program Files\Git\bin\bash.exe" -c 'python -m pytest -q tests/test_actor_context_characterization.py'`

Expected: PASS with the existing service adapters unchanged.

- [ ] **Step 4: Commit the actor contract**

```bash
git add tests/test_actor_context_characterization.py
git commit -m "test: freeze actor adapter contracts"
```

### Task 3: Freeze Production Operation and CLI Mechanics

**Files:**
- Create: `tests/test_production_operations_characterization.py`
- Read only: `scripts/export_performance_v2_review_diff.py`
- Read only: `scripts/production_performance_v2_apply.py`
- Read only: `scripts/production_performance_v2_approve.py`
- Read only: `scripts/production_performance_v2_cutover.py`
- Read only: `scripts/production_performance_v2_post_cutover_smoke.py`
- Read only: `scripts/production_performance_v2_preflight.py`
- Read only: `scripts/production_performance_v2_supervisor_review.py`
- Read only: `scripts/validate_performance_v57_replica.py`

**Interfaces:**
- Consumes: `_open_ro(path) -> sqlite3.Connection`, `_backup(source, target) -> None`, `_database_backup(source, target) -> None`, payroll fingerprint functions, and `main(argv=None) -> int`.
- Produces: mechanical equivalence tests that remediation Tasks 4 and 5 must keep green while delegating to `scripts/production_operations.py`.

- [ ] **Step 1: Create fixtures and the exact provider matrices**

Create `tests/test_production_operations_characterization.py` with:

```python
import json
import sqlite3
from types import SimpleNamespace

import pytest

from scripts import export_performance_v2_review_diff as review_export
from scripts import production_performance_v2_apply as performance_apply
from scripts import production_performance_v2_approve as performance_approve
from scripts import production_performance_v2_cutover as performance_cutover
from scripts import production_performance_v2_post_cutover_smoke as performance_smoke
from scripts import production_performance_v2_preflight as performance_preflight
from scripts import production_performance_v2_supervisor_review as performance_review
from scripts import validate_performance_v57_replica as performance_replica


READ_ONLY_OPENERS = (
    performance_apply._open_ro,
    performance_approve._open_ro,
    performance_cutover._open_ro,
    performance_smoke._open_ro,
    performance_review._open_ro,
    review_export._open_ro,
)

BACKUP_FUNCTIONS = (
    performance_apply._backup,
    performance_approve._backup,
    performance_review._backup,
    performance_cutover._database_backup,
)

PAYROLL_FUNCTIONS = (
    performance_apply._payroll_fingerprint,
    performance_approve._payroll,
    performance_cutover._payroll,
    performance_smoke._payroll,
    performance_review._payroll,
)

CLI_MODULES = (
    (review_export, None),
    (performance_apply, None),
    (performance_approve, None),
    (performance_cutover, None),
    (performance_smoke, None),
    (performance_preflight, None),
    (performance_review, None),
    (performance_replica, 2),
)

PAYROLL_TABLES = (
    "payroll_batches",
    "payroll_employee_lines",
    "payroll_adjustments",
    "payroll_detail_lines",
    "payroll_work_price_resolutions",
    "payroll_events",
    "payroll_migration_manifests",
)


@pytest.fixture
def source_database(tmp_path):
    path = tmp_path / "source.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
    db.execute("INSERT INTO sample(value) VALUES ('基线')")
    db.commit()
    db.close()
    return path


def _parser_stub():
    return SimpleNamespace(parse_args=lambda argv: SimpleNamespace())
```

- [ ] **Step 2: Characterize read-only connections and byte-valid backups**

Append:

```python
@pytest.mark.parametrize("open_ro", READ_ONLY_OPENERS)
def test_read_only_openers_preserve_sqlite_safety_pragmas(source_database, open_ro):
    db = open_ro(source_database)
    try:
        assert db.row_factory is sqlite3.Row
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert db.execute("PRAGMA busy_timeout").fetchone()[0] == 10000
        assert db.execute("PRAGMA query_only").fetchone()[0] == 1
        assert dict(db.execute("SELECT * FROM sample").fetchone()) == {
            "id": 1,
            "value": "基线",
        }
        with pytest.raises(sqlite3.OperationalError):
            db.execute("INSERT INTO sample(value) VALUES ('禁止写入')")
    finally:
        db.close()


@pytest.mark.parametrize("backup", BACKUP_FUNCTIONS)
def test_database_backup_helpers_preserve_schema_and_rows(
    tmp_path, source_database, backup
):
    target = tmp_path / "backup.db"
    backup(source_database, target)

    db = sqlite3.connect(target)
    try:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("SELECT id,value FROM sample").fetchall() == [(1, "基线")]
    finally:
        db.close()
```

- [ ] **Step 3: Characterize payroll table ordering and counts**

Append:

```python
@pytest.mark.parametrize("fingerprint", PAYROLL_FUNCTIONS)
def test_payroll_fingerprints_preserve_keys_order_and_counts(fingerprint):
    db = sqlite3.connect(":memory:")
    try:
        for index, table in enumerate(PAYROLL_TABLES):
            db.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
            db.executemany(
                f"INSERT INTO {table}(id) VALUES (?)",
                [(row_id,) for row_id in range(1, index + 1)],
            )

        actual = fingerprint(db)
        assert list(actual) == list(PAYROLL_TABLES)
        assert actual == {
            table: index for index, table in enumerate(PAYROLL_TABLES)
        }
    finally:
        db.close()
```

- [ ] **Step 4: Characterize success and failure CLI streams and exit codes**

Append:

```python
@pytest.mark.parametrize("module,failure_indent", CLI_MODULES)
def test_performance_cli_success_contract(
    monkeypatch, capsys, module, failure_indent
):
    result = {"status": "passed", "message": "受控完成"}
    monkeypatch.setattr(module, "_parser", _parser_stub)
    monkeypatch.setattr(module, "run", lambda args: result)

    assert module.main([]) == 0
    captured = capsys.readouterr()
    assert captured.out == json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    assert captured.err == ""


@pytest.mark.parametrize("module,failure_indent", CLI_MODULES)
def test_performance_cli_failure_contract(
    monkeypatch, capsys, module, failure_indent
):
    def fail(_args):
        raise RuntimeError("受控失败")

    monkeypatch.setattr(module, "_parser", _parser_stub)
    monkeypatch.setattr(module, "run", fail)

    assert module.main([]) == 1
    captured = capsys.readouterr()
    expected = {"status": "failed", "error": "受控失败"}
    assert captured.out == ""
    assert captured.err == (
        json.dumps(expected, ensure_ascii=False, indent=failure_indent) + "\n"
    )
```

The `performance_replica` failure stream is intentionally pretty-printed with indent `2`; the other seven failure streams are compact. Remediation Task 4 may unify implementation, but remediation Task 5 must preserve each external CLI byte contract unless a separate behavior change is approved.

- [ ] **Step 5: Run the operation characterization tests**

Run: `& "C:\Program Files\Git\bin\bash.exe" -c 'python -m pytest -q tests/test_production_operations_characterization.py'`

Expected: PASS; every failed CLI case returns `1`, writes only to stderr, and creates no production artifact because `run()` is replaced before execution.

Run: `& "C:\Program Files\Git\bin\bash.exe" -c 'python -m pytest -q tests/test_process_v2_operations_scripts.py tests/test_pending_route_price_v074_operations.py tests/test_deployment_contracts.py'`

Expected: PASS; existing read-only preflight, staged failure, backup verification, non-overwrite, and rollback contracts remain green.

- [ ] **Step 6: Commit the production-operation contract**

```bash
git add tests/test_production_operations_characterization.py
git commit -m "test: freeze production operation contracts"
```

### Task 4: Freeze the Performance History Manifest

**Files:**
- Modify: `tests/test_performance_history_migration.py:346`
- Read only: `modules/services/performance_history_migration_service.py:148`

**Interfaces:**
- Consumes: existing `_seed_history(db) -> dict` fixture and `PerformanceHistoryMigrationService.analyze(db, start_month, end_month) -> dict`.
- Produces: an exact 2026-06 synthetic manifest contract used by remediation Task 6 to prove decomposition of `_month_plan()` has zero differences.

- [ ] **Step 1: Add a deterministic projection helper beside `_expected_counts()`**

Insert after `_expected_counts()`:

```python
def _manifest_projection(plan):
    month = plan["months"][0]
    return {
        "manifest_sha256": plan["manifest_sha256"],
        "month_manifest_sha256": month["manifest_sha256"],
        "record_count": len(month["records"]),
        "stable_keys": [record["stable_key"] for record in month["records"]],
        "classifications": {
            record["stable_key"]: record["classification"]
            for record in month["records"]
        },
        "cross_month_work_user_ids": month["cross_month_work_user_ids"],
        "cross_month_quality_user_ids": month["cross_month_quality_user_ids"],
        "multi_source_quality_user_ids": month["multi_source_quality_user_ids"],
        "missing_target_user_ids": month["missing_target_user_ids"],
    }
```

- [ ] **Step 2: Add the exact manifest baseline test**

Insert after `test_preflight_reports_stable_sorted_manifest_and_all_audit_classes`:

```python
def test_history_manifest_matches_exact_pre_refactor_characterization(client):
    with client.application.app_context():
        db = get_db()
        seeded = _seed_history(db)
        actual = _manifest_projection(
            PerformanceHistoryMigrationService.analyze(db, MONTH, MONTH)
        )

        assert actual == {
            "manifest_sha256": "5978dbcd4cecfd76272d60da9ef0557a5fff8503720de8a67e20906119a5c368",
            "month_manifest_sha256": "308b9601d94c8685aa1b873d162b958b486bd3f9a42cc00e06302aff2c6ab9c5",
            "record_count": 13,
            "stable_keys": [
                "assignment_history:00000000000000000006",
                "assignment_history:00000000000000000007",
                "legacy_manifest:00000000000000000001",
                "legacy_score:00000000000000001001",
                "legacy_score:00000000000000001002",
                "legacy_score:00000000000000001003",
                "position_target:00000000000000000001",
                "process_quality_evaluation:00000000000000000001",
                "quality_ambiguity_historical_quality:00000000000000000902",
                "rule_version:00000000000000000001",
                "work_record:00000000000000000001",
                "work_record:00000000000000000002",
                "work_record:00000000000000000003",
            ],
            "classifications": {
                "assignment_history:00000000000000000006": "historical_assignment_snapshot",
                "assignment_history:00000000000000000007": "historical_assignment_snapshot",
                "legacy_manifest:00000000000000000001": "legacy_v1_manifest",
                "legacy_score:00000000000000001001": "prior_revisions_unavailable",
                "legacy_score:00000000000000001002": "missing_position_snapshot",
                "legacy_score:00000000000000001003": "missing_position_target",
                "position_target:00000000000000000001": "approved_position_target",
                "process_quality_evaluation:00000000000000000001": "production_month_boundary",
                "quality_ambiguity_historical_quality:00000000000000000902": "quality_source_confirmation_required",
                "rule_version:00000000000000000001": "published_rule",
                "work_record:00000000000000000001": "production_month_boundary",
                "work_record:00000000000000000002": "production_month_work",
                "work_record:00000000000000000003": "production_month_work",
            },
            "cross_month_work_user_ids": [seeded["confirmed_user"]],
            "cross_month_quality_user_ids": [seeded["confirmed_user"]],
            "multi_source_quality_user_ids": [],
            "missing_target_user_ids": [seeded["no_target_user"]],
        }
```

- [ ] **Step 3: Run the focused performance-history suite twice**

Run: `& "C:\Program Files\Git\bin\bash.exe" -c 'python -m pytest -q tests/test_performance_history_migration.py'`

Run the same command a second time: `& "C:\Program Files\Git\bin\bash.exe" -c 'python -m pytest -q tests/test_performance_history_migration.py'`

Expected: both runs PASS with identical digests. Any difference between the two runs indicates a non-deterministic fixture or manifest input and blocks the commit.

- [ ] **Step 4: Commit the history-manifest contract**

```bash
git add tests/test_performance_history_migration.py
git commit -m "test: freeze performance history manifests"
```

### Task 5: Freeze Process Management UI Workflows

**Files:**
- Modify: `frontend/tests/unit/ProcessList.spec.js:1`
- Read only: `frontend/src/views/ProcessList.vue`
- Read only: `frontend/src/composables/useProcessVersions.js`

**Interfaces:**
- Consumes: the current `ProcessList` button labels, five modal workflows, `useProcessVersions` request payloads, `can(permission)`, `showToast(message, type?)`, and API facade mocks.
- Produces: a parent-level behavioral harness that remediation Task 8 must keep green while extracting dialogs; children may emit intent, but request order, payloads, permission visibility, toast text, close behavior, and reload timing remain owned by the page/composable.

- [ ] **Step 1: Extend the API mock and reset block**

Add `createVersionedProcess: vi.fn()` to `mocks`, expose it beside the other process-version APIs, and reset it in `beforeEach`:

```javascript
const mocks = vi.hoisted(() => ({
  listProcesses: vi.fn(),
  listProcessVersions: vi.fn(),
  getProcessVersionImpact: vi.fn(),
  createVersionedProcess: vi.fn(),
  createProcessRevision: vi.fn(),
  updateProcessVersion: vi.fn(),
  submitProcessVersion: vi.fn(),
  approveProcessVersion: vi.fn(),
  rejectProcessVersion: vi.fn(),
  requestProcessRetirement: vi.fn(),
  requestProcessReactivation: vi.fn(),
  showToast: vi.fn(),
  can: vi.fn(() => true),
  router: { page: 'all-processes' },
}))
```

```javascript
processVersions: {
  listProcessVersions: mocks.listProcessVersions,
  getProcessVersionImpact: mocks.getProcessVersionImpact,
  createVersionedProcess: mocks.createVersionedProcess,
  createProcessRevision: mocks.createProcessRevision,
  updateProcessVersion: mocks.updateProcessVersion,
  submitProcessVersion: mocks.submitProcessVersion,
  approveProcessVersion: mocks.approveProcessVersion,
  rejectProcessVersion: mocks.rejectProcessVersion,
  requestProcessRetirement: mocks.requestProcessRetirement,
  requestProcessReactivation: mocks.requestProcessReactivation,
},
```

```javascript
mocks.createVersionedProcess.mockReset()
```

- [ ] **Step 2: Add deterministic mount and button helpers after `processDetail()`**

```javascript
function seedList(row = processRow) {
  mocks.listProcesses.mockResolvedValue({
    processes: [row],
    total: 1,
    category_counts: { '结构件': 0, '机加工': 1 },
  })
}

function button(wrapper, label) {
  const match = wrapper.findAll('button').find((item) => item.text() === label)
  expect(match, `missing button: ${label}`).toBeTruthy()
  return match
}

async function mountDetail(versions, rootOverrides = {}) {
  seedList()
  mocks.listProcessVersions.mockResolvedValue({
    ...processDetail(versions),
    process: { ...processDetail(versions).process, ...rootOverrides },
  })
  const wrapper = mount(ProcessList)
  await flushPromises()
  await button(wrapper, '查看版本').trigger('click')
  await flushPromises()
  return wrapper
}
```

- [ ] **Step 3: Characterize V1 creation, validation, payload, dialog transition, and reload**

Append inside `describe('ProcessList loading', ...)`:

```javascript
it('creates a V1 draft, opens its detail, toasts, and reloads the list', async () => {
  seedList()
  const root = {
    id: 8,
    process_code: 'PROC-0008',
    lifecycle_status: 'active',
    current_effective_version_id: null,
    row_version: 0,
  }
  const version = {
    ...publishedVersion,
    id: 81,
    process_id: 8,
    version: 1,
    status: 'draft',
    row_version: 0,
    name: '外圆磨',
    revision_reason: '新增磨削工艺',
  }
  mocks.createVersionedProcess.mockResolvedValue({ root, version })
  mocks.listProcessVersions.mockResolvedValue({ process: root, versions: [version], events: [] })

  const wrapper = mount(ProcessList)
  await flushPromises()
  await button(wrapper, '新建工序').trigger('click')
  await wrapper.find('.process-form-modal input[placeholder]').setValue('外圆磨')
  const textareas = wrapper.findAll('.process-form-modal textarea')
  await textareas[0].setValue('磨削外圆')
  await textareas[1].setValue('新增磨削工艺')
  await button(wrapper, '创建 V1 草稿').trigger('click')
  await flushPromises()

  expect(mocks.createVersionedProcess).toHaveBeenCalledWith({
    name: '外圆磨',
    category: '结构件',
    description: '磨削外圆',
    seq_order: 0,
    revision_reason: '新增磨削工艺',
    idempotency_key: expect.stringMatching(/^process-create:/),
  })
  expect(mocks.listProcessVersions).toHaveBeenCalledWith(8)
  expect(mocks.listProcesses).toHaveBeenCalledTimes(2)
  expect(mocks.showToast).toHaveBeenCalledWith('V1 草稿已创建')
  expect(wrapper.text()).toContain('PROC-0008')
})
```

- [ ] **Step 4: Characterize draft save and submit payloads independently**

```javascript
it('saves a draft with row concurrency data and refreshes detail before list reload', async () => {
  const draft = { ...publishedVersion, id: 72, version: 2, status: 'draft', row_version: 3, supersedes_version_id: 71 }
  mocks.updateProcessVersion.mockResolvedValue({ ...draft, row_version: 4, name: '精车二序' })
  const wrapper = await mountDetail([publishedVersion, draft])

  await wrapper.find('.version-editor input').setValue('精车二序')
  await button(wrapper, '保存草稿').trigger('click')
  await flushPromises()

  expect(mocks.updateProcessVersion).toHaveBeenCalledWith(72, {
    row_version: 3,
    name: '精车二序',
    category: '机加工',
    description: '精加工',
    seq_order: 20,
  })
  expect(mocks.listProcessVersions).toHaveBeenCalledTimes(2)
  expect(mocks.listProcesses).toHaveBeenCalledTimes(2)
  expect(mocks.updateProcessVersion.mock.invocationCallOrder[0])
    .toBeLessThan(mocks.listProcessVersions.mock.invocationCallOrder[1])
  expect(mocks.listProcessVersions.mock.invocationCallOrder[1])
    .toBeLessThan(mocks.listProcesses.mock.invocationCallOrder[1])
  expect(mocks.showToast).toHaveBeenCalledWith('草稿已保存')
})

it('submits an unchanged draft with an idempotency key and row version', async () => {
  const draft = { ...publishedVersion, id: 72, version: 2, status: 'draft', row_version: 3, supersedes_version_id: 71 }
  mocks.submitProcessVersion.mockResolvedValue({ ...draft, status: 'pending_approval', row_version: 4 })
  const wrapper = await mountDetail([publishedVersion, draft])

  await button(wrapper, '提交审批').trigger('click')
  await flushPromises()

  expect(mocks.submitProcessVersion).toHaveBeenCalledWith(72, {
    row_version: 3,
    idempotency_key: expect.stringMatching(/^process-submit:/),
  })
  expect(mocks.showToast).toHaveBeenCalledWith('版本已提交审批')
  expect(mocks.listProcesses).toHaveBeenCalledTimes(2)
})
```

- [ ] **Step 5: Characterize approval and rejection, including rejection validation**

```javascript
it('approves a pending version with the frozen transition payload', async () => {
  const pending = { ...publishedVersion, id: 72, version: 2, status: 'pending_approval', row_version: 4, supersedes_version_id: 71 }
  mocks.approveProcessVersion.mockResolvedValue({ ...pending, status: 'published', row_version: 5 })
  const wrapper = await mountDetail([publishedVersion, pending])

  await button(wrapper, '批准并发布').trigger('click')
  await flushPromises()

  expect(mocks.approveProcessVersion).toHaveBeenCalledWith(72, {
    row_version: 4,
    idempotency_key: expect.stringMatching(/^process-approve:/),
  })
  expect(mocks.showToast).toHaveBeenCalledWith('版本已批准并发布')
})

it('validates and submits a rejection reason without closing early', async () => {
  const pending = { ...publishedVersion, id: 72, version: 2, status: 'pending_approval', row_version: 4, supersedes_version_id: 71 }
  mocks.rejectProcessVersion.mockResolvedValue({ ...pending, status: 'rejected', row_version: 5 })
  const wrapper = await mountDetail([publishedVersion, pending])

  await button(wrapper, '驳回').trigger('click')
  await button(wrapper, '确认驳回').trigger('click')
  expect(mocks.showToast).toHaveBeenLastCalledWith('请填写至少 2 个字符的驳回原因', 'error')
  expect(mocks.rejectProcessVersion).not.toHaveBeenCalled()

  await wrapper.find('.command-modal textarea').setValue('工艺参数不完整')
  await button(wrapper, '确认驳回').trigger('click')
  await flushPromises()

  expect(mocks.rejectProcessVersion).toHaveBeenCalledWith(72, {
    row_version: 4,
    idempotency_key: expect.stringMatching(/^process-reject:/),
    reason: '工艺参数不完整',
  })
  expect(mocks.showToast).toHaveBeenCalledWith('版本已驳回')
})
```

- [ ] **Step 6: Characterize both lifecycle commands and permission visibility**

```javascript
it.each([
  ['active', '申请退休', mocks.requestProcessRetirement, /^process-retire:/, '退休申请已提交'],
  ['retired', '申请重新启用', mocks.requestProcessReactivation, /^process-reactivate:/, '重新启用申请已提交'],
])('submits the %s lifecycle command with root concurrency data', async (
  lifecycleStatus, label, apiMethod, keyPattern, toast
) => {
  apiMethod.mockResolvedValue({ id: 91 })
  const wrapper = await mountDetail([publishedVersion], { lifecycle_status: lifecycleStatus })

  const matchingButtons = wrapper.findAll('button').filter((item) => item.text() === label)
  await matchingButtons[matchingButtons.length - 1].trigger('click')
  await wrapper.find('.command-modal textarea').setValue('生命周期受控申请')
  await button(wrapper, '提交申请').trigger('click')
  await flushPromises()

  expect(apiMethod).toHaveBeenCalledWith(7, {
    row_version: 4,
    reason: '生命周期受控申请',
    idempotency_key: expect.stringMatching(keyPattern),
  })
  expect(mocks.showToast).toHaveBeenCalledWith(toast)
})

it('keeps read access while hiding every command denied by permission checks', async () => {
  mocks.can.mockReturnValue(false)
  seedList()
  mocks.listProcessVersions.mockResolvedValue(processDetail())
  const wrapper = mount(ProcessList)
  await flushPromises()

  expect(wrapper.text()).toContain('查看版本')
  expect(wrapper.text()).not.toContain('新建工序')
  expect(wrapper.text()).not.toContain('创建修订版')
  expect(wrapper.text()).not.toContain('申请退休')
  await button(wrapper, '查看版本').trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('已锁定，只读查看')
})

it('maps a stale API error, keeps detail open, and does not reload the list', async () => {
  const draft = { ...publishedVersion, id: 72, version: 2, status: 'draft', row_version: 3, supersedes_version_id: 71 }
  const stale = Object.assign(new Error('stale'), { action: 'refresh_process_version' })
  mocks.updateProcessVersion.mockRejectedValue(stale)
  const wrapper = await mountDetail([publishedVersion, draft])

  await button(wrapper, '保存草稿').trigger('click')
  await flushPromises()

  expect(mocks.showToast).toHaveBeenCalledWith(
    '数据已被其他操作更新，请刷新版本详情后重试',
    'error',
  )
  expect(mocks.listProcesses).toHaveBeenCalledTimes(1)
  expect(wrapper.find('.version-detail-modal').exists()).toBe(true)

  await wrapper.find('.version-detail-modal .modal-close').trigger('click')
  expect(wrapper.find('.version-detail-modal').exists()).toBe(false)
})
```

- [ ] **Step 7: Run the focused UI suite and architecture checks**

Run: `& "C:\Program Files\Git\bin\bash.exe" -c 'npm run test:unit -- frontend/tests/unit/ProcessList.spec.js'`

Expected: PASS; all existing and added `ProcessList` cases pass.

Run: `& "C:\Program Files\Git\bin\bash.exe" -c 'npm run check:architecture'`

Expected: PASS; API facade and frontend import-cycle checks report no violations.

- [ ] **Step 8: Commit the UI workflow contract**

```bash
git add frontend/tests/unit/ProcessList.spec.js
git commit -m "test: freeze process management workflows"
```

### Task 6: Run Full Regression and Record the Characterization Gate

**Files:**
- Create: `docs/superpowers/evidence/2026-08-26-task-1-characterization-baseline.md`
- Verify only: `modules/migrations/__init__.py`
- Verify only: all files changed by Tasks 1 through 5.

**Interfaces:**
- Consumes: all new characterization tests and the repository's existing backend, frontend, architecture, build, and E2E commands.
- Produces: a reviewed test-only Task 1 branch that is the mandatory baseline for remediation Tasks 2 through 8.

- [ ] **Step 1: Prove the branch contains no production-code or schema edits**

Run: `& "C:\Program Files\Git\bin\bash.exe" -c 'git diff --name-only cd6f999836de47a78f0b36f9b251c6f1faa47f49...HEAD'`

Expected: only the approved design/plan, the four backend test files, and `frontend/tests/unit/ProcessList.spec.js` appear at this point; no path under `modules/`, `scripts/`, or `frontend/src/` appears. The evidence document is added only in Step 5 below.

Run: `& "C:\Program Files\Git\bin\bash.exe" -c 'SECRET_KEY=task-1-schema-check python -c "from modules.migrations import LATEST_VERSION; assert LATEST_VERSION == 75; print(LATEST_VERSION)"'`

Expected stdout: `75`.

- [ ] **Step 2: Run all focused backend characterization tests**

Run:

```powershell
& "C:\Program Files\Git\bin\bash.exe" -c 'python -m pytest -q tests/test_evidence_protocol_characterization.py tests/test_actor_context_characterization.py tests/test_production_operations_characterization.py tests/test_performance_history_migration.py tests/test_process_v2_operations_scripts.py tests/test_pending_route_price_v074_operations.py tests/test_deployment_contracts.py'
```

Expected: PASS with no warnings converted to errors and no production artifacts written.

- [ ] **Step 3: Run the complete backend and migration gates**

Run: `& "C:\Program Files\Git\bin\bash.exe" -c 'python -m pytest -q'`

Expected: PASS; the original 1026 tests plus every new parameterized characterization case pass.

Run: `& "C:\Program Files\Git\bin\bash.exe" -c 'python -m pytest -q tests/test_architecture_imports.py tests/test_migrations.py'`

Expected: PASS; Python internal imports remain acyclic and all migrated test databases end at `user_version=75`.

- [ ] **Step 4: Run complete frontend, architecture, build, and E2E gates**

Run: `& "C:\Program Files\Git\bin\bash.exe" -c 'npm run test:unit'`

Expected: PASS; the original 140 cases plus the new `ProcessList` cases pass.

Run: `& "C:\Program Files\Git\bin\bash.exe" -c 'npm run check:architecture'`

Expected: PASS; API facade and frontend import cycles remain clean.

Run: `& "C:\Program Files\Git\bin\bash.exe" -c 'npm run build'`

Expected: PASS and a production bundle is generated without modifying tracked source files.

Run: `& "C:\Program Files\Git\bin\bash.exe" -c 'npm run test:e2e'`

Expected: all 19 existing end-to-end workflows PASS.

- [ ] **Step 5: Create the baseline evidence document only after every gate passes**

Create `docs/superpowers/evidence/2026-08-26-task-1-characterization-baseline.md` with exactly this content:

```markdown
# Task 1 Behavior Characterization Baseline

**Date:** 2026-08-26
**Source production baseline:** `cd6f999836de47a78f0b36f9b251c6f1faa47f49`
**Database schema:** `user_version=75`
**Scope:** tests and evidence only; production code, APIs, permissions, state machines, migrations, and feature flags unchanged

## Frozen Contracts

- Canonical JSON UTF-8 SHA-256: `b684ca625660639998b74c8d97a06487a7c62f3755a93e590de9b8153a20f1cf`
- Synthetic history plan SHA-256: `5978dbcd4cecfd76272d60da9ef0557a5fff8503720de8a67e20906119a5c368`
- Synthetic history month SHA-256: `308b9601d94c8685aa1b873d162b958b486bd3f9a42cc00e06302aff2c6ab9c5`
- Actor adapters preserve the exact `id/name/role` mapping and `ValidationError("操作人不能为空")` contract.
- Performance production commands preserve read-only SQLite, backup, payroll fingerprint, stdout, stderr, and exit-code behavior.
- `ProcessList` preserves creation, version editing, submit, approve, reject, revision, lifecycle, permission, toast, and reload behavior.

## Verification

- Focused backend characterization suite: PASS
- Complete backend suite: PASS
- Python architecture and migration suite: PASS
- Complete frontend unit suite: PASS
- Frontend API facade and import-cycle checks: PASS
- Frontend production build: PASS
- Existing 19-workflow E2E suite: PASS

## Gate

Remediation Tasks 2 through 8 may proceed only while these contracts remain green. Any intentional contract change requires separate design review and approval.
```

- [ ] **Step 6: Commit the verified baseline evidence**

```bash
git add docs/superpowers/evidence/2026-08-26-task-1-characterization-baseline.md
git commit -m "docs: record task 1 characterization baseline"
```

- [ ] **Step 7: Perform the final branch review**

Run: `& "C:\Program Files\Git\bin\bash.exe" -c 'git status --short --branch'`

Expected: clean `codex/task-1-behavior-characterization` branch; no untracked test databases, frontend bundles, coverage files, or evidence artifacts.

Run: `& "C:\Program Files\Git\bin\bash.exe" -c 'git log --oneline --decorate -9'`

Expected: the approved design and plan followed by six narrowly scoped Task 1 commits: evidence bytes, actor adapters, production operations, performance manifests, process UI workflows, and the final evidence record. Do not push or create a PR until the user separately authorizes that external change.

## Task 1 Exit Criteria

- Every new characterization test passes against the unrefactored production baseline.
- The exact evidence UTF-8 bytes and three SHA-256 values in this plan match runtime output.
- All seven actor adapters share the recorded mapping, error, and boolean-ID behavior.
- The selected production scripts share the recorded SQLite, backup, payroll, and CLI behavior, including the replica command's indented failure JSON.
- The performance manifest contains exactly 13 sorted records with the recorded classifications and user sets.
- `ProcessList` workflows retain request payloads, request order, permission visibility, toast copy, modal behavior, and reloads.
- All backend, frontend unit, architecture, build, and 19 E2E gates pass.
- No production code, database migration, feature flag, deployed service, or external repository state changes.
