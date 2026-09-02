# Brooks-Lint Review

**Mode:** PR Review
**Scope:** 生产 `192.168.1.8:/home/dubin/qr-system`（已部署提交 `4008e4ba`）及本地等价代码树；审查角色路由、服务、仓储、管理员策略、有效权限和主角色解析、审批角色引用、权限目录、Vue 角色页面/composable/API，以及角色、用户角色和审批相关测试。生产数据库仅执行只读一致性查询；跳过生成文件和打包产物。
**Health Score:** 74/100
**Trend:** 84 → 74 (-10) over last 2 runs

角色 CRUD 的真实管理员校验、事务审计、内置管理员保护和删除引用检查总体可靠，但角色编码、状态和权限闭包还没有形成单一稳定的领域约束，当前生产数据也已出现权限目录漂移。

---

## Findings

### 🟡 Warning

**Domain Model Distortion — 可变角色编码被其他业务当作稳定标识**
Symptom: `modules/services/role_service.py:263-270` 允许直接修改所有非内置角色的 `code`，没有检查引用或同步下游；同时 `approval_config.approver_role`、多级审批配置和部分兼容逻辑以角色编码字符串识别角色（`modules/services/approval_service.py:336-379`），而用户绑定本身又使用稳定的 `role_id`。生产当前 4 条审批配置只引用内置 `admin`，尚未断链，但系统已经支持选择自定义审批角色。
Source: Evans — *Domain-Driven Design*, Entity Identity / Aggregate Invariants
Consequence: 自定义审批角色一旦改编码，用户的权限仍因 `role_id` 绑定而存在，审批配置却继续要求旧编码，形成“看似有权限但无法审批”的分裂状态；历史兼容字段和外部脚本也可能继续引用旧值，故障只会在业务执行时暴露。
Remedy: 将角色 `id` 作为配置和业务引用的唯一标识；审批配置迁移为 `approver_role_id` 并保留角色编码/名称快照。迁移完成前，已分配用户或已被配置引用的角色编码设为只读；确需更名时在同一事务中写编码别名并受控更新活动引用，历史步骤保持快照不变。

**Domain Model Distortion — 停用状态只撤销权限，没有统一撤销角色身份**
Symptom: 有效权限查询明确过滤 `r.status = 'active'`（`modules/repositories/access_policy_repository.py:9-15`），但登录主角色和审批当前角色查询不检查状态（`modules/repositories/auth_repository.py:138-153`、`modules/repositories/user_repository.py:395-408`）。用户角色查询和权限矩阵也会返回停用绑定。生产当前没有停用角色，因此尚未触发数据异常。
Source: Brooks — *The Mythical Man-Month*, Conceptual Integrity
Consequence: 多角色用户停用某个角色后，常规 API 权限会立即失效，但身份展示和基于角色编码的审批判断仍可能选中该停用角色；若另一个活动角色仍授予 `approvals:edit`，用户可能继续以已停用身份满足审批步骤。运维人员也无法用“停用角色”准确推断系统行为。
Remedy: 区分“全部绑定角色”和“有效角色”查询，认证、主角色、审批和管理员判定统一只使用活动角色；历史/审计接口可返回停用角色但必须标注为非有效身份。停用前提供影响人数和审批配置引用预检，并补充多角色停用回归测试。

**Backward Compatibility — 生产角色保留了目录外权限，编辑保存会失败**
Symptom: 生产只读核对发现 `production_manager` 和 `qc_inspector` 均包含已从 `ALL_PERMISSION_CODES` 删除的 `page:production.quality`。前端编辑时保留该未知编码并把完整权限集合回传（`frontend/src/composables/settings/useRoleManage.js:101-115`），后端则拒绝任何未知权限（`modules/services/administrator_policy.py:60-63`）。
Source: Winters et al. — *Software Engineering at Google*, Hyrum's Law / Backward Compatibility
Consequence: 管理员即使只修改这两个角色的名称、描述或状态，也会因随表单提交的旧权限得到“未知权限编码”错误；权限目录演进已经使既有生产记录变成不可编辑数据。
Remedy: 为权限编码建立显式退役/别名迁移机制。先将 `page:production.quality` 受控映射到当前 `page:quality-management` 或在确认无语义后删除，记录迁移审计；以后目录删除编码前运行角色引用预检，并允许读取历史编码、禁止新授予、在保存时给出明确迁移提示。

**Knowledge Duplication — 权限依赖闭包由前端补全，后端只校验单项合法性**
Symptom: `frontend/src/lib/permissions.js:131-150` 在保存前补齐 implied 权限及页面链，`modules/permission_catalog.py:487-500` 也定义了页面推导规则，但 `RoleService.create_role/update_role` 只调用 `normalize_permissions()` 做格式和目录校验，没有执行闭包规范化。因此直接 API、脚本或迁移可以保存 `orders:view` 却不含 `page:production.orders` 的角色。
Source: Hunt & Thomas — *The Pragmatic Programmer*, DRY / Knowledge Duplication
Consequence: 同一权限集合经 UI 和 API 创建会得到不同结果；用户可能具备后端操作权限却无法打开对应页面，或页面可见但缺少隐含查看权限。每次新增权限关系都必须同步修改并测试多个实现点。
Remedy: 在后端建立唯一的 `RolePermissionPolicy.normalize_closure()`，统一完成目录校验、implied 权限和页面链补全，所有角色写入、迁移和预检复用该策略；前端仅展示后端返回的规范化结果，不承担授权领域规则。

**Primitive Obsession — 名称、编码和级别缺少一致的角色标识约束**
Symptom: 创建角色只检查名称非空和编码唯一，更新时虽存在 `RoleRepository.find_by_name_exclude()` 却未使用；`level` 在创建和更新中未经类型、范围或层级一致性校验直接写库（`modules/services/role_service.py:159-199,271-296`），编码也没有大小写、字符集和长度规范。生产快照当前无重复名称、非法级别或父子循环。
Source: Fowler — *Refactoring*, Primitive Obsession
Consequence: 可以创建同名角色或写入负数/文本级别，角色选择器将难以区分同名项；`level` 又参与主角色排序，错误值会改变登录展示和审批身份选择。数据库唯一约束只能保护编码的完全相等，不能阻止大小写近似标识。
Remedy: 定义统一角色请求 Schema 和 `RoleIdentity` 校验：名称按业务规则唯一，编码使用小写稳定格式并限制长度，级别限定整数范围且与父级关系一致；数据库增加相应 CHECK/唯一索引，并在迁移前输出冲突清单。

### 🟢 Suggestion

**Information Hiding — 只读角色查看者仍看到所有写操作**
Symptom: `frontend/src/views/settings/RoleManage.vue:14,48-50,163` 无条件显示新增、编辑、删除和保存按钮，`useRoleManage.js` 也没有像角色组模块那样计算 `canCreate/canEdit/canDelete`。后端 `roles:create/edit/delete` 和真实管理员校验仍会阻止越权，因此不是后端授权绕过。
Source: Ousterhout — *A Philosophy of Software Design*, Information Hiding
Consequence: 仅具 `roles:view` 的生产主管会进入完整编辑流程，最后才收到 403；界面表达与实际能力不一致，增加误操作和支持成本。
Remedy: 使用统一 `can()` 计算各操作能力，隐藏或禁用无权按钮并在 composable 再做一次前端守卫；后端鉴权保持不变。同步增加仅查看用户的组件/API 403 测试。

---

## Verification

- 生产运行基线：Git HEAD、`.deployed_commit` 均为 `4008e4ba`，`qr-system.service` 为 `active`。
- 生产只读数据：9 个角色全部启用，48 条用户角色绑定；未发现停用角色绑定、孤立引用、重复名称、非法级别、父子循环或缺失审批角色。
- 生产权限目录差异：2 个活动角色保留同一个未知编码 `page:production.quality`。
- 后端目标测试：角色/权限/管理员 21 项通过，审批角色与权限边界 6 项通过，共 27 项通过。
- 前端目标测试：`useRoleManage.spec.js` 2 项通过。
- 未执行会修改生产业务数据的测试、迁移或服务操作。

## Summary

优先处理角色编码稳定性、停用角色的统一失效语义和生产中的目录外权限；这三项决定角色授权是否可解释、可迁移。随后把权限闭包收口到后端并补齐角色标识 Schema，最后修正只读用户的按钮显示。现有测试覆盖了管理员保护、通配权限、未知权限、循环关系和审计回滚，但仍缺少“停用多角色用户”“被引用角色改编码”“历史权限目录升级”和角色 API 403 的直接回归测试。
