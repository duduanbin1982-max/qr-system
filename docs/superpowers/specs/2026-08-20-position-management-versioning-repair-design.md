# 岗位管理版本化修复设计

- 日期：2026-08-20
- 状态：待书面确认
- 目标系统：`192.168.1.8:/home/dubin/qr-system`
- 生产基线：数据库 v069，部署提交 `f9ed7385`
- 目标架构：稳定岗位身份、不可变岗位修订和精确事实快照
- 发布策略：P0 止损补丁先行，v070 兼容层渐进切换

## 1. 背景

岗位管理当前同时承担岗位主数据、员工默认岗位、可报工工序范围和绩效岗位语义。生产审查确认以下问题：

1. 后端岗位列表返回 `processes`，前端编辑表单读取 `process_ids`。编辑任何字段时，前端会提交空工序数组，后端随后删除全部岗位工序关联。
2. 岗位停用只影响活动岗位列表，不影响 `AccessPolicyService` 解析出的工序范围，停用岗位仍可能授权订单查看和报工。
3. 岗位名称可直接修改，但绩效岗位历史只在员工自身信息变化时生成新快照，后续绩效事实可能继续使用旧岗位名称。
4. 删除影响检查只统计当前员工，没有覆盖活跃会话、绩效目标、岗位历史、绩效事实、评分快照和报工记录。
5. 岗位写入与 `safe_audit_log` 不在同一事务，审计内容也没有记录状态和工序范围前后差异。
6. 前端没有按 `positions:create/edit/delete` 控制按钮和命令，新增与编辑还采用不同的岗位名称校验规则。

生产数据库现有 12 个启用岗位。多数生产岗位已被员工、报工、绩效目标、岗位历史、来源事实和评分快照引用，因此不能通过加强物理删除或继续直接更新来解决问题。

## 2. 方案比较

### 2.1 方案一：只修复字段契约

仅修复 `processes/process_ids`、前端权限和名称 Schema。优点是改动小、可以快速止损；缺点是岗位改名、停用撤权、绩效快照和审计边界仍然不完整。

### 2.2 方案二：一次性替换全部岗位读写

直接上线全新的岗位版本表、API 和 UI，并同时迁移所有引用。优点是最终形态统一；缺点是生产风险集中，岗位权限错误会直接影响车间报工，不适合当前 SQLite 单机生产系统一次切换。

### 2.3 方案三：P0 止损加渐进版本化

先修复破坏性字段契约，再建立稳定根、不可变修订、兼容投影和双读验证，最后分阶段阻断旧写路径。该方案可以立即停止工序关联丢失，又能把生产迁移风险拆分为可验证步骤。

本设计采用方案三。

## 3. 目标与非目标

### 3.1 目标

1. 保留稳定的 `position_id`，不改变员工、会话和历史事实对岗位身份的引用。
2. 岗位名称、描述和可报工工序范围变化生成新修订版。
3. 已发布、已取代和已退休修订版永久只读。
4. 停用岗位不再提供新业务权限，历史事实继续可读。
5. 岗位名称变化后，新绩效事实使用新名称，旧事实保持原快照。
6. 岗位影响检查覆盖全部直接和间接引用。
7. 高影响写入使用双人审批、乐观锁、幂等键和事务内强制审计。
8. Legacy 查询保持兼容，Legacy 写入在验证完成后被阻断。

### 3.2 非目标

本次不修改：

- 工资金额、工价匹配和工资月份规则；
- 绩效评分公式、排名和审批规则；
- 工序和路线版本化模型；
- 员工部门范围和角色权限模型；
- 历史报工、工资或已发布绩效结果的业务含义。

这些模块只补充岗位版本引用或改用统一的岗位有效范围服务。

## 4. 核心业务规则

### 4.1 稳定身份

- `positions.id` 是岗位稳定身份。
- 同一现实岗位的改名、描述调整和工序范围调整属于岗位修订，不创建新根实体。
- 如果职责、技能和组织含义已经变成另一个岗位，应创建新岗位根实体，并通过员工调岗处理，不能复用旧 ID。
- 已被引用的岗位根实体不允许物理删除。

### 4.2 修订与发布

- 新岗位先创建根实体和 V1 草稿，发布前不能分配给员工或进入报工授权。
- 每个岗位最多存在一个草稿或待审批修订版，最多存在一个当前已发布修订版。
- 制单人与批准人必须不同。
- 发布时原子取代旧版本、切换根实体当前版本指针并更新 Legacy 投影。
- 发布后版本内容和工序清单禁止更新或删除。

### 4.3 退休与重新启用

- 岗位不再直接切换 `active/inactive`，退休和重新启用通过独立生命周期申请完成。
- 存在启用员工时禁止批准退休，必须先完成调岗。
- 存在活跃登录会话时禁止批准退休；员工调岗或会话失效后重新提交影响检查。
- 退休岗位不进入员工岗位选择、新岗位目标选择或新报工授权。
- 历史报工、绩效、工资和岗位历史仍按稳定 ID 与快照读取。
- 重新启用前必须先创建并批准一个新岗位修订版。

### 4.4 工序生命周期例外

岗位修订发布时只能新增当前有效工序。工序以后被退休时，不自动改写已发布岗位修订版。

统一权限解析遵循：

- 岗位根实体必须为启用状态；
- 工序必须存在于该岗位当前已发布修订版；
- 退休工序不能进入新订单、新路线或新岗位修订；
- 已经绑定退休工序版本的历史在制订单仍可由原授权岗位继续查看和流转。

因此不能在所有读取入口简单增加 `processes.status='active'`。新业务选择和历史在制流转必须分别校验。

## 5. 数据模型

### 5.1 `positions` 稳定根

保留现有主键并增加：

```text
position_code
lifecycle_status             active / retired
current_effective_version_id
row_version
created_by
retired_at
```

兼容期保留现有 `name`、`description` 和 `status` 字段，作为当前已发布版本的 Legacy 投影。应用服务不得将这些字段作为历史事实来源。

稳定编码按现有 ID 生成，例如 `POS-0001`，生成后不可修改。

### 5.2 `position_versions`

```text
id
position_id
version
position_code_snapshot
name
description
status                       draft / pending_approval / published /
                             superseded / rejected / cancelled / retired
effective_from
effective_to
supersedes_version_id
revision_reason
legacy_baseline
prior_revision_unavailable
content_digest
impact_digest
idempotency_key
created_by
created_by_name
submitted_at
approved_by
approved_by_name
approved_at
published_at
row_version
created_at
```

约束：

- `UNIQUE(position_id, version)`；
- `UNIQUE(idempotency_key)`；
- 同一岗位最多一个开放修订版；
- 同一岗位最多一个当前 `published` 版本；
- 已发布、已取代和已退休版本禁止内容更新和删除；
- `position_id`、版本号和稳定编码快照不可改变。

### 5.3 `position_version_processes`

```text
id
position_version_id
process_id
seq_order
created_at
```

约束：

- `UNIQUE(position_version_id, process_id)`；
- 草稿中不得重复工序；
- 发布时新增工序必须为当前有效工序根；
- 岗位版本发布后，关联工序不可增加、删除或换序。

`position_processes` 在兼容期保留为当前版本投影，由发布事务重建。授权服务和 V2 API 不再把它作为权威来源。

### 5.4 `position_version_events`

记录不可变领域事件：

```text
position_id
position_version_id
event_type
from_status
to_status
actor_id
actor_name
actor_role
reason
impact_digest
payload_json
idempotency_key
created_at
```

事件表禁止更新和删除。

### 5.5 `position_lifecycle_requests`

```text
position_id
action                       retire / reactivate
status                       pending / approved / rejected / cancelled
reason
impact_digest
requested_by
requested_by_name
approved_by
approved_by_name
row_version
idempotency_key
created_at
resolved_at
```

同一岗位最多一个开放生命周期申请，请求人不得批准本人申请。

### 5.6 事实版本字段

新增可空字段：

| 表 | 字段 | 规则 |
|---|---|---|
| `performance_assignment_history` | `position_version_id` | 新区间绑定发布时有效版本 |
| `performance_source_facts` | `position_version_id` | 新事实绑定业务发生时的岗位版本 |
| `performance_score_revisions` | `position_version_id_snapshot` | 使用生产月结束时有效岗位版本作展示快照 |
| `work_records` | `submit_position_version_id` | 新报工保存提交岗位版本 |
| `performance_position_target_versions` | `position_version_id_snapshot` | 记录目标创建时岗位版本，仅作来源证明 |

旧记录保留空版本 ID 和原有名称快照，展示和计算不得因为空版本 ID 失败。旧数据标记为 `legacy_snapshot`，不把当前 V1 伪装成历史真实版本。

## 6. P0 契约止损

P0 不等待 v070，先完成以下兼容修复：

1. `GET /api/positions` 同时返回：
   - `processes`：结构化工序对象；
   - `process_ids`：纯整数 ID 数组。
2. 前端编辑优先读取 `process_ids`，缺失时从 `processes[].process_id` 推导。
3. `PUT /api/positions/<id>` 仅在请求明确包含 `process_ids` 时替换关联。
4. 前端只修改名称、描述或状态时，必须保留已加载的工序集合。
5. 新增和编辑共用相同岗位名称规则。
6. 影响查询失败时，删除和停用动作失败关闭。

P0 必须有 API 契约和前端 composable 回归测试，才能独立发布。

## 7. 服务边界

### 7.1 `PositionVersionService`

负责：

- 创建岗位根和 V1 草稿；
- 从当前版本创建修订；
- 更新草稿；
- 提交、批准、驳回和取消；
- 发布时原子切换版本、重建兼容投影并写入领域事件；
- 处理幂等重放和 `row_version` 冲突。

### 7.2 `PositionLifecycleService`

负责退休和重新启用申请，批准时重新计算影响摘要。影响变化、存在启用员工或活跃会话时返回稳定冲突，不执行部分状态更新。

### 7.3 `PositionImpactService`

统一统计：

- 启用、停用和已删除员工；
- 活跃会话；
- 当前与历史岗位工序；
- 未完成订单和相关路线；
- 绩效岗位目标版本；
- 员工岗位历史；
- 绩效来源事实和评分快照；
- 报工记录；
- 其他通过岗位引用目录注册的直接引用。

返回结构化分类、总数、阻断原因和 `impact_digest`。提交与批准时摘要不一致则要求重新复核。

### 7.4 `PositionAccessService`

成为岗位工序范围的唯一解析入口。`AccessPolicyService`、活动岗位、订单数据范围、移动扫码和桌面报工通过该服务获取有效范围，不再分别读取 `position_processes`。

显式员工工序授权继续与岗位范围合并；拥有全局数据权限的用户仍返回全局范围。岗位退休只撤销岗位来源的范围，不影响经过独立授权且仍有效的员工工序范围。

### 7.5 `PositionSnapshotService`

发布岗位改名时，以 `published_at` 为生效时刻，在同一事务中：

1. 找到分配到该岗位的启用员工；
2. 关闭当前开放的 `performance_assignment_history` 区间；
3. 使用相同稳定岗位 ID、新版本 ID 和新名称创建新区间；
4. 保留发布时刻之前的全部事实和名称快照。

只修改描述或工序范围时不切分绩效岗位历史。

### 7.6 `PositionAuditService`

提供事务感知的强制审计适配器，显式接收操作人、请求 ID、幂等键和结构化差异，并使用调用方传入的数据库事务写入 `audit_logs`。路由层只负责提取请求 ID，迁移和后台命令使用各自的运行 ID；服务不依赖 Flask `g` 才能完成审计。

## 8. API 与兼容

### 8.1 查询

```text
GET /api/positions
GET /api/positions/<id>/versions
GET /api/position-versions/<id>
GET /api/position-versions/<id>/impact
GET /api/positions/<id>/lifecycle-requests
```

Legacy 列表继续返回扁平岗位字段，并增加：

```text
process_ids
current_effective_version_id
current_version
lifecycle_status
row_version
```

### 8.2 版本命令

```text
POST /api/positions
POST /api/positions/<id>/revisions
PUT  /api/position-versions/<id>
POST /api/position-versions/<id>/submit
POST /api/position-versions/<id>/approve
POST /api/position-versions/<id>/reject
POST /api/position-versions/<id>/cancel
```

### 8.3 生命周期命令

```text
POST /api/positions/<id>/retirement-requests
POST /api/position-lifecycle-requests/<id>/approve
POST /api/position-lifecycle-requests/<id>/reject
POST /api/positions/<id>/reactivation-requests
```

所有写命令必须携带：

```text
row_version
idempotency_key
revision_reason 或 lifecycle_reason
```

V2 正式切换后，旧 `PUT /api/positions/<id>` 和 `DELETE /api/positions/<id>` 返回 `409 POSITION_LEGACY_WRITE_BLOCKED`。Legacy 查询继续可用。

## 9. 权限设计

保留现有权限并增加：

```text
positions:view
positions:create
positions:edit              兼容期草稿编辑
positions:delete            仅未发布、未引用草稿根
positions:submit
positions:approve
positions:reject
positions:history
positions:impact
positions:retire
positions:reactivate
```

规则：

- 查看页面只需要 `positions:view`；
- 创建和修订需要 `positions:create`；
- 编辑草稿需要 `positions:edit`；
- 提交、批准、驳回分别使用独立权限；
- 退休和重新启用使用专用权限；
- `positions:approve` 不能批准本人制单的修订或生命周期申请；
- 前端隐藏无权限操作，composable 命令本身也必须再次阻断；
- 后端权限始终是最终安全边界。

## 10. 审计和错误处理

### 10.1 强制审计

岗位创建、修订、提交、批准、驳回、退休和重新启用通过 `PositionAuditService` 在业务事务内写入 mandatory 审计记录；现有 `required_audit_log` 仅作为 HTTP 适配入口，`safe_audit_log` 不得用于这些状态转换。审计详情保存结构化摘要：

```text
position_id
position_version_id
from_status / to_status
changed_fields
added_process_ids
removed_process_ids
reason
impact_digest
idempotency_key
```

审计写入失败时业务事务回滚。领域事件和跨系统审计记录使用相同幂等键关联。

### 10.2 稳定错误码

```text
POSITION_NOT_FOUND
POSITION_VERSION_NOT_FOUND
POSITION_VERSION_STALE
POSITION_VERSION_IMMUTABLE
POSITION_VERSION_ALREADY_OPEN
POSITION_APPROVAL_SEPARATION_REQUIRED
POSITION_PROCESS_INVALID
POSITION_IMPACT_CHANGED
POSITION_ACTIVE_EMPLOYEES_EXIST
POSITION_ACTIVE_SESSIONS_EXIST
POSITION_REFERENCE_CONFLICT
POSITION_LEGACY_WRITE_BLOCKED
POSITION_MIGRATION_REVIEW_REQUIRED
```

响应返回中文说明、稳定错误码、结构化详情和建议动作，不暴露 SQLite 错误或堆栈。

## 11. UI/UX

岗位页面继续采用现有安静、紧凑的设置页样式，不建立独立营销式页面。页面分为：

1. 当前岗位列表；
2. 待审批修订；
3. 历史版本；
4. 影响和引用。

当前岗位列表显示岗位名称、稳定编码、当前版本、关联工序、员工数、生命周期和待办状态。原“编辑”变为“创建修订版”，已发布版本只读；原“删除”仅对从未发布且未引用的草稿根显示，其他岗位显示“申请退休”。

修订界面从当前版本复制内容，展示新增和移除工序差异。提交前显示员工、会话、在制订单、绩效和历史事实影响。批准界面显示制单人、原因、字段差异、工序差异和影响摘要。

岗位列表保留 `processes` 的名称标签，同时以 `process_ids` 作为表单选择的稳定值。所有图标按钮提供 `title` 或 tooltip，按钮尺寸保持稳定。

## 12. 历史迁移与取证

### 12.1 工序关联取证

生产操作日志中已有 16 次岗位更新，但现有审计详情不足以还原工序差异。正式迁移前：

1. 从生产备份建立只读临时副本；
2. 选择岗位更新时间前后的最近备份；
3. 比较 `positions` 和 `position_processes`；
4. 输出岗位、原工序、当前工序、证据来源和置信状态；
5. 仅自动恢复能够由备份精确证明的关联；
6. 无证据或存在冲突的记录进入人工确认清单。

不使用名称相似度、工序类别或员工历史进行自动猜测。

### 12.2 v070 基线迁移

v070 执行：

- 扩展 `positions` 稳定根；
- 创建岗位版本、版本工序、事件和生命周期申请表；
- 为现有岗位建立 V1 `published` 基线；
- 将当前 `position_processes` 复制到 V1；
- 标记 `legacy_baseline=1` 和 `prior_revision_unavailable=1`；
- 增加事实版本字段；
- 旧事实版本字段保持空值，不回填虚构版本；
- 为当前启用员工的开放岗位历史从切换时刻建立绑定 V1 的新区间；
- 建立索引、唯一约束和不可变触发器；
- 生成迁移摘要和异常表。

迁移不得改变员工数、岗位数、报工数量、工资金额、绩效分数或历史名称快照。

## 13. 功能开关和切换

```text
POSITION_VERSIONED_QUERY_ENABLED
POSITION_COMPAT_AUDIT_ENABLED
POSITION_VERSIONED_WRITE_ENABLED
POSITION_LEGACY_WRITE_BLOCKED
```

切换顺序：

1. 上线 P0 契约止损；
2. 部署 v070 表和 Legacy V1 基线，业务仍读取旧投影；
3. 开启版本化查询和双读差异审计；
4. 双读差异连续为零后开启版本化写入；
5. 上线新版岗位 UI；
6. 阻断 Legacy 写入；
7. 稳定运行后清理旧写代码，但保留 Legacy 查询兼容。

每个开关独立切换并生成证据，禁止跳过阶段。

## 14. 测试策略

### 14.1 P0 契约测试

- 列表同时返回 `processes` 和 `process_ids`；
- 前端从真实后端响应正确回填工序；
- 只修改名称或描述不会清空工序；
- 显式提交空数组才会清空草稿工序；
- 影响接口失败时删除失败关闭；
- 新增和编辑名称校验一致。

### 14.2 版本和不可变测试

- V1 基线幂等创建；
- 已发布版本不可修改或删除；
- 同一岗位不能存在两个开放或当前发布版本；
- 过期 `row_version` 返回 409；
- 重复幂等键不创建重复修订；
- 制单人不能批准本人修订；
- 发布任一步失败时版本、根指针、投影、岗位历史和审计全部回滚。

### 14.3 权限和生命周期测试

- 停用或退休岗位不再提供岗位工序范围；
- 显式员工工序授权不被错误撤销；
- 有启用员工或活跃会话时退休被阻断；
- 无权限用户看不到按钮且不能直接调用命令；
- 退休工序不能加入新岗位修订；
- 历史在制订单仍能按原工序版本流转。

### 14.4 快照测试

- 岗位改名前事实保留旧名称；
- 岗位改名发布后关闭并重开开放岗位历史；
- 新报工和绩效事实绑定新岗位版本；
- 同一生产月中途改名仍按稳定岗位 ID 聚合；
- 月度评分使用生产月结束时的岗位版本作为展示快照；
- 旧记录版本 ID 为空时仍可查询、导出和复算。

### 14.5 全量验证

```text
python -m pytest
npm run test:unit
npm run check:architecture
npm run build
npm run test:e2e
```

测试使用干净 Python 虚拟环境，避免本机损坏的 pytest 安装掩盖结果。

## 15. 生产预检和验收

### 15.1 预检门槛

```text
非法岗位状态                         0
重复岗位名称                         0
岗位关联不存在工序                   0
岗位工序重复关联                     0
启用员工引用不存在岗位               0
开放岗位历史重叠                     0
无法确认的工序恢复项                 0 或已人工接受
数据库完整性检查                     ok
新增外键违规                         0
```

### 15.2 生产验收

- `qr-system.service` 为 `active/running`；
- `/api/health` 返回 `status=ok`；
- 数据库版本达到 v070；
- 备份可打开且 SHA-256 已记录；
- 岗位列表 V1/Legacy 双读差异为零；
- 编辑描述不会改变工序范围；
- 无编辑权限用户只有查看界面；
- 使用测试岗位完成修订、提交和独立批准；
- 岗位工序变化后授权范围在下一请求生效；
- 历史日报、工资和绩效抽样结果不变；
- Legacy 查询正常，Legacy 写入返回预期 409；
- 审计日志能够还原修订前后差异。

## 16. 回滚边界

P0 仅改变接口和前端契约，可以回滚代码，不需要数据库恢复。

v070 版本化写入开启前，可以关闭功能开关并回滚应用代码，新增表和字段保留。正式迁移前备份必须通过独立打开、完整性和 SHA-256 校验。

版本化写入产生正式岗位修订后，不允许用迁移前数据库覆盖新数据，也不允许回退到可直接修改岗位和工序关联的旧代码。故障时关闭岗位写入、保持查询可用并执行前向修复。

## 17. 实施顺序

1. P0 字段契约、权限按钮和名称 Schema 止损；
2. 岗位历史工序关联取证工具和差异清单；
3. v070 稳定根、版本表、事件表和事实版本字段；
4. 纯状态、摘要、差异和不可变策略；
5. 版本仓储、影响目录和事务服务；
6. 统一岗位有效工序范围；
7. 绩效岗位历史和事实快照切换；
8. 版本化 Schema、API、权限和 Legacy 兼容；
9. 当前、待审批、历史和影响 UI；
10. 预检、副本迁移、全量回归和生产发布工具。

该顺序先消除当前会破坏数据的路径，再建立数据库不变量，最后切换业务引用和 UI，避免在底层仍可直接修改时提前暴露新版操作入口。
