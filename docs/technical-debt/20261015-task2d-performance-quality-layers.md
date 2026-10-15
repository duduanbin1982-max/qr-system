# Brooks-debt Task 2D：绩效工资、工时和质量历史依赖迁移

## 范围与基线

- 实施日期：2026-10-15，Asia/Shanghai。
- 基线：实施时已核实的 GitHub `master`，`c1730882ade5f490e9ffea39923722329f1f5e0f`（Task 2C / PR #103 合并提交）。
- 独立分支：`codex/brooks-debt-task2d-performance-quality-layers`。
- 状态：实现、验证和正式本地 diff 审核通过，进入提交准备；没有提交、推送、创建 PR 或修改生产环境。
- 本批仅治理 D05 / Task 2D 的 **48 条历史边、21 个 Vue 消费文件**。Task 2E 的 19 条和 Task 2F 的 14 条继续待处理，D05 整体未关闭。

## 实施与行为保护

21 个 Vue 消费文件保留模板、样式、组件注册及 props / emits / expose 声明，将查询、状态、权限、导航和操作协调迁到对应 Composable。所有入口同步调用，传递原响应式 props 对象及 emit，保留 watch、生命周期、父子组件 ref 和公开操作方法。

| 消费范围 | 新协调入口 |
|---|---|
| 绩效 `PerformancePage.vue` | `composables/performance/usePerformanceWorkspace.js` |
| 工资工作台、旧单价页、历史单价确认、版本编辑、调整、个人工资、异常、台账、版本及工序工资，共 10 个消费文件 | `composables/wage/use*.js` |
| 工时工作台、审核、记录、复核弹窗和标准工时，共 5 个消费文件 | `composables/workTime/use*.js` |
| 工序质量处置、工序质量评价、质量管理、检验和返修，共 5 个消费文件 | `composables/quality/use*.js` |

API facade、权限和通知等依赖保留在 Composable 内；Vue 不再直接依赖本批被治理的 `lib` 模块。标准工时模板使用的纯展示 helper `routeSeqLabel` 由 Composable 返回，未将 API facade 等基础设施对象暴露给模板。

保留的行为包括：绩效查询及来源展示；工资权限、调整及冲销金额、个人工资加载错误、异常原因和审批确认、台账导出及版本冲突、精确路线版本覆盖和历史单价草稿幂等；工时筛选、低于 80% 的审核边界、订单工序选择、标准工时回退提示、历史版本编辑限制、复核表单重新加载和保存事件；质量豁免及处置权限、预览及原因校验、分页与勾选、错误重试、检验导出、返修旧请求响应处理及批量部分失败。

本批通过 AST 迁移保持原协调逻辑、查询参数、统计和错误处理口径，没有同时拆分计算算法。没有修改后端实现、API facade、包清单或锁文件。

门禁历史边 **81 → 33**，只删除本批 48 项；剩余摘要、纯工具白名单及 bootstrap digest 保持不变。Task 0 原始盘点仍保留 **127 条 / 60 个消费文件**，仅更新本批 48 项的状态为 `local_reviewed_pending_commit`，并写入本报告的证据路径。

## 本次实际验证

固定工具链：Node **24.22.0**、npm **11.19.1**、Python **3.12.10**。安装依赖后，先运行现有单测基线及新增保护测试，再迁移生产代码。

| 检查 | 本次结果 |
|---|---|
| 修改前全量前端单测基线 | **57 个文件 / 401 passed** |
| 修改前定向行为保护 | 6 个文件 / **37 passed**，其中新增 27 项 |
| 修改后同组行为保护 | 6 个文件 / **37 passed** |
| 最终 `npm run verify:frontend` | 退出码 0，包含以下架构、单测、E2E 和生产构建 |
| 工具链 fixture | **21 passed** |
| 后端架构检查 | **32 passed** |
| API facade | 34 namespaces / 455 unique domain methods，通过 |
| 前端导入环 | 263 文件 / 572 内部边，无环 |
| 前端分层 | **82 fixture passed**；263 文件 / 571 边 / 33 冻结历史边 |
| 全量前端单测 | **60 个文件 / 428 passed**，较本批基线增加 27 项 |
| E2E | **25/25 passed**，1.7 分钟，无失败重试 |
| 前端生产构建 | 成功，344 模块，最终构建 825 ms |
| 相关后端 API 契约 | **93 passed**，34.80 秒 |
| 全范围等价检查 | 全部 21 个 Vue 的模板/CSS 字节一致；原 setup 协调 AST、imports、options / macros、同步委托及返回绑定一致 |
| 台账及门禁检查 | 精确移除 48 项例外；台账仅改对应状态/证据；原始盘点及其余摘要不变 |
| 空白检查 | `git diff --check` 和新增代码行末空白检查通过 |

后端契约执行命令：

```bash
python -m pytest -q \
  tests/test_performance_contracts.py \
  tests/test_performance_permissions.py \
  tests/test_work_time.py \
  tests/test_work_time_source_contracts.py \
  tests/test_payroll_ledger.py \
  tests/test_process_quality_evaluation.py \
  tests/test_quality_management.py \
  tests/test_quality_review_workflow.py \
  tests/test_pending_route_price_api.py
```

本批没有后端实现变更，运行了上述定向契约和后端架构测试，没有重复运行全量后端；历史全量数量不作为本次证据。

新增的 3 个行为测试文件通过真实 Vue 消费入口执行，共 27 项：工资 13 项、工时 7 项、质量 7 项。测试覆盖响应式 props 变更、父子组件公开方法、权限、API 参数、失败处理及成功事件。既有绩效、价格版本和工时复核测试同组通过。

分层负向 fixture 遍历全部 21 个消费文件，并逐一恢复其原始依赖，全部 48 条边均必须被阻断。全范围等价检查额外核验 script setup 的 props / emits / expose 和模板引用的导入 helper，避免只检查 setup 主体而遗漏模板绑定。

E2E 使用 `127.0.0.1:4173` 的隔离服务与测试数据库，未访问生产数据。沿用现有库存、排程、扫码、审批及工资单价版本浏览器用例；没有将其表述为全部 21 个消费页面的新增浏览器验收。

最终验证没有失败、跳过或预期失败。日志保留隔离 Flask 开发服务器提示及 `NO_COLOR` / `FORCE_COLOR` 环境提示。

## 原始证据与后续边界

原始日志和只读等价校验脚本位于工作树外：
`C:/Users/dubin/Documents/生产管理系统升级版/.architecture-audits/20261015-task2d-performance-quality-layers/`。

| 证据 | SHA-256 |
|---|---|
| `baseline-unit.log` | `cd84c443137ef418e2fac9b5cddef8f71e982d395c86f05a3f3d379c77c8971c` |
| `baseline-behavior.log` | `acc3c8438a5e3f0ebff96bb1dbef6072f8b53e8cd350d69fa4e318149e87c6ed` |
| `targeted-behavior.log` | `e1f72222bafa4d0ee09ccb7c38ba4c30a1e1673fe885c8651961a5ce0de59e05` |
| `verify-frontend-final.log` | `1fc80875c94d517c9f631ac13998de206db18abb74cfb0f0733ad0aab7053327` |
| `domain-api.log` | `7c6b277d9a44ec4877ea086e540c36115a5ec5fd179164ec55046078f8957bcb` |
| `equivalence.log` | `91b40aefd8d4cb69f82b6a32561e5577c45e010292b1cac7dc265eff55003b7b` |
| `verify-equivalence.mjs` | `2afc6292ec19fbd856f4bdd28b0d13c200cf2ce52fba9615314755b629e14568` |
| `template-bindings.mjs` | `fc5447d063f8c382481eef5d926a898bf7b5560156ce4b51756cd23b33822afb` |

本批变更范围为 49 个文件：21 个 Vue、21 个 Composable、3 个单测文件、分层门禁测试、门禁基线、原始台账及本报告。排除 `.brooks-lint-history.json`、Task 0 其他报告、`.tmp-*`、临时部署脚本、原始日志、依赖、数据库及构建/E2E 产物。

## 正式本地 diff 审核与提交准备

2026-10-16 完成正式本地 diff 审核，结论为通过：Critical 0、Warning 0、Suggestion 0；本次差异的 Health Score 为 100/100。人工重点核验工资版本、质量处置及权限、工时标准及复核、父子组件公开方法，并通过全范围 AST 比对核验全部 21 个消费文件。差异超过 500 行，人工审核以高风险路径抽查为主，未宣称逐行穷举。

审核期间重新运行 6 个文件的定向行为回归（37 passed）、前端分层门禁（82 passed）、全范围等价校验和空白检查，均通过。正式审核报告保留在上述工作树外证据目录的 `formal-local-review.md`。

提交准备仅更新本批 48 项台账状态及本报告，并按明确清单暂存 49 个文件；其余批次台账、历史例外摘要和生产代码保持审核时内容。暂存区须通过范围、空白及台账等价检查，继续排除临时文件和原始日志。

建议提交信息：`refactor(frontend): migrate performance wage and quality dependencies`。

下一步待单独授权后执行 commit、push 和创建合并到 `master` 的 PR。本次本地审核不代替独立 PR 审核、批准或生产发布授权。
