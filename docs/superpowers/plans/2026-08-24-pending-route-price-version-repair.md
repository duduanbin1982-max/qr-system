# Pending Route Price Version Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow exact price drafts to be created for frozen `pending_approval` route and process versions, then approve them only through an atomic grouped release while preserving auditability and historical bindings.

**Architecture:** Add V074 price lifecycle and audit controls, put pricing eligibility and digest checks in a pure domain module, and enforce them in repositories and transactional services. Expose the same exact-version editor from the wage price page and route detail, while keeping route approval, price preparation, and grouped release approval as separate permissions.

**Tech Stack:** Python 3, Flask, SQLite migrations and triggers, pytest, Vue 3 Composition API, Vitest, Playwright, npm/Vite.

## Global Constraints

- Run every shell command through Git Bash using `& "C:\Program Files\Git\bin\bash.exe" -c '<command>'`.
- Start implementation from the locally committed design at `docs/superpowers/specs/2026-08-24-pending-route-price-version-repair-design.md`.
- Database target is exactly `PRAGMA user_version=74`.
- `draft` routes are preview-only; only `pending_approval` and `published` routes are priceable.
- A pending route node may reference only a `published` or `pending_approval` process version.
- Pending-route price drafts can be approved only inside a grouped release containing their exact route version.
- Price identity is `route_version_id + process_version_id`; root IDs are never selection or grouping keys.
- Route rejection changes bound price drafts to immutable `voided` records in the same transaction.
- Existing approved and retired prices, orders, work facts, payroll facts, and payroll ledgers remain unchanged.
- No automatic inheritance or similarity-based repair of old prices is allowed.
- Production deployment, migration, service restart, feature-flag changes, push, PR creation, and merge each require their own explicit authorization.

---

## File Structure

### New backend files

- `modules/migration_pending_route_price_v074.py`: V074 preconditions, schema rebuild, audit tables, indexes, and triggers.
- `modules/domain/price_versioning.py`: exact-reference keys, pricing modes, digest policy, and stable domain errors.
- `modules/schemas/payroll.py`: strict create, void, and batch-member mutation request schemas.
- `tests/test_pending_route_price_v074_migration.py`: V073-to-V074 preservation and trigger tests.
- `tests/test_pending_route_price_policy.py`: pure policy and repository reference tests.
- `tests/test_pending_route_price_api.py`: service and HTTP contract tests.
- `tests/test_pending_route_price_workflow.py`: route rejection and grouped-release transaction tests.
- `tests/pending_route_price_helpers.py`: reusable exact process/route/price workflow factories for backend tests.
- `tests/test_pending_route_price_v074_operations.py`: read-only preflight and replica validation tests.
- `scripts/pending_route_price_v074_operations.py`: production preflight, replica validation, and staged flag inspection.

### New frontend files

- `frontend/src/composables/useRoutePriceVersions.js`: exact-version catalog, selection, form payloads, and status helpers.
- `frontend/src/components/wage/PriceVersionEditor.vue`: shared exact-version create and void dialog.

### Modified backend files

- `modules/migration_catalog.py`
- `modules/config.py`
- `modules/schemas/__init__.py`
- `modules/schemas/process_versioning.py`
- `modules/repositories/payroll_repository.py`
- `modules/repositories/master_data_release_repository.py`
- `modules/repositories/process_version_repository.py`
- `modules/services/price_version_service.py`
- `modules/services/route_version_service.py`
- `modules/services/process_version_service.py`
- `modules/services/master_data_release_service.py`
- `modules/routes/payroll.py`
- `modules/routes/master_data_releases.py`
- `tests/test_migrations.py`
- `tests/test_master_data_release_workflow.py`
- `tests/test_route_version_workflow.py`
- `tests/test_process_version_workflow.py`

### Modified frontend files

- `frontend/src/lib/api/wages.js`
- `frontend/src/lib/api/master-data-releases.js`
- `frontend/src/lib/router.js`
- `frontend/src/views/WageList.vue`
- `frontend/src/views/wage/PriceVersionTab.vue`
- `frontend/src/views/RouteList.vue`
- `frontend/src/composables/useRouteVersions.js`
- `frontend/src/composables/useMasterDataReleases.js`
- `frontend/src/components/master-data/ReleaseBatchPanel.vue`
- `frontend/tests/unit/PriceVersionTab.spec.js`
- `frontend/tests/unit/RouteVersions.spec.js`
- `frontend/tests/unit/MasterDataRelease.spec.js`
- `frontend/tests/e2e/wage-price-versions.spec.js`

---

### Task 1: Establish the V074 price lifecycle and audit schema

**Files:**
- Create: `modules/migration_pending_route_price_v074.py`
- Create: `tests/test_pending_route_price_v074_migration.py`
- Modify: `modules/migration_catalog.py`
- Modify: `tests/test_migrations.py`

**Interfaces:**
- Produces: `m074_pending_route_price_controls(db: sqlite3.Connection) -> None`.
- Produces columns: `idempotency_key`, `request_digest`, route/process digest snapshots, and void metadata on `route_price_versions`.
- Produces immutable tables: `master_data_release_member_events` and `route_price_reference_compat_audit`.
- Produces terminal status: `voided`.

- [ ] **Step 1: Write failing V074 migration and preservation tests**

Add tests that migrate an in-memory database through V073, record the complete price aggregate, run V074, and assert the new contract:

```python
def test_v074_preserves_prices_and_adds_voided_lifecycle():
    db = migrate_database_through(73)
    before = price_snapshot(db)

    m074_pending_route_price_controls(db)

    columns = {row["name"] for row in db.execute("PRAGMA table_info(route_price_versions)")}
    assert {
        "idempotency_key", "request_digest",
        "route_content_digest_snapshot", "process_content_digest_snapshot",
        "voided_at", "voided_by", "voided_by_name", "void_reason",
    }.issubset(columns)
    assert price_snapshot(db) == before
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_v074_voided_price_is_immutable():
    db = migrated_v074_database_with_draft_price()
    db.execute(
        "UPDATE route_price_versions SET status='voided',"
        "voided_at='2026-08-24 12:00:00',voided_by_name='测试人',"
        "void_reason='路线驳回' WHERE id=1"
    )
    with pytest.raises(sqlite3.IntegrityError, match="voided price versions are immutable"):
        db.execute("UPDATE route_price_versions SET remark='changed' WHERE id=1")
```

Define the test helpers in the same file so the migration fixture is reproducible:

```python
def migrate_database_through(target):
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    for version, _, migration in MIGRATIONS:
        if version > target:
            break
        migration(db)
        db.execute(f"PRAGMA user_version={version}")
        db.commit()
    return db


def price_snapshot(db):
    rows = db.execute(
        "SELECT status,COUNT(*) AS rows,"
        "COALESCE(SUM(normal_unit_price_micros),0) AS micros "
        "FROM route_price_versions GROUP BY status ORDER BY status"
    ).fetchall()
    return [(row["status"], row["rows"], row["micros"]) for row in rows]


def seed_pending_price_binding(db, price_count=1):
    process_id = db.execute(
        "INSERT INTO processes(name,category,status,process_code,lifecycle_status) "
        "VALUES ('V074 工序','机加工','active','PROC-V074','active')"
    ).lastrowid
    process_version_id = db.execute(
        "INSERT INTO process_versions(process_id,version,process_code_snapshot,name,"
        "category,status,content_digest,idempotency_key) "
        "VALUES (?,1,'PROC-V074','V074 工序','机加工','pending_approval',"
        "'process-digest','v074-process')", (process_id,)
    ).lastrowid
    route_id = db.execute(
        "INSERT INTO process_routes(name,category,status,route_code,lifecycle_status) "
        "VALUES ('V074 路线','机加工','inactive','ROUTE-V074','active')"
    ).lastrowid
    route_version_id = db.execute(
        "INSERT INTO process_route_versions(process_route_id,version,route_code_snapshot,"
        "name,category,status,content_digest,idempotency_key) "
        "VALUES (?,1,'ROUTE-V074','V074 路线','机加工','pending_approval',"
        "'route-digest','v074-route')", (route_id,)
    ).lastrowid
    db.execute(
        "INSERT INTO process_route_version_items(route_version_id,process_id,"
        "process_version_id,seq_order) VALUES (?,?,?,10)",
        (route_version_id, process_id, process_version_id),
    )
    for index in range(price_count):
        db.execute(
            "INSERT INTO route_price_versions(route_id,route_version_id,process_id,"
            "process_version_id,normal_unit_price_micros,valid_from,status,remark) "
            "VALUES (?,?,?,?,100000,?,'draft',?)",
            (
                route_id, route_version_id, process_id, process_version_id,
                f"2026-08-{index + 1:02d} 07:00:00", f"draft-{index + 1}",
            ),
        )
    db.commit()
    return db


def migrated_v074_database_with_draft_price():
    return seed_pending_price_binding(migrate_database_through(74))
```

Also assert migration refusal for null exact bindings and duplicate drafts on one pending node. The exception must be `MigrationInvariantError` and include the blocking price IDs.

- [ ] **Step 2: Run the migration tests and verify the expected failure**

Run:

```bash
pytest -q tests/test_pending_route_price_v074_migration.py tests/test_migrations.py::test_migration_catalog_declares_and_validates_the_linear_dependency_chain
```

Expected: FAIL because V074, its module, and dependency `74 -> 73` are not registered.

- [ ] **Step 3: Implement the V074 migration**

Implement explicit preconditions before schema mutation:

```python
def _blocking_price_issues(db):
    rows = db.execute(
        "SELECT price.id FROM route_price_versions price "
        "LEFT JOIN process_route_version_items item "
        "ON item.route_version_id=price.route_version_id "
        "AND item.process_id=price.process_id "
        "AND item.process_version_id=price.process_version_id "
        "WHERE price.route_version_id IS NULL OR price.process_version_id IS NULL "
        "OR item.id IS NULL ORDER BY price.id"
    ).fetchall()
    return [int(row[0]) for row in rows]


def m074_pending_route_price_controls(db):
    blocking = _blocking_price_issues(db)
    if blocking:
        raise MigrationInvariantError(
            "V074 invalid exact price bindings: " + ",".join(map(str, blocking))
        )
    _rebuild_route_price_versions(db)
    _create_member_event_table(db)
    _create_reference_audit_table(db)
    _create_price_v074_indexes(db)
    _create_price_v074_triggers(db)
```

The table rebuild must copy every V073 column, add the V074 columns, permit exactly
`draft|approved|retired|voided`, recreate all V062 exact-binding and overlap triggers,
and add this terminal protection:

```sql
CREATE TRIGGER protect_voided_price_version
BEFORE UPDATE ON route_price_versions
WHEN OLD.status='voided'
BEGIN SELECT RAISE(ABORT,'voided price versions are immutable'); END;
```

Create the non-empty idempotency unique index as:

```sql
CREATE UNIQUE INDEX idx_route_price_versions_idempotency
ON route_price_versions(idempotency_key)
WHERE idempotency_key IS NOT NULL AND idempotency_key<>'';
```

Backfill both snapshot digests from the exact route and process versions for every structurally
valid price. For each pre-existing draft, append one `price_version_v074_digest_backfilled`
`payroll_events` row with deterministic idempotency key `v074:price:<id>:digest`; rerunning the
migration must not duplicate that evidence.

Create immutable member events with exact columns:

```sql
CREATE TABLE master_data_release_member_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('added','removed','replaced')),
    member_type TEXT NOT NULL CHECK(member_type IN
        ('process_version','route_version','price_version')),
    member_id INTEGER NOT NULL,
    replacement_member_id INTEGER,
    actor_id INTEGER,
    actor_name TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY(batch_id) REFERENCES master_data_release_batches(id) ON DELETE RESTRICT,
    FOREIGN KEY(actor_id) REFERENCES users(id) ON DELETE SET NULL
);
```

Create immutable reference observations with published-subset digests, mismatch `0|1`, detail
JSON, and observation time. Add update/delete rejection triggers to both audit tables.

Register the migration and dependency:

Import `PENDING_ROUTE_PRICE_MIGRATIONS` in `modules/migration_catalog.py`, add
`*PENDING_ROUTE_PRICE_MIGRATIONS` as the final entry of the existing registry list, and change the
chain declaration to:

```python
MIGRATION_VERSION_CHAIN = (1, *range(13, 75))
```

Update the three V073 terminal assertions in `tests/test_migrations.py`: the read-only plan from
V070 targets 74 with pending versions `[71, 72, 73, 74]`, and `LATEST_VERSION` equals 74.

- [ ] **Step 4: Run migration tests and the complete migration contract**

Run:

```bash
pytest -q tests/test_pending_route_price_v074_migration.py tests/test_migrations.py tests/test_process_price_version_migration.py
```

Expected: PASS; `LATEST_VERSION == 74`, V073 data aggregates are unchanged, and all price triggers remain active.

- [ ] **Step 5: Commit Task 1**

```bash
git add modules/migration_pending_route_price_v074.py modules/migration_catalog.py tests/test_pending_route_price_v074_migration.py tests/test_migrations.py
git commit -m "feat: add v074 pending route price controls"
```

---

### Task 2: Add pure pricing policy and exact-version repository contracts

**Files:**
- Create: `modules/domain/price_versioning.py`
- Create: `tests/test_pending_route_price_policy.py`
- Modify: `modules/repositories/payroll_repository.py`
- Modify: `modules/repositories/master_data_release_repository.py`
- Modify: `modules/repositories/process_version_repository.py`

**Interfaces:**
- Produces: `price_reference_key(route_version_id, process_version_id) -> str`.
- Produces: `pricing_mode(route_status) -> str`.
- Produces: `assert_exact_price_binding(binding, route_id, process_id) -> None`.
- Produces: `assert_expected_digest(expected, actual) -> None`.
- Produces: `assert_price_snapshot_current(price, binding) -> None`.
- Produces stable errors with codes from the approved design.
- Produces: `PayrollRepository.list_route_process_references(include_pending=False, db=None)`.
- Produces repository methods for idempotent create lookup, exact draft lookup, digest persistence, and transactional voiding.

- [ ] **Step 1: Write failing pure policy and repository tests**

Add pure assertions:

```python
def test_reference_key_uses_both_exact_version_ids():
    assert price_reference_key(82, 72) == "82:72"
    assert price_reference_key(83, 72) != price_reference_key(82, 72)


@pytest.mark.parametrize(
    ("status", "expected"),
    [("published", "published_adjustment"), ("pending_approval", "pending_group_release")],
)
def test_pricing_mode_accepts_only_frozen_states(status, expected):
    assert pricing_mode(status) == expected


def test_pricing_mode_rejects_draft():
    with pytest.raises(RouteVersionNotPricableError):
        pricing_mode("draft")
```

Build one published V1 and one pending V2 under the same route root. Assert the default repository call returns only V1, while `include_pending=True` returns both and preserves two different `reference_key` values.

- [ ] **Step 2: Run the policy tests and verify failure**

Run:

```bash
pytest -q tests/test_pending_route_price_policy.py
```

Expected: FAIL because `modules.domain.price_versioning` and the expanded repository contract do not exist.

- [ ] **Step 3: Implement pure policy and repository methods**

Define stable errors without parsing message strings:

```python
class RouteVersionNotPricableError(ConflictError):
    code = "ROUTE_VERSION_NOT_PRICABLE"


class PriceBindingMismatchError(ConflictError):
    code = "PRICE_BINDING_MISMATCH"


class PriceBindingStaleError(ConflictError):
    code = "PRICE_BINDING_STALE"


class PriceVersionVoidedError(ConflictError):
    code = "PRICE_VERSION_VOIDED"


class GroupReleaseRequiredError(ConflictError):
    code = "GROUP_RELEASE_REQUIRED"


class ProcessVersionNotFrozenError(ConflictError):
    code = "PROCESS_VERSION_NOT_FROZEN"


class ActiveReleaseBatchConflictError(ConflictError):
    code = "ACTIVE_RELEASE_BATCH_CONFLICT"


class PendingRoutePriceWriteDisabledError(ConflictError):
    code = "PENDING_ROUTE_PRICE_WRITE_DISABLED"


class IdempotencyConflictError(ConflictError):
    code = "IDEMPOTENCY_CONFLICT"


class StaleRowVersionError(ConflictError):
    code = "STALE_ROW_VERSION"
```

Use a candidate-version CTE in `list_route_process_references`. The published branch must
join only `route.current_effective_version_id`; the optional pending branch must select
`process_route_versions.status='pending_approval'`. Each returned row includes route/process
version numbers, statuses, content digests, sequence, pricing mode, and exact key.

Add these repository signatures:

```python
price_version_by_idempotency_key(idempotency_key, db=None)
draft_price_for_binding(route_version_id, process_version_id, db=None)
void_price_version(version_id, expected_row_version, payload, db)
void_draft_prices_for_route(route_version_id, payload, db)
pending_routes_for_process_version(process_version_id, db=None)
active_batches_for_route_version(route_version_id, db=None)
insert_release_member_event(payload, db)
list_release_member_events(batch_id, db=None)
```

Every update must include expected status and `row_version` in its `WHERE` clause.

- [ ] **Step 4: Run focused repository and policy tests**

Run:

```bash
pytest -q tests/test_pending_route_price_policy.py tests/test_process_version_repositories.py tests/test_master_data_release_workflow.py
```

Expected: PASS; V1 and V2 never collapse, and no existing repository behavior regresses.

- [ ] **Step 5: Commit Task 2**

```bash
git add modules/domain/price_versioning.py modules/repositories/payroll_repository.py modules/repositories/master_data_release_repository.py modules/repositories/process_version_repository.py tests/test_pending_route_price_policy.py
git commit -m "feat: add exact route price policy"
```

---

### Task 3: Enforce price eligibility, idempotency, schemas, API errors, and feature flags

**Files:**
- Create: `modules/schemas/payroll.py`
- Create: `tests/test_pending_route_price_api.py`
- Modify: `modules/config.py`
- Modify: `modules/schemas/__init__.py`
- Modify: `modules/services/price_version_service.py`
- Modify: `modules/routes/payroll.py`
- Modify: `tests/test_process_price_version_migration.py`

**Interfaces:**
- Produces flags: `ROUTE_PRICE_PENDING_REFERENCE_ENABLED`, `ROUTE_PRICE_PENDING_COMPAT_AUDIT_ENABLED`, and `ROUTE_PRICE_PENDING_WRITE_ENABLED`.
- Produces: `PriceVersionService.create(data, actor_user)` with exact IDs, expected digests, and idempotency.
- Produces: `PriceVersionService.void(version_id, data, actor_user)`.
- Produces endpoints: pending-aware reference and `POST /api/route-price-versions/<id>/void`.

- [ ] **Step 1: Write failing API and flag tests**

Cover default-closed flags and ordered activation:

```python
def test_pending_price_flags_are_fail_closed():
    assert config.get_pending_route_price_flags({}) == {
        "ROUTE_PRICE_PENDING_REFERENCE_ENABLED": False,
        "ROUTE_PRICE_PENDING_COMPAT_AUDIT_ENABLED": False,
        "ROUTE_PRICE_PENDING_WRITE_ENABLED": False,
    }


def test_pending_price_write_requires_reference_and_audit():
    with pytest.raises(RuntimeError, match="待发布路线工价功能开关组合无效"):
        config.validate_pending_route_price_flags({
            "ROUTE_PRICE_PENDING_REFERENCE_ENABLED": True,
            "ROUTE_PRICE_PENDING_COMPAT_AUDIT_ENABLED": False,
            "ROUTE_PRICE_PENDING_WRITE_ENABLED": True,
        })
```

Add API tests for: default published-only response, enabled pending response, exact create payload,
idempotent replay, idempotency conflict, disabled pending write, standalone pending approval rejection,
manual void by creator, and stable `DomainError.to_payload()` codes.

- [ ] **Step 2: Run the API tests and verify failure**

Run:

```bash
pytest -q tests/test_pending_route_price_api.py
```

Expected: FAIL on missing schemas, feature flags, stable error codes, and void endpoint.

- [ ] **Step 3: Implement flags and strict schemas**

Add flag validation:

```python
def validate_pending_route_price_flags(flags=None):
    values = flags or {
        name: globals().get(name, False) for name in PENDING_ROUTE_PRICE_FLAG_NAMES
    }
    if values["ROUTE_PRICE_PENDING_COMPAT_AUDIT_ENABLED"] and not values["ROUTE_PRICE_PENDING_REFERENCE_ENABLED"]:
        raise RuntimeError("待发布路线工价功能开关组合无效：兼容审计要求先开启引用查询")
    if values["ROUTE_PRICE_PENDING_WRITE_ENABLED"] and not (
        values["ROUTE_PRICE_PENDING_REFERENCE_ENABLED"]
        and values["ROUTE_PRICE_PENDING_COMPAT_AUDIT_ENABLED"]
    ):
        raise RuntimeError("待发布路线工价功能开关组合无效：写入要求先完成引用兼容审计")
    return values
```

Register strict JSON schemas named `route_price_version_create` and
`route_price_version_void`. The create schema requires four IDs, two expected digests,
`valid_from`, one price representation, and `idempotency_key`; reject unknown properties.

- [ ] **Step 4: Implement service and HTTP behavior**

At create time, read the binding inside the transaction, verify expected digests against the
database, derive `pricing_mode`, and only then insert:

```python
binding = PayrollRepository.exact_price_binding(route_version_id, process_version_id, db)
assert_exact_price_binding(binding, route_id, process_id)
assert_expected_digest(
    data["expected_route_content_digest"], binding["route_content_digest"]
)
assert_expected_digest(
    data["expected_process_content_digest"], binding["process_content_digest"]
)
mode = pricing_mode(binding["route_version_status"])
if mode == "pending_group_release" and not config.ROUTE_PRICE_PENDING_WRITE_ENABLED:
    raise PendingRoutePriceWriteDisabledError()
```

Store the database digests, not untrusted client values. Return
`approval_mode='grouped_release_only'` for pending routes. In `approve`, raise
`GroupReleaseRequiredError` before any update when the route is not published.

Update `_json_error` to serialize any `DomainError` with its status code:

```python
if isinstance(exc, DomainError):
    return jsonify(exc.to_payload()), exc.status_code
```

When compatibility audit is enabled, compare the new published subset digest to the legacy
published catalog digest and append one immutable audit observation. Pending additions are not
counted as mismatches.

- [ ] **Step 5: Run API, payroll, and schema regression tests**

Run:

```bash
pytest -q tests/test_pending_route_price_api.py tests/test_process_price_version_migration.py tests/test_payroll_ledger.py
```

Expected: PASS; published-route pricing still works and pending-route standalone approval returns `GROUP_RELEASE_REQUIRED` with HTTP 409.

- [ ] **Step 6: Commit Task 3**

```bash
git add modules/config.py modules/schemas/payroll.py modules/schemas/__init__.py modules/services/price_version_service.py modules/routes/payroll.py tests/test_pending_route_price_api.py tests/test_process_price_version_migration.py
git commit -m "feat: expose pending route price drafts"
```

---

### Task 4: Freeze route dependencies and void prices on route rejection

**Files:**
- Create: `tests/pending_route_price_helpers.py`
- Create: `tests/test_pending_route_price_workflow.py`
- Modify: `modules/services/route_version_service.py`
- Modify: `modules/services/process_version_service.py`
- Modify: `modules/repositories/payroll_repository.py`
- Modify: `tests/test_route_version_workflow.py`
- Modify: `tests/test_process_version_workflow.py`

**Interfaces:**
- Consumes: Task 2 repository void and dependency queries.
- Produces: route submit guard for process states.
- Produces: atomic route reject plus price void events.
- Produces: process reject guard when a pending route depends on the process version.
- Produces test factories: `pending_route_with_prices(client, price_count=2)` and
  `route_draft_using_process_status(client, process_status)`.

- [ ] **Step 1: Write failing freeze and rejection transaction tests**

Add these scenarios and enable the staged write flags only inside this test module:

```python
@pytest.fixture(autouse=True)
def enable_pending_price_write(monkeypatch):
    monkeypatch.setattr(config, "ROUTE_PRICE_PENDING_REFERENCE_ENABLED", True)
    monkeypatch.setattr(config, "ROUTE_PRICE_PENDING_COMPAT_AUDIT_ENABLED", True)
    monkeypatch.setattr(config, "ROUTE_PRICE_PENDING_WRITE_ENABLED", True)


def test_route_submit_rejects_draft_process_version(client):
    preparer, _ = _actors(client)
    route = route_draft_using_process_status(client, "draft", preparer)
    with pytest.raises(ProcessVersionNotFrozenError):
        RouteVersionService.submit(route["id"], {
            "row_version": route["row_version"],
            "idempotency_key": "route-submit-draft-process",
        }, preparer)


def test_route_reject_voids_exact_price_drafts_atomically(client):
    preparer, approver = _actors(client)
    route, prices = pending_route_with_prices(client, preparer, price_count=2)
    rejected = RouteVersionService.reject(
        route["id"], {
            "row_version": route["row_version"],
            "idempotency_key": "route-reject-with-prices",
            "reason": "节点需要调整",
        }, approver
    )
    assert rejected["status"] == "draft"
    with client.application.app_context():
        loaded = [PayrollRepository.price_version(price["id"]) for price in prices]
    assert [price["status"] for price in loaded] == ["voided", "voided"]
    assert all(price["void_reason"] == "节点需要调整" for price in loaded)
```

Implement the shared factories with the existing process/route workflow helpers. The price
factory must read digests from `PayrollRepository.exact_price_binding` and pass all required
create fields:

```python
def pending_route_with_prices(client, actor, price_count=2):
    process_versions = []
    for index in range(price_count):
        created = _create_process(client, actor, f"待发布定价工序 {index + 1}")
        with client.application.app_context():
            process_versions.append(ProcessVersionService.submit(
                created["version"]["id"],
                {
                    "row_version": created["version"]["row_version"],
                    "idempotency_key": f"pending-price-process-submit-{uuid.uuid4().hex}",
                },
                actor,
            ))
    route_created = _create_route(client, actor, process_versions)
    with client.application.app_context():
        route = RouteVersionService.submit(
            route_created["version"]["id"],
            {
                "row_version": route_created["version"]["row_version"],
                "idempotency_key": f"pending-price-route-submit-{uuid.uuid4().hex}",
            },
            actor,
        )
        prices = []
        for item in route["items"]:
            binding = PayrollRepository.exact_price_binding(
                route["id"], item["process_version_id"]
            )
            prices.append(PriceVersionService.create({
                "route_id": route["process_route_id"],
                "route_version_id": route["id"],
                "process_id": item["process_id"],
                "process_version_id": item["process_version_id"],
                "expected_route_content_digest": binding["route_content_digest"],
                "expected_process_content_digest": binding["process_content_digest"],
                "normal_unit_price": "1.25",
                "valid_from": "2026-08-24 07:00:00",
                "idempotency_key": f"pending-price-create-{uuid.uuid4().hex}",
            }, actor))
        return route, prices


def route_draft_using_process_status(client, process_status, actor):
    created = _create_process(client, actor, "路线冻结校验工序")
    process_version = created["version"]
    if process_status == "pending_approval":
        with client.application.app_context():
            process_version = ProcessVersionService.submit(
                process_version["id"],
                {
                    "row_version": process_version["row_version"],
                    "idempotency_key": "freeze-check-process-submit",
                },
                actor,
            )
    elif process_status != "draft":
        raise ValueError("test factory supports draft or pending_approval")
    return _create_route(client, actor, [process_version])["version"]


def create_exact_price_for_route_item(route, item, actor, amount):
    binding = PayrollRepository.exact_price_binding(
        route["id"], item["process_version_id"]
    )
    return PriceVersionService.create({
        "route_id": route["process_route_id"],
        "route_version_id": route["id"],
        "process_id": item["process_id"],
        "process_version_id": item["process_version_id"],
        "expected_route_content_digest": binding["route_content_digest"],
        "expected_process_content_digest": binding["process_content_digest"],
        "normal_unit_price": amount,
        "valid_from": "2026-08-24 07:00:00",
        "idempotency_key": f"exact-price-{uuid.uuid4().hex}",
    }, actor)
```

Monkeypatch `void_draft_prices_for_route` to raise after one update and assert the route and both
prices retain their original states after rollback. Add tests that block route rejection from a
pending batch and block process rejection while referenced by a pending route.

- [ ] **Step 2: Run workflow tests and verify failure**

Run:

```bash
pytest -q tests/test_pending_route_price_workflow.py tests/test_route_version_workflow.py tests/test_process_version_workflow.py
```

Expected: FAIL because route submit accepts draft process versions and rejection does not void prices.

- [ ] **Step 3: Implement route submission and rejection guards**

During route submission, resolve all node versions and require frozen states:

```python
process_versions = {
    row["id"]: row
    for row in ProcessVersionRepository.versions_by_ids(
        [item["process_version_id"] for item in version["items"]], db=db
    )
}
invalid = [
    item for item in version["items"]
    if process_versions[item["process_version_id"]]["status"]
    not in {"published", "pending_approval"}
]
if invalid:
    raise ProcessVersionNotFrozenError(
        details={"process_version_ids": [item["process_version_id"] for item in invalid]}
    )
```

During route rejection, block only `pending_approval` release batches, then void prices before
transitioning the route. Use one `BaseService.transaction()` and one timestamp:

```python
active = MasterDataReleaseRepository.active_batches_for_route_version(version_id, db=db)
if any(batch["status"] == "pending_approval" for batch in active):
    raise ActiveReleaseBatchConflictError(details={"batch_ids": [row["id"] for row in active]})
void_payload = {
    "voided_at": now,
    "voided_by": actor["id"],
    "voided_by_name": actor["name"],
    "void_reason": reason,
}
voided = PayrollRepository.void_draft_prices_for_route(version_id, void_payload, db)
for price in voided:
    PayrollRepository.insert_event({
        "event_type": "price_version_voided",
        "operator_id": actor["id"],
        "operator_name": actor["name"],
        "idempotency_key": f"{key}:price:{price['id']}",
        "payload": {"price_version_id": price["id"], "reason": reason},
    }, db)
return RouteVersionRepository.transition_version(
    version_id, "pending_approval", expected, "draft", {}, db
)
```

In process rejection, query pending route dependencies and return a conflict listing exact route
version IDs. Do not cascade process rejection.

- [ ] **Step 4: Run workflow and repository regression tests**

Run:

```bash
pytest -q tests/test_pending_route_price_workflow.py tests/test_route_version_workflow.py tests/test_process_version_workflow.py tests/test_process_version_repositories.py
```

Expected: PASS; failure injection proves no partial price void or route transition is committed.

- [ ] **Step 5: Commit Task 4**

```bash
git add modules/services/route_version_service.py modules/services/process_version_service.py modules/repositories/payroll_repository.py tests/pending_route_price_helpers.py tests/test_pending_route_price_workflow.py tests/test_route_version_workflow.py tests/test_process_version_workflow.py
git commit -m "feat: invalidate prices when routes are rejected"
```

---

### Task 5: Harden grouped release membership, separation of duties, and atomic approval

**Files:**
- Modify: `modules/schemas/process_versioning.py`
- Modify: `modules/repositories/master_data_release_repository.py`
- Modify: `modules/services/master_data_release_service.py`
- Modify: `modules/routes/master_data_releases.py`
- Modify: `tests/test_master_data_release_workflow.py`
- Modify: `tests/test_pending_route_price_workflow.py`

**Interfaces:**
- Consumes: exact price snapshots and terminal `voided` status from Tasks 1-3.
- Produces: `remove_member(batch_id, command, actor_user)` and
  `replace_member(batch_id, command, actor_user)`.
- Produces HTTP endpoints `/members/remove` and `/members/replace` for draft batches.
- Produces grouped-release digest and duties validation for every member.

- [ ] **Step 1: Write failing release-member and atomic approval tests**

Add tests that prove. Include the pytest `monkeypatch` fixture in this test signature:

```python
def test_draft_batch_can_auditably_replace_voided_price(client, monkeypatch):
    monkeypatch.setattr(config, "ROUTE_PRICE_PENDING_REFERENCE_ENABLED", True)
    monkeypatch.setattr(config, "ROUTE_PRICE_PENDING_COMPAT_AUDIT_ENABLED", True)
    monkeypatch.setattr(config, "ROUTE_PRICE_PENDING_WRITE_ENABLED", True)
    preparer, _ = _actors(client)
    route, prices = pending_route_with_prices(client, preparer, price_count=1)
    with client.application.app_context():
        voided_price = PriceVersionService.void(
            prices[0]["id"], {
                "row_version": prices[0]["row_version"],
                "reason": "金额录入错误",
                "idempotency_key": "void-price-before-replace",
            }, preparer
        )
        replacement = create_exact_price_for_route_item(
            route, route["items"][0], preparer, "1.50"
        )
    batch = _create_batch(
        client, preparer, route_ids=[route["id"]], price_ids=[voided_price["id"]]
    )
    command = {
        "member_type": "price_version",
        "member_id": voided_price["id"],
        "replacement_member_id": replacement["id"],
        "row_version": batch["row_version"],
        "reason": "替换已作废工价",
        "idempotency_key": "replace-voided-price",
    }
    with client.application.app_context():
        result = MasterDataReleaseService.replace_member(
            batch["id"], command, preparer
        )
        event = MasterDataReleaseRepository.list_release_member_events(batch["id"])[-1]
    assert [row["id"] for row in result["price_versions"]] == [replacement["id"]]
    assert event["action"] == "replaced"
    assert event["member_id"] == voided_price["id"]
    assert event["replacement_member_id"] == replacement["id"]
```

Add `create_exact_price_for_route_item(route, item, actor, amount)` to
`tests/pending_route_price_helpers.py`; it reads the current binding digests and calls
`PriceVersionService.create` with a fresh deterministic-prefix idempotency key.

Also test: non-draft batch mutation is rejected; voided or stale prices block submit; a pending
price not matching a route node blocks submit; approver matching any process, route, price, or
batch creator blocks approval; and injected price approval failure rolls back process and route
publication.

- [ ] **Step 2: Run grouped-release tests and verify failure**

Run:

```bash
pytest -q tests/test_master_data_release_workflow.py tests/test_pending_route_price_workflow.py
```

Expected: FAIL on missing member mutation and incomplete duties/digest validation.

- [ ] **Step 3: Implement audited draft-member mutation**

Add strict schemas requiring `member_type`, IDs, `row_version`, reason, and idempotency key.
Whitelist table mappings in the repository:

```python
MEMBER_TABLES = {
    "process_version": ("master_data_release_process_versions", "process_version_id"),
    "route_version": ("master_data_release_route_versions", "route_version_id"),
    "price_version": ("master_data_release_price_versions", "price_version_id"),
}
```

Within one transaction, require `batch.status == 'draft'`, write an immutable member event,
change the active join row, increment batch `row_version`, and return the complete batch. An
idempotent replay returns the already-mutated batch. Update `create_batch` so each initial member
also receives an `added` event keyed from the batch-create idempotency key and exact member ID;
existing batches are not retroactively fabricated into user actions.

- [ ] **Step 4: Implement complete submit and approval validation**

Before submit and again before approval, validate every price:

```python
route_nodes = {
    (int(route["id"]), int(item["process_version_id"]))
    for route in batch["route_versions"]
    for item in route.get("items") or []
}
if price["status"] not in {"draft", "approved"}:
    if price["status"] == "voided":
        raise PriceVersionVoidedError(details={"price_version_id": price["id"]})
    raise PriceBindingMismatchError(details={
        "price_version_id": price["id"], "status": price["status"]
    })
binding = PayrollRepository.exact_price_binding(
    price["route_version_id"], price["process_version_id"], db
)
assert_price_snapshot_current(price, binding)
if (price["route_version_id"], price["process_version_id"]) not in route_nodes:
    raise PriceBindingMismatchError(details={"price_version_id": price["id"]})
```

Before any publication, call `assert_separation_of_duties` for batch creator and every included
process, route, and price creator. Preserve the existing process -> route -> price update order in
one transaction. Recompute the release digest after any member replacement.

- [ ] **Step 5: Run grouped release and domain regression tests**

Run:

```bash
pytest -q tests/test_master_data_release_workflow.py tests/test_pending_route_price_workflow.py tests/test_process_management.py tests/test_payroll_ledger.py
```

Expected: PASS; grouped publication remains idempotent and rollback-safe.

- [ ] **Step 6: Commit Task 5**

```bash
git add modules/schemas/process_versioning.py modules/repositories/master_data_release_repository.py modules/services/master_data_release_service.py modules/routes/master_data_releases.py tests/test_master_data_release_workflow.py tests/test_pending_route_price_workflow.py
git commit -m "feat: harden grouped route price releases"
```

---

### Task 6: Build the shared exact-version price editor and repair the wage price page

**Files:**
- Create: `frontend/src/composables/useRoutePriceVersions.js`
- Create: `frontend/src/components/wage/PriceVersionEditor.vue`
- Modify: `frontend/src/lib/api/wages.js`
- Modify: `frontend/src/views/wage/PriceVersionTab.vue`
- Modify: `frontend/tests/unit/PriceVersionTab.spec.js`

**Interfaces:**
- Produces: `priceReferenceKey(reference) -> string`.
- Produces: `useRoutePriceVersions()` with `load`, `selectReference`, `createDraft`, and `voidDraft`.
- Produces editor props `reference`, `currentPrice`, `open`; emits `created`, `voided`, and `close`.
- Produces pending-aware and void API methods.

- [ ] **Step 1: Replace root-ID fixtures with exact-version fixtures and write failing UI tests**

Use references that intentionally share root IDs:

```javascript
const references = [
  {
    reference_key: '81:71', route_id: 8, route_version_id: 81, route_version: 1,
    route_name: '标准机加工路线', route_version_status: 'published',
    route_content_digest: 'route-v1', process_id: 7, process_version_id: 71,
    process_version: 1, process_name: '精车', process_version_status: 'published',
    process_content_digest: 'process-v1', pricing_mode: 'published_adjustment',
  },
  {
    reference_key: '82:72', route_id: 8, route_version_id: 82, route_version: 2,
    route_name: '标准机加工路线', route_version_status: 'pending_approval',
    route_content_digest: 'route-v2', process_id: 7, process_version_id: 72,
    process_version: 2, process_name: '精车二序', process_version_status: 'pending_approval',
    process_content_digest: 'process-v2', pricing_mode: 'pending_group_release',
  },
]
```

Assert two independent route-version rows render, pending mode has the fixed grouped-release
notice, no standalone approve button is shown for pending prices, and create sends:

```javascript
expect(mocks.createVersion).toHaveBeenCalledWith(expect.objectContaining({
  route_id: 8,
  route_version_id: 82,
  process_id: 7,
  process_version_id: 72,
  expected_route_content_digest: 'route-v2',
  expected_process_content_digest: 'process-v2',
  idempotency_key: expect.stringMatching(/^route-price-create:/),
}))
```

- [ ] **Step 2: Run unit tests and verify failure**

Run:

```bash
npm run test:unit -- frontend/tests/unit/PriceVersionTab.spec.js
```

Expected: FAIL because the current page groups and submits by root IDs.

- [ ] **Step 3: Implement the composable and API facade**

Update API methods:

```javascript
getRoutePriceVersionReference: params => request(
  'GET', '/api/route-price-versions/reference' + buildQuery(params)
),
voidRoutePriceVersion: (id, data) => request(
  'POST', `/api/route-price-versions/${id}/void`, data
),
```

The composable key function must be exact:

```javascript
export function priceReferenceKey(reference) {
  return `${Number(reference.route_version_id)}:${Number(reference.process_version_id)}`
}
```

`createDraft` copies locked IDs and expected digests from the selected reference, generates one
idempotency key per save attempt, and never derives a version ID from a root ID.

- [ ] **Step 4: Extract and use the shared editor**

`PriceVersionEditor.vue` owns price fields, validation, pending-route notice, change preview, and
the save/void commands. It receives one immutable reference object and disables route/process
selectors while open. The page owns view selection and data loading.

Replace route cards with unframed, version-grouped tables and expose exactly these views:

```javascript
const viewOptions = [
  { value: 'published', label: '当前已发布' },
  { value: 'pending-route', label: '待发布路线' },
  { value: 'voided', label: '已作废记录' },
]
```

Display route label `路线名称 · 当前 Vn` or `路线名称 · 待发布 Vn`, process sequence and
version, and `approval_mode`. The voided view is read-only and shows reason, time, and operator.

- [ ] **Step 5: Run focused frontend tests and architecture checks**

Run:

```bash
npm run test:unit -- frontend/tests/unit/PriceVersionTab.spec.js
npm run check:architecture
```

Expected: PASS; no API facade or import-cycle violations.

- [ ] **Step 6: Commit Task 6**

```bash
git add frontend/src/composables/useRoutePriceVersions.js frontend/src/components/wage/PriceVersionEditor.vue frontend/src/lib/api/wages.js frontend/src/views/wage/PriceVersionTab.vue frontend/tests/unit/PriceVersionTab.spec.js
git commit -m "feat: add exact version price editor"
```

---

### Task 7: Connect route coverage and grouped release UI to exact pricing

**Files:**
- Modify: `frontend/src/views/RouteList.vue`
- Modify: `frontend/src/composables/useRouteVersions.js`
- Modify: `frontend/src/lib/api/master-data-releases.js`
- Modify: `frontend/src/lib/router.js`
- Modify: `frontend/src/views/WageList.vue`
- Modify: `frontend/src/composables/useMasterDataReleases.js`
- Modify: `frontend/src/components/master-data/ReleaseBatchPanel.vue`
- Modify: `frontend/tests/unit/RouteVersions.spec.js`
- Modify: `frontend/tests/unit/MasterDataRelease.spec.js`
- Modify: `frontend/tests/unit/router.spec.js`

**Interfaces:**
- Consumes: Task 6 `PriceVersionEditor` and exact reference key.
- Produces: route coverage states and batch prefill from exact route/process versions.
- Produces frontend commands for audited release-member removal and replacement.

- [ ] **Step 1: Write failing route coverage and batch repair tests**

Assert route draft, pending, and rejected-price behavior:

```javascript
expect(draftWrapper.text()).toContain('提交审批后可定价')
expect(draftWrapper.find('[data-testid="create-exact-price-72"]').attributes('disabled')).toBeDefined()

await pendingWrapper.find('[data-testid="create-exact-price-72"]').trigger('click')
expect(mocks.navigate).toHaveBeenCalledWith('wages', {
  wage_tab: 'priceversions',
  route_version_id: 82,
  process_version_id: 72,
})
```

For `ReleaseBatchPanel`, provide one `voided` price and assert submit is disabled, the invalid
member is named, and replacement calls the API with batch `row_version`, reason, exact member IDs,
and an idempotency key.

- [ ] **Step 2: Run route and release UI tests and verify failure**

Run:

```bash
npm run test:unit -- frontend/tests/unit/RouteVersions.spec.js frontend/tests/unit/MasterDataRelease.spec.js
```

Expected: FAIL because route coverage has no shared editor and batch membership cannot be repaired.

- [ ] **Step 3: Implement route coverage states and shared editor entry**

Compute coverage only by exact IDs:

```javascript
const coverageRows = computed(() => (selectedVersion.value?.items || []).map(node => {
  const exact = priceVersions.value.filter(price => (
    Number(price.route_version_id) === Number(selectedVersion.value.id)
    && Number(price.process_version_id) === Number(node.process_version_id)
  ))
  return Object.assign({}, node, {
    exact_prices: exact,
    coverage_status: exact.some(price => price.status === 'approved')
      ? 'approved'
      : exact.some(price => price.status === 'draft')
        ? 'draft'
        : exact.some(price => price.status === 'voided') ? 'voided' : 'missing',
  })
}))
```

For a route draft, load only the previous route revision's exact approved price with the same
`process_id` as `reference_price`; never count it as coverage. Show create and bulk-create actions
only when route status is `pending_approval` and `can('wages:prepare')` is true. Those actions call
`navigate('wages', params)` and persist the wage tab plus exact IDs.

Extend `requestedNavigation()` with `wage_tab`, `route_version_id`, and `process_version_id`.
`WageList.vue` passes those values to `PriceVersionTab`; the price page restores the exact
selection after refresh and clears the one-time create intent after opening the shared editor.

- [ ] **Step 4: Implement batch member repair and dependency prefill**

Add API facade methods:

```javascript
removeReleaseBatchMember: (id, data) => request(
  'POST', `/api/master-data-release-batches/${id}/members/remove`, data
),
replaceReleaseBatchMember: (id, data) => request(
  'POST', `/api/master-data-release-batches/${id}/members/replace`, data
),
```

When creating a batch from a pending route, include each non-published process version, the exact
route version, and only exact `draft` prices. Never include `voided` prices. Disable submit while
any invalid member remains and show its stable backend error action.

- [ ] **Step 5: Run frontend unit tests and production build**

Run:

```bash
npm run test:unit -- frontend/tests/unit/RouteVersions.spec.js frontend/tests/unit/MasterDataRelease.spec.js frontend/tests/unit/PriceVersionTab.spec.js
npm run build
```

Expected: PASS; Vite build completes and no text or controls overflow in component tests.

- [ ] **Step 6: Commit Task 7**

```bash
git add frontend/src/views/RouteList.vue frontend/src/composables/useRouteVersions.js frontend/src/lib/api/master-data-releases.js frontend/src/lib/router.js frontend/src/views/WageList.vue frontend/src/composables/useMasterDataReleases.js frontend/src/components/master-data/ReleaseBatchPanel.vue frontend/tests/unit/RouteVersions.spec.js frontend/tests/unit/MasterDataRelease.spec.js frontend/tests/unit/router.spec.js
git commit -m "feat: connect route pricing to grouped release"
```

---

### Task 8: Add V074 read-only preflight, replica validation, and staged cutover controls

**Files:**
- Create: `scripts/pending_route_price_v074_operations.py`
- Create: `tests/test_pending_route_price_v074_operations.py`
- Create: `docs/pending-route-price-v074-runbook.md`

**Interfaces:**
- Produces: `run_preflight(database_path) -> dict` without changing source bytes.
- Produces: `validate_replica(source_path, replica_path) -> dict`.
- Produces: `read_pending_price_flags(env_path) -> dict` and controlled next-stage validation.
- Produces internal helpers: `database_sha256`, `database_health`, `price_aggregates`,
  `blocking_price_differences`, `release_batch_summary`,
  `payroll_price_reference_summary`, and `canonical_sha256`.

- [ ] **Step 1: Write failing read-only operations tests**

Add source-hash and report assertions:

```python
def test_v074_preflight_is_read_only_and_lists_blockers(tmp_path):
    source = copy_v073_database(tmp_path)
    before = database_sha256(source)
    report = run_preflight(source)
    assert database_sha256(source) == before
    assert report["mode"] == "read_only_preflight"
    assert report["database"]["user_version"] == 73
    assert set(report["blocking"]) == {
        "empty_bindings", "binding_mismatches", "duplicate_pending_drafts"
    }
```

Define the V073 fixture in the same test file:

```python
def copy_v073_database(tmp_path):
    source = tmp_path / "source-v073.db"
    db = sqlite3.connect(source)
    db.row_factory = sqlite3.Row
    for version, _, migration in MIGRATIONS:
        if version > 73:
            break
        migration(db)
        db.execute(f"PRAGMA user_version={version}")
        db.commit()
    db.close()
    return source
```

Replica validation must assert target version 74, equal approved/retired aggregates, zero blocking
differences, `foreign_key_check=[]`, and `integrity_check='ok'`. Flag tests must permit only:
closed -> reference+audit -> reference+audit+write.

- [ ] **Step 2: Run operations tests and verify failure**

Run:

```bash
pytest -q tests/test_pending_route_price_v074_operations.py
```

Expected: FAIL because the V074 operations module does not exist.

- [ ] **Step 3: Implement read-only preflight and replica validation**

Open source databases as `file:<path>?mode=ro`, set `PRAGMA query_only=ON`, and collect:

```python
report = {
    "mode": "read_only_preflight",
    "database": database_health(db),
    "price_aggregates": price_aggregates(db),
    "blocking": blocking_price_differences(db),
    "release_batches": release_batch_summary(db),
    "payroll_references": payroll_price_reference_summary(db),
}
report["summary_sha256"] = canonical_sha256(report)
```

Replica validation copies the database, calls the shared `run_migrations`, compares business
aggregates, and never rewrites the source. Exit nonzero when any blocking collection is non-empty.

- [ ] **Step 4: Write the exact runbook**

Document commands for: read-only preflight, backup verification, replica validation, migration
plan inspection, maintenance-window stop/migrate/start, flag stages, acceptance queries, and full
database/code rollback. State that the runbook is not authorization to execute production changes.

- [ ] **Step 5: Run operations and deployment contract tests**

Run:

```bash
pytest -q tests/test_pending_route_price_v074_operations.py tests/test_deployment_contracts.py tests/test_migrations.py
```

Expected: PASS; source database hashes remain unchanged during preflight and replica validation.

- [ ] **Step 6: Commit Task 8**

```bash
git add scripts/pending_route_price_v074_operations.py tests/test_pending_route_price_v074_operations.py docs/pending-route-price-v074-runbook.md
git commit -m "ops: add pending route price v074 controls"
```

---

### Task 9: Complete end-to-end workflow and full regression acceptance

**Files:**
- Modify: `frontend/tests/e2e/wage-price-versions.spec.js`
- Modify: `tests/test_pending_route_price_workflow.py`
- Modify: `docs/superpowers/specs/2026-08-24-pending-route-price-version-repair-design.md` only if an implementation-discovered contract correction is explicitly approved.

**Interfaces:**
- Consumes every prior task.
- Produces automated evidence for exact selection, grouped release, history preservation, rejection voiding, responsive UI, and zero runtime failures.

- [ ] **Step 1: Write the complete browser workflow before final implementation adjustments**

Mock or seed published V1 and pending V2 under the same route root. The Playwright test must:

```javascript
let createdPayload = {}
await page.route(/\/api\/route-price-versions$/, async route => {
  if (route.request().method() === 'POST') createdPayload = route.request().postDataJSON()
  await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ id: 301, status: 'draft' }) })
})
await main.getByRole('button', { name: '工价版本', exact: true }).click()
await main.getByTestId('view-pending-route').click()
await expect(main.getByText('标准机加工路线 · 待发布 V2')).toBeVisible()
await main.getByTestId('create-price-82-72').click()
await expect(page.locator('.price-version-editor')).toContainText('只能随路线成组发布')
await page.locator('[data-testid="save-price-draft"]').click()
await expect.poll(() => createdPayload.route_version_id).toBe(82)
await expect.poll(() => createdPayload.process_version_id).toBe(72)
```

Then visit route details, verify exact coverage, prefill a release batch, approve it with a distinct
actor fixture, and verify V1 historical rows remain visible. A second scenario rejects V3 and
asserts the price appears only in the voided view.

- [ ] **Step 2: Run E2E and verify any remaining failure**

Run:

```bash
npm run test:e2e -- frontend/tests/e2e/wage-price-versions.spec.js
```

Expected before final adjustments: FAIL only on assertions not yet connected by Tasks 6-7; no unrelated runtime exception is acceptable.

- [ ] **Step 3: Make only contract-preserving integration adjustments**

Fix selectors, API mock shapes, and state refreshes required by the E2E flow. Do not weaken exact
ID checks, pending-only write rules, duties separation, digest checks, or atomic rollback. Any
required behavior change outside the approved design stops implementation for user review.

- [ ] **Step 4: Run the focused backend acceptance suite**

Run:

```bash
pytest -q tests/test_pending_route_price_v074_migration.py tests/test_pending_route_price_policy.py tests/test_pending_route_price_api.py tests/test_pending_route_price_workflow.py tests/test_master_data_release_workflow.py tests/test_pending_route_price_v074_operations.py
```

Expected: PASS with zero skipped tests in these files.

- [ ] **Step 5: Run full backend and frontend regression**

Run:

```bash
pytest -q
npm run test:unit
npm run check:architecture
npm run build
npm run test:e2e
```

Expected: all commands exit 0. Record exact test totals and any pre-existing skips in the eventual
PR evidence; do not describe a failing or unrun suite as passed.

- [ ] **Step 6: Inspect desktop and mobile screenshots**

Verify at `1440x900` and `390x844` that route/version labels, price inputs, grouped-release warning,
void reason, and action buttons do not overlap or trigger horizontal document scrolling. Confirm
the pending route and actual product/process context remain visible without opening another panel.

- [ ] **Step 7: Commit Task 9**

```bash
git add frontend/tests/e2e/wage-price-versions.spec.js tests/test_pending_route_price_workflow.py
git commit -m "test: verify pending route price workflow"
```

---

## Completion Gate

Implementation is complete only when all of the following are true:

- V074 migrates a V073 replica without changing approved/retired price aggregates.
- Default reference queries remain published-only; enabled pending queries add exact frozen versions.
- The UI and API submit four exact IDs and two expected content digests.
- Pending-route prices cannot be approved independently.
- Route rejection atomically produces immutable `voided` prices and audit events.
- Draft batch member repair is audited; submitted batch membership remains immutable.
- Grouped release checks every creator, every digest, every exact node, and rolls back on failure.
- New orders use the new published route/process/price versions; historical orders and payroll remain unchanged.
- Preflight is byte-for-byte read-only, replica validation passes, and feature flags advance only in order.
- Full backend, frontend unit, architecture, build, and E2E commands all pass.
- No GitHub or production mutation occurs without separate explicit authorization.
