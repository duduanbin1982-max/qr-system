# Brooks-debt Task 2F：应用上下文和业务入口依赖迁移

## 范围与基线

- 实施日期：2026-10-16，Asia/Shanghai。
- 基线：Task 2E 合并后的 `master`，`69f47aa34ae66ffc122e089d772818c75ee968a8`。
- 独立分支：`codex/brooks-debt-task2f-app-context-flows`。
- 状态：实现、验证和正式本地 diff 审核完成，待单独授权提交、推送和创建 PR；尚未修改生产环境。
- 本批治理 D05 / Task 2F 的 **14 条历史依赖、5 个 Vue 消费文件**。
- 不修改后端、API facade 实现、数据库、依赖包或锁文件。

## 迁移入口

| 消费入口 | 新协调入口 |
|---|---|
| `views/AppLayout.vue` | `composables/application/useAppLayout.js` |
| `views/ApprovalPage.vue` | `composables/approval/useApprovalPage.js` |
| `views/LoginPage.vue` | `composables/auth/useLoginPage.js` |
| `views/ScanReport.vue` | `composables/scan/useScanReport.js` |
| `views/TracePage.vue` | `composables/trace/useTracePage.js` |

页面模板、样式和对外绑定保持不变。应用布局仍保留动态页面加载、权限落地页、导航恢复、会话恢复、登录设备状态和 `window.A` 兼容契约；错误页和动态组件声明留在视图层，协调状态和基础设施访问由 Composable 负责。审批筛选、批量处理、分页、统计和权限判断保持原行为。登录的首次改密、请求页恢复和权限落地保持原行为。扫码报工保留数量约束、序列号报工、报工后刷新和失败提示。追溯保留历史记录、分页查询、竞态保护和打印入口。

## 架构门禁

- 删除 14 条 Task 2F 冻结边，新增 14 条负向 fixture。
- 保留原始依赖台账，14 条状态更新为 `local_reviewed_pending_commit` 并指向本报告。
- 视图层只依赖 Vue、组件和 Composable；API、认证、路由和 store 访问集中在 Composable。

## 本次实际验证

本机仓库的 npm 门禁要求 Node `24.22.0` / npm `11.19.1`，当前交互环境为 Node `25.2.1` / npm `11.6.2`，因此 `npm run test:e2e` 和 `npm run check:architecture` 的 npm 包装入口会先按预期拒绝执行。未修改工具链门禁或依赖文件；改用仓库已安装的 Vitest、Vite、Playwright 及独立检查脚本完成同等验证，工具链不匹配作为环境限制单独记录。

| 检查 | 实际结果 |
|---|---|
| Task 2F 行为测试 | **5 passed** |
| 全量前端单元测试 | **62 个文件 / 450 passed**；0 failed / skipped / todo |
| 后端架构检查 | **32 passed** |
| API facade | **34 namespaces / 455 unique domain methods**，通过 |
| 前端导入环 | **277 files / 587 internal edges**，无循环 |
| 前端分层 fixture | **98 passed**；0 failed / skipped / todo |
| 前端分层扫描 | **277 files / 586 edges / 0 frozen legacy edges** |
| 前端生产构建 | 成功，**358 modules**，约 821 ms |
| E2E | **25/25 passed**，0 failed / skipped；约 1.6 分钟 |
| 空白检查 | `git diff --check` 通过 |

E2E 使用临时静态目录和隔离测试服务运行，没有访问生产数据。生产构建只生成被 `.gitignore` 排除的 `public/static/` 产物，未进入工作树变更。保留既有 `NO_COLOR` / `FORCE_COLOR` 和 Flask 开发服务器提示，不将其计为失败。

## 正式本地 diff 审核

审核范围为本批 14 条历史边、5 个 Vue 消费入口、5 个 Composable、行为测试、前端分层门禁、门禁基线、台账和本报告。重点核验：

- 五个视图的模板、样式、组件注册和对外绑定未改变；
- 登录、审批、扫码报工、追溯和应用布局的请求参数、权限、生命周期、错误处理及刷新行为保持等价；
- 14 个历史依赖均有对应负向 fixture，恢复任一直接依赖都会被分层门禁阻断；
- 没有新增 HTTP client 直连、循环依赖、API facade 绕过或运行时资源变更；
- 变更范围不包含 `.brooks-lint-history.json`、Task 0 报告、`.tmp-*`、临时部署脚本、日志、数据库或构建产物。

结论：**Critical 0、Warning 0、Suggestion 0；本地 diff 审核通过。** 本结论不代替独立 PR 审核、批准或生产发布授权。

下一步在获得单独授权后，按精确清单执行提交、推送和创建合并到 `master` 的 PR。
