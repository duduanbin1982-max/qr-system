# 工序管理版本化台账修复详细实施计划

> 设计依据：`docs/superpowers/specs/2026-08-11-process-management-versioning-repair-design.md`

## 目标

将现有可覆盖式工序和工艺路线主数据改造成稳定根实体、不可变版本、双人审批和精确历史绑定的版本化台账。生产迁移采用兼容层渐进切换：先建立 V1 基线和 V2 查询，再切换订单、工价工资、事实快照和前端写入，最终阻断 Legacy 直接修改与删除。

## 生产与代码基线

- 生产主机：`192.168.1.8`
- 生产目录：`/home/dubin/qr-system`
- 设计基线提交：`e169a68a822b150eb5e849897fcf50a819954c6e`
- 设计文档提交：`335f4f9`
- 当前数据库版本：59
- 目标数据库版本：63
- 当前工序：31
- 当前路线：51
- 当前路线节点：310
- 当前工价版本：305
- 当前报工记录：3,708
- 最近正式部署基线：后端 649 项、前端单元 74 项、浏览器关键流程 16 项通过
- 计划分支：`codex/process-management-versioning-design`
- 实施分支：从本计划提交创建 `codex/process-management-versioning-repair`

## 架构边界

- `processes`、`process_routes` 只作为稳定身份根；兼容字段由版本服务投影，业务代码不能直接写。
- 已发布工序版本、路线版本、版本节点、事件和正式事实只允许追加或状态转换，不允许覆盖式修改。
- `ProcessVersionService`、`RouteVersionService` 和 `MasterDataReleaseService` 是版本状态变化的唯一入口。
- `MasterDataReferenceCatalog` 是工序和路线引用的唯一登记来源；数据库触发器和影响检查从同一登记表生成。
- 路线版本固定绑定工序版本。影响当前生产路线的工序修订必须与路线修订和工价版本成组发布，或存在批准例外。
- 岗位和员工授权绑定稳定 `process_id`；订单、报工、工价、工资、绩效和质量事实绑定精确版本。
- Legacy 查询保留；Legacy 写入在切换后返回结构化 409。
- 本计划不修改工资计算公式、绩效评分公式、质量评分流程或产品版本模型。

## 实施原则

- 每项任务先写失败测试，再做最小实现，再执行定向验证并独立提交。
- 迁移不按名称相似度猜测映射，不伪造迁移前不存在的修订版。
- 所有状态命令携带 `row_version`，所有创建类命令携带 `idempotency_key`。
- 制单人与批准人必须不同，通配管理员也不能绕过职责分离。
- 已发布版本的内容保护同时存在于服务层和数据库触发器。
- 生产迁移必须先在生产数据库副本完成同版本演练。
- V2 正式写入后不得用迁移前数据库覆盖新业务数据；故障采用关闭写入和向前修复。
- 保留用户和其他任务产生的无关工作区修改，不清理、不覆盖、不提交 `.brooks-lint-history.json`。

## 任务 1：建立 v060 版本化主数据基础迁移

**文件**

- 新增：`modules/migration_process_versioning.py`
- 修改：`modules/migrations.py`
- 新增：`tests/test_process_version_migrations.py`
- 修改：`tests/test_migrations.py`

**先写测试**

1. 从纯 v059 数据库执行 v060，断言创建：
   - `process_versions`
   - `process_route_versions`
   - `process_route_version_items`
   - `process_version_events`
   - `process_route_version_events`
   - `process_lifecycle_requests`
   - `process_route_lifecycle_requests`
   - `master_data_release_batches`
   - `master_data_release_process_versions`
   - `master_data_release_route_versions`
   - `master_data_release_price_versions`
   - `process_version_migration_manifests`
   - `process_version_migration_exceptions`
2. 断言 `processes` 增加稳定编码、生命周期、当前有效版本指针和 `row_version`。
3. 断言 `process_routes` 增加对应根字段。
4. 断言每个 Legacy 工序生成唯一 V1，编码按原 ID 生成 `PROC-xxxx`。
5. 断言每个 Legacy 路线及节点生成 V1，编码按原 ID 生成 `ROUTE-xxxx`。
6. 断言 V1 标记 `legacy_baseline=1`、`prior_revision_unavailable=1`。
7. 断言根实体当前有效版本指针正确，Legacy 字段与 V1 内容一致。
8. 断言版本号、当前发布版本、路线节点顺序和幂等键唯一索引存在。
9. 断言已发布、已取代或已退休版本无法更新或删除，版本事件无法更新或删除。
10. 断言迁移重复执行不产生重复根、版本、节点、事件或清单。
11. 断言 `LATEST_VERSION == 60`，迁移版本连续且无重复。

**实现**

1. 新迁移模块按“根字段、版本表、索引、Legacy V1、触发器、迁移清单”的顺序组织私有函数。
2. 稳定编码只使用原始 ID，不使用名称、拼音或分类。
3. `current_effective_version_id` 指向最后有效版本；退休后仍保留该指针。
4. 对 Legacy 表保留原字段，不在 v060 删除或重建既有业务表。
5. 版本表状态使用设计文档中的固定枚举，SQLite 触发器拒绝非法内容修改。
6. 成组发布使用三个具备真实外键的明细表，不使用无法建立外键的多态 `entity_type/entity_id` 表。
7. 迁移异常记录实体、原始主键、原因码和原始摘要；存在阻断异常时抛出错误并回滚。

**验证**

```bash
pytest -q tests/test_process_version_migrations.py tests/test_migrations.py
python3 -c "from modules.migrations import LATEST_VERSION; assert LATEST_VERSION == 60"
```

**提交**

```text
feat:add process master versioning schema
```

## 任务 2：实现版本状态、差异和摘要纯策略

**文件**

- 新增：`modules/domain/process_versioning.py`
- 新增：`tests/test_process_versioning_policy.py`

**先写测试**

1. 工序和路线版本只允许设计中的状态转换。
2. 已发布版本不能回到草稿或待审批。
3. 制单人和批准人相同返回职责分离错误。
4. 过期 `row_version` 返回稳定冲突错误。
5. 相同版本内容和影响输入产生相同规范 JSON 与 SHA-256 摘要。
6. 工序差异能够区分名称、分类、描述和排序变化。
7. 路线差异能够区分节点增加、删除、换序、工序版本变化和审批要求变化。
8. 根身份判断拒绝把制造含义已改变的对象作为普通修订提交。
9. 分类变化必须标记为高影响变更并要求授权复核。
10. 发布批次依赖不完整时返回明确原因码。

**实现**

1. 定义状态、事件、错误码、允许转换、行版本校验和职责分离函数。
2. 实现工序、路线和节点的规范化差异计算。
3. 实现影响摘要和发布批次摘要的稳定序列化。
4. 纯策略不得读取数据库、当前时间、环境变量或 Flask 上下文；时间由调用方显式传入。
5. 定义结构化领域错误：不可变、过期版本、职责分离、依赖缺失、分类不一致和 Legacy 写入阻断。

**验证**

```bash
pytest -q tests/test_process_versioning_policy.py
```

**提交**

```text
feat:add process versioning domain policy
```

## 任务 3：建立版本仓储和事务接口

**文件**

- 新增：`modules/repositories/process_version_repository.py`
- 新增：`modules/repositories/route_version_repository.py`
- 新增：`modules/repositories/master_data_release_repository.py`
- 新增：`modules/repositories/master_data_lifecycle_repository.py`
- 新增：`tests/test_process_version_repositories.py`

**先写测试**

1. 根实体、当前版本、指定版本和版本历史均可精确查询。
2. 创建修订版在同一根下原子分配下一版本号。
3. 相同幂等键返回原修订版，不重复插入。
4. 路线版本节点按 `seq_order,id` 稳定返回。
5. 仓储不会自行提交传入事务。
6. 条件状态更新同时校验状态和 `row_version`，受影响行数不是 1 时失败。
7. 成组发布明细不允许重复绑定同一版本。
8. 生命周期请求能够读取当前待审批请求并阻止重复申请。

**实现**

1. 所有写方法显式接收 `db`，通过 `resolve_db` 保持测试与生产一致。
2. 仓储只封装 SQL 和乐观锁条件，不决定业务状态转换。
3. 列表接口批量预取版本和节点，禁止 N+1 查询。
4. 单独提供兼容投影更新方法，但只允许版本服务在发布事务内调用。
5. 事件写入只提供 INSERT，不提供 UPDATE/DELETE 方法。

**验证**

```bash
pytest -q tests/test_process_version_repositories.py
```

**提交**

```text
feat:add process version repositories
```

## 任务 4：统一工序和路线引用目录及影响服务

**文件**

- 新增：`modules/master_data_references.py`
- 修改：`modules/process_references.py`
- 新增：`modules/services/master_data_impact_service.py`
- 修改：`modules/repositories/process_repository.py`
- 修改：`modules/repositories/route_repository.py`
- 修改：`modules/migration_process_management.py`
- 新增：`tests/test_master_data_reference_catalog.py`
- 修改：`tests/test_process_management.py`

**先写测试**

1. 引用目录覆盖所有 `process_id`、`*_process_id`、`process_version_id`、`route_id` 和 `route_version_id` 字段，显式豁免项除外。
2. 当前遗漏的工资、绩效和工价版本表必须出现在目录中。
3. 路线影响必须覆盖订单、产品、工价版本、工价历史、标准工时和质量配置。
4. 生产审计中12条被工价引用但旧逻辑未锁定的路线，在新影响服务中均为已引用。
5. 影响结果返回稳定业务标签、数量、阻断级别和建议动作，不把表名翻译留给前端。
6. 新增一个未登记的模拟引用表时，契约测试失败。
7. 删除保护触发器从同一目录生成；引用存在时根实体和版本实体均不能删除。

**实现**

1. 使用不可变 `ReferenceSpec` 定义根字段、版本字段、CSV 兼容字段、业务标签和删除策略。
2. `process_references.py` 暂时重导出新目录中的工序规格，保持旧调用兼容。
3. `MasterDataImpactService` 统一处理表存在性、字段存在性、计数和结构化输出。
4. 每次新增迁移引用字段时必须在同一提交更新目录和触发器重建函数。
5. 前端不再维护数据库表名到中文标签的重复映射。

**验证**

```bash
pytest -q tests/test_master_data_reference_catalog.py tests/test_process_management.py
```

**提交**

```text
fix:centralize process and route reference guards
```

## 任务 5：实现工序、路线、生命周期和成组发布服务

**文件**

- 新增：`modules/services/process_version_service.py`
- 新增：`modules/services/route_version_service.py`
- 新增：`modules/services/master_data_release_service.py`
- 新增：`modules/services/master_data_lifecycle_service.py`
- 新增：`tests/test_process_version_workflow.py`
- 新增：`tests/test_route_version_workflow.py`
- 新增：`tests/test_master_data_release_workflow.py`

**先写测试**

1. 新建工序和路线只创建根与 V1 草稿，未发布前不能用于业务。
2. 创建修订版复制当前有效版本并要求修订原因。
3. 同一根只能存在一个活跃草稿或待审批修订。
4. 提交时保存影响摘要；批准时摘要变化必须拒绝。
5. 批准人与制单人相同返回职责分离错误。
6. 发布在同一事务取代旧版本、发布新版本、切换指针、更新兼容投影并写事件。
7. 路线版本发布校验节点工序版本、分类、顺序和工价处置。
8. 工序修订影响当前路线时，缺少路线修订或批准例外不得发布。
9. 成组发布任一成员失败时全部状态、指针、投影和事件回滚。
10. 退休和重新启用使用双人生命周期请求；退休后历史可读，新业务解析失败关闭。
11. 幂等重试返回同一结果，不重复写事件。

**实现**

1. 服务使用 `BaseService.transaction()` 组织所有状态命令。
2. 版本策略只接受已规范化输入；服务负责读取当前数据库状态和授权 actor。
3. 发布顺序固定为校验、旧版取代、新版发布、根指针、兼容投影、事件。
4. 成组发布按工序版本、路线版本、工价版本依赖顺序校验，但在一个事务内落库。
5. 发布例外必须包含路线版本、保留的旧工序版本、原因、批准人和有效范围。

**验证**

```bash
pytest -q tests/test_process_version_workflow.py tests/test_route_version_workflow.py tests/test_master_data_release_workflow.py
```

**提交**

```text
feat:add versioned process master workflows
```

## 任务 6：增加版本化权限、请求 Schema 和 API

**文件**

- 修改：`modules/permission_catalog.py`
- 新增：`modules/schemas/process_versioning.py`
- 修改：`modules/schemas/__init__.py`
- 新增：`modules/routes/process_versions.py`
- 新增：`modules/routes/route_versions.py`
- 新增：`modules/routes/master_data_releases.py`
- 修改：`modules/routes/registry.py`
- 新增：`tests/test_process_version_api.py`
- 修改：`tests/test_permission_catalog_contracts.py`
- 修改：`frontend/src/lib/permissionFallback.generated.js`（通过导出脚本生成）

**先写测试**

1. 权限目录包含设计中的工序和路线查看、制单、提交、批准、驳回、影响、退休和重新启用权限。
2. 旧 `processes:view`、`routes:view` 最多迁移为新版查看权限。
3. 旧创建、编辑和删除权限不自动获得批准、退休或重新启用权限。
4. 请求 Schema 禁止额外字段，校验 `row_version`、幂等键、原因和节点结构。
5. 草稿、提交、批准、驳回、影响、退休和重新启用 API 返回稳定状态和错误码。
6. 无权限用户不能查看草稿或影响详情。
7. 通配管理员仍受制单人与批准人不同的服务约束。
8. 所有路由保持薄层，不直接执行 SQL 或状态转换。

**实现**

1. 新增资源中性的版本审批权限标签，不复用工资或绩效动作名称。
2. 生成权限迁移影响报告，列出持有旧敏感权限的角色和用户；不自动授予批准人。
3. 路由统一使用领域错误全局映射，返回 `error/code/details/action`。
4. 安全审计只记录路由访问补充信息，正式状态事件由服务事务写入。
5. 导出前端权限回退目录并执行一致性检查。

**验证**

```bash
pytest -q tests/test_process_version_api.py tests/test_permission_catalog_contracts.py
python3 scripts/export_permission_catalog.py --check
```

**提交**

```text
feat:expose process versioning api and permissions
```

## 任务 7：切换 Legacy 查询兼容并阻断旧写路径

**文件**

- 新增：`modules/services/legacy_process_compatibility_service.py`
- 修改：`modules/services/process_service.py`
- 修改：`modules/services/route_service.py`
- 修改：`modules/routes/processes.py`
- 修改：`modules/routes/process_routes.py`
- 修改：`modules/config.py`
- 修改：`tests/test_process_management.py`
- 新增：`tests/test_process_version_compatibility.py`

**先写测试**

1. V2 查询关闭时 Legacy GET 行为保持当前契约。
2. V2 查询开启时 Legacy GET 返回当前有效版本扁平字段及版本元数据。
3. 退休根在历史查询中可见，在可选列表中不可见。
4. 双读审计记录字段、数量和排序差异，但不改变响应。
5. `PROCESS_VERSIONED_WRITE_ENABLED=true` 后，新版写接口可用。
6. `PROCESS_LEGACY_WRITE_BLOCKED=true` 后，旧 POST/PUT/DELETE 返回 409 和建议动作。
7. 旧路线应用接口解析当前有效路线版本并继续执行订单数据范围检查。
8. 功能开关组合非法时应用启动失败，不静默回退。

**实现**

1. 定义四个设计开关并集中校验依赖顺序。
2. 兼容服务负责根、当前版本和 Legacy 字段的扁平投影。
3. 双读差异写入审计表或结构化日志，避免在正常响应中暴露内部细节。
4. Legacy 写阻断在路由和服务双层实现，防止内部调用绕过。
5. 保留现有 GET 响应中的 `process_name`、`processes` 等字段，新增版本字段而不删除旧字段。

**验证**

```bash
pytest -q tests/test_process_management.py tests/test_process_version_compatibility.py
```

**提交**

```text
feat:switch process legacy api to versioned compatibility
```

## 任务 8：建立 v061 订单、路线和订单工序版本绑定

**文件**

- 修改：`modules/migration_process_versioning.py`
- 新增：`tests/test_process_order_version_migration.py`
- 修改：`tests/test_migrations.py`

**先写测试**

1. v061 为 `orders` 增加 `route_version_id` 和路线名称快照。
2. v061 为 `order_processes` 增加 `process_version_id`、编码、名称和分类快照。
3. 有 `route_id` 的订单精确绑定路线 V1；订单工序绑定对应路线节点 V1。
4. 无路线但有自定义工序的订单按稳定工序映射 V1。
5. 无法映射的订单进入异常表并阻断正式迁移。
6. 订单数量、路线节点数量、已完成数量和报工数量不变。
7. 新增唯一索引和查询索引，不破坏现有 `order_id,process_id` 兼容唯一约束。
8. 迁移重复执行保持幂等，`LATEST_VERSION == 61`。

**实现**

1. 只根据稳定 ID 和 V1 清单回填，不使用名称匹配。
2. 路线为空时允许 `route_version_id` 为空，但每个订单工序必须完成工序版本映射。
3. 快照使用迁移时 V1 内容，并标记来源为 Legacy 基线。
4. v061 完成后重建涉及订单和路线版本字段的引用保护触发器。

**验证**

```bash
pytest -q tests/test_process_order_version_migration.py tests/test_migrations.py
python3 -c "from modules.migrations import LATEST_VERSION; assert LATEST_VERSION == 61"
```

**提交**

```text
feat:bind orders to process and route versions
```

## 任务 9：切换订单、路线应用和扫码报工写入版本

**文件**

- 修改：`modules/repositories/order_repository.py`
- 修改：`modules/services/order_process_sync_service.py`
- 修改：`modules/services/order_service.py`
- 修改：`modules/repositories/scan_repository.py`
- 修改：`modules/services/scan_helper_service.py`
- 修改：`modules/routes/scan_work.py`
- 修改：`tests/test_route_order_sync.py`
- 新增：`tests/test_order_process_versioning.py`
- 修改：`tests/test_scan_helper.py`

**先写测试**

1. 创建订单时解析并保存当前有效路线版本。
2. 路线节点复制到订单时保存精确工序版本和文本快照。
3. 路线发布新版本不修改既有订单。
4. 新订单使用成组发布后的新路线和新工序版本。
5. 退休路线或缺失当前版本时禁止新订单绑定。
6. 路线重新应用仍禁止修改已有有效报工的订单。
7. 扫码报工从订单工序读取版本，不从当前工序根重新解析。
8. 新报工保存工序版本和快照；重试不会重复报工。
9. 数据范围继续按稳定工序身份判断，版本字段不能扩大授权。

**实现**

1. `OrderProcessSyncService` 接收路线版本 ID 或显式工序版本列表。
2. 根路线 ID 兼容入口只在订单创建时解析一次当前有效版本。
3. 订单工序查询返回根 ID、版本 ID、快照和当前显示字段。
4. 扫码链路禁止用当前 `processes.name` 覆盖订单快照。
5. 保留现有顺序、数量上限、审批要求和数据范围策略。

**验证**

```bash
pytest -q tests/test_route_order_sync.py tests/test_order_process_versioning.py tests/test_scan_helper.py tests/test_process_reporting_policy.py
```

**提交**

```text
feat:write order and work facts with process versions
```

## 任务 10：建立 v062 工价和工资精确版本绑定

**文件**

- 修改：`modules/migration_process_versioning.py`
- 修改：`modules/repositories/payroll_repository.py`
- 修改：`modules/services/price_version_service.py`
- 修改：`modules/services/payroll_service.py`
- 修改：`modules/routes/payroll.py`
- 新增：`tests/test_process_price_version_migration.py`
- 修改：`tests/test_payroll_ledger.py`
- 修改：`tests/test_payroll_history_migration.py`

**先写测试**

1. v062 为 `route_price_versions` 增加路线版本和工序版本字段。
2. 现有305条工价版本按稳定 ID 精确绑定 V1。
3. 已批准工价保护触发器在迁移后仍然存在并生效。
4. 新工价必须绑定同一路线版本中的工序版本。
5. 工价区间重叠检查包含精确路线和工序版本维度。
6. 工资计算金额与迁移前一致，既有工资明细不被重算。
7. 新工资明细保存精确版本和快照。
8. 发布新路线版本时，缺少工价或“不适用”处置会阻止生产可用发布。
9. 成组发布工价失败时，工序和路线版本均不切换。
10. `LATEST_VERSION == 62`，迁移重复执行幂等。

**实现**

1. 迁移在事务内暂时移除并重建阻止已批准工价更新的触发器，不能静默绕过保护。
2. Legacy 工价绑定 V1，不复制或猜测新价格。
3. 工价查询优先按版本匹配；兼容期允许只读回退旧字段并记录差异。
4. 工资台账继续使用已解析的 `price_version_id`，不因主数据发布重新解析历史工资。

**验证**

```bash
pytest -q tests/test_process_price_version_migration.py tests/test_payroll_ledger.py tests/test_payroll_history_migration.py
python3 -c "from modules.migrations import LATEST_VERSION; assert LATEST_VERSION == 62"
```

**提交**

```text
feat:bind payroll prices to route and process versions
```

## 任务 11：建立 v063 业务事实版本字段和快照

**文件**

- 修改：`modules/migration_process_versioning.py`
- 修改：`modules/process_references.py`
- 新增：`tests/test_process_fact_version_migration.py`
- 修改：`tests/test_migrations.py`

**迁移范围**

- `work_records`
- `material_consumptions`
- `order_completion_focus_events`
- `process_handoff_reviews`
- `process_quality_evaluation_tasks`
- `process_quality_evaluation_task_audits`
- `process_quality_evaluations`
- `quality_inspection_tasks`
- `quality_inspections`
- `quality_nonconformances`
- `rework_records`
- `scrap_records`
- `work_time_records`
- `work_time_standards`
- `payroll_detail_lines`
- `performance_quality_events`
- `performance_source_facts`

配置类表保留稳定根 ID；事件和事实类表增加精确版本 ID 与文本快照。

**先写测试**

1. v063 为事实表增加相应版本 ID 和快照字段。
2. Legacy 事实按稳定工序 V1 回填，并标记基线来源。
3. 不可变工资和绩效表完成回填后，原保护触发器全部恢复。
4. 迁移前后的金额、数量、评分、摘要和原始主键不变。
5. 新增字段索引覆盖按版本、订单、用户和时间查询。
6. 无法映射的事实进入异常清单并阻断切换。
7. 引用目录契约在完整 v063 Schema 上无遗漏。
8. 删除保护触发器包含根引用和版本引用。
9. `LATEST_VERSION == 63`，重复执行无副作用。

**实现**

1. 对带不可变触发器的表，迁移必须显式保存、移除、回填并重建触发器，或安全重建表；不能吞掉更新异常。
2. 事实快照使用 V1 内容，不读取以后发布的新版本。
3. 配置和授权类引用按设计继续绑定根实体，但加入根删除保护目录。
4. v063 是引用保护收口版本，完成后任何新增引用字段必须通过契约测试。

**验证**

```bash
pytest -q tests/test_process_fact_version_migration.py tests/test_migrations.py tests/test_master_data_reference_catalog.py
python3 -c "from modules.migrations import LATEST_VERSION; assert LATEST_VERSION == 63"
```

**提交**

```text
feat:version process references across business facts
```

## 任务 12：切换事实采集、历史报表和追溯读取

**文件**

- 修改：`modules/repositories/stats_repository.py`
- 修改：`modules/repositories/reports_repository.py`
- 修改：`modules/repositories/wage_repository.py`
- 修改：`modules/repositories/trace_repository.py`
- 修改：`modules/repositories/work_time_repository.py`
- 修改：`modules/repositories/performance_fact_repository.py`
- 修改：`modules/repositories/process_quality_evaluation_repository.py`
- 修改：`modules/repositories/process_quality_evaluation_task_repository.py`
- 修改：`modules/repositories/quality_repository.py`
- 新增：`tests/test_process_version_history_reads.py`
- 修改：`tests/test_stats_contracts.py`
- 修改：`tests/test_reporting_repairs.py`
- 修改：`tests/test_performance_fact_collector.py`
- 修改：`tests/test_process_quality_evaluation.py`

**先写测试**

1. 工序 V2 发布后，V1 报工、日报、工资和追溯仍显示 V1 快照。
2. 新报工和质量事件显示 V2 快照。
3. 报表优先级固定为“事实快照 → 精确版本 → Legacy 当前名称”。
4. Legacy 无版本记录仍可查询，但写入兼容差异日志。
5. 绩效来源事实保存并读取精确工序版本，不因当前名称变化重算摘要。
6. 工序质量评价任务和审核记录保留目标与评价工序版本。
7. 查询数量、金额和评分与迁移前保持一致。
8. 列表查询不引入 N+1，分页前完成权限和过滤。

**实现**

1. 为历史展示建立统一 SQL 投影约定，避免各仓储自行决定回退顺序。
2. 新事实采集从订单工序或来源事实取得版本，不查询“当前工序”替代来源版本。
3. 性能和工资不可变摘要不得因补充展示字段而改变。
4. 在兼容期记录缺失版本 ID 的读取次数，稳定后降为零。

**验证**

```bash
pytest -q tests/test_process_version_history_reads.py tests/test_stats_contracts.py tests/test_reporting_repairs.py tests/test_performance_fact_collector.py tests/test_process_quality_evaluation.py
```

**提交**

```text
feat:read historical process facts from version snapshots
```

## 任务 13：实现工序版本管理 UI

**文件**

- 新增：`frontend/src/lib/api/process-versions.js`
- 修改：`frontend/src/lib/api.js`
- 新增：`frontend/src/composables/useProcessVersions.js`
- 新增：`frontend/src/components/master-data/VersionDiffPanel.vue`
- 新增：`frontend/src/components/master-data/ImpactSummaryPanel.vue`
- 修改：`frontend/src/views/ProcessList.vue`
- 新增：`frontend/tests/unit/ProcessVersions.spec.js`
- 修改：`frontend/tests/unit/ProcessList.spec.js`

**先写测试**

1. 页面显示稳定编码、当前版本、生命周期、引用数量和待审批状态。
2. “编辑”替换为“创建修订版”，“删除”替换为“申请退休”。
3. 当前版本、待审批和历史版本可切换。
4. 已发布版本表单只读。
5. 创建修订、提交、批准、驳回、退休和重新启用调用正确版本 API。
6. 影响摘要变化、职责分离和并发冲突显示明确操作建议。
7. 保存中禁用按钮，重复点击不会重复创建修订。
8. 后端返回业务标签，前端不再维护引用表名翻译字典。

**实现**

1. 把现有335行页面中的加载、修订、审批和影响逻辑提取到 composable。
2. 共用差异和影响组件，避免路线页面重复实现。
3. 旧查询字段继续支持，但所有写操作走新版本 API。
4. 退休对象在历史视图可见，在新业务选择模式中隐藏；重新启用入口要求先存在可发布的新修订版。

**验证**

```bash
npm run test:unit -- frontend/tests/unit/ProcessList.spec.js frontend/tests/unit/ProcessVersions.spec.js
npm run check:architecture
```

**提交**

```text
feat:add process version management ui
```

## 任务 14：实现路线版本、工价覆盖和成组发布 UI

**文件**

- 新增：`frontend/src/lib/api/process-route-versions.js`
- 新增：`frontend/src/lib/api/master-data-releases.js`
- 修改：`frontend/src/lib/api.js`
- 新增：`frontend/src/composables/useRouteVersions.js`
- 新增：`frontend/src/composables/useMasterDataReleases.js`
- 新增：`frontend/src/components/master-data/RouteVersionEditor.vue`
- 新增：`frontend/src/components/master-data/ReleaseBatchPanel.vue`
- 修改：`frontend/src/views/RouteList.vue`
- 修改：`frontend/src/views/wage/ProcessWageTab.vue`
- 新增：`frontend/tests/unit/RouteVersions.spec.js`
- 新增：`frontend/tests/unit/MasterDataRelease.spec.js`

**先写测试**

1. 路线页面显示当前版本、节点版本、工价覆盖、引用和修订状态。
2. 已发布路线只能查看，不能直接修改节点。
3. 创建修订版复制节点和审批要求。
4. 工序版本变化时显示受影响路线和需要建立的工价版本。
5. 缺少工价处置时不能提交生产发布。
6. 发布批次展示工序、路线、工价依赖和完整差异。
7. 成组批准只调用一次幂等命令；冲突后刷新整个批次。
8. 退休路线从新订单选择中隐藏，但历史版本仍可展开；重新启用前必须已有可发布的新修订版。

**实现**

1. 重用工序页面的差异和影响组件。
2. 路线节点选择器只允许选择已发布且分类一致的工序版本。
3. 工价覆盖状态来自后端，不在前端自行推断。
4. 页面不保留旧的直接编辑、删除或自动同步历史订单入口。

**验证**

```bash
npm run test:unit -- frontend/tests/unit/RouteVersions.spec.js frontend/tests/unit/MasterDataRelease.spec.js
npm run check:architecture
npm run build
```

**提交**

```text
feat:add route version and release batch ui
```

## 任务 15：实现生产预检、差异、迁移和切换脚本

**文件**

- 新增：`scripts/production_process_v2_preflight.py`
- 新增：`scripts/validate_process_v2_replica.py`
- 新增：`scripts/export_process_v2_review_diff.py`
- 新增：`scripts/production_process_v2_cutover.py`
- 新增：`scripts/production_process_v2_post_cutover_smoke.py`
- 新增：`tests/test_process_v2_operations_scripts.py`
- 修改：`DEPLOY.md`

**先写测试**

1. 预检只读运行，输出版本、记录数、重复项、分类错配、引用覆盖和异常。
2. 预检能识别旧逻辑遗漏的12条工价引用路线。
3. 副本校验比较根、版本、节点、工价、订单、事实和摘要。
4. 差异导出包含人可读清单与机器可读 JSON，不自动应用修复。
5. 切换脚本按阶段校验功能开关，不允许跳级。
6. 切换命令需要目标提交、数据库 SHA-256、操作者和幂等键。
7. 后验收检查健康、权限、Legacy 409、V2查询、历史快照和缺失版本计数。
8. 任一强制检查失败时脚本非零退出，不写“成功”标记。

**实现**

1. 生产脚本默认只读；正式写入必须显式 `--apply` 并校验预检摘要。
2. 副本演练和正式迁移复用同一迁移入口，不复制 SQL。
3. 切换脚本记录阶段、提交、数据库版本、备份路径、摘要和执行人。
4. 任何无法唯一映射的数据进入人工确认清单。
5. 文档明确 V2 写入后的回滚只能关闭写入并向前修复。

**验证**

```bash
pytest -q tests/test_process_v2_operations_scripts.py
python3 scripts/production_process_v2_preflight.py --help
python3 scripts/production_process_v2_cutover.py --help
```

**提交**

```text
ops:add process versioning preflight and cutover tools
```

## 任务 16：全量回归、生产副本演练与正式发布

**文件**

- 新增：`docs/process-management-v2-production-preflight-2026-08-11.md`
- 新增：`docs/process-management-v2-release-evidence-2026-08-11.md`
- 视验收结果修改：`deploy.sh`

**执行步骤**

1. 运行所有定向测试和完整后端测试。
2. 运行前端单元、API门面、循环依赖、生产构建和关键浏览器流程。
3. 在生产数据库只读预检中确认：
   - 数据库仍为预期版本；
   - 工序、路线、节点、工价和事实数量与设计基线差异可解释；
   - 规范化重复、分类错配、外键和完整性无阻断问题；
   - 引用目录遗漏为零。
4. 创建生产SQLite一致性备份并校验 SHA-256 与 `integrity_check=ok`。
5. 在生产数据库副本执行 v060-v063，运行副本验收和双读差异。
6. 人工确认所有迁移异常；未确认异常数量必须为零。
7. 在维护窗口停止生产写入，正式执行迁移。
8. 依次开启：
   - `PROCESS_VERSIONED_QUERY_ENABLED`
   - `PROCESS_VERSION_COMPAT_AUDIT_ENABLED`
   - `PROCESS_VERSIONED_WRITE_ENABLED`
   - `PROCESS_LEGACY_WRITE_BLOCKED`
9. 使用真实制单人和批准人完成一条工序修订、一条路线修订和一次成组发布。
10. 使用测试订单验证路线版本、订单工序版本、扫码报工、工价解析和历史快照。
11. 核对历史日报、工资、绩效和质量抽样。
12. 观察24小时重点指标和72小时稳定指标，形成发布证据。

**全量验证**

```bash
pytest -q
npm run test:unit
npm run check:architecture
npm run build
npm run test:e2e
```

**生产强制验收**

- `PRAGMA user_version = 63`
- `PRAGMA integrity_check = ok`
- 外键违规数量为零
- 工序、路线、订单、工价、工资和绩效数量差异为零或有批准解释
- 新增订单路线版本缺失为零
- 新增订单工序版本缺失为零
- 新增报工版本缺失为零
- Legacy GET 正常
- Legacy POST/PUT/DELETE 返回预期 409
- 服务 `active/running`
- 健康接口 `status=ok`
- 生产工作区干净
- 备份可读且校验值已记录

**提交**

```text
release:record process versioning production evidence
```

## 任务依赖顺序

```text
Task 1  v060 Schema
  ↓
Task 2  纯版本策略
  ↓
Task 3  仓储
  ↓
Task 4  引用目录与影响
  ↓
Task 5  工作流与成组发布
  ↓
Task 6  权限、Schema、API
  ↓
Task 7  Legacy兼容
  ↓
Task 8  v061订单迁移
  ↓
Task 9  订单与报工写入
  ↓
Task 10 v062工价工资
  ↓
Task 11 v063事实迁移
  ↓
Task 12 历史读取与事实采集
  ↓
Task 13-14 前端可并行实现
  ↓
Task 15 生产工具
  ↓
Task 16 副本演练和正式发布
```

Task 13 和 Task 14 只能在 Task 6 的 API 契约稳定后并行；Task 16 必须等待其余任务全部完成。

## 完成定义

只有同时满足以下条件，整个修复才算完成：

1. 数据库达到 v063，所有不变量和引用保护在数据库层生效。
2. 新业务全部写入稳定 ID、版本 ID 和文本快照。
3. 工序、路线和工价成组发布可以原子完成。
4. 历史订单、日报、工资、绩效和质量结果不随主数据修订变化。
5. Legacy 查询兼容，Legacy 写入被稳定阻断。
6. 双读差异、版本映射异常和新增缺失版本记录均为零。
7. 全量自动化、生产副本演练和真实业务验收全部通过。
8. 生产备份、迁移清单、差异清单和发布证据完整保存。
