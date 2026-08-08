# 绩效管理版本化台账修复详细实施计划

> 设计依据：`docs/superpowers/specs/2026-08-04-performance-management-repair-design.md`

## 目标

将现有覆盖式绩效评分改造成版本化绩效台账：统一使用每日 07:00 生产月边界，以已批准岗位目标计算产量分，区分合格参评与数据不足，保存不可变来源和评分修订，执行部门范围授权、主管复核和独立批准，并为改进计划建立证据化复评闭环。

## 生产与代码基线

- 生产主机：`192.168.1.8`，SSH 别名 `codex-8`
- 生产目录：`/home/dubin/qr-system`
- 已确认生产提交：`c0817bb15cb6a346de411f94bb8142f04145ad0c`
- 设计提交：`433a48e`
- 当前数据库版本：55
- 本计划目标数据库版本：56
- 实施分支：从本计划最终提交创建 `codex/performance-ledger-repair`

## 架构边界

- `modules/repositories/performance_repository.py` 只保留 Legacy 兼容读取；不再承担 V2 写入。
- 新建台账、事实、配置和改进计划仓储，避免继续扩大现有 410 行仓储。
- `PerformanceScoringPolicy` 保持纯计算，不自行查询数据库或读取“当前配置”。
- 所有批次命令经 `PerformanceLedgerService` 执行，数据库触发器作为第二层不可变保护。
- 所有查询和对象命令统一经 `PerformanceAuthorizationService` 注入本人、部门或全局范围。
- 旧 `performance_scores`、`performance_reviews`、`performance_improvement_plans` 在 V56 迁移后只读。
- 本轮不写工资台账，不增加奖金、处分或解聘自动化。

## 实施原则

- 每项任务先写失败测试，再完成最小实现，再运行定向测试并独立提交。
- 不能用更新或删除模拟修订；评分、复核、事实和事件只允许追加。
- 历史岗位、质量重复关系和目标配置不按相似度或当前值自动猜测。
- 所有时间范围使用 `modules.domain.reporting_day.reporting_month_bounds` 的左闭右开区间。
- 所有写命令带幂等键；所有状态命令带 `row_version`。
- 生产迁移必须先在生产数据库副本完成同版本演练。
- 实施时保留用户或其他任务产生的无关工作区变更，不清理、不覆盖、不提交。

## 任务 1：增加 V56 绩效台账数据库迁移

**文件**

- 修改：`modules/migration_performance.py`
- 修改：`tests/test_migrations.py`

**先写测试**

1. 从 V55 内存数据库执行 `m056_versioned_performance_ledger`，断言创建：
   - `performance_rule_versions`
   - `performance_position_target_versions`
   - `performance_batches`
   - `performance_score_revisions`
   - `performance_source_facts`
   - `performance_reviews_v2`
   - `performance_batch_events`
   - `performance_data_exceptions`
   - `performance_quality_events`
   - `performance_quality_event_sources`
   - `performance_assignment_history`
   - `performance_department_scopes`
   - `performance_improvement_plans_v2`
   - `performance_plan_events`
   - `performance_plan_evidence`
   - `performance_plan_reassessments`
   - `performance_permission_migration_report`
   - `performance_migration_manifests`
2. 断言生产月版本、员工修订号、规范质量来源和部门授权关系的唯一索引存在。
3. 断言批次状态只允许已批准设计中的转换，并通过数据库触发器阻止非法跳转。
4. 断言事实、复核、事件、迁移清单和评分修订版不能更新或删除。
5. 断言已批准、已取代或已取消批次不能追加评分修订版。
6. 断言 Legacy 三张表在导入完成后拒绝 INSERT、UPDATE 和 DELETE。
7. 断言迁移可重复调用，Legacy 行数量和原始主键不变。
8. 断言 `LATEST_VERSION == 56` 且迁移版本连续、无重复。
9. 断言旧 `performance:view/create/edit` 不会迁移为全局、制单或批准权限；基础员工和旧查看者最多获得本人查看及绩效页面权限。

**实现**

1. 在 `migration_performance.py` 增加 `m056_versioned_performance_ledger`，按“表、索引、Legacy 导入、权限影响清单、触发器”的顺序组织私有函数。
2. `performance_batches` 增加 `legacy_imported`、`idempotency_key`、`row_version` 和版本取代字段，允许 Legacy V1 不绑定 V2 规则。
3. 把现有 `performance_scores` 按月份导入为 Legacy V1 批次和评分修订版；保存原评分主键、原时间和原 JSON 依据。
4. `updated_at > generated_at` 的 Legacy 行标记 `prior_revisions_unavailable=1`，不伪造历史修订。
5. 仅从 Legacy `score_details` 中读取可靠岗位快照；缺少快照时创建 `missing_position_snapshot` 异常，不读取当前 `users.position_id` 回填。
6. 将旧改进计划复制到 V2 迁移区；无法映射到合法状态的记录创建迁移异常，不伪造复评证据。
7. 保存含旧绩效权限的角色、权限 JSON 和受影响人数；移除旧 `performance:view/create/edit`，仅把基础员工和旧查看者降级为 `page:performance + performance:view_self`，不自动授予部门、全局、复核、制单或批准权限。
8. 所有触发器命名固定并使用 `CREATE TRIGGER IF NOT EXISTS`；迁移幂等通过表、索引、触发器存在性和 Legacy 唯一键保证，不静默吞掉异常。

**验证**

```bash
pytest -q tests/test_migrations.py
python3 -c "from modules.migrations import LATEST_VERSION; assert LATEST_VERSION == 56"
```

**提交**

```text
feat:add versioned performance ledger schema
```

## 任务 2：实现版本化纯评分规则

**文件**

- 新增：`modules/domain/performance_policy.py`
- 修改：`modules/services/performance_scoring_policy.py`
- 新增：`tests/test_performance_scoring_policy.py`

**先写测试**

1. 产量分使用 `min(output_qty / target_output_qty, 1) * 35`，不再接受岗位月最大值。
2. 零产量、缺岗位、缺岗位目标、有效报工日不足或存在未确认异常时返回 `insufficient_data`，分数、等级和排名均为空。
3. 有效产量且无质量事件时质量扣分为零；同一规范事件不能重复进入不良数量。
4. 质量、交付、纪律、改进和主管评议的上限、下限及首版权重保持 30、15、10、10。
5. 主管评议只能从默认 10 分向下调整；纪律或评议扣分缺原因时拒绝计算。
6. 同岗位少于 3 名合格员工不产生排名；3 人以上使用并列排名，稳定主键只决定输出顺序。
7. `2026-08-01 06:59:59` 属于 7 月，`2026-08-01 07:00:00` 属于 8 月。
8. 相同规则、目标、事实和复核输入产生完全一致的规范 JSON 和 SHA-256 摘要。

**实现**

1. 在 `performance_policy.py` 定义状态常量、原因码、`PerformanceConflictError`、月份校验、行版本校验和允许的状态转换。
2. 把 `PerformanceScoringPolicy.score_worker` 改成只接受规则字典、岗位目标、指标、复核和质量事实，不访问仓储。
3. 返回 `eligibility_status`、原因码、五维分数、总分、等级、依据字典和输入摘要。
4. 新增纯排名函数，一次接收完整岗位合格结果，返回同一计算时间的排名修订数据。
5. 保留现有五维警戒阈值语义；删除 `max_output <= 0` 自动给 35 分的分支。

**验证**

```bash
pytest -q tests/test_performance_scoring_policy.py
```

**提交**

```text
feat:score performance against versioned targets
```

## 任务 3：记录稳定的岗位与部门任职历史

**文件**

- 新增：`modules/repositories/performance_assignment_repository.py`
- 新增：`modules/services/performance_assignment_service.py`
- 修改：`modules/services/user_service.py`
- 修改：`modules/repositories/user_repository.py`
- 修改：`tests/test_user_service_extended.py`
- 新增：`tests/test_performance_assignments.py`

**先写测试**

1. 修改员工岗位或部门时，在同一事务关闭旧任职区间并追加新任职记录。
2. 员工改名时保留姓名、工号、岗位名和部门名快照，但不伪造岗位变更。
3. 修改失败时用户表和任职历史同时回滚。
4. 同一员工任职区间不得重叠。
5. 查询历史生产月时返回当时有效任职，不读取当前岗位覆盖历史。
6. V56 首次基线只标记 `current_baseline` 和迁移时间，不把当前岗位反向延伸到未知历史月份。
7. 当前离职或停用员工只要生产月内存在可靠任职或有效来源事实，仍进入历史候选集合。

**实现**

1. `PerformanceAssignmentService` 负责比较用户旧值和新值，并在用户更新事务中记录任职事件。
2. `PerformanceAssignmentRepository` 提供按半开时间区间查询和区间冲突检查。
3. 用户更新服务显式把当前数据库事务传给任职服务，禁止提交后再补写历史。
4. 对迁移前缺少任职证据的月份返回异常状态，不使用 `users.position_id` 猜测。

**验证**

```bash
pytest -q tests/test_user_service_extended.py tests/test_performance_assignments.py
```

**提交**

```text
feat:track performance assignment history
```

## 任务 4：拆分绩效权限和部门数据范围

**文件**

- 修改：`modules/permission_catalog.py`
- 新增：`modules/repositories/performance_authorization_repository.py`
- 新增：`modules/services/performance_authorization_service.py`
- 新增：`modules/routes/performance_authorization.py`
- 修改：`modules/routes/registry.py`
- 修改：`frontend/src/lib/permissionFallback.generated.js`（由脚本生成）
- 修改：`tests/test_permission_catalog_contracts.py`
- 新增：`tests/test_performance_permissions.py`

**先写测试**

1. 权限目录包含 `view_self`、`view_department`、`view_all`、`review_department`、`prepare`、`approve`、`plan_manage`、`plan_reassess`。
2. `performance:view` 不隐式获得 `view_all`；质检员和仓库管理员的旧权限不扩大为全局查看。
3. 本人范围只能返回 actor 自己；部门范围只返回 `performance_department_scopes` 中显式授权部门；全局范围返回全部。
4. 多权限用户取范围并集，但不能通过传入其他 `department_id` 或 `user_id` 扩大范围。
5. 部门历史结果按评分中的部门快照匹配，而不是员工当前部门。
6. `review_department` 只允许复核授权部门成员；`view_all` 不自动获得写权限。
7. 通配管理员可以调用动作，但后续服务层职责分离检查仍生效。
8. 基础 worker 角色可以打开绩效页面并查看本人；旧广域查看角色迁移后不能读取他人数据。
9. 只有 `users:admin` 可以替换用户的部门范围；范围配置不能同时授予绩效查看或复核动作权限。

**实现**

1. 扩展后端权限目录及标签，配置必要的页面权限推导，不为旧敏感权限添加兼容蕴含。
2. 把公用动作标签 `view_self`、`view_all`、`prepare`、`approve` 改为资源中性的“查看本人、查看全部、制单、批准”，避免绩效权限被显示成工资权限；工资模块名称仍由资源标签提供。
3. `PerformanceAuthorizationService` 返回明确 scope 对象：`self_user_id`、`department_ids` 或 `all`。
4. 部门授权关系只通过专用仓储读取；空部门列表必须失败关闭，不能解释为全局。
5. 通过 `python3 scripts/export_permission_catalog.py` 更新前端回退目录。
6. 权限服务只负责授权决策，不拼接业务 SQL；仓储接收规范 scope 并在分页前应用。
7. 提供管理员部门范围 GET/PUT 接口；PUT 在事务中整体替换范围、校验部门存在并写安全审计日志。

**验证**

```bash
pytest -q tests/test_permission_catalog_contracts.py tests/test_performance_permissions.py
python3 scripts/export_permission_catalog.py --check
```

**提交**

```text
feat:scope performance access by employee and department
```

## 任务 5：实现规则和岗位目标版本服务

**文件**

- 新增：`modules/repositories/performance_configuration_repository.py`
- 新增：`modules/services/performance_configuration_service.py`
- 新增：`modules/routes/performance_configuration.py`
- 修改：`modules/routes/registry.py`
- 新增：`tests/test_performance_configuration.py`

**先写测试**

1. 草稿规则可编辑；发布后权重、生效月份和阈值不可修改或删除。
2. 首个 V2 规则的五维权重合计 100，并保留当前阈值和扣分参数。
3. 岗位目标要求目标产量大于零、最低有效报工日大于零、生效月份合法。
4. 同岗位已批准目标版本的生效区间不能重叠。
5. 目标被评分引用后不能修改、退休生效区间或删除。
6. 给定岗位和生产月只能返回一个已批准目标；缺少目标返回明确异常，不回退当前值。
7. 规则发布、目标批准均保存操作人和时间，并使用行版本防止并发覆盖。
8. 路由权限分别要求 `performance:prepare` 和 `performance:approve`。

**实现**

1. 仓储集中实现草稿新增、更新、发布、批准、区间查询和引用检查。
2. 服务层验证权重、阈值、月份区间和并发版本。
3. 路由提供规格中的规则版本和岗位目标版本 GET/POST 命令，不暴露任意字段更新。
4. 把新路由模块注册到 `modules/routes/registry.py`。

**验证**

```bash
pytest -q tests/test_performance_configuration.py tests/test_permission_catalog_contracts.py
```

**提交**

```text
feat:version performance rules and position targets
```

## 任务 6：建立规范质量事件和来源映射

**文件**

- 新增：`modules/repositories/performance_fact_repository.py`
- 新增：`modules/services/performance_quality_event_service.py`
- 修改：`modules/services/work_report_writer.py`
- 修改：`modules/repositories/scan_repository.py`
- 修改：`modules/services/rework_service.py`
- 修改：`modules/repositories/rework_repository.py`
- 修改：`modules/services/quality_service.py`
- 修改：`modules/services/process_quality_evaluation_service.py`
- 修改：`tests/test_architecture_imports.py`
- 新增：`tests/test_performance_quality_events.py`
- 修改：`tests/test_scan_flow.py`
- 修改：`tests/test_rework_service.py`
- 修改：`tests/test_process_quality_evaluation.py`
- 修改：`tests/test_quality_management.py`

**先写测试**

1. 同一报废或返工业务动作产生一个规范质量事件，相关来源行都映射到该事件。
2. `rework_records.source_ncr_id` 指向同一不合格处置时复用规范事件，不重复创建。
3. 单独质检失败和工序质量评价各自保留稳定来源 ID。
4. 同一 `(source_type, source_id)` 只能映射一次；重试返回原事件。
5. 同一事件被多个来源引用时，绩效质量事实只保留一次数量。
6. 历史候选仅因订单、工序、员工、数量或相近时间相似时创建 `ambiguous_quality_source` 异常，不自动合并。
7. 规范事件或来源映射写入失败时，原业务写入同事务回滚。

**实现**

1. `PerformanceQualityEventService` 接受明确业务关联或源主键，创建规范事件并幂等登记来源。
2. 在报废、返工和已知 NCR 派生路径中传递同一规范事件 ID；不在绩效读取阶段按文本相似度临时去重。
3. `QualityService` 和 `ProcessQualityEvaluationService` 在原写入事务内，以稳定业务主键创建事件；存在明确 `target_work_record_id` 或 `source_ncr_id` 时登记关联。
4. `PerformanceFactRepository` 提供规范事件及所有来源查询，为下一任务的事实采集使用。
5. 更新架构约束：V2 绩效只能读取规范质量事实和权威工序质量评价，不得重新依赖 `process_handoff_reviews` 或在服务层嵌入 SQL。

**验证**

```bash
pytest -q tests/test_performance_quality_events.py tests/test_scan_flow.py tests/test_rework_service.py tests/test_process_quality_evaluation.py tests/test_quality_management.py
```

**提交**

```text
feat:canonicalize performance quality events
```

## 任务 7：实现 07:00 来源事实采集与输入摘要

**文件**

- 新增：`modules/services/performance_fact_collector.py`
- 修改：`modules/repositories/performance_fact_repository.py`
- 新增：`tests/test_performance_fact_collector.py`
- 修改：`tests/test_performance_contracts.py`

**先写测试**

1. 所有来源查询使用 `period_start <= business_at < period_end`，不使用 `LIKE 'YYYY-MM%'` 或自然日 `DATE()`。
2. 月初 06:59 的报工和质量评价进入上月，07:00 进入本月。
3. 参与人员集合包含生产月有效任职人员和有有效来源事实的离职人员，不只查询当前 active worker。
4. 报工、工时、质量评价、工序交接和计划状态都保存来源主键、业务时间和内容摘要。
5. 规范质量事件多来源只生成一条质量事实；未确认歧义生成异常且不进入合格指标。
6. 缺历史岗位关系生成岗位异常，不使用当前岗位。
7. 相同截止时间和相同源数据产生相同排序、规范 JSON 和输入 SHA-256。
8. 事实写入后不能修改；源数据后来变化不改变已保存事实。

**实现**

1. 使用 `reporting_month_bounds` 计算生产月，分别读取各来源的权威业务时间字段。
2. 在 Python 中按 07:00 生产日计算有效报工日，避免仓储继续用 `DATE(created_at)`。
3. 通过任职历史确定岗位与部门；把员工、工号、岗位、部门、订单、产品和工序名称固化到事实。
4. 对所有事实按稳定键排序后生成摘要，再一次性写入批次事实和异常。
5. 将旧 `PerformanceRepository.worker_month_metrics` 标记为 Legacy 专用，不再供 V2 调用。

**验证**

```bash
pytest -q tests/test_performance_fact_collector.py tests/test_performance_contracts.py
```

**提交**

```text
feat:capture immutable performance source facts
```

## 任务 8：生成幂等的绩效批次和员工修订版

**文件**

- 新增：`modules/repositories/performance_ledger_repository.py`
- 新增：`modules/services/performance_ledger_service.py`
- 新增：`tests/test_performance_ledger.py`

**先写测试**

1. 同一幂等键和相同月份返回原批次；同一键用于不同月份返回 409 冲突。
2. 新月份从 V1 开始；已有 Legacy V1 的月份下一版本严格为 V2。
3. 批次固定规则版本、07:00 区间、截止时间、输入摘要、制单人和修订原因。
4. 每名员工生成首个评分修订版；合格行绑定目标，数据不足行分数、等级和排名为空。
5. 同岗位合格人数少于 3 人不排名；3 人以上的排名修订使用同一计算时间和排名摘要。
6. 缺目标、岗位不明和来源歧义进入异常；确认数据不足后允许批次继续，但不能形成评分。
7. 生成中任一员工失败时批次、事实、异常和评分全部回滚。
8. 批次创建后源数据变化能够被摘要比较检测，不静默覆盖草稿。

**实现**

1. `PerformanceLedgerRepository` 只处理批次、评分修订、复核、异常和事件持久化。
2. `PerformanceLedgerService.create_batch` 使用 `BEGIN IMMEDIATE`、幂等键和显式 actor 信息创建批次。
3. 调用事实采集器和纯评分策略，先在内存完成岗位组评分及排名，再追加数据库修订版。
4. 返回批次、合格人数、数据不足人数、异常数量、目标缺失数量和输入摘要。
5. 不写 Legacy 表，也不把草稿作为普通员工正式结果。

**验证**

```bash
pytest -q tests/test_performance_ledger.py tests/test_performance_scoring_policy.py tests/test_performance_fact_collector.py
```

**提交**

```text
feat:generate versioned performance batches
```

## 任务 9：实现主管复核与岗位排名原子重算

**文件**

- 修改：`modules/services/performance_ledger_service.py`
- 修改：`modules/repositories/performance_ledger_repository.py`
- 新增：`tests/test_performance_review_workflow.py`

**先写测试**

1. 只有 `supervisor_review` 状态、授权部门内的员工可以保存复核。
2. 纪律扣分、改进调整或主管评议扣分缺原因时拒绝保存。
3. 保存时追加 `performance_reviews_v2` 和被复核员工评分修订版，不更新旧修订。
4. 被复核员工分数改变后，同岗位所有名次受影响人员都在同一事务追加修订版。
5. 新岗位排名使用同一计算时间、同一排名输入摘要，不混合历史计算时间。
6. 强制评分失败时复核和所有排名修订均回滚。
7. 旧 `row_version` 返回 409，不能覆盖他人刚保存的复核。
8. 相同幂等键重试不重复追加复核或评分修订。

**实现**

1. 服务层加载批次当前事实、目标、规则和员工最新修订，不重新读取变化中的业务源表。
2. 在单一事务追加复核，重算员工分数，再重算完整岗位组排名。
3. 仅对分数、等级或排名发生变化的人员追加新修订，但所有新修订共享计算批次标识。
4. 更新批次 `row_version` 并追加 `supervisor_review_saved` 事件。

**验证**

```bash
pytest -q tests/test_performance_review_workflow.py tests/test_performance_ledger.py
```

**提交**

```text
feat:recalculate performance reviews atomically
```

## 任务 10：实现批次提交、双人批准和版本取代

**文件**

- 修改：`modules/services/performance_ledger_service.py`
- 修改：`modules/repositories/performance_ledger_repository.py`
- 新增：`tests/test_performance_batch_workflow.py`

**先写测试**

1. `draft -> supervisor_review -> approval_pending -> approved -> superseded` 合法，其余跳转失败。
2. `supervisor_review -> draft`、`approval_pending -> supervisor_review` 退回必须有原因。
3. `draft/supervisor_review -> cancelled` 必须有原因，取消后不可写入。
4. 未确认异常、合格评分缺目标、复核不完整或输入摘要漂移时不能提交批准。
5. 输入漂移时旧草稿取消，并以新版本重新采集；不能在原事实集合上覆盖刷新。
6. 制单人与批准人相同，即使有 `*` 权限也不能批准。
7. 批准 V3 时在一个事务内把 V2 设为 `superseded` 并使 V3 成为唯一正式版本。
8. 批准、退回、取消和取代事件不可变且可按幂等键重试。
9. 已批准批次不能修改事实、复核、评分、规则或目标引用。

**实现**

1. 为完整性检查建立单一服务方法，返回结构化阻断原因，不在各路由重复实现。
2. 所有转换校验 actor、`row_version`、当前状态和职责分离。
3. 批准事务先锁定旧正式版本，再切换新版本，避免同月存在两个正式结果。
4. 修订命令复制批准版本的身份和原因，但重新采集事实、重新复核、重新批准。
5. 比较服务按员工输出 V1/V2 或 V2/V3 的资格、五维、总分、等级、排名和原因差异。

**验证**

```bash
pytest -q tests/test_performance_batch_workflow.py tests/test_performance_review_workflow.py
```

**提交**

```text
feat:approve and supersede performance revisions
```

## 任务 11：实现证据化改进计划状态机

**文件**

- 新增：`modules/repositories/performance_improvement_repository.py`
- 新增：`modules/services/performance_improvement_service.py`
- 新增：`modules/routes/performance_plans.py`
- 修改：`modules/routes/registry.py`
- 新增：`tests/test_performance_improvement_workflow.py`

**先写测试**

1. 仅允许 `draft -> active -> reassessment_pending -> closed`、失败复评回到 `active`，以及带原因取消。
2. 激活前必须有依据、可衡量目标、措施、负责人和截止日期。
3. 申请复评前必须存在证据；证据记录不可更新或删除。
4. 复评人不能是计划负责人；通配管理员也不能绕过。
5. 通过复评关闭计划；失败复评增加轮次并要求新措施和新截止日期。
6. 直接从草稿关闭、任意状态字符串和重复复评均返回冲突。
7. 绩效事实采集按 `source_cutoff_at` 读取计划事件快照，后续关闭不修改已批准月份。
8. 旧 PUT 任意更新接口返回 Legacy 只读错误。

**实现**

1. 仓储只提供追加计划事件、证据和复评记录，以及受行版本保护的状态指针转换。
2. 服务层集中验证转换、必填字段、职责分离和证据引用。
3. 路由分别提供计划创建、状态转换、证据上传元数据和复评命令。
4. 所有事件保存 actor、前后状态、轮次、原因和时间。

**验证**

```bash
pytest -q tests/test_performance_improvement_workflow.py tests/test_performance_fact_collector.py
```

**提交**

```text
feat:enforce performance improvement reassessment
```

## 任务 12：切换版本化 API 并保留 Legacy 查询兼容

**文件**

- 修改：`modules/config.py`
- 修改：`modules/routes/performance.py`
- 新增：`modules/routes/performance_ledger.py`
- 修改：`modules/routes/registry.py`
- 修改：`modules/services/performance_service.py`
- 修改：`modules/repositories/performance_repository.py`
- 修改：`tests/test_performance_contracts.py`
- 新增：`tests/test_performance_api.py`

**先写测试**

1. `/api/performance/scores` 默认读取指定月份唯一正式批次，返回版本、来源、状态、07:00 区间和资格字段。
2. 没有已批准 V2 或查询切换关闭时返回 Legacy V1，并明确 `result_source=legacy_v1`。
3. 数据不足行不返回红黄绿等级或排名，汇总平均分和等级数量排除该行。
4. `/api/performance/generate` 和旧 `/reviews` 写接口返回 409 `LEGACY_LEDGER_READ_ONLY`。
5. 批次准备、复核、提交、批准、退回、取消、异常和比较接口返回新 `row_version` 和事件 ID。
6. GET 列表在分页前应用本人、部门或全局 scope；直接传其他员工、部门、批次或计划 ID 返回 403/404。
7. 错误码稳定映射：输入 400、权限 403、状态/并发/只读 409。
8. `PERFORMANCE_LEDGER_V2_QUERY_ENABLED=false` 时管理员仍可影子计算，但普通正式查询保持 Legacy。

**实现**

1. `performance.py` 只保留 overview、正式结果、规则展示和旧写接口失败关闭。
2. `performance_ledger.py` 承载版本化批次命令，调用授权服务和台账服务，不直接执行 SQL。
3. `PerformanceService` 改为正式结果查询门面；删除生成和覆盖式复核调用链。
4. Legacy 仓储查询按原评分快照展示，不能再次关联当前岗位改变历史语义。
5. 配置开关默认关闭；批准 V2 不自动切换普通用户查询。

**验证**

```bash
pytest -q tests/test_performance_contracts.py tests/test_performance_api.py tests/test_performance_permissions.py
```

**提交**

```text
feat:expose versioned performance workflow api
```

## 任务 13：重构绩效页面为正式结果与工作流视图

**文件**

- 修改：`frontend/src/lib/api/performance.js`
- 修改：`frontend/src/views/PerformancePage.vue`
- 修改：`frontend/src/composables/usePerformancePageData.js`
- 修改：`frontend/src/composables/usePerformanceModals.js`
- 修改：`frontend/src/views/performance/PerformanceScoreTable.vue`
- 修改：`frontend/src/views/performance/PerformanceDetailModal.vue`
- 修改：`frontend/src/views/performance/PerformanceReviewModal.vue`
- 修改：`frontend/src/views/performance/ImprovementPlanTable.vue`
- 修改：`frontend/src/views/performance/PerformancePlanModal.vue`
- 新增：`frontend/src/views/performance/PerformanceBatchPanel.vue`
- 新增：`frontend/src/views/performance/PerformanceComparisonPanel.vue`
- 新增：`frontend/src/views/performance/PerformanceExceptionPanel.vue`
- 新增：`frontend/src/views/performance/PerformanceTargetPanel.vue`
- 新增：`frontend/src/views/performance/PerformanceScopePanel.vue`
- 新增：`frontend/tests/unit/PerformancePage.spec.js`
- 修改：`frontend/tests/e2e/admin-pages.spec.js`

**先写测试**

1. 正式结果显示版本、Legacy/V2 来源、生产月区间和批次状态。
2. 数据不足显示独立状态，不显示等级色块或排名，不计入汇总。
3. 页面不再显示“按同岗位当月最高产量”或“生成/重算本月评分”。
4. 本人、部门查看者、主管复核者、制单人和批准人看到的标签和动作符合权限。
5. 制单、复核、提交、退回和批准命令携带幂等键或 `row_version`，409 时刷新并显示冲突。
6. 版本对比按原因分类展示；异常面板不能一键相似度合并。
7. 岗位目标发布前显示草稿，批准后显示生效区间和只读状态。
8. 改进计划必须经过证据和复评流程，不能从列表直接“已完成复评”关闭。
9. 390×844、768×1024 和 1440×900 视口无按钮、筛选器、表格和弹窗重叠。
10. 只有 `users:admin` 显示部门授权视图；保存范围不会改变该用户的角色或绩效动作权限。

**实现**

1. API 门面增加规则、目标、批次、比较、异常、转换、证据和复评调用。
2. 页面采用正式结果、版本对比、批次审批、数据异常、岗位目标、改进计划六个业务视图，并为管理员增加部门授权视图。
3. 复用现有卡片、表格、弹窗、按钮和权限样式，不引入新的 UI 框架。
4. 使用操作权限决定按钮，使用接口响应的 `allowed_actions` 再限制当前状态动作。
5. E2E 夹具改为先配置目标和生成 V2 草稿，不再调用旧生成接口。

**验证**

```bash
npm run test:unit -- --run frontend/tests/unit/PerformancePage.spec.js
npx playwright test frontend/tests/e2e/admin-pages.spec.js --grep "performance"
npm run check:architecture
npm run build
```

**提交**

```text
feat:operate versioned performance ledger in ui
```

## 任务 14：实现历史 V2 预检、差异清单和受控生成

**文件**

- 新增：`modules/repositories/performance_history_migration_repository.py`
- 新增：`modules/services/performance_history_migration_service.py`
- 新增：`scripts/migrate_performance_history.py`
- 新增：`tests/test_performance_history_migration.py`

**先写测试**

1. 预检按全部历史月份输出 Legacy 行数、曾覆盖行、岗位缺失、跨月报工、跨月质量、质量歧义和目标缺失数量。
2. 已知审计基线能够识别 64 条不可恢复旧修订、30 条岗位快照缺失、5 条跨月报工和 11 条跨月质量评价。
3. 期望数量不一致时 `--apply` 前失败，不写任何 V2 数据。
4. 清单按稳定主键排序并生成 SHA-256；源数据变化后旧清单不能复用。
5. 无人工岗位确认时不读取当前岗位，相关员工在 V2 中为数据不足。
6. 无人工质量来源确认时不自动相似合并，相关记录保持异常。
7. 相同月份和清单重复执行保持幂等，不重复生成批次、事实、异常或事件。
8. 应用只生成草稿或主管复核状态 V2，不自动批准、不切换正式查询、不写工资。

**实现**

1. 脚本默认只执行 `preflight`；`--apply` 必须提供制单人 ID、期望审计计数和明确月份范围。
2. 为每月保存不可变迁移 manifest、逐条分类、输入摘要和关联 V2 批次。
3. 复用台账服务生成 V2，不另写一套评分 SQL。
4. 输出 Legacy/V2 逐人差异，分类为月份边界、岗位目标、质量去重、参评资格、主管复核和规则变化。
5. 脚本返回结构化 JSON，失败时事务回滚并以非零状态退出。

**验证**

```bash
pytest -q tests/test_performance_history_migration.py tests/test_performance_ledger.py
python3 scripts/migrate_performance_history.py --help
```

**提交**

```text
feat:migrate legacy performance into reviewed revisions
```

## 任务 15：全量回归、生产迁移和真实验收

**文件**

- 新增：`docs/performance-management-repair-release-evidence-2026-08-04.md`

**实施前保护**

1. 确认实施分支只包含本方案提交，记录 `git status`、HEAD 和相对生产提交的差异。
2. 在生产数据库副本执行 V55 -> V56，保存 `PRAGMA integrity_check`、表数量、Legacy 数量和迁移耗时。
3. 在项目目录外创建生产数据库备份，记录路径、字节数和 SHA-256；验证备份可打开且完整性为 `ok`。
4. 导出当前绩效权限影响清单和角色用户数量，完成本人、部门、制单、批准和计划复评人员的显式授权表。
5. 准备应用提交和前端静态资源回滚点；数据库迁移只前进，不设计破坏性降级。

**完整验证**

```bash
pytest -q
npm run check:architecture
npm run test:unit
npm run test:e2e
npm run build
```

全部命令必须通过。环境性失败必须有独立证据证明与本次变更无关，不能用跳过测试代替修复。

**发布顺序**

1. 在 `codex-8:/home/dubin/qr-system` 确认干净工作区和待部署提交，并运行 `bash scripts/deploy.sh --check-only`。
2. 保持 `PERFORMANCE_LEDGER_V2_QUERY_ENABLED=false`，执行 `bash deploy.sh`；脚本先测试、备份，再迁移 V56、构建前端和重载服务。
3. 验证 `PRAGMA user_version = 56`、Legacy 只读触发器、新表和索引存在，服务健康检查为 `ok`。
4. 使用本人、部门、制单、批准四类账号验证权限矩阵；确认质检员和仓库管理员不能查看全局绩效。
5. 执行历史迁移 preflight，核对 64、30、5、11 四组已知审计证据和实际生产清单摘要。
6. 由业务负责人录入并批准岗位目标、最低有效报工日和首个 V2 规则版本。
7. 执行历史迁移 `--apply` 生成影子 V2；处理所有人工岗位映射和质量来源异常。
8. 导出 V1/V2 对账，确认提交审批时未确认异常为 0，数据不足原因完整。
9. 部门主管完成复核；制单人提交；不同批准人批准整月 V2。
10. 打开 V2 正式查询开关并重启服务，执行正式结果和 Legacy 回退冒烟测试。
11. 将提交号、备份路径与摘要、迁移结果、权限矩阵、历史差异、审批事件、测试输出和健康检查写入发布证据文档。

**真实验收**

1. 零产量员工没有分数、等级和排名。
2. 有目标员工的产量分按目标计算，单人岗位不因自身最高产量自动满分且不发布排名。
3. 月初 06:59 与 07:00 两侧的报工、质量和计划状态归属正确。
4. 同一质量事件多个来源只扣分一次；人工未确认来源不能进入合格评分。
5. 主管复核改变一人分数时，同岗位相关排名修订时间和摘要一致。
6. 制单人不能批准本人批次；旧 `row_version` 请求返回 409。
7. 本人、部门和全局用户均不能通过 URL 参数或对象 ID 越权。
8. 改进计划不能跳状态，失败复评回到执行中并保存新措施。
9. V2 批准后 V1 只读可查；创建 V3 能保留并取代 V2。
10. 绩效相关操作前后工资台账行数和金额摘要完全一致。

**观察期**

- 连续运行两个完整生产月，每月保存来源摘要、异常数、V1/V2 或 V2/V3 差异、权限拒绝和计算耗时证据。
- 观察期内不创建绩效来源工资调整；绩效模块写入工资台账数量必须为 0。
- 两个月完成后另行设计和批准工资联动，不把该动作包含在本计划完成条件内。

**回滚**

- 关闭 V2 正式查询开关并切回 Legacy 查询。
- 回滚应用和静态资源到发布前提交；V56 表、事实、事件和迁移清单保留。
- Legacy 数据库只读触发器继续生效，旧生成和覆盖复核接口失败关闭。
- 只有迁移破坏数据库完整性时才停止服务并从外置备份恢复；不得在运行中反向删表。

**提交**

```text
chore:record performance ledger release evidence
```

## 完成标准

1. 已批准设计中的 12 项验收标准都有自动化或生产证据。
2. 新正式评分不再写入或覆盖 Legacy 表。
3. 每条合格正式评分都能追溯规则、岗位目标、来源事实、复核和批准。
4. 数据不足不会被解释成低绩效或参与排名。
5. 权限、职责分离、并发和不可变约束在服务层与数据库层同时生效。
6. 历史 64、30、5、11 四组审计证据得到明确迁移或异常处理结果。
7. 后端完整测试、前端单元测试、关键浏览器测试、构建和生产健康检查全部通过。
8. 两个完整生产月观察期内绩效模块没有写入工资台账。
