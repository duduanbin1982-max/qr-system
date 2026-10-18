# Brooks-debt Task 2B：排程和甘特图历史依赖迁移

## 范围与状态

- 实施日期：2026-10-15，Asia/Shanghai。
- 基线：Task 2A / PR #101 合并后核实的 GitHub `master`，`62ebbac7f3ed9267b1824ceb25c148ba724e2c31`。
- 独立分支：`codex/brooks-debt-task2b-schedule-layers`。
- 本批状态：本地实现、验证和正式 diff 审核已通过，进入提交准备；尚未 commit、push 或创建 PR，未执行生产部署。

| 追踪项 | 消费文件 | 移出的直接依赖 |
|---|---|---|
| D05-007 | `frontend/src/components/schedule/ScheduleCapacityDashboard.vue` | `lib/api.js` |
| D05-008 | 同上 | `lib/store.js` |
| D05-026 | `frontend/src/views/GanttChart.vue` | `lib/api.js` |
| D05-027 | 同上 | `lib/store.js` |

Task 2A 已合并；本报告只记录 2B。Task 2C–2F 仍待分别实施、审核、提交和合并，D05 整体保持未关闭。原始台账的批次依赖保持有效，下一批须在本批合并并通过回归后开始。

## 实施与行为保护

新增 `useScheduleRevisionComparison()`，承接版本查询、前一版本选择、保存的动态重排差异及兼容 payload 解析。保留历史查询 `limit: 100`、版本明细 `limit: 1000`、字段比较顺序、顶层字段优先级、错误提示和 loading 释放行为。

新增 `useSchedulePriority()`，承接优先级抽屉状态和保存协调。保留 `expected_priority_version` 的数值转换及默认值、重复提交保护、失败保留输入、成功关闭抽屉及订单/容量视图刷新。页面继续转发模拟重排和工序查看操作。

两个 Vue 消费文件只通过 Composable 协调上述操作。API facade、后端、包清单和锁文件保持基线内容；两个文件的模板、样式及 script 以外内容经逐字节比较完全一致。

运行门禁的历史边由 **126 → 122**，只删除上述四项。其余摘要、白名单和 checker 的 bootstrap digest 保持原值。Task 0 原始盘点仍保留 **127 条 / 60 个消费文件**，只更新四项的 `status` 和 `evidence`，没有删除追踪记录。

新增页面行为测试覆盖版本切换、首版无前驱、查询失败后重新打开、保存证据优先、坏 JSON、顶层覆盖、新增/移除工序、优先级版本参数、重复提交、失败重试、权限及其他抽屉操作。UTC/上海等值时间样本保护既有显示日期，不改变原有版本差异对时间字符串的比较规则。

补齐甘特图测试替身的必填 props、响应式状态和页面方法；console spy 保留原输出。Task 0 记载的历史 Vue warning 在本次修改前基线中未复现，本次定向和全量日志也没有 Vue warning，不将其表述为已复现并修复的 98 条警告。

门禁新增两个真实消费文件的负向 fixture：恢复任一直接 API 或 store import 均须失败；合法的 View/Component → Composable → API facade 链通过。

## 本次实际验证

使用 Task 1 固定工具链 Node **24.22.0** / npm **11.19.1**，Python **3.12.10**。验证均使用本地隔离数据。

| 检查 | 实际结果 |
|---|---|
| 修改前定向基线 | 2 个文件 / 10 passed；development 模式甘特图另 7 passed |
| 修改后定向行为测试 | 2 个文件 / 21 passed |
| `npm run verify:frontend` | 退出码 0；包含架构、全量单测、E2E 和生产构建 |
| 工具链 fixture | 21 passed，0 failed / skipped / cancelled / todo |
| 后端架构检查 | 32 passed |
| API facade | 34 namespaces / 455 unique domain methods，通过 |
| 前端导入环 | 222 个文件 / 535 条内部边，无环 |
| 前端分层 | 37 fixture passed；534 条边 / 122 条冻结历史边 |
| 全量前端单元测试 | 56 个文件 / 365 passed，较本批基线增加 11 项；0 failed / skipped / todo |
| E2E | 25/25 passed，0 failed / skipped，无失败重试；用时 1.8 分钟 |
| 前端生产构建 | 成功，303 个模块；最终 Vite 构建 749 ms |
| 排程后端 API/工作流回归 | 23 passed，3.31 秒 |
| 等价迁移校验 | 版本组件迁出的 9 项声明 AST 一致；优先级 4 项声明及打开动作在显式参数替换后 AST 一致 |
| 数据和范围校验 | 两个 Vue 模板/CSS 原字节不变；门禁仅删 4 条，其余摘要一致；原始台账仅改 4 对状态/证据 |
| 空白检查 | `git diff --check` 通过 |

后端定向命令为 `python -m pytest -q tests/test_schedule_order_priority_v084.py tests/test_production_node_schedule_workflow.py tests/test_schedule_revision_service.py`。本批没有后端业务变更，未重复运行全量后端，不将历史全量数算作本批结果。

E2E 使用本地 4192 端口、仓库外隔离数据库及独立静态目录。原有用例覆盖节点工作台的桌面/移动端、焦点、关闭及排程查询刷新；版本和优先级的新增交互由本批组件行为测试覆盖。

早期验证出现两类测试实现错误：定向测试将数值订单 ID `12` 误期望为字符串，初次为 20 passed / 1 failed；架构 fixture 将完整 Vue 文本交给 JS parser，初次为 35 passed / 2 failed。已修正测试期望和 script 提取，再运行全部通过，没有为消除这些失败修改生产行为。最终全量验证无失败、skip 或 xfail；保留 E2E 的 `NO_COLOR` / `FORCE_COLOR` 环境提示。

## 原始证据与交付范围

原始日志位于仓库外 `C:/Users/dubin/Documents/生产管理系统升级版/.architecture-audits/20261015-task2b-schedule-layers/`，不进入提交。

| 日志 | SHA-256 |
|---|---|
| `verify-frontend.log` | `5d062a6879bc0f8a93d19a2a2213ac811511cf6adb09168db2b1815f289fc96e` |
| `schedule-api.log` | `24267c572a55307f9866b691918cd883139b2c777349c9ad5a5867b2850ef8f0` |
| `targeted-final.log` | `8791d16cc467272a8da10d3cb05ce1af8d142d75e9954bef690b8845f55cd4b3` |
| `layer-fixtures-final.log` | `7cd148d5f018abb811943eb5638435b4b38e599ffa192fcd8c676c1fd3f64690` |
| `equivalence.log` | `3ffc16cdabee51b5d9a6aea1c93ae98f8a99356f057ce581ea651717648707b0` |

交付范围共 10 个文件：两个消费文件、两个 Composable、三个测试文件、运行门禁删减、原始台账四项状态及本报告。排除 `.brooks-lint-history.json`、Task 0 其他报告、原始审计报告、`.tmp-*`、临时部署脚本、日志、依赖、数据库和构建/E2E 产物。

## 正式本地审核与提交准备

- 审核日期：2026-10-15，Asia/Shanghai；模式：PR Review；范围：上述 10 个文件。
- 审核结论：通过，未发现新增 P1/P2 或提交阻断项；Health Score 为 100/100，仅代表本批 diff。
- 审核轮实际重跑：定向行为测试 21 passed、后端架构 32 passed、工具链 fixture 21 passed、前端分层 fixture 37 passed；API facade、导入环和等价迁移校验均通过。
- 已逐一核验上述五份日志的 SHA-256；全量前端 365 passed、E2E 25/25 和生产构建使用本批已完成的验证证据，没有重复计算历史结果。
- 提交准备仅更新本报告及 D05-007、D05-008、D05-026、D05-027 的状态为 `local_reviewed_pending_commit`，审核后的运行代码和测试未再修改。
- 建议提交信息：`refactor(frontend): move schedule coordination into composables`。后续推送使用 `github` remote，PR 目标为 `master`。

commit、push、PR 和合并记录待实际发生后登记；本地验收不代表生产已发布。
