# Brooks-Lint Review

**Mode:** PR Review
**Scope:** 生产 `/home/dubin/qr-system`（提交 `da2f8e8b0b7e352f4dfec6124eaf18e3fd582043`）及其本地等价代码树；审查角色组路由、服务、仓储、权限策略、权限目录、Vue 页面/composable，以及角色/权限相关测试。生产数据库只读核对 `role_groups`、`roles`、`user_roles`；未审查或修改生成文件、打包产物和生产数据。
**Health Score:** 84/100
**Trend:** 39 → 84 (+45) over last 2 runs

角色组的写入事务、管理员保护和层级约束总体可靠，但“角色组仅作分类”尚未成为实际权限计算的唯一规则；发布前必须先完成历史权限差异核对和受控迁移。

---

## Findings

### 🔴 Critical

**Domain Model Distortion — 角色组仍然是有效权限来源**
Symptom: `frontend/src/views/settings/RoleGroups.vue:76-80` 和 `AdministratorPolicy.normalize_group_permissions()`（`modules/services/administrator_policy.py:66-70`）都声明角色组只用于分类、不能授予权限；但 `modules/repositories/access_policy_repository.py:7-9` 仍查询 `rg.permissions as group_perms`，`modules/access_policy.py:18-38` 又把 `role_perms` 与 `group_perms` 一起解析。该查询也没有按 `rg.status` 过滤。生产只读快照显示 6 个角色组中 4 个仍保存非空权限；其中 3 个角色组挂有 5 个角色、关联 45 个用户（系统管理组 7 人、普通员工组 38 人，管理员组当前无用户），另有财务组保留一整套业务权限。当前快照中管理员的通配权限和普通员工角色的重复权限暂未产生额外权限差集，但旧来源仍处于有效计算链路中。
Source: Evans — *Domain-Driven Design*, Ubiquitous Language / Domain Model
Consequence: 管理员按界面语义把角色组当作分类时，角色分配、角色组停用或历史数据复用仍可能静默携带旧权限；由于停用组也未被排除，权限收回和审计解释都不可靠，后续把用户加入现有角色组即可触发未预期授权。权限来源的双轨状态也使迁移结果无法仅凭角色配置推断。
Remedy: 先生成逐用户的“角色权限 vs 角色组遗留权限”差异清单并由授权人确认，不能直接盲目清空；在受控事务中将历史 `role_groups.permissions` 迁移为 `[]` 并写入审计/迁移清单。随后从 `get_permission_rows()` 移除 `group_perms`，让 `collect_permission_codes()` 只接受角色权限；保留字段只读兼容一段观察期后废弃。补充回归测试，证明非空、停用角色组权限都不会进入有效权限集合，并更新当前仍断言“合并角色组权限”的测试。

### 🟢 Suggestion

**Information Hiding — 角色组操作按钮未按权限隐藏**
Symptom: `frontend/src/views/settings/RoleGroups.vue:8,24-25,86` 无条件渲染新增、编辑、删除按钮；页面没有使用 `hasPermission()` 或统一权限 composable。后端路由 `modules/routes/roles.py:37-80` 仍正确执行 `role_groups:create/edit/delete` 校验，因此这不是绕过后端授权的漏洞。
Source: Ousterhout — *A Philosophy of Software Design*, Information Hiding
Consequence: 只有查看权限的用户会看到不可用操作，点击后才收到 403/授权错误，造成界面噪声和无效往返，也把同一授权决策重复留在前后端两个地方。
Remedy: 在 composable 中注入当前用户权限，使用统一 `hasPermission` 计算 `canCreate/canEdit/canDelete`，按权限隐藏按钮；后端校验继续保留，前端只负责可用性表达。

## Verification

- 生产只读查询：角色组总数 6，非空权限组 4；未发现停用且挂有角色的角色组；权限关联统计如上。
- 前端：`npm run test:unit -- --run frontend/tests/unit/useRoleManage.spec.js`，2 个测试通过。
- 后端：目标测试文件已定位，但本地运行环境没有安装 `pytest`，`python3 -m pytest` 无法执行；未对生产数据库运行会写入数据的测试。

## Summary

角色组的创建、更新、删除已具备事务、审计、层级循环和真实管理员保护，基础 CRUD 风险较低。当前发布阻断点是历史角色组权限仍被实际权限解析器读取，且数据库中仍有 4 条非空记录；应先完成用户权限差异清单和受控清理，再切换为纯角色权限模型。前端按钮权限过滤属于体验改进，不替代后端鉴权。
