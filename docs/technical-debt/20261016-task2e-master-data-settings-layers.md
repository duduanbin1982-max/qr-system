# Brooks-debt Task 2E：主数据和设置历史依赖迁移

## 范围与基线

- 实施日期：2026-10-16，Asia/Shanghai。
- 基线：实施开始时已核实的 GitHub `master`，`0a2196bfb26ead4ead0e5cefce776d3c97cf6aa8`（Task 2D / PR #104 合并提交）。
- 独立分支：`codex/brooks-debt-task2e-master-data-settings-layers`。
- 状态：实现和验证完成，待正式本地 diff 审核；尚未暂存、commit、push、创建 PR 或修改生产环境。
- 本批治理 D05 / Task 2E 的 **19 条历史依赖、9 个 Vue 消费文件**。剩余 Task 2F 的 14 条继续待处理，D05 整体未关闭。

## 实施与行为保护

Vue 保留原有模板、样式、组件注册及 props / emits / expose 契约，将查询、状态、权限、导航和操作协调迁入 Composable。调用保持同步，沿用原生命周期和 watch 注册时机；发布批次继续接收完整响应式 props 对象及 emit。

| 消费入口 | 新协调入口（相对 `frontend/src/composables/`） |
|---|---|
| `components/master-data/ReleaseBatchPanel.vue` | `masterData/useReleaseBatchPanel.js` |
| `views/BasicSettings.vue` | `settings/useBasicSettings.js` |
| `views/CustomerList.vue` | `masterData/useCustomerList.js` |
| `views/ProcessList.vue` | `masterData/useProcessList.js` |
| `views/ProductionSettings.vue` | `settings/useProductionSettings.js` |
| `views/RouteList.vue` | `masterData/useRouteList.js` |
| `views/SettingsPage.vue` | `settings/useSettingsWorkspace.js` |
| `views/settings/Positions.vue` | `settings/usePositionsWorkspace.js` |
| `views/settings/ProcessConfig.vue` | `settings/useProcessConfigWorkspace.js` |

API facade、权限和通知等依赖保留在 Composable 内。Vue 仅取得页面需要的状态、方法和展示 helper，不返回原始 API 或认证对象。工艺设置的 `hasUnsavedChanges` 继续引用原状态对象的方法，并通过 `defineExpose` 供父页面的离开确认使用。

保留的行为包括：

- 基础、生产和系统设置的权限页签、历史选择修正及保存；基础/生产已访问子页面的保留；系统设置未保存改动的确认和取消。
- 客户筛选、服务端分页、统计、重复保存保护、详情及错误反馈；原删除关联检查口径保持不变。
- 工序分类、排序分页、导航类别同步、初始化重试、版本草稿及审批、影响和引用展示。
- 路线分类、搜索、分页、可选工序版本、精确工价覆盖、提交审批后再导航定价、成组发布后的刷新。
- 岗位版本和生命周期操作、确认、忙状态、错误反馈与权限；工艺修订的自审限制、未保存状态和驳回重试。
- 发布批次使用最新 props，去重工序版本，只纳入精确路线/工序对应的工价草稿；保留 row_version、幂等键、价格处置及成功发布事件。

本批采用 AST 迁移并核验原协调逻辑，没有同时改变业务规则、API facade、后端实现、依赖包或锁文件。

历史例外基线 **33 → 14**，精确删除本批 19 项，其余摘要和纯工具白名单保持不变。Task 0 原始盘点继续保留 **127 条 / 60 个消费文件**，仅更新 Task 2E 的 19 项状态为 `implemented_pending_local_review`，并写入本报告路径。

## 本次实际验证

固定工具链：Node **24.22.0**、npm **11.19.1**、Python **3.12.10**。先运行既有单测基线及新增行为保护，再迁移生产代码。

| 检查 | 实际结果 |
|---|---|
| 修改前全量前端单测 | **60 个文件 / 428 passed** |
| 修改前定向行为保护 | **8 个文件 / 57 passed**，其中新增 17 项 |
| 修改后同组行为保护 | **8 个文件 / 57 passed** |
| `npm run verify:frontend` | 退出码 0，包含以下架构、单测、E2E 和生产构建 |
| 工具链 fixture | **21 passed** |
| 后端架构检查 | **32 passed** |
| API facade | **34 namespaces / 455 unique domain methods**，通过 |
| 前端导入环 | **272 文件 / 581 内部边**，无环 |
| 前端分层 | **92 fixture passed**；272 文件 / 580 边 / 14 冻结历史边 |
| 全量前端单测 | **61 个文件 / 445 passed**，较基线增加 17 项 |
| E2E | **25/25 passed**，1.6 分钟，无失败重试 |
| 前端生产构建 | 成功，353 模块，最终构建 807 ms |
| 相关后端 API 契约 | **58 passed**，16.40 秒 |
| 全范围等价检查 | 全部 9 个 Vue 的模板/CSS 字节一致，原协调 AST、imports、options/macros、同步委托及返回绑定一致 |
| 台账和门禁检查 | 精确移除 19 项例外，其余摘要和台账内容不变 |
| 变更范围和空白检查 | 仅本批 25 个文件，`git diff --check` 和新增文件行末空白检查通过 |

后端契约命令：

```bash
python -m pytest -q \
  tests/test_customers.py \
  tests/test_process_management.py \
  tests/test_process_version_api.py \
  tests/test_route_version_workflow.py \
  tests/test_position_version_api.py \
  tests/test_process_config.py \
  tests/test_master_data_release_workflow.py
```

本批没有后端实现变更，执行了上述相关契约和后端架构测试，没有重复运行全量后端；不将历史全量结果作为本次执行证据。

新增的 17 项行为测试经真实 Vue 消费入口执行：设置工作台 11 项、发布批次 4 项、工艺设置 2 项。覆盖权限变化、历史页签修正、懒加载保留、响应式 props、精确草稿选择、幂等参数、成功事件、失败反馈、公开未保存方法和驳回重试。既有客户、工序、路线、岗位及设置测试继续通过。

分层门禁增加 10 个 fixture，逐一恢复全部 9 个消费文件的 19 条历史依赖，均必须被阻断。等价检查额外核验脚本宏、模板使用的导入 helper，以及工艺设置公开方法的精确别名。

E2E 使用 `127.0.0.1:4173` 的隔离服务与测试数据库，沿用既有库存、排程、扫码、审批和工资版本浏览器用例；没有声称新增了全部 9 个消费入口的浏览器验收。最终验证无失败、跳过或预期失败。

安装依赖沿用基线锁文件，npm 报告既有的 10 项依赖漏洞（3 moderate / 7 high）及 glob 弃用提示；本批没有运行自动依赖升级。验证日志另保留 Flask 开发服务器及 `NO_COLOR` / `FORCE_COLOR` 环境提示。

## 原始证据与后续边界

原始日志、AST 迁移和只读等价校验脚本位于工作树外：
`C:/Users/dubin/Documents/生产管理系统升级版/.architecture-audits/20261016-task2e-master-data-settings-layers/`。

| 证据 | SHA-256 |
|---|---|
| `baseline-unit.log` | `1c565e2e1c6859890865bb44cbbf04f2ccec0523f1a8129fac559fbdc6d3050a` |
| `baseline-behavior.log` | `307451f893ff3d76d7c5f58b2cb5ce4b8df515ebee6445d77b5e66b1bc3621fa` |
| `targeted-behavior.log` | `2c5696cae8b1e5ee7f086780ec2e1d84f8568a99142aa0b37dccb4291ad80309` |
| `verify-frontend.log` | `5cda9752827ee758009fefa3e1da1b6273498744da8ff8037011f8d9b5ab7293` |
| `domain-api.log` | `c92a431d403159ef2870d31dc630eadf9565eaa9213d5aa018bda5e411319052` |
| `equivalence.log` | `76e409df829eb9bedaad457a04b605e8bbab617d4a10c253032b650ea6c07c8a` |
| `verify-equivalence.mjs` | `e9b46ccd0069d1f06e02254587e9c3cb4eb8c70cb1e72e969aea3a4a3390400f` |
| `template-bindings.mjs` | `fc5447d063f8c382481eef5d926a898bf7b5560156ce4b51756cd23b33822afb` |

本批共 25 个文件：9 个 Vue、9 个 Composable、3 个单测文件、分层门禁测试、门禁基线、原始台账及本报告。排除 `.brooks-lint-history.json`、Task 0 其他报告、`.tmp-*`、临时部署脚本、原始日志、依赖、数据库及构建/E2E 产物。

下一步进行正式本地 diff 审核，通过后再进入单独授权的提交、推送和 PR 阶段。生产发布另行安排，本批没有生产操作。
