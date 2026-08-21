# 岗位管理版本化修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 先消除岗位编辑会清空工序关联的破坏性契约缺陷，再建立稳定岗位身份、不可变岗位修订、双人审批、事务审计、精确事实快照和可回退的 v070 渐进切换。

**Architecture:** `positions` 保留为稳定根与 Legacy 当前投影，`position_versions` 和 `position_version_processes` 保存不可变修订；所有状态变化由版本/生命周期服务在一个事务中完成。查询、授权、绩效和报工逐步改用统一的 `PositionAccessService` 与精确 `position_version_id`，功能开关控制双读、写入和 Legacy 阻断。

**Tech Stack:** Python 3、Flask、SQLite、JSON Schema、Vue 3、Vitest、现有 Repository/Service 分层和进程级环境功能开关。

## Global Constraints

- 设计依据：`docs/superpowers/specs/2026-08-20-position-management-versioning-repair-design.md`，不改变已确认的总体架构和修复边界。
- 当前生产基线：数据库 v069、部署提交 `f9ed7385d2bcedf54c30ff8328e4984068464ff0`；目标数据库版本固定为 v070。
- `positions.id` 是稳定岗位身份；岗位改名、描述或可报工工序变化只创建修订版。
- 已发布、已取代和已退休版本永久只读；服务层与 SQLite 触发器同时保护。
- 新岗位发布前不能用于员工分配、绩效目标或报工授权。
- 制单人与批准人必须不同，管理员通配权限不能绕过职责分离。
- 所有写命令携带 `row_version` 与 `idempotency_key`；修订和生命周期命令还携带明确原因。
- 停用/退休岗位不提供新业务岗位权限；显式员工工序授权与历史在制订单例外继续有效。
- 旧事实保留原名称快照和空版本 ID，不把 v070 创建的 V1 伪装成历史版本。
- 强制审计与业务写入同一事务，岗位状态命令不得依赖路由层 `safe_audit_log`。
- 历史工序关联只使用备份中的精确证据恢复，不按名称、分类或相似度猜测。
- P0 可独立部署；v070 正式迁移、开关切换、停服和生产部署必须另行获得明确授权。
- 使用 Git Bash 运行命令；后端定向测试使用干净依赖目录 `C:/Users/dubin/AppData/Local/Temp/codex-position-review-pytest`。
- 保留并排除任务外的 `.brooks-lint-history.json` 修改。

---

## File Map

- `modules/domain/position_versioning.py`：纯状态、乐观锁、职责分离、差异和摘要策略。
- `modules/migration_position_versioning.py`：v070 根字段、版本表、事实字段、V1 基线、索引与不可变触发器。
- `modules/repositories/position_version_repository.py`：岗位根、版本、版本工序、事件和生命周期请求 SQL 原语。
- `modules/services/position_impact_service.py`：统一引用计数、阻断原因和稳定影响摘要。
- `modules/services/position_access_service.py`：新业务与历史在制业务的岗位工序授权解析。
- `modules/services/position_audit_service.py`：事务内 mandatory 审计写入。
- `modules/services/position_snapshot_service.py`：岗位改名发布时切分绩效岗位历史并解析事实快照。
- `modules/services/position_version_service.py`：岗位根和修订版工作流唯一写入口。
- `modules/services/position_lifecycle_service.py`：退休、重新启用申请与批准。
- `modules/schemas/position_versioning.py`、`modules/routes/position_versions.py`：V2 请求契约和 HTTP 适配。
- `frontend/src/lib/api/position-versions.js`、`frontend/src/composables/settings/usePositionVersions.js`：版本 API 与 UI 状态机。
- `frontend/src/views/settings/Positions.vue`：当前岗位、待审批、历史和影响四个工作视图。
- `scripts/preflight_position_v070.py`、`scripts/recover_position_processes.py`、`scripts/validate_position_v070_replica.py`：只读预检、证据恢复和副本验收。

### Task 1: P0 岗位字段契约和前端破坏性写入止损

**Files:**
- Modify: `modules/services/position_service.py`
- Modify: `modules/schemas/positions.py`
- Modify: `frontend/src/composables/settings/usePositions.js`
- Modify: `frontend/src/views/settings/Positions.vue`
- Create: `tests/test_position_contract.py`
- Create: `frontend/tests/unit/Positions.spec.js`

**Interfaces:**
- Consumes: `PositionRepository.find_position_processes(pos_ids)` 返回 `position_id/process_id/process_name`。
- Produces: `PositionService.list_positions(page=1, limit=100)` 的每项同时包含 `processes: list[dict]` 与 `process_ids: list[int]`；`normalizePositionProcessIds(position)` 返回去重整数数组；`update_position()` 仅在请求存在 `process_ids` 键时替换关联。

- [ ] **Step 1: 写后端失败契约测试**

```python
def test_position_list_exposes_structured_processes_and_ids(client):
    position_id, process_id = seed_position_with_process(client)
    row = next(p for p in PositionService.list_positions()["positions"] if p["id"] == position_id)
    assert row["process_ids"] == [process_id]
    assert row["processes"] == [{"position_id": position_id, "process_id": process_id, "process_name": "测试工序"}]

def test_position_partial_update_preserves_processes(client):
    position_id, process_id = seed_position_with_process(client)
    PositionService.update_position(position_id, {"description": "只改描述"})
    assert PositionRepository.find_process_ids_by_position(position_id) == {process_id}
```

- [ ] **Step 2: 写前端失败契约测试**

```js
it('normalizes the real backend processes response without clearing selections', () => {
  const { openEditPosition, positionForm } = usePositions({ autoLoad: false })
  openEditPosition({ id: 3, name: '焊工', processes: [{ process_id: 11 }] })
  expect(positionForm.process_ids).toEqual([11])
})

it('fails closed when impact lookup fails', async () => {
  mocks.getPositionImpact.mockRejectedValue(new Error('影响查询失败'))
  await deletePosition(3)
  expect(mocks.deletePosition).not.toHaveBeenCalled()
})

it('fails closed before deactivating when impact lookup fails', async () => {
  openEditPosition({ id: 3, name: '焊工', status: 'active', process_ids: [11] })
  positionForm.status = 'inactive'
  mocks.getPositionImpact.mockRejectedValue(new Error('影响查询失败'))
  await savePosition()
  expect(mocks.updatePosition).not.toHaveBeenCalled()
})
```

- [ ] **Step 3: 运行测试并确认失败原因**

Run:
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=/c/Users/dubin/AppData/Local/Temp/codex-position-review-pytest python -m pytest -q tests/test_position_contract.py
cd frontend && npm run test:unit -- --run tests/unit/Positions.spec.js
```
Expected: 后端缺少 `process_ids`、前端从 `processes` 回填失败且影响查询失败后仍可继续删除。

- [ ] **Step 4: 实现最小兼容修复和统一名称规则**

```python
# modules/services/position_service.py
processes = proc_map.get(pos["id"], [])
pos["processes"] = processes
pos["process_ids"] = [int(item["process_id"]) for item in processes]

# 只有明确提供键时才执行以下替换
if "process_ids" in data:
    PositionRepository.delete_position_processes_by_pos(pos_id, db=txn)
```

```js
// frontend/src/composables/settings/usePositions.js
export function normalizePositionProcessIds(position) {
  const raw = Array.isArray(position?.process_ids)
    ? position.process_ids
    : (position?.processes || []).map(item => item.process_id)
  return [...new Set(raw.map(Number).filter(Number.isInteger))]
}
```

将新增、编辑的 `name` Schema 复用同一个定义：`minLength: 1, maxLength: 64, pattern: '^[一-龥a-zA-Z0-9\\s\\-/().+#]+$'`；在 composable 中增加 `canCreate/canEdit/canDelete`，命令入口无权限时直接返回；在模板按权限隐藏新增、编辑、删除按钮。删除和从 `active` 改为 `inactive` 之前都先调用影响接口，影响查询异常时显示错误并立即返回，不继续确认或保存。

- [ ] **Step 5: 运行 P0 定向测试**

Run:
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=/c/Users/dubin/AppData/Local/Temp/codex-position-review-pytest python -m pytest -q tests/test_position_contract.py tests/test_role_position_price_services.py
cd frontend && npm run test:unit -- --run tests/unit/Positions.spec.js
```
Expected: 全部通过，描述更新不改变岗位工序集合，显式空数组仍会清空关联。

- [ ] **Step 6: 提交 P0**

```bash
git add modules/services/position_service.py modules/schemas/positions.py frontend/src/composables/settings/usePositions.js frontend/src/views/settings/Positions.vue tests/test_position_contract.py frontend/tests/unit/Positions.spec.js
git commit -m "fix: preserve position process assignments"
```

### Task 2: 版本状态、差异、摘要和稳定错误纯策略

**Files:**
- Create: `modules/domain/position_versioning.py`
- Create: `tests/test_position_versioning_policy.py`

**Interfaces:**
- Consumes: 只接受调用方提供的字典、actor ID、时间字符串和行版本，不读取数据库、Flask 或环境变量。
- Produces: `validate_transition(current, target) -> str`、`assert_row_version(expected, actual) -> int`、`assert_separation_of_duties(prepared_by, approved_by) -> None`、`normalize_position_content(payload) -> dict`、`position_diff(before, after) -> dict`、`content_digest(payload) -> str`、`impact_digest(items) -> str`，以及设计中的稳定异常类。

- [ ] **Step 1: 写纯策略失败测试**

```python
def test_published_revision_is_immutable():
    with pytest.raises(PositionVersionImmutableError) as error:
        validate_transition("published", "draft")
    assert error.value.code == "POSITION_VERSION_IMMUTABLE"

def test_digest_is_order_stable():
    left = impact_digest([{"key": "users", "count": 2}, {"key": "facts", "count": 4}])
    right = impact_digest([{"count": 4, "key": "facts"}, {"count": 2, "key": "users"}])
    assert left == right
```

- [ ] **Step 2: 运行并确认模块不存在**

Run:
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=/c/Users/dubin/AppData/Local/Temp/codex-position-review-pytest python -m pytest -q tests/test_position_versioning_policy.py
```
Expected: FAIL，`modules.domain.position_versioning` 尚不存在。

- [ ] **Step 3: 实现固定状态机与规范摘要**

```python
VERSION_TRANSITIONS = {
    "draft": frozenset({"draft", "pending_approval", "cancelled"}),
    "pending_approval": frozenset({"published", "rejected"}),
    "published": frozenset({"superseded", "retired"}),
    "superseded": frozenset(),
    "rejected": frozenset(),
    "cancelled": frozenset(),
    "retired": frozenset(),
}

def stable_digest(payload):
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

定义 `PositionVersionStaleError`、`PositionVersionImmutableError`、`PositionVersionAlreadyOpenError`、`PositionApprovalSeparationError`、`PositionProcessInvalidError`、`PositionImpactChangedError`、`PositionActiveEmployeesError`、`PositionActiveSessionsError`、`PositionReferenceConflictError`、`PositionLegacyWriteBlockedError` 和 `PositionMigrationReviewRequiredError`；每类设置设计中完全一致的 `code` 和建议动作。

- [ ] **Step 4: 验证并提交**

Run:
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=/c/Users/dubin/AppData/Local/Temp/codex-position-review-pytest python -m pytest -q tests/test_position_versioning_policy.py
git add modules/domain/position_versioning.py tests/test_position_versioning_policy.py
git commit -m "feat: add position versioning domain policy"
```
Expected: 纯策略测试全部通过。

### Task 3: v070 稳定根、版本基线和事实字段迁移

**Files:**
- Create: `modules/migration_position_versioning.py`
- Modify: `modules/migrations.py`
- Create: `tests/test_position_version_migrations.py`
- Modify: `tests/test_migrations.py`

**Interfaces:**
- Consumes: v069 数据库及现有 `positions`、`position_processes`、绩效和报工表。
- Produces: `m070_position_versioning(db) -> None`、`MIGRATIONS = [(70, "position versioning ledger", m070_position_versioning)]`，并令 `LATEST_VERSION == 70`。

- [ ] **Step 1: 写迁移失败测试**

```python
def test_v070_creates_published_v1_without_fabricating_old_fact_versions(v069_db):
    position_id = seed_legacy_position(v069_db, process_ids=[3, 5])
    m070_position_versioning(v069_db)
    root = row(v069_db, "SELECT * FROM positions WHERE id=?", (position_id,))
    version = row(v069_db, "SELECT * FROM position_versions WHERE position_id=?", (position_id,))
    assert root["position_code"] == f"POS-{position_id:04d}"
    assert version["version"] == 1 and version["status"] == "published"
    assert version["legacy_baseline"] == version["prior_revision_unavailable"] == 1
    assert ids(v069_db, "SELECT process_id FROM position_version_processes WHERE position_version_id=?", (version["id"],)) == [3, 5]
    assert scalar(v069_db, "SELECT COUNT(*) FROM work_records WHERE submit_position_version_id IS NOT NULL") == 0
```

补充测试覆盖 6 张新表、5 个事实字段、开放版本唯一索引、当前发布唯一索引、事件不可更新删除、终态版本内容不可更新删除、已引用岗位根不可物理删除、迁移重复执行幂等、岗位/员工/报工/工资/绩效聚合不变和 `PRAGMA foreign_key_check` 为零。

- [ ] **Step 2: 运行并确认 v070 未注册**

Run:
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=/c/Users/dubin/AppData/Local/Temp/codex-position-review-pytest python -m pytest -q tests/test_position_version_migrations.py tests/test_migrations.py
```
Expected: FAIL，缺少迁移模块且 `LATEST_VERSION` 仍为 69。

- [ ] **Step 3: 实现迁移顺序和数据库不变量**

```python
def m070_position_versioning(db):
    _add_position_root_columns(db)
    _create_position_version_tables(db)
    _add_position_fact_columns(db)
    _create_legacy_v1_baselines(db)
    _split_open_assignments_at_cutover(db)
    _create_position_version_indexes(db)
    _create_position_immutable_triggers(db)
    _write_position_migration_manifest(db)

MIGRATIONS = [(70, "position versioning ledger", m070_position_versioning)]
```

创建 `position_versions`、`position_version_processes`、`position_version_events`、`position_lifecycle_requests`、`position_version_migration_manifests`、`position_version_migration_exceptions`；向设计列出的五张事实表添加可空版本字段。V1 使用 `POS-%04d`、`published`、`legacy_baseline=1`、`prior_revision_unavailable=1`；旧事实不回填。迁移切换时刻关闭启用员工的开放岗位历史并建立绑定 V1 的新区间，两个区间不得重叠。删除触发器拒绝删除已发布过或被员工、会话、岗位历史、绩效、报工、当前/历史岗位工序引用的岗位根；从未发布且完全无引用的草稿根仍可删除。

- [ ] **Step 4: 验证迁移并提交**

Run:
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=/c/Users/dubin/AppData/Local/Temp/codex-position-review-pytest python -m pytest -q tests/test_position_version_migrations.py tests/test_migrations.py
PYTHONPATH=/c/Users/dubin/AppData/Local/Temp/codex-position-review-pytest python -c "from modules.migrations import LATEST_VERSION; assert LATEST_VERSION == 70"
git add modules/migration_position_versioning.py modules/migrations.py tests/test_position_version_migrations.py tests/test_migrations.py
git commit -m "feat: add position versioning schema"
```
Expected: 定向测试通过且版本连续、无重复。

### Task 4: 版本仓储和事务 SQL 接口

**Files:**
- Create: `modules/repositories/position_version_repository.py`
- Create: `tests/test_position_version_repository.py`

**Interfaces:**
- Consumes: Task 3 的 v070 表和 Task 2 的 stale 异常。
- Produces: `root()`、`roots()`、`version()`、`current_version()`、`open_version()`、`list_versions()`、`create_root(payload, db)`、`create_revision(position_id, payload, db)`、`replace_version_processes(version_id, process_ids, db)`、`transition_version(...)`、`update_compatibility_projection(...)`、`create_event(payload, db)`、`create_lifecycle_request(payload, db)`；所有写方法不提交传入事务。

- [ ] **Step 1: 写仓储失败测试**

```python
def test_create_revision_is_idempotent_and_allocates_one_number(db):
    first = PositionVersionRepository.create_revision(1, revision_payload("same-key"), db)
    second = PositionVersionRepository.create_revision(1, revision_payload("same-key"), db)
    assert first["id"] == second["id"]
    assert scalar(db, "SELECT COUNT(*) FROM position_versions WHERE position_id=1") == 2

def test_conditional_transition_rejects_stale_row_version(db):
    with pytest.raises(PositionVersionStaleError):
        PositionVersionRepository.transition_version(2, "draft", 99, "pending_approval", {}, db)
```

- [ ] **Step 2: 运行并确认失败**

Run:
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=/c/Users/dubin/AppData/Local/Temp/codex-position-review-pytest python -m pytest -q tests/test_position_version_repository.py
```
Expected: FAIL，仓储模块不存在。

- [ ] **Step 3: 实现 SQL-only 仓储**

```python
@staticmethod
def transition_version(version_id, expected_status, expected_row_version, target_status, fields, db):
    assignments = ["status=?", *[name + "=?" for name in fields], "row_version=row_version+1"]
    values = [target_status, *fields.values(), version_id, expected_status, expected_row_version]
    cursor = db.execute(
        "UPDATE position_versions SET " + ",".join(assignments) +
        " WHERE id=? AND status=? AND row_version=?", values,
    )
    if cursor.rowcount != 1:
        raise PositionVersionStaleError("岗位版本已变化，请刷新后重试")
    return PositionVersionRepository.version(version_id, db=db)
```

根与版本列表采用至多三次批量查询预取当前版本和工序，按 `position_id/version/id` 和 `seq_order/id` 稳定排序；事件仅提供 INSERT；幂等唯一冲突后按 key 查询并返回原结果。

- [ ] **Step 4: 验证并提交**

Run:
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=/c/Users/dubin/AppData/Local/Temp/codex-position-review-pytest python -m pytest -q tests/test_position_version_repository.py
git add modules/repositories/position_version_repository.py tests/test_position_version_repository.py
git commit -m "feat: add position version repository"
```
Expected: 仓储测试全部通过，外层回滚能够撤销仓储写入。

### Task 5: 完整岗位引用目录和影响服务

**Files:**
- Modify: `modules/master_data_references.py`
- Create: `modules/services/position_impact_service.py`
- Modify: `modules/repositories/position_repository.py`
- Create: `tests/test_position_impact_service.py`
- Modify: `tests/test_master_data_reference_catalog.py`

**Interfaces:**
- Consumes: 数据库 schema 与 Task 2 的 `impact_digest()`。
- Produces: 不可变 `POSITION_REFERENCE_SPECS`；`PositionImpactService.summarize(position_id, db=None) -> {position_id, categories, total, blockers, impact_digest}`；`assert_deletable()` 与 `assert_retirable()`。

- [ ] **Step 1: 写引用覆盖和影响失败测试**

```python
def test_position_reference_catalog_covers_all_live_columns(db):
    discovered = discover_reference_columns(db, roots=("position_id",), snapshots=("position_version_id", "position_version_id_snapshot", "submit_position_version_id"))
    assert discovered - registered_position_reference_columns() == set()

def test_impact_includes_sessions_history_facts_scores_targets_and_work(db):
    seed_all_position_references(db, position_id=7)
    result = PositionImpactService.summarize(7, db=db)
    assert {item["key"] for item in result["categories"]} >= {
        "active_employees", "active_sessions", "assignment_history", "source_facts",
        "score_revisions", "target_versions", "work_records",
    }
```

- [ ] **Step 2: 运行并确认旧影响只统计用户**

Run:
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=/c/Users/dubin/AppData/Local/Temp/codex-position-review-pytest python -m pytest -q tests/test_position_impact_service.py tests/test_master_data_reference_catalog.py
```
Expected: FAIL，目录和结构化影响服务不存在。

- [ ] **Step 3: 实现引用规格和稳定摘要**

```python
POSITION_REFERENCE_SPECS = (
    ReferenceSpec("users", root_column="position_id", key="active_employees", label="启用员工", blocker="retire"),
    ReferenceSpec("sessions", root_column="active_position_id", key="active_sessions", label="活跃会话", blocker="retire"),
    ReferenceSpec("position_processes", root_column="position_id", key="current_position_processes", label="当前岗位工序"),
    ReferenceSpec("position_version_processes", version_column="position_version_id", key="historical_position_processes", label="历史岗位工序"),
    ReferenceSpec("performance_assignment_history", root_column="position_id", version_column="position_version_id", key="assignment_history", label="岗位分配历史"),
    ReferenceSpec("performance_source_facts", root_column="position_id", version_column="position_version_id", key="source_facts", label="绩效来源事实"),
    ReferenceSpec("performance_score_revisions", root_column="position_id", version_column="position_version_id_snapshot", key="score_revisions", label="绩效评分修订"),
    ReferenceSpec("performance_position_target_versions", root_column="position_id", version_column="position_version_id_snapshot", key="target_versions", label="绩效岗位目标"),
    ReferenceSpec("work_records", version_column="submit_position_version_id", key="work_records", label="报工记录"),
)
```

服务忽略不存在的兼容表，但测试数据库中存在的岗位引用列必须登记；`categories` 由目录顺序产生，摘要只包含 `key/count/blocking_level`，不包含时间或翻译文本。`PositionImpactService` 另以当前岗位工序集合连接未完成订单及其精确路线版本，返回 `open_orders/current_routes` 两个间接影响分类；不得把全库所有订单误算为该岗位影响。

- [ ] **Step 4: 验证并提交**

Run:
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=/c/Users/dubin/AppData/Local/Temp/codex-position-review-pytest python -m pytest -q tests/test_position_impact_service.py tests/test_master_data_reference_catalog.py
git add modules/master_data_references.py modules/services/position_impact_service.py modules/repositories/position_repository.py tests/test_position_impact_service.py tests/test_master_data_reference_catalog.py
git commit -m "fix: centralize position impact references"
```
Expected: 目录覆盖测试和影响摘要测试通过。

### Task 6: 统一岗位有效工序授权服务

**Files:**
- Create: `modules/services/position_access_service.py`
- Modify: `modules/services/access_policy_service.py`
- Modify: `modules/services/active_position_service.py`
- Modify: `modules/services/mobile_scan_service.py`
- Modify: `modules/routes/scan_work.py`
- Create: `tests/test_position_access_service.py`
- Modify: `tests/test_access_policy_service.py`
- Modify: `tests/test_active_position.py`
- Modify: `tests/test_scan_flow.py`

**Interfaces:**
- Consumes: `PositionVersionRepository.current_version()` 与现有显式员工工序授权。
- Produces: `PositionAccessService.new_business_process_ids(position_id, db=None) -> list[int]`、`historical_wip_process_ids(position_id, order_id, db=None) -> list[int]`、`effective_user_process_ids(user, order_id=None, db=None) -> list[int] | None`。

- [ ] **Step 1: 写授权失败测试**

```python
def test_retired_position_grants_no_new_business_processes(db):
    seed_published_position(db, position_id=4, process_ids=[2, 3], lifecycle="retired")
    assert PositionAccessService.new_business_process_ids(4, db=db) == []

def test_retired_process_remains_available_only_for_bound_wip(db):
    seed_published_position(db, position_id=4, process_ids=[2])
    retire_process(db, 2)
    order_id = seed_wip_order_bound_to_process_version(db, process_id=2)
    assert PositionAccessService.new_business_process_ids(4, db=db) == []
    assert PositionAccessService.historical_wip_process_ids(4, order_id, db=db) == [2]
```

- [ ] **Step 2: 运行并确认分散旧查询不满足规则**

Run:
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=/c/Users/dubin/AppData/Local/Temp/codex-position-review-pytest python -m pytest -q tests/test_position_access_service.py tests/test_access_policy_service.py tests/test_active_position.py tests/test_scan_flow.py
```
Expected: FAIL，退休岗位仍通过 `position_processes` 授权。

- [ ] **Step 3: 实现统一解析并替换调用点**

```python
class PositionAccessService:
    @staticmethod
    def effective_user_process_ids(user, order_id=None, db=None):
        if AccessPolicyService.has_global_scope(user):
            return None
        explicit = set(AccessPolicyRepository.list_user_process_ids(user["id"], db=db))
        if order_id is None:
            position = set(PositionAccessService.new_business_process_ids(user.get("position_id"), db=db))
        else:
            position = set(PositionAccessService.historical_wip_process_ids(user.get("position_id"), order_id, db=db))
        return sorted(explicit | position)
```

所有新选择列表使用 `new_business_process_ids`；扫码读取已有订单时显式传 `order_id`。不得在底层通用工序查询全局增加 `status='active'`。

- [ ] **Step 4: 验证并提交**

Run:
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=/c/Users/dubin/AppData/Local/Temp/codex-position-review-pytest python -m pytest -q tests/test_position_access_service.py tests/test_access_policy_service.py tests/test_active_position.py tests/test_scan_flow.py
git add modules/services/position_access_service.py modules/services/access_policy_service.py modules/services/active_position_service.py modules/services/mobile_scan_service.py modules/routes/scan_work.py tests/test_position_access_service.py tests/test_access_policy_service.py tests/test_active_position.py tests/test_scan_flow.py
git commit -m "fix: centralize effective position process scope"
```
Expected: 退休岗位撤权、显式授权保留、历史在制订单例外均通过。

### Task 7: 事务审计与绩效岗位快照服务

**Files:**
- Create: `modules/services/position_audit_service.py`
- Create: `modules/services/position_snapshot_service.py`
- Modify: `modules/repositories/performance_assignment_repository.py`
- Modify: `modules/services/performance_assignment_service.py`
- Create: `tests/test_position_audit_service.py`
- Create: `tests/test_position_snapshot_service.py`

**Interfaces:**
- Consumes: 调用方事务、actor、request ID、幂等键、Task 2 的 diff；现有绩效岗位历史仓储。
- Produces: `PositionAuditService.record(db, *, action, actor, request_id, idempotency_key, position_id, position_version_id, before, after, reason, impact_digest) -> int`；`PositionSnapshotService.apply_published_name(position_id, position_version_id, name, published_at, db) -> int`；`version_at(position_id, occurred_at, db=None) -> dict | None`。

- [ ] **Step 1: 写回滚与改名切分失败测试**

```python
def test_audit_failure_rolls_back_business_transaction(db, monkeypatch):
    monkeypatch.setattr(PositionAuditService, "_insert", Mock(side_effect=RuntimeError("audit failed")))
    with pytest.raises(RuntimeError), BaseService.transaction() as txn:
        PositionVersionRepository.create_event(event_payload(), txn)
        PositionAuditService.record(txn, **audit_payload())
    assert scalar(db, "SELECT COUNT(*) FROM position_version_events") == 0

def test_name_publish_splits_only_open_assignments(db):
    seed_open_assignment(db, user_id=8, position_id=2, name="旧名", valid_from="2026-08-01 07:00:00")
    count = PositionSnapshotService.apply_published_name(2, 19, "新名", "2026-08-20 10:00:00", db)
    assert count == 1
    assert assignment_intervals(db, 8) == [("旧名", None, "2026-08-20 10:00:00"), ("新名", 19, None)]
```

- [ ] **Step 2: 运行并确认服务不存在**

Run:
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=/c/Users/dubin/AppData/Local/Temp/codex-position-review-pytest python -m pytest -q tests/test_position_audit_service.py tests/test_position_snapshot_service.py
```
Expected: FAIL，新服务不存在。

- [ ] **Step 3: 实现事务适配器和时间区间切分**

```python
@staticmethod
def apply_published_name(position_id, position_version_id, name, published_at, db):
    current = PerformanceAssignmentRepository.open_assignments_for_position(position_id, db=db)
    for assignment in current:
        PerformanceAssignmentRepository.close_assignment(assignment["id"], published_at, db=db)
        PerformanceAssignmentRepository.create_assignment(
            user_id=assignment["user_id"], position_id=position_id,
            position_name_snapshot=name, position_version_id=position_version_id,
            valid_from=published_at, valid_to=None, db=db,
        )
    return len(current)
```

审计详情使用规范 JSON，记录 `changed_fields/added_process_ids/removed_process_ids/reason/impact_digest/idempotency_key`；重复幂等键返回原审计行，不重复插入。只在名称变化时切分岗位历史。

- [ ] **Step 4: 验证并提交**

Run:
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=/c/Users/dubin/AppData/Local/Temp/codex-position-review-pytest python -m pytest -q tests/test_position_audit_service.py tests/test_position_snapshot_service.py tests/test_performance_assignment_service.py
git add modules/services/position_audit_service.py modules/services/position_snapshot_service.py modules/repositories/performance_assignment_repository.py modules/services/performance_assignment_service.py tests/test_position_audit_service.py tests/test_position_snapshot_service.py
git commit -m "feat: add transactional position audit and snapshots"
```
Expected: 审计失败全事务回滚，描述/工序变化不切分岗位历史。

### Task 8: 岗位修订版工作流服务

**Files:**
- Create: `modules/services/position_version_service.py`
- Create: `tests/test_position_version_workflow.py`

**Interfaces:**
- Consumes: Tasks 2、4、5、7 的策略、仓储、影响、审计和快照服务。
- Produces: `create_position(command, actor_user, request_id="")`、`create_revision(position_id, command, actor_user, request_id="")`、`update_draft(version_id, command, actor_user, request_id="")`、`submit(version_id, command, actor_user, request_id="")`、`approve(version_id, command, actor_user, request_id="")`、`reject(...)`、`cancel(...)`、`list_versions(position_id)`、`get_version(version_id)`。

- [ ] **Step 1: 写工作流失败测试**

```python
def test_publish_atomically_supersedes_projects_snapshots_and_audits(client):
    draft = create_and_submit_revision(client, position_id=2, name="新岗位名", process_ids=[4, 6], preparer=1000)
    published = PositionVersionService.approve(
        draft["id"], {"row_version": draft["row_version"], "idempotency_key": "approve-1"},
        actor(1004), "req-1",
    )
    assert published["status"] == "published"
    assert current_projection(2) == {"name": "新岗位名", "process_ids": [4, 6]}
    assert previous_version(2)["status"] == "superseded"
    assert latest_assignment(2)["position_version_id"] == published["id"]
    assert mandatory_audit("approve-1")["position_version_id"] == published["id"]
```

补充：一根一个开放版本、非法/退休工序、幂等重放、过期行版本、本人批准、提交后影响变化、发布任一步失败全回滚、制造含义变化要求新根。

- [ ] **Step 2: 运行并确认工作流不存在**

Run:
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=/c/Users/dubin/AppData/Local/Temp/codex-position-review-pytest python -m pytest -q tests/test_position_version_workflow.py
```
Expected: FAIL，版本服务不存在。

- [ ] **Step 3: 实现唯一事务工作流**

```python
@staticmethod
def approve(version_id, command, actor_user, request_id=""):
    actor = PositionVersionService._actor(actor_user)
    with BaseService.transaction() as txn:
        version = PositionVersionService._pending(version_id, command["row_version"], txn)
        assert_separation_of_duties(version["created_by"], actor["id"])
        impact = PositionImpactService.summarize(version["position_id"], db=txn)
        assert_impact_digest(version["impact_digest"], impact["impact_digest"])
        previous = PositionVersionRepository.current_version(version["position_id"], db=txn)
        published_at = local_now()
        PositionVersionService._publish(previous, version, actor, published_at, txn)
        PositionAuditService.record(txn, action="position_version_approve", actor=actor,
            request_id=request_id, idempotency_key=command["idempotency_key"],
            position_id=version["position_id"], position_version_id=version_id,
            before=previous, after=version, reason=version["revision_reason"],
            impact_digest=impact["impact_digest"])
        return PositionVersionRepository.version(version_id, db=txn)
```

`_publish` 顺序固定为校验工序、取代旧版、发布新版、切换根指针、重建 `position_processes` 投影、名称变化时切分岗位历史、写领域事件；任一异常回滚全部步骤。

- [ ] **Step 4: 验证并提交**

Run:
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=/c/Users/dubin/AppData/Local/Temp/codex-position-review-pytest python -m pytest -q tests/test_position_version_workflow.py tests/test_position_audit_service.py tests/test_position_snapshot_service.py
git add modules/services/position_version_service.py tests/test_position_version_workflow.py
git commit -m "feat: add position revision workflow"
```
Expected: 工作流、幂等、乐观锁、职责分离和原子回滚测试通过。

### Task 9: 岗位退休与重新启用生命周期服务

**Files:**
- Create: `modules/services/position_lifecycle_service.py`
- Create: `tests/test_position_lifecycle_workflow.py`

**Interfaces:**
- Consumes: Tasks 4、5、7、8。
- Produces: `request_retirement(position_id, command, actor_user, request_id="")`、`approve_request(lifecycle_request_id, command, actor_user, request_id="")`、`reject_request(...)`、`request_reactivation(...)`、`list_requests(position_id)`。

- [ ] **Step 1: 写生命周期失败测试**

```python
def test_retirement_requires_no_active_employee_or_session(db):
    request = request_retirement(db, position_id=3, preparer=1000)
    seed_active_employee_and_session(db, position_id=3)
    with pytest.raises(PositionActiveEmployeesError):
        approve_lifecycle(db, request, approver=1004)
    assert position_root(db, 3)["lifecycle_status"] == "active"

def test_reactivation_requires_new_approved_revision(db):
    retire_position(db, 3)
    with pytest.raises(PositionReferenceConflictError):
        request_reactivation(db, position_id=3, preparer=1000)
```

- [ ] **Step 2: 运行并确认失败**

Run:
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=/c/Users/dubin/AppData/Local/Temp/codex-position-review-pytest python -m pytest -q tests/test_position_lifecycle_workflow.py
```
Expected: FAIL，生命周期服务不存在。

- [ ] **Step 3: 实现提交/批准二次影响核验**

```python
def _approve_retirement(request_row, actor, db):
    assert_separation_of_duties(request_row["requested_by"], actor["id"])
    impact = PositionImpactService.summarize(request_row["position_id"], db=db)
    assert_impact_digest(request_row["impact_digest"], impact["impact_digest"])
    if impact["counts"]["active_employees"]:
        raise PositionActiveEmployeesError("岗位仍有启用员工，请先完成调岗")
    if impact["counts"]["active_sessions"]:
        raise PositionActiveSessionsError("岗位仍有活跃会话，请先失效会话")
```

批准退休原子更新根 `lifecycle_status='retired'`、Legacy `status='inactive'`、当前版本为 `retired` 并写事件/审计；重新启用要求存在退休后新建并批准的修订，批准后发布该修订并恢复 `active`。

- [ ] **Step 4: 验证并提交**

Run:
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=/c/Users/dubin/AppData/Local/Temp/codex-position-review-pytest python -m pytest -q tests/test_position_lifecycle_workflow.py tests/test_position_access_service.py
git add modules/services/position_lifecycle_service.py tests/test_position_lifecycle_workflow.py
git commit -m "feat: add position lifecycle workflow"
```
Expected: 阻断、职责分离、影响漂移和重新启用前置条件测试通过。

### Task 10: V2 Schema、API、权限、功能开关与 Legacy 写入阻断

**Files:**
- Create: `modules/schemas/position_versioning.py`
- Modify: `modules/schemas/__init__.py`
- Create: `modules/routes/position_versions.py`
- Modify: `modules/routes/registry.py`
- Modify: `modules/routes/positions.py`
- Modify: `modules/permission_catalog.py`
- Modify: `modules/config.py`
- Create: `tests/test_position_version_api.py`
- Create: `tests/test_position_version_flags.py`
- Modify: `tests/test_permission_catalog.py`

**Interfaces:**
- Consumes: Tasks 8 和 9 的服务。
- Produces: 设计第 8 节全部 API；`get_position_versioning_flags(environ=None) -> dict[str, bool]`；四个固定开关 `POSITION_VERSIONED_QUERY_ENABLED`、`POSITION_COMPAT_AUDIT_ENABLED`、`POSITION_VERSIONED_WRITE_ENABLED`、`POSITION_LEGACY_WRITE_BLOCKED`。

- [ ] **Step 1: 写 API/开关失败测试**

```python
def test_position_flag_order_is_fail_closed():
    with pytest.raises(RuntimeError):
        validate_position_versioning_flags({
            "POSITION_VERSIONED_QUERY_ENABLED": False,
            "POSITION_VERSIONED_WRITE_ENABLED": True,
            "POSITION_LEGACY_WRITE_BLOCKED": False,
            "POSITION_COMPAT_AUDIT_ENABLED": False,
        })

def test_legacy_put_returns_stable_409_when_blocked(client, auth_headers, monkeypatch):
    monkeypatch.setattr(config, "POSITION_LEGACY_WRITE_BLOCKED", True)
    response = client.put("/api/positions/1", json={"description": "x"}, headers=auth_headers)
    assert response.status_code == 409
    assert response.get_json()["code"] == "POSITION_LEGACY_WRITE_BLOCKED"
```

- [ ] **Step 2: 运行并确认路由和权限不存在**

Run:
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=/c/Users/dubin/AppData/Local/Temp/codex-position-review-pytest python -m pytest -q tests/test_position_version_api.py tests/test_position_version_flags.py tests/test_permission_catalog.py
```
Expected: FAIL，V2 路由、Schema 和新增权限不存在。

- [ ] **Step 3: 实现严格请求 Schema 与 HTTP 适配**

```python
version_transition = {
    "type": "object", "additionalProperties": False,
    "required": ["row_version", "idempotency_key"],
    "properties": {"row_version": {"type": "integer", "minimum": 0},
                   "idempotency_key": {"type": "string", "minLength": 8, "maxLength": 128}},
}

@app.post("/api/position-versions/<int:version_id>/approve")
@check_auth
@check_permission("positions:approve")
@validate_json("position_version_transition")
def approve_position_version(version_id):
    data = get_json_body()
    return jsonify(PositionVersionService.approve(
        version_id, data,
        g.current_user, request.headers.get("X-Request-ID", ""),
    ))
```

新增 `positions:submit/approve/reject/history/impact/retire/reactivate`；影响接口改用 `positions:impact`。V2 命令在写开关关闭时返回稳定 409；Legacy PUT/DELETE 仅在阻断开关开启时返回 `POSITION_LEGACY_WRITE_BLOCKED`。路由不再为 V2 命令调用 `safe_audit_log`。

- [ ] **Step 4: 验证并提交**

Run:
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=/c/Users/dubin/AppData/Local/Temp/codex-position-review-pytest python -m pytest -q tests/test_position_version_api.py tests/test_position_version_flags.py tests/test_permission_catalog.py
git add modules/schemas/position_versioning.py modules/schemas/__init__.py modules/routes/position_versions.py modules/routes/registry.py modules/routes/positions.py modules/permission_catalog.py modules/config.py tests/test_position_version_api.py tests/test_position_version_flags.py tests/test_permission_catalog.py
git commit -m "feat: expose versioned position api"
```
Expected: 请求验证、权限、错误码和开关顺序测试全部通过。

### Task 11: 报工与绩效事实绑定精确岗位版本

**Files:**
- Modify: `modules/repositories/scan_repository.py`
- Modify: `modules/services/scan_helper_service.py`
- Modify: `modules/services/work_report_writer.py`
- Modify: `modules/repositories/performance_fact_repository.py`
- Modify: `modules/services/performance_fact_collector.py`
- Modify: `modules/repositories/performance_ledger_repository.py`
- Modify: `modules/services/performance_ledger_service.py`
- Modify: `modules/repositories/performance_configuration_repository.py`
- Modify: `modules/services/performance_configuration_service.py`
- Create: `tests/test_position_fact_bindings.py`
- Modify: `tests/test_performance_fact_collector.py`
- Modify: `tests/test_performance_ledger_service.py`

**Interfaces:**
- Consumes: `PositionSnapshotService.version_at(position_id, occurred_at)` 与 v070 可空字段。
- Produces: 新 `work_records.submit_position_version_id`、`performance_source_facts.position_version_id`、`performance_score_revisions.position_version_id_snapshot`、`performance_position_target_versions.position_version_id_snapshot` 写入；Legacy 空值读取回退原快照。

- [ ] **Step 1: 写事实绑定失败测试**

```python
def test_work_report_binds_submitter_position_version(db):
    version = seed_published_position(db, position_id=3)
    record_id = submit_work(db, user_id=8, position_id=3, occurred_at="2026-08-20 12:00:00")
    assert scalar(db, "SELECT submit_position_version_id FROM work_records WHERE id=?", (record_id,)) == version["id"]

def test_legacy_null_version_uses_saved_name_snapshot(db):
    fact_id = seed_legacy_fact(db, position_id=3, position_name_snapshot="旧岗位", position_version_id=None)
    assert render_fact(db, fact_id)["position_name"] == "旧岗位"
```

- [ ] **Step 2: 运行并确认字段尚未由写路径使用**

Run:
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=/c/Users/dubin/AppData/Local/Temp/codex-position-review-pytest python -m pytest -q tests/test_position_fact_bindings.py tests/test_performance_fact_collector.py tests/test_performance_ledger_service.py
```
Expected: FAIL，新事实版本字段为空或写入签名不接受字段。

- [ ] **Step 3: 在事实产生时解析一次并保存**

```python
position_version = PositionSnapshotService.version_at(position_id, occurred_at, db=db)
payload["position_version_id"] = position_version["id"] if position_version else None
payload["position_name_snapshot"] = (
    position_version["name"] if position_version else payload.get("position_name_snapshot", "")
)
```

报工写入从当前认证用户的有效岗位解析；绩效来源事实按事实发生时间解析；月度评分按生产月结束的 07:00 边界解析展示版本。旧记录为 NULL 时只读取原快照，不连接当前岗位名称覆盖历史语义。

- [ ] **Step 4: 验证并提交**

Run:
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=/c/Users/dubin/AppData/Local/Temp/codex-position-review-pytest python -m pytest -q tests/test_position_fact_bindings.py tests/test_performance_fact_collector.py tests/test_performance_ledger_service.py tests/test_scan_flow.py tests/test_reports.py
git add modules/repositories/scan_repository.py modules/services/scan_helper_service.py modules/services/work_report_writer.py modules/repositories/performance_fact_repository.py modules/services/performance_fact_collector.py modules/repositories/performance_ledger_repository.py modules/services/performance_ledger_service.py modules/repositories/performance_configuration_repository.py modules/services/performance_configuration_service.py tests/test_position_fact_bindings.py tests/test_performance_fact_collector.py tests/test_performance_ledger_service.py
git commit -m "feat: bind position versions to business facts"
```
Expected: 新事实精确绑定，Legacy 事实查询、导出、复算不失败且名称不漂移。

### Task 12: 版本化岗位前端 API、composable 和四视图 UI

**Files:**
- Create: `frontend/src/lib/api/position-versions.js`
- Modify: `frontend/src/lib/api.js`
- Modify: `frontend/src/lib/api/positions.js`
- Create: `frontend/src/composables/settings/usePositionVersions.js`
- Modify: `frontend/src/composables/settings/usePositions.js`
- Modify: `frontend/src/views/settings/Positions.vue`
- Reuse: `frontend/src/components/master-data/ImpactSummaryPanel.vue`
- Reuse: `frontend/src/components/master-data/VersionDiffPanel.vue`
- Create: `frontend/tests/unit/PositionVersions.spec.js`
- Modify: `frontend/tests/unit/Positions.spec.js`

**Interfaces:**
- Consumes: Task 10 API 和现有 `can(permission)`。
- Produces: `positionVersionsApi` 全部查询/命令方法；`usePositionVersions()` 暴露 `activeTab/current/pending/history/impact/selectedVersion/loading/commandBusy` 与创建修订、提交、批准、驳回、退休、重新启用命令。

- [ ] **Step 1: 写 UI 状态和权限失败测试**

```js
it('shows current pending history and impact views from versioned responses', async () => {
  const wrapper = mountPositions({ permissions: ['positions:view', 'positions:history', 'positions:impact'] })
  await flushPromises()
  expect(wrapper.get('[data-tab="current"]').exists()).toBe(true)
  expect(wrapper.get('[data-tab="history"]').exists()).toBe(true)
  expect(wrapper.get('[data-tab="impact"]').exists()).toBe(true)
})

it('blocks self approval and stale duplicate commands in the composable', async () => {
  const state = usePositionVersions({ actor: { id: 1000 }, autoLoad: false })
  state.selectedVersion.value = { id: 8, created_by: 1000, row_version: 2 }
  await state.approveSelected()
  expect(mocks.approve).not.toHaveBeenCalled()
})
```

- [ ] **Step 2: 运行并确认新版 UI 不存在**

Run:
```bash
cd frontend && npm run test:unit -- --run tests/unit/PositionVersions.spec.js tests/unit/Positions.spec.js
```
Expected: FAIL，版本 API/composable/视图不存在。

- [ ] **Step 3: 实现紧凑工作界面与命令二次权限阻断**

```js
export const positionVersionsApi = {
  list: positionId => request('GET', `/api/positions/${positionId}/versions`),
  get: versionId => request('GET', `/api/position-versions/${versionId}`),
  impact: versionId => request('GET', `/api/position-versions/${versionId}/impact`),
  createRevision: (positionId, data) => request('POST', `/api/positions/${positionId}/revisions`, data),
  update: (versionId, data) => request('PUT', `/api/position-versions/${versionId}`, data),
  submit: (versionId, data) => request('POST', `/api/position-versions/${versionId}/submit`, data),
  approve: (versionId, data) => request('POST', `/api/position-versions/${versionId}/approve`, data),
  reject: (versionId, data) => request('POST', `/api/position-versions/${versionId}/reject`, data),
  lifecycleRequests: positionId => request('GET', `/api/positions/${positionId}/lifecycle-requests`),
  requestRetirement: (positionId, data) => request('POST', `/api/positions/${positionId}/retirement-requests`, data),
  requestReactivation: (positionId, data) => request('POST', `/api/positions/${positionId}/reactivation-requests`, data),
  approveLifecycle: (requestId, data) => request('POST', `/api/position-lifecycle-requests/${requestId}/approve`, data),
  rejectLifecycle: (requestId, data) => request('POST', `/api/position-lifecycle-requests/${requestId}/reject`, data),
}
```

当前列表显示稳定编码、当前版本、工序、员工数、生命周期和待办；“编辑”改成“创建修订”；有引用的已发布岗位只显示“申请退休”。复用影响和差异组件，按钮使用现有图标库/样式并提供 `title`，不嵌套卡片。每个 composable 命令先检查对应权限和 `commandBusy`，再调用 API。

- [ ] **Step 4: 验证构建并提交**

Run:
```bash
cd frontend && npm run test:unit -- --run tests/unit/PositionVersions.spec.js tests/unit/Positions.spec.js
cd frontend && npm run build
git add frontend/src/lib/api/position-versions.js frontend/src/lib/api.js frontend/src/lib/api/positions.js frontend/src/composables/settings/usePositionVersions.js frontend/src/composables/settings/usePositions.js frontend/src/views/settings/Positions.vue frontend/tests/unit/PositionVersions.spec.js frontend/tests/unit/Positions.spec.js
git commit -m "feat: add versioned position management ui"
```
Expected: 单元测试通过，生产构建成功且无文本溢出或重叠。

### Task 13: 历史恢复预检、副本验收、全量回归与发布证据

**Files:**
- Create: `scripts/preflight_position_v070.py`
- Create: `scripts/recover_position_processes.py`
- Create: `scripts/validate_position_v070_replica.py`
- Create: `tests/test_position_v070_preflight.py`
- Create: `tests/test_position_process_recovery.py`
- Create: `docs/operations/position-v070-production-runbook.md`

**Interfaces:**
- Consumes: 只读生产数据库副本、明确传入的前后备份路径、Task 3 迁移和全部功能开关。
- Produces: JSON 预检报告、CSV 人工确认清单、恢复 manifest、SHA-256 证据和副本验收报告；脚本没有生产主机、用户名或密码硬编码。

- [ ] **Step 1: 写预检与恢复失败测试**

```python
def test_recovery_accepts_only_exact_backup_evidence(tmp_path):
    report = recover(before_db, current_db, output_dir=tmp_path)
    assert report["auto_restored"] == [{"position_id": 2, "process_ids": [3, 4], "evidence": before_db.name}]
    assert report["manual_review"][0]["reason_code"] == "POSITION_PROCESS_EVIDENCE_CONFLICT"

def test_preflight_blocks_unresolved_manual_review(replica_db):
    result = preflight(replica_db, recovery_manifest=manifest_with_unresolved_item())
    assert result["ready"] is False
    assert result["checks"]["unresolved_recovery_items"] == 1
```

- [ ] **Step 2: 运行并确认工具不存在**

Run:
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=/c/Users/dubin/AppData/Local/Temp/codex-position-review-pytest python -m pytest -q tests/test_position_v070_preflight.py tests/test_position_process_recovery.py
```
Expected: FAIL，脚本模块不存在。

- [ ] **Step 3: 实现只读取证、门槛和副本验收**

```python
PRECHECK_THRESHOLDS = {
    "invalid_position_status": 0,
    "duplicate_position_name": 0,
    "missing_position_process": 0,
    "duplicate_position_process": 0,
    "active_user_missing_position": 0,
    "overlapping_open_assignment": 0,
    "unresolved_recovery_items": 0,
    "foreign_key_violations": 0,
}

def open_read_only(path):
    return sqlite3.connect(f"file:{Path(path).resolve().as_posix()}?mode=ro", uri=True)
```

恢复工具只在前后备份的相同岗位 ID/工序 ID 集合能精确证明时生成可执行映射；矛盾或缺失证据只进入 CSV。验收脚本复制数据库到临时副本、执行 v070、检查业务聚合与快照不变、V1/Legacy 双读差异、完整性、外键和幂等重跑。runbook 固定顺序为备份可打开与 hash 验证、只读预检、副本演练、代码部署、迁移、四阶段开关、健康/权限/历史抽样和回滚边界。

- [ ] **Step 4: 运行定向与全量验证**

Run:
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=/c/Users/dubin/AppData/Local/Temp/codex-position-review-pytest python -m pytest -q tests/test_position_v070_preflight.py tests/test_position_process_recovery.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=/c/Users/dubin/AppData/Local/Temp/codex-position-review-pytest python -m pytest -q
cd frontend && npm run test:unit
cd frontend && npm run check:architecture
cd frontend && npm run build
```
Expected: 后端、前端、架构检查和构建全部通过；预检报告的每项门槛为零或 `ok`。

- [ ] **Step 5: 记录浏览器验收证据**

在本地服务中以查看者、制单人和独立批准人三种权限验证岗位四视图、修订差异、影响展示、按钮隐藏、自审批阻断和 Legacy 409；保存桌面与移动视口截图到任务证据目录，不提交包含令牌、完整联系人或生产数据的截图。

- [ ] **Step 6: 提交发布工具与验收文档**

```bash
git add scripts/preflight_position_v070.py scripts/recover_position_processes.py scripts/validate_position_v070_replica.py tests/test_position_v070_preflight.py tests/test_position_process_recovery.py docs/operations/position-v070-production-runbook.md
git commit -m "test: add position v070 release validation"
```
Expected: 分支只包含岗位修复、测试、迁移、脚本和文档，不包含 `.brooks-lint-history.json`。

## Final Acceptance Gate

- P0：真实列表响应可正确回填，修改描述不会清空工序，影响失败时删除和停用均失败关闭。
- 数据：岗位、员工、报工、工资、绩效数量和历史名称快照不变；V1/Legacy 当前投影完全一致。
- 不可变：终态版本、版本工序和事件不能更新或删除；根身份和稳定编码不变。
- 工作流：修订、提交、独立批准、发布、退休和重新启用均具备幂等、乐观锁和事务回滚。
- 权限：退休岗位不授权新业务；显式员工授权不误撤；历史在制订单按精确绑定继续流转。
- 事实：新报工和绩效事实绑定精确岗位版本，旧 NULL 版本事实仍按原快照查询、导出和复算。
- 安全：V2 后端权限为最终边界，前端按钮与命令双重阻断，强制审计失败时业务回滚。
- 发布：生产只读预检和数据库副本演练先完成；未经单独授权不连接、迁移、停服或重启 `192.168.1.8`。
