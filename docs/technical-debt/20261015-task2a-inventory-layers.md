# Brooks-debt Task 2A：库存前端历史依赖迁移

## 范围与状态

- 实施日期：2026-10-15，Asia/Shanghai。
- 基线：实施时已核实的 GitHub `master`，Task 1 / PR #100 合并提交 `d47fd3f95b5d1706802fac79b29f90c8bb8c05ba`。
- 独立分支：`codex/brooks-debt-task2a-inventory-layers`。
- 本批对应 D05-004：`ProductInventoryDrawer.vue → lib/api.js`，仅涉及一个历史消费文件、一条历史边。
- 状态：本地实现和验证完成，等待正式 diff 审核；未提交、推送或创建 PR，未关闭 D05，未执行生产部署。

Task 2 按冻结方案分为 2A–2F。本批不包含排程、报表、绩效、主数据和应用入口的依赖迁移；下一批 2B 须在本批审核、独立提交、PR 和合并后开始。

## 实施内容与行为保护

新增 `useProductInventoryDrawer(props)`，接收组件原有响应式 props，承接兼容分组、预览、正式出库、历史查询、撤销与详情导出状态及操作。组件通过 Composable 调用 API facade，不再直接依赖 facade；模板、样式、props 和关闭事件保持原字节。

保留原 API 方法、参数、默认值、watch 时机及错误提示。正式出库继续提交服务端 `preview_digest` 和预览解析后的兼容键；原幂等键、撤销确认、功能开关和导出权限语义不变。没有修改 API 实现、后端业务、数据库或附件。

运行门禁中的历史边由 **127 → 126**，仅删除 D05-004 对应项，其余 126 条及摘要不变。没有扩大白名单、重算剩余引用摘要或修改 checker 的 bootstrap digest。Task 0 原始逐边盘点仍保留 127 条 / 60 个消费文件，只为 D05-004 更新本地状态和证据路径，未删除追踪记录。

新增组件行为测试覆盖预览等待及重复点击、人工来源筛选、出库 digest 和幂等参数、失败保留预览、历史失败、产品切换、功能开关、撤销确认/取消/失败，以及导出权限和兼容分组。新增门禁负向 fixture：将直接 API import 注回已迁移组件时必须失败。

修正库存 CSV 既有测试缺少 `window.open` 替身的问题，使用测试局部 spy 并断言 URL；不屏蔽 jsdom 日志。全量验证中未再出现 `Window.open()` 未实现提示。

## 本次实际验证

全部测试在本地隔离数据上执行，没有访问生产主机。统一采用 Task 1 固定工具链 Node 24.22.0 / npm 11.19.1；本机 Python 3.12.10。

| 检查 | 实际结果 |
|---|---|
| `npm ci --no-audit --no-fund` | 成功，安装 186 个包 |
| 库存前端定向单测 | 11 个文件，44 passed |
| `npm run verify:frontend` | 退出码 0；20:08:55–20:11:52 |
| 工具链 fixture | 21 passed，0 failed / skipped / cancelled / todo |
| 后端架构检查 | 32 passed |
| API facade | 34 namespaces / 455 unique domain methods，通过 |
| 前端导入环 | 220 个文件 / 533 条内部边，无环 |
| 前端分层 | 35 fixture passed；532 条边 / 126 条冻结历史边 |
| 全量前端单元测试 | 56 个文件 / 354 passed，较 Task 1 增加 15 项；0 failed / skipped / todo |
| E2E | 25 passed；0 failed / skipped，无失败重试；用时 1.8 分钟 |
| 前端生产构建 | 成功，301 个模块；最终 Vite 构建 860 ms |
| 库存后端 API 回归 | 38 passed，12.96 秒；分配预览、产品查询、筛选三个测试文件 |
| 等价迁移与范围校验 | 迁出状态、watch 和操作的规范化 AST 与原组件一致；模板/CSS 原字节不变；其余 126 条门禁摘要及 127 条原始台账记录保持不变 |
| 空白与文件范围检查 | `git diff --check` 通过；待审 9 个文件，没有临时文件或构建产物 |

E2E 使用本地 4191 端口、独立临时数据库和静态目录，包含原有库存移动端详情入口、筛选/冻结列、统计卡片联动用例。E2E 未替代新增的出库/撤销组件行为测试。

本批没有后端业务改动，未重复运行全量后端；32 项架构和 38 项库存 API 为本次实际后端覆盖范围，不将 Task 0 历史全量数计入本批。本次上述检查没有失败、skip 或 xfail。保留 E2E 的 `NO_COLOR` / `FORCE_COLOR` 环境提示；安装时既有 glob 弃用提示没有通过升级依赖消除。

## 原始证据与交付边界

原始日志保存在仓库外的 `C:/Users/dubin/Documents/生产管理系统升级版/.architecture-audits/20261015-task2a-inventory-layers/`，不进入提交。

| 日志 | SHA-256 |
|---|---|
| `verify-frontend.log` | `88bdacf9c1e48622dcaaf462e1f3a0e94a3b3a25ca496e59a80c6d9cd4d51d59` |
| `inventory-api.log` | `e33244899eb393d35c49405df7e304943306441b1a505bc338bc0d12af5dec5f` |

提交范围仅为本批组件、Composable、相关行为/架构测试、运行门禁删减、D05-004 台账状态及本报告。排除 `.brooks-lint-history.json`、原始审计报告、Task 0 其他报告、`.tmp-*`、临时部署脚本、日志、数据库、依赖、构建和 E2E 产物。

正式 diff 审核、commit、push、PR、独立审核和合并记录待后续实际发生后登记。本地验证不代表已合并或已发布；生产发布仍须单独核实维护窗口、幂等键、生产 SHA、回退 SHA、操作人/批准人和发布范围。
