# 工序管理版本化台账修复设计

- 日期：2026-08-11
- 状态：已确认
- 目标系统：`192.168.1.8:/home/dubin/qr-system`
- 生产基线：数据库 v059，部署提交 `e169a68a`
- 目标架构：完整版本化台账
- 发布策略：兼容层渐进迁移

## 1. 背景

工序管理模块已具备权限校验、分类校验、路线应用、停用工序限制和删除引用保护，但当前模型仍允许直接修改已被业务使用的工序名称、分类和排序。日报、工资、订单、质量和追溯查询中存在大量对当前 `processes.name` 的实时关联，因此修改主数据会改变历史记录的展示语义。

工艺路线虽然对订单和产品引用进行了锁定，但锁定范围没有覆盖工价版本、标准工时和质量配置。2026-08-09 的生产只读检查发现，12 条路线被工价版本引用，却仍被当前页面判断为“未锁定”。

当前工序引用注册表还遗漏：

- `payroll_detail_lines.process_id`
- `performance_quality_events.process_id`
- `performance_source_facts.process_id`
- `route_price_versions.process_id`

因此本次修复不再继续堆叠直接更新和补丁式删除保护，而是建立稳定身份、不可变版本、精确事实绑定和兼容迁移机制。

## 2. 已确认的核心决策

### 2.1 工序身份

- 保留稳定的 `process_id`。
- 已使用工序的名称、分类、描述和默认排序变化必须生成工序修订版。
- 历史业务绑定原工序版本，新业务使用最新已发布版本。
- 停用和退休不改变历史事实。

### 2.2 路线身份

- 保留稳定的 `process_route_id`。
- 路线名称、分类、节点顺序和审批要求变化必须生成路线修订版。
- 已被订单、产品或工价引用的路线版本永久只读。
- 历史订单绑定原路线版本，新订单使用最新已发布版本。
- 工价版本绑定具体路线版本和工序版本。

### 2.3 实施方式

- 方案二“完整版本化台账”作为最终目标架构。
- 方案三“兼容层渐进迁移”作为生产发布策略。
- 不通过名称相似度自动修复历史映射。
- 没有历史证据时，只建立 Legacy V1 基线，不伪造更早版本。

## 3. 目标与非目标

### 3.1 目标

1. 工序和路线拥有稳定、不可变的业务身份。
2. 已发布版本不可修改、不可删除，只能被新修订版取代。
3. 订单、报工、工价、工资、绩效和质量事实可以精确还原当时使用的工序和路线版本。
4. 影响检查覆盖所有工序和路线引用。
5. 版本发布采用双人复核、乐观锁和原子切换。
6. Legacy 查询继续兼容，Legacy 写入在正式切换后被阻断。
7. 迁移可预检、可演练、可校验，并保留明确回滚边界。

### 3.2 非目标

本次不重做：

- 报工顺序计算算法；
- 工资金额计算规则；
- 绩效评分规则；
- 产品自身的版本模型；
- 工序质量评价的评分流程。

这些模块只调整对工序和路线的引用方式。

## 4. 总体架构

### 4.1 稳定根实体

`processes` 作为工序身份根，保存：

- `id`
- `process_code`
- `lifecycle_status`
- `current_effective_version_id`
- `row_version`
- `created_by`
- `created_at`

`process_routes` 作为路线身份根，保存：

- `id`
- `route_code`
- `lifecycle_status`
- `current_effective_version_id`
- `row_version`
- `created_by`
- `created_at`

根实体禁止物理删除。`retired` 只表示不能进入新业务，历史版本和事实继续可读。

`current_effective_version_id` 指向最后一次生效的版本。根实体退休后，该指针仍保留并指向状态为 `retired` 的最后版本，供历史查询使用；重新启用必须先发布新版本，再原子切换该指针。

兼容期内，根表原有名称、分类、描述、排序和状态字段暂时保留，作为 Legacy 投影字段，由版本服务维护；业务代码不得直接写入。

### 4.2 不可变版本实体

新增：

- `process_versions`
- `process_route_versions`
- `process_route_version_items`
- `process_version_events`
- `process_route_version_events`
- `master_data_release_batches`

版本服务负责草稿、提交、批准、驳回、发布、取代和退休。仓储层只提供事务内的精确读写能力，不包含状态转换策略。

### 4.3 服务边界

- `ProcessVersionService`：工序版本工作流和发布原子性。
- `RouteVersionService`：路线版本、节点和分类一致性。
- `MasterDataImpactService`：统一计算工序与路线引用。
- `LegacyProcessCompatibilityService`：为旧查询提供当前版本扁平投影。
- `MasterDataReferenceCatalog`：工序和路线引用的唯一登记来源。
- `MasterDataReleaseService`：协调工序版本、受影响路线版本和工价版本的成组发布。

订单、工资、绩效、质量等模块只能通过上述服务解析版本，不得直接推断“当前名称就是历史名称”。

### 4.4 身份边界

只有现实中的同一项制造工序或同一条工艺路线发生修订时，才沿用稳定根 ID。仅改名、纠正分类、调整描述或调整同一路线的节点属于修订。

如果制造含义、技能要求或工艺目的已经改变，应创建新的工序或路线根实体，不能借版本修订复用旧身份。工序分类变更属于高影响纠正，发布前必须复核岗位和员工授权是否继续适用。

## 5. 数据模型

### 5.1 `process_versions`

主要字段：

```text
id
process_id
version
process_code_snapshot
name
category
description
seq_order
status
effective_from
effective_to
supersedes_version_id
revision_reason
legacy_baseline
prior_revision_unavailable
created_by
approved_by
created_at
published_at
row_version
```

状态：

```text
draft
pending_approval
published
superseded
rejected
cancelled
retired
```

约束：

- `UNIQUE(process_id, version)`。
- 每个 `process_id` 最多一个 `published` 版本。
- `published`、`superseded`、`retired` 禁止内容更新和删除。
- `process_id`、`version` 和稳定编码快照不可改变。
- 本次不支持未来定时发布；`effective_from` 在实际发布时写入。

### 5.2 `process_route_versions`

主要字段：

```text
id
process_route_id
version
name
category
description
status
effective_from
effective_to
supersedes_version_id
revision_reason
legacy_baseline
prior_revision_unavailable
created_by
approved_by
created_at
published_at
row_version
```

约束与工序版本一致，同一路线根最多一个当前 `published` 版本。

### 5.3 `process_route_version_items`

主要字段：

```text
id
route_version_id
process_id
process_version_id
seq_order
required_audit
is_required
```

约束：

- `process_version_id` 必须属于对应 `process_id`。
- 路线发布时，节点工序版本必须已经发布。
- 同一路线版本不得重复使用同一工序。
- 路线版本内节点顺序必须唯一。
- 路线分类必须与全部节点工序版本分类一致。
- 路线版本发布后，节点禁止增加、删除、换序或修改审批要求。

### 5.4 版本事件

工序和路线分别使用不可变事件表，记录：

```text
entity_id
version_id
event_type
actor_id
actor_name
actor_role
reason
impact_digest
idempotency_key
from_status
to_status
created_at
```

事件禁止更新和删除。

### 5.5 生命周期请求

退休和重新启用属于根实体生命周期命令，不能通过修改版本状态直接完成。分别使用工序和路线生命周期请求记录：

```text
entity_id
action                 retire / reactivate
status                 pending / approved / rejected
reason
requested_by
approved_by
row_version
created_at
resolved_at
```

请求人与批准人必须不同。批准退休后，根实体变为 `retired`，当前版本保持历史可读；批准重新启用时必须已有可发布的新修订版。

### 5.6 `master_data_release_batches`

用于协调相互依赖的工序、路线和工价版本：

```text
id
release_no
status                 draft / pending_approval / published / rejected / cancelled
revision_reason
impact_digest
created_by
approved_by
row_version
created_at
published_at
```

批次明细保存待发布的工序版本、路线版本和工价版本。批次发布时必须保证全部依赖已经满足，并在同一事务中切换所有当前版本指针。

## 6. 引用绑定规则

| 数据类型 | 绑定对象 |
|---|---|
| 岗位工序、员工工序授权 | 稳定 `process_id` |
| 产品默认路线 | 稳定 `process_route_id` |
| 订单 | 精确 `route_version_id` |
| 订单工序 | 精确 `process_version_id` |
| 报工、质量、返工、报废 | 精确工序版本和文本快照 |
| 工价版本 | `route_version_id + process_version_id` |
| 工资、绩效来源事实 | 精确版本 ID 和文本快照 |
| 历史报表 | 优先读取事实快照 |

产品只保存默认路线根。创建订单时解析当时的当前已发布路线版本，并把精确版本写入订单。以后路线发布新版本，不自动切换既有订单。

新写入事实至少保存：

```text
process_id
process_version_id
process_code_snapshot
process_name_snapshot
process_category_snapshot
route_id
route_version_id
route_name_snapshot
```

## 7. 工价一致性

`route_price_versions` 增加：

- `route_version_id`
- `process_version_id`

新工价不得只绑定裸 `route_id + process_id`。发布前校验：

1. 路线版本已发布；
2. 工序版本已发布；
3. 工序版本属于该路线版本；
4. 生效区间不存在重叠；
5. 已确认工资台账引用的工价版本不可修改。

新路线版本不会自动继承旧工价。发布前必须完成工价影响处理：需要计件工价的节点应绑定新工价版本，或者记录明确的“不适用计件工价”处置结果。

### 7.1 跨版本发布一致性

路线版本固定绑定工序版本，因此发布工序新版本时不得静默改变现有路线。若当前生产路线引用旧工序版本，必须采用以下一种处理方式：

1. 在同一个发布批次中包含使用新工序版本的路线修订版和对应工价版本；或
2. 对指定路线记录经过批准的“继续使用旧工序版本”例外。

没有路线修订版或批准例外时，工序新版本不能成为新业务的当前有效版本。这样既保证历史路线不可变，也保证新订单不会无意继续使用已经被取代的工序版本。

## 8. 不可变和并发约束

数据库触发器和服务层共同保证：

- 禁止修改、删除已发布版本；
- 禁止删除任何已引用版本；
- 禁止绕过服务修改根实体当前版本指针；
- 禁止未发布工序版本进入正式路线；
- 禁止同一根实体存在两个当前发布版本；
- 禁止同一用户提交并批准同一版本；
- 禁止使用过期 `row_version` 覆盖新操作；
- 禁止 Legacy 代码直接写兼容投影字段。

发布采用单事务：

1. 读取并锁定根实体当前状态；
2. 校验草稿、审批人、影响摘要和 `row_version`；
3. 将旧发布版本改为 `superseded`；
4. 将新版本改为 `published`；
5. 更新根实体当前版本指针和兼容投影；
6. 写入版本事件；
7. 提交事务。

任一步失败时全部回滚。

## 9. 操作流程

### 9.1 新建

新建工序或路线时创建稳定根实体和 V1 草稿。草稿批准发布前不能用于新业务。

### 9.2 创建修订版

从当前已发布版本复制内容，生成下一版本草稿。修订原因必填。旧版本在新版本发布前继续有效。

### 9.3 影响检查

提交审批前计算：

- 订单、产品、岗位和员工授权；
- 报工、工资、绩效和质量事实；
- 工价版本和标准工时；
- 待重新确认的工价映射；
- 新版本发布后将影响的新业务入口。

影响摘要保存哈希。批准时重新计算；摘要变化则退回重新提交。

### 9.4 退休

退休采用独立双人审批请求。退休后不进入新业务选择列表，但历史订单和已开始订单仍按原版本流转。

## 10. API 设计

工序版本：

```text
GET  /api/processes/<id>/versions
POST /api/processes/<id>/revisions
POST /api/process-versions/<id>/submit
POST /api/process-versions/<id>/approve
POST /api/process-versions/<id>/reject
POST /api/processes/<id>/retirement-requests
POST /api/process-retirement-requests/<id>/approve
POST /api/processes/<id>/reactivation-requests
POST /api/process-reactivation-requests/<id>/approve
```

路线版本：

```text
GET  /api/process-routes/<id>/versions
POST /api/process-routes/<id>/revisions
POST /api/process-route-versions/<id>/submit
POST /api/process-route-versions/<id>/approve
POST /api/process-route-versions/<id>/reject
POST /api/process-routes/<id>/retirement-requests
POST /api/process-route-retirement-requests/<id>/approve
POST /api/process-routes/<id>/reactivation-requests
POST /api/process-route-reactivation-requests/<id>/approve
```

成组发布：

```text
POST /api/master-data-release-batches
POST /api/master-data-release-batches/<id>/submit
POST /api/master-data-release-batches/<id>/approve
POST /api/master-data-release-batches/<id>/reject
```

所有写命令携带：

```text
row_version
idempotency_key
revision_reason 或 lifecycle_reason
```

Legacy 查询继续返回当前发布版本的扁平数据，并额外返回版本 ID、版本号和状态。V2 正式切换后，旧修改和删除接口返回 `409 LEGACY_MASTER_DATA_WRITE_BLOCKED`。

## 11. 权限和数据范围

工序权限：

```text
process_versions:view
process_versions:create
process_versions:submit
process_versions:approve
process_versions:reject
process_versions:impact
processes:retire
processes:reactivate
```

路线权限：

```text
route_versions:view
route_versions:create
route_versions:submit
route_versions:approve
route_versions:reject
route_versions:impact
process_routes:retire
process_routes:reactivate
```

第一阶段按统一主数据范围管理，不使用个人工序授权限制审批。未来如需分权，只按“结构件/机加工”分类范围扩展。

制单人不能批准本人版本；普通管理员不能依靠旧权限绕过专用审批权限。

## 12. UI/UX

工序与路线页面统一拆分为：

1. 当前版本；
2. 待审批修订；
3. 历史版本；
4. 影响和引用。

页面显示稳定编码、当前版本号、生命周期、版本状态、生效时间、引用数量、待审批状态、修订原因、制单人和批准人。

原“编辑”改为“创建修订版”，原“删除”改为“申请退休”。已发布版本只读。批准页面显示字段差异、节点差异、工价覆盖和影响摘要。

## 13. 错误处理

稳定错误码包括：

```text
PROCESS_VERSION_NOT_FOUND
PROCESS_VERSION_STALE
PROCESS_VERSION_IMMUTABLE
PROCESS_VERSION_ALREADY_PENDING
PROCESS_APPROVAL_SEPARATION_REQUIRED
PROCESS_REFERENCE_CONFLICT
ROUTE_VERSION_NOT_FOUND
ROUTE_VERSION_STALE
ROUTE_VERSION_IMMUTABLE
ROUTE_PROCESS_CATEGORY_MISMATCH
ROUTE_PROCESS_VERSION_INVALID
ROUTE_REFERENCE_CONFLICT
PRICE_VERSION_BINDING_REQUIRED
LEGACY_MASTER_DATA_WRITE_BLOCKED
MIGRATION_MAPPING_REQUIRED
```

错误响应返回中文说明、稳定错误码、结构化详情和建议动作，不暴露 SQLite 异常或堆栈。

## 14. 历史迁移

### 14.1 预检

预检覆盖工序、路线、节点、工价、订单、报工、工资、绩效、质量、标准工时、重复名称、非法状态、分类错配、外键和引用注册表完整性。

无法唯一映射的记录进入异常清单，并阻止正式迁移。

### 14.2 稳定编码

Legacy 编码只依赖原始 ID：

```text
PROC-0001
ROUTE-0001
```

编码生成后永久不可修改。

### 14.3 迁移版本

#### v060：版本化主数据基础

- 扩展根实体；
- 创建版本、事件、生命周期请求和成组发布表；
- 建立索引与不可变触发器；
- 将现有工序和路线初始化为 V1；
- 标记 `legacy_baseline=1`、`prior_revision_unavailable=1`；
- 记录迁移清单和摘要。

#### v061：订单和路线绑定

- 订单增加 `route_version_id`；
- 订单工序增加 `process_version_id`；
- 回填版本 ID 和文本快照；
- 新订单开始双写。

#### v062：工价和工资绑定

- 工价版本增加精确版本字段；
- 回填现有工价；
- 工价解析改用版本匹配；
- 禁止创建只绑定裸根 ID 的新工价。

#### v063：事实与引用保护收口

- 报工、质量、绩效、返工、报废和标准工时补齐版本 ID 与快照；
- 补齐当前遗漏引用；
- 建立完整路线引用注册表；
- 重建删除保护触发器；
- 增加引用目录契约测试。

所有迁移可重复执行，不改变原始数量和金额，不伪造历史修订。

## 15. 生产切换

功能开关：

```text
PROCESS_VERSIONED_QUERY_ENABLED
PROCESS_VERSIONED_WRITE_ENABLED
PROCESS_LEGACY_WRITE_BLOCKED
PROCESS_VERSION_COMPAT_AUDIT_ENABLED
```

切换顺序：

1. V2 表和 V1 基线存在，业务仍使用 Legacy；
2. 开启 V2 查询和双读差异记录；
3. 新业务双写版本字段和兼容字段；
4. 切换新版 UI 与写接口；
5. 阻断 Legacy 写入；
6. 稳定运行后移除旧写路径。

只有双读差异连续为零才进入下一阶段。

正式迁移使用短维护窗口，依次执行：停止写入、备份、备份校验、副本演练、正式迁移、数据核对、服务重载、业务验收和解除维护。

## 16. 回滚边界

V2 正式写入前，可以关闭功能开关并回滚应用代码，新增表和字段保留。

V2 产生正式业务版本后，不允许用迁移前数据库覆盖新数据，也不允许回退到可直接修改 Legacy 主数据的旧代码。故障时关闭新写入、保持 V2 只读，并向前修复。

## 17. 测试策略

### 17.1 迁移测试

- 从纯 v059 迁移；
- 重复执行无重复版本；
- 工序、路线、节点和工价完整映射；
- 数量、金额和摘要保持一致；
- 外键和完整性检查通过；
- 异常进入异常表；
- 失败事务完整回滚。

### 17.2 不可变和并发测试

- 已发布版本无法修改、删除；
- 被引用版本无法删除；
- 未发布工序版本无法进入正式路线；
- 双人审批不可绕过；
- 过期 `row_version` 返回 409；
- Legacy 写接口被阻断；
- 幂等键不会创建重复修订。
- 工序版本不能在缺少路线修订或批准例外时单独切换为当前有效版本。
- 成组发布任一成员失败时，全部版本指针和状态保持原值。

### 17.3 业务场景测试

- 工序 V2 发布后，历史报工仍显示 V1 快照；
- 路线 V2 发布后，历史订单继续使用 V1；
- 新订单使用成组发布后的新路线版本和新工序版本；
- 新工价绑定精确路线和工序版本；
- 退休后不进入新业务选择列表；
- 已开始订单继续按原版本流转。

### 17.4 前端测试

- 当前、待审批和历史版本切换；
- 创建修订、差异展示、影响摘要；
- 提交、批准、驳回和退休；
- 并发冲突刷新；
- 防重复点击；
- Legacy 错误提示；
- 桌面端和移动端基本可用性。

## 18. 验收标准

切换前要求：

```text
工序列表差异             0
路线列表差异             0
订单路线版本缺失         0
订单工序版本缺失         0
工价版本映射缺失         0
新增报工版本缺失         0
工资金额差异             0
绩效来源数量差异         0
质量记录数量差异         0
引用注册表遗漏           0
```

生产正式验收要求：

- 服务 `active/running`；
- 健康接口 `status=ok`；
- 数据库达到最终迁移版本；
- 备份校验成功；
- 后端、前端和关键浏览器流程通过；
- 真实制单人完成一次修订提交；
- 真实批准人完成一次批准；
- 使用测试路线完成订单创建和报工；
- 历史日报、工资、绩效和质量记录抽样一致；
- Legacy 查询正常，Legacy 写入返回预期 409；
- 24 小时内没有未处理的版本映射异常。

任一强制验收项失败，都不能宣布正式切换完成。

## 19. 实施优先级

1. 版本化根实体和不可变版本表；
2. 完整工序与路线引用目录；
3. 订单和路线版本绑定；
4. 工价和工资版本绑定；
5. 质量、绩效和报工事实快照；
6. 双人审批、权限和审计事件；
7. 新版 UI 和 Legacy 写入阻断；
8. 生产迁移、双读验证和正式切换。

该顺序优先建立数据库不变量，再迁移业务写入和界面，避免新版 UI 上线后底层仍可被旧路径绕过。
