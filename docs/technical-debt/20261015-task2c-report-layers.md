# Brooks-debt Task 2C：报表、统计和首页历史依赖迁移

## 范围与基线

- 实施日期：2026-10-15，Asia/Shanghai。
- 基线：已核实的 GitHub `master`，`d04769246e2196ed1400d3caa218e0383af81a7f`（Task 2B / PR #102 合并提交）。
- 独立分支：`codex/brooks-debt-task2c-report-layers`。
- 本批实现、验证及本地 diff 审核已通过，提交和 PR 以实际 Git/GitHub 记录为准。独立 PR 审核与合并批准由后续步骤完成。
- 本批仅治理 D05 / Task 2C 的 **41 条历史边、22 个消费文件**。Task 2D–2F 继续保持待处理，D05 整体未关闭。

## 实施与行为保护

20 个 Vue 消费文件保留模板、样式、props 和组件注册，将查询、状态、权限与导出协调迁到对应 Composable。Vue 的 `setup()` 同步调用 Composable，保留响应式 props、watch、mounted/unmounted 时序和返回字段。

| 消费范围 | 新协调入口 |
|---|---|
| 首页 `DashboardPage.vue` | `composables/reports/useDashboardOverview.js` |
| 报表工作台 `ReportsPage.vue` | `composables/reports/useReportsWorkspace.js` |
| 统计工作台 `StatsPage.vue` | `composables/stats/useStatsWorkspace.js` |
| 8 个报表页签：Dashboard、Matrix、Model、Order、Quality、Rework、Trend、Worker | `composables/reports/useReport*.js` |
| 9 个统计页签：Customer、Daily、Material、ModelProcess、Product、Progress、Scrap、Shipment、Worker | `composables/stats/use*Stats.js` |

两个旧 `views/**/shared.js` 消费文件移除：页签声明分别迁至 `reportTabs.js` 和 `statsTabs.js`；共享加载、参数和 CSV 实现从 `lib/report-utils.js` 移至 `composables/reports/reportSupport.js`，只移除原本未使用的 Vue import，没有复制第二套实现。

保护的口径包括日期和产品筛选、查询刷新、报工日 07:00 边界、加权完成率、型号/规格聚合、工人 Top 15 展示与完整计数、工序补零和合计、日报正常/返修/报废数量、CSV 列及公式防护、PDF 参数和 `stats:view` 导出按钮权限。首页保留错误重试、30 秒数据刷新、60 秒时钟、visibility 监听及卸载清理，外部看板仍先取得 token 再打开页面。

本轮没有修改 API facade、后端业务、包清单或锁文件。既有查询上限、日期生成、异常提示及统计口径保持基线行为，未顺带调整算法。

运行门禁历史边 **122 → 81**，仅删除本批 41 项；剩余摘要、纯工具白名单和 bootstrap digest 保持原值。Task 0 原始台账保留 **127 条 / 60 个消费文件**，仅更新本批 41 项状态和证据路径。

## 本次实际验证

固定工具链：Node **24.22.0**、npm **11.19.1**、Python **3.12.10**。执行 `npm ci` 后，先在原代码上通过保护测试，再进行迁移。

| 检查 | 本次结果 |
|---|---|
| 修改前定向行为基线 | 3 个文件 / **50 passed**，其中新增 36 项行为保护测试 |
| 修改后同组测试 | 3 个文件 / **50 passed** |
| `npm run verify:frontend` | 退出码 0，包含以下架构、单测、E2E 和生产构建 |
| 工具链 fixture | 21 passed |
| 后端架构检查 | 32 passed |
| API facade | 34 namespaces / 455 unique domain methods，通过 |
| 前端导入环 | 242 文件 / 551 内部边，无环 |
| 前端分层 | **60 fixture passed**；242 文件 / 550 边 / 81 冻结历史边 |
| 全量前端单测 | **57 个文件 / 401 passed**，较本批基线增加 36 项 |
| E2E | **25/25 passed**，1.9 分钟，无失败重试 |
| 前端生产构建 | 成功，323 模块，最终构建 920 ms |
| 报表、统计及导出 API 契约 | **9 passed**，3.44 秒 |
| 全范围等价检查 | 20 个 Vue 模板/CSS 原字节一致；setup 参数及完整 body、顶层 helper、组件注册及迁移后的 imports AST 一致 |
| 共享模块/台账检查 | 共享实现等价；门禁精确删 41；台账仅改本批 41 对状态/证据，原盘点未删减 |
| 空白检查 | 最终暂存区 `git diff --cached --check` 通过 |

API 契约命令：`python -m pytest -q tests/test_reports_contracts.py tests/test_stats_contracts.py tests/test_export_contracts.py`。本批没有后端业务变更，未重复运行全量后端，历史全量测试数量不作为本次结果。

新增分层负向 fixture 遍历全部 22 个消费文件，恢复任一原始历史边均必须被阻断。新增 36 项组件行为测试通过 Vue 消费入口执行，覆盖 API 参数、响应式刷新、失败数据保留、实际 CSV Blob 内容、统计计算及首页生命周期；既有 14 项日报明细/CSV 安全测试继续通过。

E2E 在本地 4193 端口运行，数据库由 `scripts/e2e_server.py` 的隔离测试入口设置，静态目录由测试脚本创建并清理；没有访问生产数据库。现有 25 项浏览器用例主要覆盖库存及排程，报表和统计新增行为由上述组件及 API 契约测试保护，不将其表述为新增报表浏览器用例。

最终各套验证均无失败或跳过；保留 E2E 环境的 `NO_COLOR` / `FORCE_COLOR` 提示。迁移产生的 5 个新文件继承了行末空格，已仅作格式清理并重新核验 AST 等价。

## Brooks-Lint Review

**Mode:** PR Review

**Scope:** Task 2C 本地 diff；大批量语义迁移，重点抽样审核日报权限/导出、工作台筛选、首页生命周期、共享 helper 和门禁，并对全部 20 个 Vue 执行 AST/模板等价校验。

**Health Score:** 100/100（仅本批 diff）

本地审核通过，未发现新增生产行为缺陷或提交阻断项；此结论不代替独立 PR 批准。

### Findings

没有新增 Critical、Warning 或 Suggestion。依赖方向为 View → Composable → API facade / 应用支持模块，未新增 HTTP client 直连、循环依赖、复制实现或门禁例外。

### Summary

本批 diff 超过 500 行，规模本身是 Change Propagation 的复核信号；涉及文件均属于已冻结的同一报表迁移批次。通过逐模块保留行为、全范围 AST 对比和新增行为测试降低审核遗漏风险，后续仍按独立 PR 审核，不将其他批次混入本次提交。既有长协调方法的语义与复杂度未改变，本阶段不声称已完成统计算法拆分。

## 原始证据与提交边界

原始日志位于仓库外：
`C:/Users/dubin/Documents/生产管理系统升级版/.architecture-audits/20261015-task2c-report-layers/`。

| 证据 | SHA-256 |
|---|---|
| `baseline-behavior.log` | `212ff984d3296e1127b21b4fa4cecc83aeb67bbe6a379fb489ca85edae9c1f87` |
| `targeted-final.log` | `cdc2568836643bbfbc9cff013d9ab2de65f8320a22a5b9fec0d9032c10e677cf` |
| `verify-frontend.log` | `ff99d01eb4b841a5831567d8a60e3fb5b9cdb4a770e2e3005b11b4d532caf80c` |
| `report-api.log` | `44bc53bbf4285567eaac7b1a0b3a997c53107405d0f479f89d04d6aae7641caf` |
| `equivalence.log` | `98f1552fd0d37d21011cba0a15bf3409e806a880b8df9fde3f08a7ef3b8bc2c5` |

提交仅包含本批消费文件、Composable 与共享模块迁移、四个测试文件、门禁 41 项删减、原始台账本批状态及本报告。排除 `.brooks-lint-history.json`、Task 0 其他报告、`.tmp-*`、临时部署脚本、原始日志、依赖、数据库和构建/E2E 产物。

提交前再次只读核实 GitHub `master` 仍为上述基线。没有执行生产部署。
