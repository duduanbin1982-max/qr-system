# Production Node Scheduling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace production-line-based capacity scheduling with stable physical production nodes while preserving historical schedules, providing staged compatibility, and enforcing node capability, calendar, locking, batch, and audit rules.

**Architecture:** Add V086 production-node master data and V087 node scheduling facts beside the existing line tables, then route reads and writes through feature-gated node repositories and policies. Keep legacy identifiers as read-only projections during dual-read auditing; switch the scheduling engine only after shadow scheduling and compatibility checks pass, and block legacy writes in a separately authorized final cutover.

**Tech Stack:** Python 3.12, Flask, SQLite, pytest, Vue 3, Vitest, Vite, Bash deployment scripts, user-level systemd.

## Global Constraints

- Run every local shell command through Git Bash using `& "C:\Program Files\Git\bin\bash.exe" -c '<command>'` from `C:\Users\dubin\Documents\生产管理系统升级版\qr-system`.
- Production nodes are stable, independently occupied physical capacity units; employees are assignments to nodes, not nodes themselves.
- Core-node baseline is exactly: 下料 1、铆接 4、焊接 10、抛丸 1、打磨 1、镗孔 2、喷漆 2.
- Same-process nodes are interchangeable only after capability matching.
- Capacity modes are exactly `exclusive` and `batch`; all migrated nodes start as `exclusive`.
- Default calendar remains `08:00–12:00` and `13:00–18:00`, 540 effective minutes per workday.
- Quantity orders may split across compatible nodes; one serial item for one operation must remain on exactly one node.
- Published schedules and completed production facts are immutable; migration must not recalculate historical time, quantity, work-time, payroll, or completion facts.
- New scheduling code uses `production_node_id`; `process_line_id` remains a deprecated read-only compatibility projection until a separately authorized legacy-write block.
- Do not delete `production_lines`, `process_production_lines`, their columns, old audit rows, backups, attachments, or deployment evidence.
- Keep `PRODUCTION_NODE_WRITE_ENABLED=false`, `PRODUCTION_NODE_ENGINE_ENABLED=false`, and `LEGACY_PROCESS_LINE_WRITE_BLOCKED=false` through query/audit and shadow phases.
- Any production migration, service stop/restart, feature-flag change, push, merge, or deployment requires its own explicit authorization for the exact commit and maintenance window.

---

## File and Responsibility Map

- `modules/migration_production_nodes.py`: V086/V087 additive schemas, exact legacy mapping, historical fact backfill, triggers, indexes, and compatibility audit tables.
- `modules/domain/production_node_scheduling.py`: pure capability matching, capacity-mode validation, error codes, serial-split constraints, and deterministic node ranking.
- `modules/repositories/production_node_repository.py`: node master data, capability, calendar override, audit event, mapping, lock, and compatibility persistence.
- `modules/services/production_node_service.py`: validated node commands and read projections used by API and UI.
- `modules/services/production_node_compatibility_service.py`: feature-gated node/legacy dual reads and immutable mismatch evidence.
- `modules/repositories/schedule_capacity_repository.py`: node-aware schedule facts, segment persistence, occupancy, revision snapshots, and deprecated line projection.
- `modules/services/schedule_capacity_service.py`: node selection, exclusive/batch allocation, serial rules, locking, publishing, and dynamic replan orchestration.
- `modules/schemas/production_nodes.py`: JSON schemas for node, capability, override, downtime, lock, adjustment, submit, approve, and reject commands.
- `modules/routes/production_nodes.py`: node master-data and audit endpoints.
- `modules/routes/schedule.py`: node scheduling, lock, adjustment, revision lifecycle, downtime, shadow, and compatibility endpoints.
- `modules/config.py`: staged production-node flags and invalid-combination startup checks.
- `modules/permission_catalog.py`: granular `production_nodes:*` and `schedules:*` permissions while preserving legacy page visibility.
- `frontend/src/lib/api/production.js`: node API facade.
- `frontend/src/composables/gantt/useProductionNodes.js`: node loading, grouping, capability and calendar commands.
- `frontend/src/composables/gantt/useGanttCapacity.js`: node filters, node downtime, generation, locking, adjustment, and blocked-code presentation.
- `frontend/src/composables/useGantt.js`: granular permission wiring.
- `frontend/src/views/GanttChart.vue`: process-node hierarchy, node management, lock indicators, downtime overlays, split detail, and compatibility-free business terminology.
- `scripts/production_node_operations.py`: read-only preflight, replica migration, compatibility audit, shadow run, cutover evidence, and flag-file transitions.
- `docs/production-node-scheduling-runbook.md`: staged rollout and rollback commands.

---

### Task 1: Freeze Legacy Scheduling Compatibility Contracts

**Files:**
- Create: `tests/test_production_node_legacy_contracts.py`
- Modify: `tests/test_schedule_capacity.py`
- Modify: `frontend/tests/unit/api-transport-contract.spec.js`

**Interfaces:**
- Consumes: existing `ScheduleCapacityService`, `/api/schedule/capacity-lines`, `/api/schedule/downtime`, and `process_line_id` responses.
- Produces: characterization tests proving legacy reads remain stable until feature flags switch; all later tasks must keep these tests green.

- [ ] **Step 1: Write failing/characterization backend tests**

Create fixtures that seed one `process_production_lines` row, one schedule, one segment, one downtime record, and one immutable revision item. Assert the exact legacy projection:

```python
def test_legacy_schedule_projection_remains_readable(client):
    seeded = seed_legacy_line_schedule(client)
    response = client.get(
        f"/api/schedule/order/{seeded['order_id']}/operations",
        headers=seeded["headers"],
    )
    assert response.status_code == 200
    operation = response.get_json()["operations"][0]
    assert operation["process_line_id"] == seeded["line_id"]
    assert operation["line_name"] == "焊接1线"
    assert operation.get("production_node_id") is None
```

Add a database fingerprint assertion covering `order_process_schedules`, `order_process_schedule_segments`, `schedule_revision_items`, and `schedule_downtime_events` before node migrations.

- [ ] **Step 2: Run the characterization tests**

Run:

```bash
python -m pytest -q tests/test_production_node_legacy_contracts.py tests/test_schedule_capacity.py
```

Expected: PASS against V085; no production-node fields are required yet.

- [ ] **Step 3: Freeze the API transport contract**

Add a Vitest assertion that the existing compatibility methods still serialize `process_line_id` exactly:

```javascript
await api.domains.production.listScheduleDowntime({ process_line_id: 41, limit: 10 })
expect(fetchMock).toHaveBeenCalledWith(
  '/api/schedule/downtime?process_line_id=41&limit=10',
  expect.any(Object),
)
```

- [ ] **Step 4: Run frontend contract tests**

Run:

```bash
npm run test:unit -- --run frontend/tests/unit/api-transport-contract.spec.js
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_production_node_legacy_contracts.py tests/test_schedule_capacity.py frontend/tests/unit/api-transport-contract.spec.js
git commit -m "test: freeze legacy schedule compatibility"
```

---

### Task 2: Add V086 Production Node Master Data

**Files:**
- Create: `modules/migration_production_nodes.py`
- Create: `tests/test_production_node_migrations.py`
- Modify: `modules/migration_catalog.py`
- Modify: `tests/test_migrations.py`

**Interfaces:**
- Consumes: V085 `process_production_lines`, `schedule_calendars`, `processes`, and `users`.
- Produces: `production_nodes`, `production_node_capabilities`, `production_node_calendar_overrides`, `production_node_audit_events`, and exact one-to-one legacy mappings.

- [ ] **Step 1: Write V086 migration tests**

Assert schema constraints, 21-node baseline, one-to-one mapping, default exclusive mode, 540-minute calendars, and idempotent migration:

```python
def test_v086_maps_each_process_line_to_one_stable_node(migrated_v085_db):
    from modules.migration_production_nodes import m086_production_node_master

    before = migrated_v085_db.execute(
        "SELECT COUNT(*) FROM process_production_lines"
    ).fetchone()[0]
    m086_production_node_master(migrated_v085_db)
    m086_production_node_master(migrated_v085_db)
    mapped = migrated_v085_db.execute(
        "SELECT COUNT(*) FROM production_nodes WHERE legacy_process_line_id IS NOT NULL"
    ).fetchone()[0]
    assert mapped == before
    assert migrated_v085_db.execute(
        "SELECT COUNT(*) FROM production_nodes WHERE capacity_mode<>'exclusive'"
    ).fetchone()[0] == 0
```

Also assert the seven-process distribution equals `{下料:1, 铆接:4, 焊接:10, 抛丸:1, 打磨:1, 镗孔:2, 喷漆:2}`.

- [ ] **Step 2: Run the migration test and verify failure**

Run:

```bash
python -m pytest -q tests/test_production_node_migrations.py::test_v086_maps_each_process_line_to_one_stable_node
```

Expected: FAIL because `modules.migration_production_nodes` does not exist.

- [ ] **Step 3: Implement the V086 schema and exact mapping**

Create `m086_production_node_master(db)` with these core definitions:

```python
def m086_production_node_master(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS production_nodes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        process_id INTEGER NOT NULL,
        node_code TEXT NOT NULL,
        node_name TEXT NOT NULL,
        capacity_mode TEXT NOT NULL DEFAULT 'exclusive'
            CHECK(capacity_mode IN ('exclusive','batch')),
        status TEXT NOT NULL DEFAULT 'active'
            CHECK(status IN ('active','inactive','maintenance')),
        calendar_id INTEGER NOT NULL,
        legacy_process_line_id INTEGER UNIQUE,
        row_version INTEGER NOT NULL DEFAULT 1 CHECK(row_version > 0),
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        UNIQUE(process_id,node_code),
        FOREIGN KEY(process_id) REFERENCES processes(id) ON DELETE RESTRICT,
        FOREIGN KEY(calendar_id) REFERENCES schedule_calendars(id) ON DELETE RESTRICT,
        FOREIGN KEY(legacy_process_line_id) REFERENCES process_production_lines(id) ON DELETE RESTRICT
    );

    CREATE TABLE IF NOT EXISTS production_node_capabilities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        production_node_id INTEGER NOT NULL,
        product_id INTEGER,
        product_family TEXT NOT NULL DEFAULT '',
        material_code TEXT NOT NULL DEFAULT '',
        specification TEXT NOT NULL DEFAULT '',
        route_version_id INTEGER,
        process_version_id INTEGER,
        max_batch_quantity INTEGER CHECK(max_batch_quantity IS NULL OR max_batch_quantity > 0),
        batch_minutes REAL CHECK(batch_minutes IS NULL OR batch_minutes > 0),
        changeover_minutes REAL NOT NULL DEFAULT 0 CHECK(changeover_minutes >= 0),
        allow_mixed_orders INTEGER NOT NULL DEFAULT 0 CHECK(allow_mixed_orders IN (0,1)),
        status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','inactive')),
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        FOREIGN KEY(production_node_id) REFERENCES production_nodes(id) ON DELETE RESTRICT
    );

    CREATE TABLE IF NOT EXISTS production_node_calendar_overrides (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        production_node_id INTEGER NOT NULL,
        start_at TEXT NOT NULL,
        end_at TEXT NOT NULL,
        override_type TEXT NOT NULL CHECK(override_type IN ('unavailable','maintenance','overtime','holiday')),
        reason TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','cancelled','completed')),
        created_by INTEGER,
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        CHECK(end_at > start_at),
        FOREIGN KEY(production_node_id) REFERENCES production_nodes(id) ON DELETE RESTRICT,
        FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS production_node_audit_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        production_node_id INTEGER,
        event_type TEXT NOT NULL,
        actor_id INTEGER,
        reason TEXT NOT NULL DEFAULT '',
        before_json TEXT NOT NULL DEFAULT '{}',
        after_json TEXT NOT NULL DEFAULT '{}',
        idempotency_key TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        FOREIGN KEY(production_node_id) REFERENCES production_nodes(id) ON DELETE RESTRICT,
        FOREIGN KEY(actor_id) REFERENCES users(id) ON DELETE SET NULL
    );
    """)
    db.execute(
        "INSERT OR IGNORE INTO production_nodes "
        "(process_id,node_code,node_name,capacity_mode,status,calendar_id,legacy_process_line_id) "
        "SELECT process_id,line_code,line_name,'exclusive',status,calendar_id,id "
        "FROM process_production_lines WHERE calendar_id IS NOT NULL"
    )
```

Add indexes for `(process_id,status)`, capability lookup, override time range, and audit node/time.

- [ ] **Step 4: Register V086 in the linear catalog**

Import `PRODUCTION_NODE_MIGRATIONS`, include it in `MIGRATIONS`, and change:

```python
MIGRATION_VERSION_CHAIN = (1, *range(13, 87))
```

Define:

```python
MIGRATIONS = [
    (86, "Add stable production-node master data", m086_production_node_master),
]
```

- [ ] **Step 5: Run migration tests**

Run:

```bash
python -m pytest -q tests/test_production_node_migrations.py tests/test_migrations.py
```

Expected: PASS and `LATEST_VERSION == 86`.

- [ ] **Step 6: Commit**

```bash
git add modules/migration_production_nodes.py modules/migration_catalog.py tests/test_production_node_migrations.py tests/test_migrations.py
git commit -m "feat: add production node master data"
```

---

### Task 3: Add V087 Node Scheduling Facts and Exact Historical Backfill

**Files:**
- Modify: `modules/migration_production_nodes.py`
- Modify: `modules/migration_catalog.py`
- Modify: `tests/test_production_node_migrations.py`
- Modify: `tests/test_migrations.py`

**Interfaces:**
- Consumes: V086 `production_nodes.legacy_process_line_id` mappings and V085 schedule facts.
- Produces: node references and immutable snapshots on schedules, segments, revisions, and downtime; `production_node_migration_differences` blocks ambiguous cutover.

- [ ] **Step 1: Write V087 backfill tests**

Seed mapped and deliberately unmapped historical rows. Assert mapped facts receive the expected node without changing time/quantity, while unmapped rows create differences and remain null:

```python
def test_v087_backfills_only_exact_legacy_mappings(v086_db):
    before = schedule_fingerprint(v086_db)
    m087_production_node_schedule_facts(v086_db)
    after = schedule_fingerprint(v086_db)
    assert after["time_quantity_digest"] == before["time_quantity_digest"]
    assert after["mapped_schedule_count"] == before["legacy_schedule_count"]
    assert after["difference_count"] == 0
```

Add a separate test proving an unknown `process_line_id` produces a `missing_mapping` row instead of a guessed node.

- [ ] **Step 2: Run the focused test and verify failure**

Run:

```bash
python -m pytest -q tests/test_production_node_migrations.py -k v087
```

Expected: FAIL because V087 fields and migration do not exist.

- [ ] **Step 3: Add V087 columns and difference evidence**

Use `add_column_if_missing` for:

```python
FACT_COLUMNS = {
    "production_node_id": "INTEGER REFERENCES production_nodes(id) ON DELETE RESTRICT",
    "node_code_snapshot": "TEXT NOT NULL DEFAULT ''",
    "node_name_snapshot": "TEXT NOT NULL DEFAULT ''",
    "capacity_mode_snapshot": "TEXT NOT NULL DEFAULT ''",
    "node_calendar_snapshot_json": "TEXT NOT NULL DEFAULT '{}'",
    "node_capability_snapshot_json": "TEXT NOT NULL DEFAULT '[]'",
    "locked": "INTEGER NOT NULL DEFAULT 0 CHECK(locked IN (0,1))",
    "lock_reason": "TEXT NOT NULL DEFAULT ''",
}
```

Add `production_node_id` to `order_process_schedule_segments`, `schedule_revision_items`, and `schedule_downtime_events`, plus node snapshots to revision items. Add:

```sql
CREATE TABLE IF NOT EXISTS production_node_migration_differences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_table TEXT NOT NULL,
    source_id INTEGER NOT NULL,
    legacy_process_line_id INTEGER,
    difference_code TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    observed_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(source_table,source_id,difference_code)
);
```

Backfill only with exact joins on `production_nodes.legacy_process_line_id`. Copy node code, name, capacity mode, and calendar into schedule facts; do not update dates, minutes, quantities, statuses, standard references, or payload digests belonging to prior immutable revision items.

Before backfilling additive node columns on `schedule_revision_items`, drop the
existing `protect_schedule_revision_items_update` trigger inside the migration
transaction. Recreate it immediately after the exact backfill with the full
old and new immutable column set. This is the only permitted mutation of
historical revision items, and the migration fingerprint test must prove that
all pre-existing business columns and payload digests remain byte-for-byte
unchanged.

- [ ] **Step 4: Protect historical revision node snapshots**

Extend the immutable trigger to reject changes to:

```sql
production_node_id,
node_code_snapshot,
node_name_snapshot,
capacity_mode_snapshot,
node_calendar_snapshot_json,
node_capability_snapshot_json,
locked,
lock_reason
```

- [ ] **Step 5: Register V087 and run tests**

Set the migration chain to `(1, *range(13, 88))`, append:

```python
(87, "Add production-node scheduling facts", m087_production_node_schedule_facts)
```

Run:

```bash
python -m pytest -q tests/test_production_node_migrations.py tests/test_migrations.py tests/test_production_node_legacy_contracts.py
```

Expected: PASS and `LATEST_VERSION == 87`; legacy fingerprint remains unchanged except for additive node fields.

- [ ] **Step 6: Commit**

```bash
git add modules/migration_production_nodes.py modules/migration_catalog.py tests/test_production_node_migrations.py tests/test_migrations.py
git commit -m "feat: add production node schedule facts"
```

---

### Task 4: Add Staged Flags and Immutable Compatibility Auditing

**Files:**
- Create: `modules/repositories/production_node_repository.py`
- Create: `modules/services/production_node_compatibility_service.py`
- Create: `tests/test_production_node_compatibility.py`
- Modify: `modules/config.py`
- Modify: `modules/migration_production_nodes.py`
- Modify: `tests/test_bootstrap_and_versioning_flags.py`

**Interfaces:**
- Consumes: legacy line rows, node mappings, and `validate_versioning_flags`.
- Produces: `get_production_node_flags()`, startup validation, `ProductionNodeCompatibilityService.list_resources()`, and immutable mismatch observations.

- [ ] **Step 1: Write flag-order tests**

```python
def test_production_node_flags_enforce_cutover_order():
    assert config.get_production_node_flags({}) == {
        "PRODUCTION_NODE_QUERY_ENABLED": False,
        "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED": False,
        "PRODUCTION_NODE_WRITE_ENABLED": False,
        "PRODUCTION_NODE_ENGINE_ENABLED": False,
        "LEGACY_PROCESS_LINE_WRITE_BLOCKED": False,
    }
    with pytest.raises(RuntimeError, match="生产节点功能开关组合无效"):
        config.validate_production_node_flags({
            "PRODUCTION_NODE_QUERY_ENABLED": False,
            "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED": True,
            "PRODUCTION_NODE_WRITE_ENABLED": False,
            "PRODUCTION_NODE_ENGINE_ENABLED": False,
            "LEGACY_PROCESS_LINE_WRITE_BLOCKED": False,
        })
```

Add cases requiring query before audit/write/engine, audit before engine, write before legacy block, and engine before legacy block.

- [ ] **Step 2: Run the flag tests and verify failure**

Run:

```bash
python -m pytest -q tests/test_bootstrap_and_versioning_flags.py -k production_node
```

Expected: FAIL because node flags are undefined.

- [ ] **Step 3: Implement flag parsing and validation**

Add five names to `modules/config.py` and call `validate_versioning_flags` for query/audit/write/legacy order, followed by explicit engine checks:

```python
if values["PRODUCTION_NODE_ENGINE_ENABLED"] and not (
    values["PRODUCTION_NODE_QUERY_ENABLED"]
    and values["PRODUCTION_NODE_COMPAT_AUDIT_ENABLED"]
    and values["PRODUCTION_NODE_WRITE_ENABLED"]
):
    violations.append("节点排程引擎要求先开启查询、兼容审计和节点写入")
```

- [ ] **Step 4: Add compatibility observation storage**

Extend V087 with:

```sql
CREATE TABLE IF NOT EXISTS production_node_compatibility_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_key TEXT NOT NULL UNIQUE,
    scope TEXT NOT NULL,
    source_id INTEGER,
    legacy_digest TEXT NOT NULL,
    node_digest TEXT NOT NULL,
    mismatch INTEGER NOT NULL CHECK(mismatch IN (0,1)),
    difference_json TEXT NOT NULL DEFAULT '{}',
    observed_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
```

- [ ] **Step 5: Implement dual-read comparison**

Create the initial read-only `ProductionNodeRepository` in this task with
`list_legacy_resources()`, `list_nodes()`, `record_compatibility_observation()`,
and payload-digest helpers. Task 6 extends this same repository with command
methods; it must not create a second persistence abstraction.

Create:

```python
class ProductionNodeCompatibilityService:
    @staticmethod
    def list_resources(process_id=None, limit=500, db=None):
        legacy = ProductionNodeRepository.list_legacy_resources(process_id, limit, db=db)
        nodes = ProductionNodeRepository.list_nodes(process_id=process_id, limit=limit, db=db)
        if config.PRODUCTION_NODE_COMPAT_AUDIT_ENABLED:
            ProductionNodeRepository.record_compatibility_observation(
                scope="resource_list",
                source_id=process_id,
                legacy_payload=normalize_legacy_resources(legacy),
                node_payload=normalize_node_resources(nodes),
                db=db,
            )
        return nodes if config.PRODUCTION_NODE_QUERY_ENABLED else legacy
```

Normalization must compare process ID, stable mapping, status, calendar, capacity minutes, occupancy, downtime, and conflict counts, not display labels alone.

- [ ] **Step 6: Run compatibility tests**

Run:

```bash
python -m pytest -q tests/test_production_node_compatibility.py tests/test_bootstrap_and_versioning_flags.py tests/test_production_node_migrations.py
```

Expected: PASS; audit-disabled reads write no evidence, audit-enabled reads append immutable observations, and query-disabled responses remain legacy-compatible.

- [ ] **Step 7: Commit**

```bash
git add modules/config.py modules/migration_production_nodes.py modules/repositories/production_node_repository.py modules/services/production_node_compatibility_service.py tests/test_production_node_compatibility.py tests/test_bootstrap_and_versioning_flags.py
git commit -m "feat: add production node compatibility flags"
```

---

### Task 5: Implement Pure Node Capability and Capacity Policies

**Files:**
- Create: `modules/domain/production_node_scheduling.py`
- Create: `tests/test_production_node_policy.py`

**Interfaces:**
- Consumes: plain dictionaries describing order operations, nodes, capabilities, occupancy, and requested allocation.
- Produces: `NodeSchedulingError`, `ProductionNodePolicy.validate_node()`, `rank_nodes()`, `validate_serial_allocation()`, and `batch_duration_minutes()`.

- [ ] **Step 1: Write policy tests**

Cover exact error codes and deterministic ranking:

```python
def test_serial_item_cannot_split_across_nodes():
    with pytest.raises(NodeSchedulingError) as error:
        ProductionNodePolicy.validate_serial_allocation(
            serial_ids=["26072401-001"],
            allocations=[{"production_node_id": 10, "serial_ids": ["26072401-001"]},
                         {"production_node_id": 11, "serial_ids": ["26072401-001"]}],
        )
    assert error.value.code == "SERIAL_ITEM_SPLIT_FORBIDDEN"

def test_node_ranking_is_stable():
    ranked = ProductionNodePolicy.rank_nodes([
        {"id": 12, "finish_at": "2026-09-18 11:00", "risk": 0, "load_minutes": 90},
        {"id": 11, "finish_at": "2026-09-18 11:00", "risk": 0, "load_minutes": 90},
    ])
    assert [node["id"] for node in ranked] == [11, 12]
```

Also test product/material/specification/route/process matching, inactive/maintenance rejection, exclusive overlap, batch maximum, changeover, and mixed-order denial.

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m pytest -q tests/test_production_node_policy.py
```

Expected: FAIL because the domain module does not exist.

- [ ] **Step 3: Implement canonical errors and policy functions**

Use this error contract:

```python
class NodeSchedulingError(ValueError):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})

    def to_payload(self):
        return {"code": self.code, "error": self.message, "details": self.details}
```

Use the exact codes `NO_COMPATIBLE_NODE`, `MISSING_WORK_TIME_STANDARD`, `VERSION_BINDING_MISMATCH`, `NODE_CALENDAR_UNAVAILABLE`, `LOCKED_TASK_CONFLICT`, `SERIAL_ITEM_SPLIT_FORBIDDEN`, and `BATCH_CAPACITY_EXCEEDED`.

Implement batch duration as:

```python
@staticmethod
def batch_duration_minutes(quantity, capability, changeover_required=False):
    batch_size = int(capability["max_batch_quantity"])
    batches = (int(quantity) + batch_size - 1) // batch_size
    duration = batches * float(capability["batch_minutes"])
    if changeover_required:
        duration += float(capability.get("changeover_minutes") or 0)
    return duration
```

- [ ] **Step 4: Run policy tests**

Run:

```bash
python -m pytest -q tests/test_production_node_policy.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add modules/domain/production_node_scheduling.py tests/test_production_node_policy.py
git commit -m "feat: define production node scheduling policy"
```

---

### Task 6: Build Node Repository, Service, Schemas, Permissions, and API

**Files:**
- Modify: `modules/repositories/production_node_repository.py`
- Create: `modules/services/production_node_service.py`
- Create: `modules/schemas/production_nodes.py`
- Create: `modules/routes/production_nodes.py`
- Create: `tests/test_production_node_api.py`
- Modify: `modules/schemas/__init__.py`
- Modify: `modules/routes/registry.py`
- Modify: `modules/permission_catalog.py`
- Modify: `tests/test_permission_catalog_contracts.py`

**Interfaces:**
- Consumes: V086 tables and Task 5 policies.
- Produces: node CRUD/read APIs, capability/calendar commands, audit history, and granular permission codes.

- [ ] **Step 1: Write permission and API tests**

Assert the catalog includes:

```python
EXPECTED_NODE_PERMISSIONS = {
    "production_nodes:view",
    "production_nodes:manage",
    "production_nodes:capability_manage",
    "production_nodes:calendar_manage",
    "production_nodes:downtime_manage",
    "schedules:view",
    "schedules:generate",
    "schedules:adjust",
    "schedules:lock",
    "schedules:unlock",
    "schedules:submit",
    "schedules:approve",
}
```

Test `GET /api/production-nodes`, `POST /api/production-nodes`, capability replacement, calendar override creation/cancellation, node disable, audit history, permission denial, optimistic row-version conflict, and delete rejection.

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m pytest -q tests/test_production_node_api.py tests/test_permission_catalog_contracts.py
```

Expected: FAIL because node API and permissions do not exist.

- [ ] **Step 3: Define request schemas**

Register schemas including this node command:

```python
"production_node_write": {
    "type": "object",
    "required": ["process_id", "node_code", "node_name", "capacity_mode", "calendar_id", "row_version", "idempotency_key"],
    "properties": {
        "process_id": {"type": "integer", "minimum": 1},
        "node_code": {"type": "string", "minLength": 1, "maxLength": 64},
        "node_name": {"type": "string", "minLength": 1, "maxLength": 128},
        "capacity_mode": {"enum": ["exclusive", "batch"]},
        "calendar_id": {"type": "integer", "minimum": 1},
        "row_version": {"type": "integer", "minimum": 1},
        "reason": {"type": "string", "minLength": 1, "maxLength": 1024},
        "idempotency_key": {"type": "string", "minLength": 8, "maxLength": 128},
    },
    "additionalProperties": False,
}
```

Define equally strict capability and calendar-override schemas.

- [ ] **Step 4: Implement repository and service commands**

Expose these exact methods:

```python
class ProductionNodeRepository:
    list_nodes(process_id=None, status=None, limit=500, db=None)
    find_node(node_id, db=None)
    list_capabilities(node_id, db=None)
    list_calendar_overrides(node_id, start_at="", end_at="", limit=500, db=None)
    create_node(data, actor_id, db)
    update_node(node_id, data, actor_id, db)
    replace_capabilities(node_id, capabilities, actor_id, idempotency_key, reason, db)
    create_calendar_override(node_id, data, actor_id, db)
    cancel_calendar_override(override_id, actor_id, reason, idempotency_key, db)
    append_audit_event(event, db)

class ProductionNodeService:
    list_nodes(process_id=None, status=None, limit=500)
    create_node(data, actor_id)
    update_node(node_id, data, actor_id)
    replace_capabilities(node_id, data, actor_id)
    create_calendar_override(node_id, data, actor_id)
    cancel_calendar_override(override_id, data, actor_id)
    list_audit_events(node_id, limit=500)
```

Node “delete” is not exposed. `update_node` changes status to `inactive` instead.

- [ ] **Step 5: Add granular permissions and routes**

Define permission resources:

```python
"production_nodes": ("生产节点", ["view", "manage", "capability_manage", "calendar_manage", "downtime_manage"]),
"schedules": ("节点排程", ["view", "generate", "adjust", "lock", "unlock", "submit", "approve"]),
```

Bind both to `page:production.schedule`. Keep legacy `schedule:view/edit` readable during migration, but new node routes check only the new permissions.

- [ ] **Step 6: Run API and permission tests**

Run:

```bash
python -m pytest -q tests/test_production_node_api.py tests/test_permission_catalog_contracts.py tests/test_schedule.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add modules/repositories/production_node_repository.py modules/services/production_node_service.py modules/schemas/production_nodes.py modules/schemas/__init__.py modules/routes/production_nodes.py modules/routes/registry.py modules/permission_catalog.py tests/test_production_node_api.py tests/test_permission_catalog_contracts.py
git commit -m "feat: add production node management api"
```

---

### Task 7: Switch Exclusive Capacity Allocation to Production Nodes

**Files:**
- Create: `tests/test_production_node_scheduling.py`
- Modify: `modules/repositories/schedule_capacity_repository.py`
- Modify: `modules/services/schedule_capacity_service.py`
- Modify: `modules/services/production_node_compatibility_service.py`

**Interfaces:**
- Consumes: `ProductionNodeRepository.list_compatible_nodes(...)` and Task 5 ranking/errors.
- Produces: node-based shadow generation and, when flags allow, node-based schedule facts and segments.

- [ ] **Step 1: Write exclusive-node scheduling tests**

Test capability filtering, earliest finish, calendar gaps, 540-minute days, cross-day continuation, downstream precedence, no overlap, and explicit block codes:

```python
def test_exclusive_node_schedule_uses_node_id_and_deprecated_line_projection(client, monkeypatch):
    enable_node_engine(monkeypatch)
    order_id, node_id, legacy_line_id = seed_node_order(client, quantity=3)
    result = ScheduleCapacityService.generate_order_schedule(
        order_id,
        start_date="2026-09-18",
        schedule_run_key="node-exclusive-001",
    )
    operation = result["operations"][0]
    assert operation["production_node_id"] == node_id
    assert operation["process_line_id"] == legacy_line_id
    assert operation["capacity_mode_snapshot"] == "exclusive"
```

- [ ] **Step 2: Run the focused test and verify failure**

Run:

```bash
python -m pytest -q tests/test_production_node_scheduling.py -k exclusive
```

Expected: FAIL because schedule generation does not produce node facts.

- [ ] **Step 3: Add node repository scheduling reads**

Implement:

```python
@staticmethod
def list_compatible_nodes(operation, order, at_time, db):
    rows = ProductionNodeRepository.list_active_nodes_for_process(operation["process_id"], db=db)
    return [row for row in rows if ProductionNodePolicy.matches_capabilities(
        node=dict(row),
        capabilities=ProductionNodeRepository.list_capabilities(row["id"], db=db),
        operation=operation,
        order=order,
        at_time=at_time,
    )]
```

Add node occupancy reads from schedule segments and node calendar overrides. Ignore soft-deleted orders and exclude the order being regenerated.

- [ ] **Step 4: Refactor allocation vocabulary without deleting compatibility fields**

Introduce node-native helpers:

```python
_allocate_on_node(db, node, earliest, duration, occupancy)
_allocate_split_on_nodes(db, nodes, earliest, quantity, standard, occupancy, serial_ids=None)
_add_segments_to_node_occupancy(occupancy, production_node_id, segments)
```

Each segment writes both:

```python
{
    "production_node_id": node["id"],
    "process_line_id": node["legacy_process_line_id"],
    "node_code_snapshot": node["node_code"],
    "node_name_snapshot": node["node_name"],
    "capacity_mode_snapshot": node["capacity_mode"],
}
```

Only call these helpers when `PRODUCTION_NODE_ENGINE_ENABLED` is true. Shadow mode computes and returns node results without replacing current projection rows.

- [ ] **Step 5: Return structured block errors**

Blocked schedule rows save both `blocked_reason` and `blocked_code`. Add `blocked_code` through V087 if not already included, and map Task 5 errors without converting them to generic strings.

- [ ] **Step 6: Run scheduling and compatibility tests**

Run:

```bash
python -m pytest -q tests/test_production_node_scheduling.py tests/test_schedule_capacity.py tests/test_production_node_compatibility.py
```

Expected: PASS; legacy mode remains unchanged, shadow mode returns node results only, and enabled engine writes node facts with deprecated line projection.

- [ ] **Step 7: Commit**

```bash
git add modules/repositories/schedule_capacity_repository.py modules/services/schedule_capacity_service.py modules/services/production_node_compatibility_service.py tests/test_production_node_scheduling.py
git commit -m "feat: schedule exclusive production nodes"
```

---

### Task 8: Implement Batch Nodes and Serial-Safe Parallel Splitting

**Files:**
- Create: `tests/test_production_node_batch_scheduling.py`
- Modify: `modules/domain/production_node_scheduling.py`
- Modify: `modules/repositories/schedule_capacity_repository.py`
- Modify: `modules/services/schedule_capacity_service.py`
- Modify: `modules/migration_production_nodes.py`

**Interfaces:**
- Consumes: node capabilities and Task 7 allocation helpers.
- Produces: batch allocation facts, per-segment quantities/serial IDs, and quantity-conservation validation.

- [ ] **Step 1: Write batch and serial tests**

Cover full/partial batches, mixed-order denial, allowed mixed orders, changeover, parallel quantity splitting, and serial integrity:

```python
def test_quantity_is_conserved_across_parallel_nodes(client, monkeypatch):
    enable_node_engine(monkeypatch)
    order_id = seed_quantity_order(client, quantity=37, compatible_node_count=4)
    result = generate(order_id, "node-split-37")
    assert sum(segment["quantity"] for operation in result["operations"] for segment in operation["segments"]) == 37

def test_serial_operation_stays_on_one_node(client, monkeypatch):
    enable_node_engine(monkeypatch)
    result = generate(seed_serial_order(client, ["A-001", "A-002"]), "node-serial-001")
    assert serial_node_ids(result, "A-001") == {result["operations"][0]["production_node_id"]}
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m pytest -q tests/test_production_node_batch_scheduling.py
```

Expected: FAIL because batch and serial facts are not implemented.

- [ ] **Step 3: Add allocation-detail facts**

Add an additive V087 table:

```sql
CREATE TABLE IF NOT EXISTS production_node_schedule_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_id INTEGER NOT NULL,
    segment_id INTEGER,
    production_node_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL CHECK(quantity >= 0),
    serial_id INTEGER,
    batch_key TEXT NOT NULL DEFAULT '',
    changeover_minutes REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY(schedule_id) REFERENCES order_process_schedules(id) ON DELETE CASCADE,
    FOREIGN KEY(segment_id) REFERENCES order_process_schedule_segments(id) ON DELETE CASCADE,
    FOREIGN KEY(production_node_id) REFERENCES production_nodes(id) ON DELETE RESTRICT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_node_allocation_serial_operation
ON production_node_schedule_allocations(schedule_id,serial_id)
WHERE serial_id IS NOT NULL;
```

- [ ] **Step 4: Implement exclusive and batch allocation branches**

For `exclusive`, use standard per-unit minutes plus setup. For `batch`, use `ProductionNodePolicy.batch_duration_minutes`, store `batch_key`, and reject invalid capability configuration with `BATCH_CAPACITY_EXCEEDED`.

Before persisting, enforce:

```python
allocated = sum(int(item["quantity"]) for item in allocations)
if allocated != int(remaining_quantity):
    raise NodeSchedulingError(
        "QUANTITY_CONSERVATION_FAILED",
        "排程拆分数量与待生产数量不一致",
        {"expected": int(remaining_quantity), "actual": allocated},
    )
```

Add `QUANTITY_CONSERVATION_FAILED` to the canonical error catalog.

- [ ] **Step 5: Run node scheduling tests**

Run:

```bash
python -m pytest -q tests/test_production_node_batch_scheduling.py tests/test_production_node_scheduling.py tests/test_schedule_capacity.py
```

Expected: PASS with 100% quantity conservation and zero duplicate serial allocations.

- [ ] **Step 6: Commit**

```bash
git add modules/migration_production_nodes.py modules/domain/production_node_scheduling.py modules/repositories/schedule_capacity_repository.py modules/services/schedule_capacity_service.py tests/test_production_node_batch_scheduling.py
git commit -m "feat: add batch and serial safe node allocation"
```

---

### Task 9: Implement Locks, Revision-Based Adjustment, and Two-Person Publication

**Files:**
- Create: `tests/test_production_node_schedule_workflow.py`
- Modify: `modules/migration_production_nodes.py`
- Modify: `modules/repositories/schedule_capacity_repository.py`
- Modify: `modules/services/schedule_capacity_service.py`
- Modify: `modules/schemas/production_nodes.py`
- Modify: `modules/routes/schedule.py`

**Interfaces:**
- Consumes: draft schedule revisions and node scheduling facts.
- Produces: atomic lock/unlock/adjust/submit/approve/reject commands with actor separation and audit events.

- [ ] **Step 1: Write workflow tests**

Test lock persistence, automatic-replan immobility, downtime conflict, required reasons, optimistic row versions, submit/approve transitions, and creator/approver separation:

```python
def test_revision_creator_cannot_approve_own_schedule(client, scheduler_headers):
    revision_id = create_and_submit_node_revision(client, scheduler_headers)
    response = client.post(
        f"/api/schedule/revisions/{revision_id}/approve",
        json={"reason": "发布执行", "idempotency_key": "approve-own-001"},
        headers=scheduler_headers,
    )
    assert response.status_code == 409
    assert response.get_json()["code"] == "INDEPENDENT_APPROVER_REQUIRED"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m pytest -q tests/test_production_node_schedule_workflow.py
```

Expected: FAIL because workflow endpoints and states do not exist.

- [ ] **Step 3: Add an independent approval state and lock/event ledgers**

Keep the existing schedule lifecycle `status` values (`draft`, `published`,
`superseded`, `cancelled`) unchanged. Add an independent
`approval_status` column with `draft`, `submitted`, `approved`, and `rejected`,
plus `submitted_by`, `submitted_at`, `approved_by`, `approved_at`,
`rejected_by`, and `rejected_at`. Existing historical revisions remain
`approval_status='approved'` only when already published; existing drafts use
`approval_status='draft'`.

Do not update immutable `schedule_revision_items` when a user locks, unlocks,
or manually adjusts work. Add an active lock table and an immutable event
ledger:

```sql
CREATE TABLE IF NOT EXISTS schedule_node_task_locks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    revision_item_id INTEGER NOT NULL,
    production_node_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','released')),
    reason TEXT NOT NULL,
    locked_by INTEGER NOT NULL,
    released_by INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    released_at TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(revision_item_id) REFERENCES schedule_revision_items(id) ON DELETE RESTRICT,
    FOREIGN KEY(production_node_id) REFERENCES production_nodes(id) ON DELETE RESTRICT,
    FOREIGN KEY(locked_by) REFERENCES users(id) ON DELETE RESTRICT,
    FOREIGN KEY(released_by) REFERENCES users(id) ON DELETE RESTRICT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_active_node_task_lock
ON schedule_node_task_locks(revision_item_id) WHERE status='active';
```

Add `schedule_node_workflow_events`:

```sql
CREATE TABLE IF NOT EXISTS schedule_node_workflow_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    revision_id INTEGER NOT NULL,
    event_type TEXT NOT NULL CHECK(event_type IN ('adjust','lock','unlock','submit','approve','reject','supersede')),
    actor_id INTEGER NOT NULL,
    reason TEXT NOT NULL,
    before_json TEXT NOT NULL DEFAULT '{}',
    after_json TEXT NOT NULL DEFAULT '{}',
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY(revision_id) REFERENCES schedule_revisions(id) ON DELETE RESTRICT,
    FOREIGN KEY(actor_id) REFERENCES users(id) ON DELETE RESTRICT
);
```

- [ ] **Step 4: Implement service commands**

Expose:

```python
lock_schedule_item(revision_item_id, reason, idempotency_key, actor_id)
unlock_schedule_item(revision_item_id, reason, idempotency_key, actor_id)
adjust_schedule_item(revision_item_id, production_node_id, planned_start_at, reason, row_version, idempotency_key, actor_id)
submit_revision(revision_id, reason, idempotency_key, actor_id)
approve_revision(revision_id, reason, idempotency_key, actor_id)
reject_revision(revision_id, reason, idempotency_key, actor_id)
```

All commands run inside `ScheduleCapacityService._transaction()`, revalidate
occupancy/capability/calendar/version facts, append exactly one event, and
return the original event on idempotent replay. Lock and unlock commands only
change `schedule_node_task_locks`. `adjust_schedule_item` clones the complete
source revision into a new draft revision, changes the requested item in the
new revision, and leaves the source revision item untouched. Submission and
approval update only the mutable revision header and workflow ledger. Publish
requires `approval_status='approved'`, and the approver must differ from
`created_by`.

- [ ] **Step 5: Add routes and granular permission checks**

Use `schedules:lock`, `schedules:unlock`, `schedules:adjust`, `schedules:submit`, and `schedules:approve`. Return `NodeSchedulingError.to_payload()` with HTTP 409 for business conflicts.

- [ ] **Step 6: Run workflow tests**

Run:

```bash
python -m pytest -q tests/test_production_node_schedule_workflow.py tests/test_schedule_capacity.py tests/test_production_node_api.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add modules/migration_production_nodes.py modules/repositories/schedule_capacity_repository.py modules/services/schedule_capacity_service.py modules/schemas/production_nodes.py modules/routes/schedule.py tests/test_production_node_schedule_workflow.py
git commit -m "feat: add node schedule lock and approval workflow"
```

---

### Task 10: Move Downtime and Dynamic Replan to Nodes

**Files:**
- Create: `tests/test_production_node_dynamic_replan.py`
- Modify: `modules/repositories/production_node_repository.py`
- Modify: `modules/repositories/schedule_capacity_repository.py`
- Modify: `modules/services/production_node_service.py`
- Modify: `modules/services/schedule_capacity_service.py`
- Modify: `modules/routes/schedule.py`

**Interfaces:**
- Consumes: node calendar overrides, locked revision items, completed/rework quantities, and node occupancy.
- Produces: node-native downtime and dynamic replan while preserving completed and locked facts.

- [ ] **Step 1: Write replan tests**

Test node downtime exclusion, completed fact preservation, remaining-quantity calculation, locked-task immobility, forced conflict output, and idempotent replay:

```python
def test_dynamic_replan_preserves_completed_and_locked_facts(client, monkeypatch):
    enable_node_engine(monkeypatch)
    context = seed_partially_completed_locked_order(client)
    result = ScheduleCapacityService.dynamic_replan_order(
        context["order_id"],
        start_at="2026-09-18 08:00",
        schedule_run_key="node-replan-001",
        reason="节点停机",
        actor_id=context["actor_id"],
    )
    assert result["operations"][0]["completed_quantity_snapshot"] == context["completed"]
    assert result["operations"][0]["production_node_id"] == context["locked_node_id"]
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m pytest -q tests/test_production_node_dynamic_replan.py
```

Expected: FAIL because downtime and replan still use line IDs.

- [ ] **Step 3: Convert downtime commands to node IDs**

Change new APIs to accept `production_node_id`; fill deprecated `process_line_id` from the stable node mapping. Reject unmapped nodes. Keep legacy GET filters during compatibility mode but record their use in compatibility observations.

- [ ] **Step 4: Rebuild occupancy by node**

Use `production_node_id` as every occupancy dictionary key. Merge schedule segments, active downtime, maintenance/unavailable overrides, and locked tasks. Overtime overrides add slots; unavailable/maintenance/holiday overrides subtract slots.

- [ ] **Step 5: Preserve locked tasks and report irresolvable conflicts**

If a locked task overlaps new downtime, do not move it. Return:

```python
{
    "code": "LOCKED_TASK_CONFLICT",
    "revision_item_id": item["id"],
    "production_node_id": item["production_node_id"],
    "requires_manual_unlock": True,
}
```

Continue planning independent unaffected operations only when predecessor rules permit; otherwise store `blocked_code="LOCKED_TASK_CONFLICT"`.

- [ ] **Step 6: Run dynamic replan tests**

Run:

```bash
python -m pytest -q tests/test_production_node_dynamic_replan.py tests/test_schedule_dynamic_replan.py tests/test_production_node_schedule_workflow.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add modules/repositories/production_node_repository.py modules/repositories/schedule_capacity_repository.py modules/services/production_node_service.py modules/services/schedule_capacity_service.py modules/routes/schedule.py tests/test_production_node_dynamic_replan.py
git commit -m "feat: replan production work by node"
```

---

### Task 11: Replace Line-Based Scheduling UI with Process-Node UX

**Files:**
- Create: `frontend/src/composables/gantt/useProductionNodes.js`
- Create: `frontend/tests/unit/useProductionNodes.spec.js`
- Modify: `frontend/src/lib/api/production.js`
- Modify: `frontend/src/composables/gantt/useGanttCapacity.js`
- Modify: `frontend/src/composables/gantt/useGanttData.js`
- Modify: `frontend/src/composables/gantt/useGanttEditor.js`
- Delete: `frontend/src/composables/gantt/useProductionLines.js`
- Modify: `frontend/src/composables/useGantt.js`
- Modify: `frontend/src/composables/order/useOrderEditor.js`
- Modify: `frontend/src/views/GanttChart.vue`
- Modify: `frontend/src/views/OrderList.vue`
- Modify: `frontend/tests/unit/useGantt.spec.js`
- Modify: `frontend/tests/unit/api-transport-contract.spec.js`

**Interfaces:**
- Consumes: node APIs, granular permissions, node schedule responses, block codes, lock/workflow endpoints.
- Produces: process-node hierarchy, node management, capability/calendar forms, node downtime, split details, locks, and explicit risk/block messages.

- [ ] **Step 1: Write frontend tests**

Assert:

```javascript
expect(wrapper.text()).toContain('生产节点管理')
expect(wrapper.text()).toContain('焊接-01')
expect(wrapper.text()).not.toContain('工序产线')
expect(wrapper.find('[data-test="locked-task"]').exists()).toBe(true)
expect(wrapper.find('[data-test="blocked-code-NO_COMPATIBLE_NODE"]').text()).toContain('没有满足能力要求的生产节点')
```

Test node grouping, permissions, downtime payloads using `production_node_id`, adjustment validation, lock/unlock, split quantity expansion, and deprecated field absence from new commands.

- [ ] **Step 2: Run frontend tests and verify failure**

Run:

```bash
npm run test:unit -- --run frontend/tests/unit/useProductionNodes.spec.js frontend/tests/unit/useGantt.spec.js frontend/tests/unit/api-transport-contract.spec.js
```

Expected: FAIL because the node composable/API do not exist and the page still says “产线”.

- [ ] **Step 3: Add node API methods**

Expose:

```javascript
listProductionNodes: (params={}) => request('GET', '/api/production-nodes' + buildQuery(params)),
createProductionNode: (data={}) => request('POST', '/api/production-nodes', data),
updateProductionNode: (id,data={}) => request('PUT', `/api/production-nodes/${id}`, data),
replaceProductionNodeCapabilities: (id,data={}) => request('PUT', `/api/production-nodes/${id}/capabilities`, data),
createProductionNodeOverride: (id,data={}) => request('POST', `/api/production-nodes/${id}/calendar-overrides`, data),
createScheduleNodeDowntime: (data={}) => request('POST', '/api/schedule/downtime', data),
lockScheduleItem: (id,data={}) => request('POST', `/api/schedule/revision-items/${id}/lock`, data),
unlockScheduleItem: (id,data={}) => request('POST', `/api/schedule/revision-items/${id}/unlock`, data),
```

- [ ] **Step 4: Implement `useProductionNodes`**

Keep state and commands focused on node master data. Group with:

```javascript
const nodesByProcess = computed(() => Object.values(nodes.value.reduce((groups, node) => {
  const key = String(node.process_id)
  if (!groups[key]) groups[key] = { process_id: node.process_id, process_name: node.process_name, nodes: [] }
  groups[key].nodes.push(node)
  return groups
}, {})))
```

Do not import or call `/api/production-lines` from this composable. Remove
`useProductionLines` from the active Gantt composition rather than leaving a
hidden legacy manager mounted.

- [ ] **Step 5: Update capacity and Gantt UI**

Rename state to `capacityNodes` and `capacityNodeFilter`. Use
`production_node_id`, `node_name`, and `node_code` for new scheduling controls.
Remove order-level `production_line_id` selection and drag/edit controls from
`OrderList.vue`, `useOrderEditor.js`, `useGanttData.js`, and
`useGanttEditor.js`; physical-node assignment belongs to order operations, not
the order header. Display old IDs only inside an audit detail section gated by
audit permission.

Map blocked codes to exact messages:

```javascript
const BLOCKED_MESSAGES = Object.freeze({
  NO_COMPATIBLE_NODE: '没有满足能力要求的生产节点',
  MISSING_WORK_TIME_STANDARD: '未配置有效标准工时',
  VERSION_BINDING_MISMATCH: '订单、路线和工序版本不一致',
  NODE_CALENDAR_UNAVAILABLE: '生产节点日历没有可用时间',
  LOCKED_TASK_CONFLICT: '锁定任务发生冲突，需要授权解锁',
  SERIAL_ITEM_SPLIT_FORBIDDEN: '单个序列工件不能跨节点拆分',
  BATCH_CAPACITY_EXCEEDED: '批处理数量或批次配置不符合要求',
  QUANTITY_CONSERVATION_FAILED: '排程拆分数量不守恒',
})
```

- [ ] **Step 6: Wire granular permissions**

Use `can('production_nodes:manage')`, `can('production_nodes:downtime_manage')`, `can('schedules:generate')`, `can('schedules:adjust')`, `can('schedules:lock')`, `can('schedules:unlock')`, `can('schedules:submit')`, and `can('schedules:approve')`. Do not use `settings:edit` or `schedule:edit` for new node operations.

- [ ] **Step 7: Run frontend tests and build**

Run:

```bash
npm run test:unit
npm run build
```

Expected: all Vitest tests pass; architecture/import checks and Vite build pass.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/lib/api/production.js frontend/src/composables/gantt/useProductionNodes.js frontend/src/composables/gantt/useGanttCapacity.js frontend/src/composables/gantt/useGanttData.js frontend/src/composables/gantt/useGanttEditor.js frontend/src/composables/gantt/useProductionLines.js frontend/src/composables/useGantt.js frontend/src/composables/order/useOrderEditor.js frontend/src/views/GanttChart.vue frontend/src/views/OrderList.vue frontend/tests/unit/useProductionNodes.spec.js frontend/tests/unit/useGantt.spec.js frontend/tests/unit/api-transport-contract.spec.js
git commit -m "feat: replace scheduling lines with production nodes"
```

---

### Task 12: Add Production Preflight, Replica, Shadow, Cutover, and Rollback Evidence

**Files:**
- Create: `scripts/production_node_operations.py`
- Create: `tests/test_production_node_operations.py`
- Create: `docs/production-node-scheduling-runbook.md`
- Modify: `scripts/production_operations.py`
- Modify: `tests/test_deployment_contracts.py`

**Interfaces:**
- Consumes: deployment manifests, database backup evidence, V086/V087 migrations, flags, compatibility observations, and shadow scheduling.
- Produces: deterministic JSON evidence for `preflight`, `migrate-replica`, `compat-audit`, `shadow-run`, `set-flags`, `acceptance`, and `rollback-readiness`.

- [ ] **Step 1: Write operations CLI tests**

Test read-only mode, wrong commit, stale database version, missing node mapping, non-zero latest mismatch, shadow conflicts, invalid flag transitions, idempotent rerun, and JSON stream output:

```python
def test_preflight_blocks_unmapped_historical_facts(tmp_path):
    result = run_node_operations(
        "preflight",
        db=seed_unmapped_replica(tmp_path),
        expected_commit="307f99e68c52626b72f3cb25159e4211510d5051",
    )
    assert result.returncode == 2
    assert json.loads(result.stdout)["checks"]["unmapped_historical_facts"] is False
```

- [ ] **Step 2: Run operations tests and verify failure**

Run:

```bash
python -m pytest -q tests/test_production_node_operations.py tests/test_deployment_contracts.py
```

Expected: FAIL because the operations script does not exist.

- [ ] **Step 3: Implement CLI commands**

Use subcommands with mandatory `--db`, `--evidence-dir`, `--expected-commit`, and `--idempotency-key` where state can change. Emit one final JSON object with `ok`, `mode`, `checks`, `counts`, `digests`, and `artifacts`.

The preflight must check:

```python
checks = {
    "database_integrity": integrity_check == "ok",
    "foreign_key_errors_zero": foreign_key_count == 0,
    "expected_database_version": user_version in {85, 86, 87},
    "core_node_count_21": core_node_count == 21,
    "legacy_mapping_complete": mapping_missing == 0,
    "unmapped_historical_facts": historical_missing == 0,
    "latest_compat_mismatch_zero": latest_mismatch_count == 0,
    "shadow_conflicts_zero": shadow_conflict_count == 0,
    "quantity_conservation_100_percent": quantity_difference == 0,
    "serial_split_violations_zero": serial_split_count == 0,
}
```

In pre-V086 mode, schema-dependent checks report `not_yet_migrated` rather than querying missing tables.

- [ ] **Step 4: Implement safe flag transitions**

Support only these ordered states:

```python
ALLOWED_STATES = {
    "off": (False, False, False, False, False),
    "query_audit": (True, True, False, False, False),
    "write_shadow": (True, True, True, False, False),
    "engine": (True, True, True, True, False),
    "legacy_blocked": (True, True, True, True, True),
}
```

Write the environment file atomically, preserve unrelated variables, record before/after digests, and refuse backward transitions unless `rollback-readiness` has produced valid evidence for the same deployed commit.

- [ ] **Step 5: Write the runbook**

Document five separately authorized production stages:

1. Code + V086/V087 migration with all flags off.
2. Query + compatibility audit.
3. Node writes + shadow engine, no production projection switch.
4. Node engine switch.
5. Legacy write block.

For each stage list backup verification, stop/start scope, acceptance queries, evidence paths, and rollback action. Explicitly state that existing production data, attachments, backups, migration logs, and audit evidence are preserved.

- [ ] **Step 6: Run operations and deployment tests**

Run:

```bash
python -m pytest -q tests/test_production_node_operations.py tests/test_deployment_contracts.py tests/test_migrations.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/production_node_operations.py scripts/production_operations.py tests/test_production_node_operations.py tests/test_deployment_contracts.py docs/production-node-scheduling-runbook.md
git commit -m "feat: add production node cutover operations"
```

---

### Task 13: Complete Integration, Real-Order Replay Fixtures, and Release Gate

**Files:**
- Create: `tests/test_production_node_real_order_replay.py`
- Create: `docs/superpowers/evidence/2026-09-17-production-node-scheduling-validation.md`
- Modify: affected tests only when an assertion is intentionally replaced by the approved production-node contract.

**Interfaces:**
- Consumes: Tasks 1–12.
- Produces: one release candidate whose migrations, backend, frontend, E2E, shadow replay, compatibility evidence, and deployment contract all pass.

- [ ] **Step 1: Add sanitized real-order replay fixtures**

Export immutable, non-sensitive fixtures containing order IDs, quantities, serial topology, route/process versions, work-time standard IDs, priority/deadline, node capabilities, calendars, occupancy, and downtime. Do not copy names, credentials, attachments, salaries, or personal data.

Assert:

```python
def test_real_order_replay_meets_node_release_gate(real_order_replay):
    report = real_order_replay.run_shadow()
    assert report["core_node_count"] == 21
    assert report["quantity_conservation_rate"] == 1.0
    assert report["serial_split_violations"] == 0
    assert report["exclusive_overlap_count"] == 0
    assert report["completed_fact_changes"] == 0
    assert report["unmapped_fact_count"] == 0
    assert report["latest_compat_mismatch_count"] == 0
```

- [ ] **Step 2: Run targeted backend tests**

Run:

```bash
python -m pytest -q \
  tests/test_production_node_legacy_contracts.py \
  tests/test_production_node_migrations.py \
  tests/test_production_node_compatibility.py \
  tests/test_production_node_policy.py \
  tests/test_production_node_api.py \
  tests/test_production_node_scheduling.py \
  tests/test_production_node_batch_scheduling.py \
  tests/test_production_node_schedule_workflow.py \
  tests/test_production_node_dynamic_replan.py \
  tests/test_production_node_operations.py \
  tests/test_production_node_real_order_replay.py \
  tests/test_schedule_capacity.py \
  tests/test_schedule_dynamic_replan.py \
  tests/test_schedule_order_priority_v084.py \
  tests/test_schedule_standard_binding_v085.py
```

Expected: PASS.

- [ ] **Step 3: Run the complete backend suite**

Run:

```bash
python -m pytest -q
```

Expected: all tests pass with zero failures.

- [ ] **Step 4: Run the complete frontend and build suite**

Run:

```bash
npm run test:frontend
npm run build
```

Expected: Vitest, Playwright E2E, API facade check, import-cycle check, and Vite build all pass.

- [ ] **Step 5: Run deployment contract checks**

Run:

```bash
bash deploy.sh --check-only
python -m pytest -q tests/test_deployment_contracts.py tests/test_production_node_operations.py
```

Expected: PASS without modifying production.

- [ ] **Step 6: Record validation evidence**

Write exact commit, migration target, test counts, build output, feature-flag defaults, replay counts, mismatch counts, node counts, quantity conservation, serial violations, integrity result, and foreign-key result into `docs/superpowers/evidence/2026-09-17-production-node-scheduling-validation.md`.

The document must state that production deployment and each feature-flag stage remain unexecuted and require separate explicit authorization.

- [ ] **Step 7: Commit the integration evidence**

```bash
git add tests/test_production_node_real_order_replay.py docs/superpowers/evidence/2026-09-17-production-node-scheduling-validation.md
git commit -m "test: validate production node scheduling release"
```

---

## Execution and Review Gates

After each task:

1. Run the task-specific tests.
2. Review only that task's diff against the confirmed design.
3. Commit the independently testable result.
4. Do not begin the next migration or cutover stage while the current task is red.

After Task 13, push and PR creation require explicit authorization. PR merge requires separate authorization. Production code deployment to V086/V087, query/audit flags, node writes/shadow, node engine switch, and legacy-write block are five distinct production decisions and must not be combined into one implicit authorization.
