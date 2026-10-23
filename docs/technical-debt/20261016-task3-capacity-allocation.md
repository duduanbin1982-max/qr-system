# Brooks-debt Task 3：纯容量分配策略拆分

## 基线与范围

- 实施时核实并同步的 `master`：`d81ba2b30af21bc2af3ed05b92b3d214cf8e39c6`（PR #107 合并提交）。
- 独立分支：`codex/brooks-debt-task3-capacity-allocation`。
- 本批处理 D01 的容量分配热点；冲突检测等后续职责仍由后续 Task 处理，D01 不据此整体关闭。
- 已完成正式本地 diff 复审，进入提交准备；此前两项 P2 门禁缺口已关闭，本轮未发现新增必须修复的问题。尚未 commit、push、创建 PR 或修改生产环境。
- 变更仅涉及领域分配器、规划 DTO、保护样本、架构检查及本报告。Service、Repository、事务编排、数据库、前端和发布工具没有修改。

## 分批迁移与策略边界

修改生产代码前，先从原实现生成 `tests/capacity_allocation_behavior_v1.json`，冻结 35 个输入的完整结果、候选回调轨迹、异常类型/消息/领域码/详情和部分占用证据。此后各批沿用同一文件，没有重新生成基准来接受差异。

| 批次 | 组件 | 输入、输出及保留的行为 | 当批验证 |
|---|---|---|---|
| 0 | 原实现保护样本 | 候选顺序、舍入、准备换型、占用、返回顺序和失败边界 | 108 passed |
| 1 | `CandidateNodeDecision` | 候选日历事实转为 `CapacityCandidate`；按完成时刻、节点 ID 选择；仅跳过回调抛出的既有日历拒绝异常 | 108 passed |
| 2 | `QuantitySplitStrategy` | 不可变事实和节点进度转为分配候选；保留 `ceil(剩余数量 / 节点数)`，每节点仅首次计准备时间 | 108 passed |
| 3 | `SerialExclusiveStrategy` | 归一化序列号组后，整组选择单一节点；保留空白、重复、数量不符和无可用节点的处理 | 108 passed |
| 4 | `BatchAllocationStrategy` | 数量及能力配置转为 `CapacityDemand`；保留批量上限、配置校验顺序、批次时长及首次换型 | 108 passed |
| 5 | `AllocationResultAccumulator` | 接收候选，累积本次调用的占用和数量，产出 `CapacityAllocationResult`；保留展平顺序及失败占用证据 | 108 passed |

执行顺序保持为：归一化数量和节点 → 校验序列号 → 生成事实及节点进度快照 → 普通数量或序列组策略 → 批次/独占需求 → 日历候选评估 → 最早完成及节点 ID 决策 → 记录分配和占用 → 数量守恒检查 → 返回兼容结果。

普通数量策略每轮重新评估全部节点。序列件策略只作一次整组决策，不调用普通数量拆分。批次配置校验仍先于序列组超出批量上限的排除，避免改变原有异常行为。

`allocate_split_on_nodes()` 从 252 行缩为 53 行；新增策略中最长方法为 34 行。上述行数均按 AST 的函数起止位置计算，目的在于降低单个职责的阅读负担，不以总代码行数下降作为验收标准。

## 不可变边界与兼容性

在已有 `schedule_planning.py` 中复用递归冻结基础能力，增加 `CapacityAllocationFacts`、`CapacityNodeFacts`、`CapacityDemand`、`CapacityCandidate` 和 `CapacityAllocationResult`。嵌套映射、列表和集合分别冻结为只读映射、tuple 和 frozenset，并与调用方的可变输入脱离。

策略间传递冻结快照；可变累积状态仅属于单次调用的结果汇总器。日历回调获得独立的节点和占用副本。公共分配器返回时恢复原有 `segments`、`allocations`、`occupancy_additions` 结构，保留整数节点键、原生 datetime 以及占用区间 tuple；不经 JSON 转换处理运行时事实。

保留的兼容细节包括：

- 完成时刻相同按节点 ID 选择；候选输入顺序不改变决策。
- 结果 segments 按原节点顺序展平，allocations 保留实际选择顺序；重复节点 ID 仍保留首个位置和最后一个值。
- 零数量在节点和序列号校验前返回空结果。
- 普通分配最终校验原始数量，序列组校验归一化后的整数数量。
- 回调内部既有日历拒绝异常可跳过候选，空回调列表的 IndexError、配置错误及非预期异常仍向外传播。
- 发生部分失败时，继续向原异常附加 `capacity_occupancy_additions`，不丢失已计算的占用证据。
- 原回调中无效时间文本的既有传递行为由样本冻结；本次重构未夹带新的校验规则。

既有生成、重排和纯规划回归继续保护跨班次、跨天、周末、停机、外协不占内部容量、旧版本不可变、失败审计、SAVEPOINT 和历史 `result_json` 列表格式。

## 架构门禁

数据库访问禁令从单个分配器文件扩展为递归检查全部 `modules/domain/**/*.py`，涵盖新增策略、共享 DTO 和未来子目录，不依赖固定文件清单。

检查静态及常量动态导入数据库驱动/Service/Repository/迁移/框架、数据库调用方法、可执行 SQL 和 DDL 字符串。最初增加 16 项嵌套违规样本及 1 项文档误报保护。真实 Python docstring 不作为可执行 SQL；函数返回值和带 docstring 的函数中声明的 SQL 仍须被阻断。原 Service/Repository 字符串检查行为不变。

正式 diff 审核发现的两项 P2 已补齐：静态和动态导入统一匹配仓库实际使用的 `modules.migration_*`，同时保留 `modules.migrations` 检查；动态导入识别位置及关键字参数，并按文件包路径、显式包名或 `__package__` 解析相对路径。`import_module` 使用 `package` 语义，`__import__` 使用 `globals` 和 `level` 语义，分别处理，兼容导入别名与包的 `__init__.py`。扫描仅解析 AST，不加载目标模块或执行被扫描代码。

先加入反例验证原门禁漏检（24 failed / 8 passed），再修复检测。最终新增 6 项真实迁移模块反例、20 项相对或关键字动态导入反例以及 11 项合法领域/标准库导入样本；反例必须报告目标模块，合法样本必须没有违规。此次修复仅涉及架构测试与本报告，没有再次修改生产分配器。

## 验证证据

原始日志存放在工作树外的 `.architecture-audits/20261016-task3-capacity-allocation/`，不进入提交。

验证环境：Windows、Python 3.12.10。架构检查按仓库固定版本使用 Node 24.22.0 / npm 11.19.1，仅为本次检查进程设置 PATH；未修改工具链门禁、依赖清单或锁文件。

| 检查 | 实际结果及执行阶段 |
|---|---|
| 修复两项 P2 后，分配、生成、重排、不可变性和架构定向回归 | 164 passed，19.87 秒；日志 `10-review-fixes-regression.log` |
| 正式复审独立复验 | 定向回归 164 passed，17.31 秒；重新加载基线分配器比较 35/35 完整轨迹与 golden 一致；`npm run check:architecture` 再次通过 |
| 重新载入基线 SHA 原始分配器，与当前实现比较完整轨迹摘要 | 35/35 一致，未重生成 golden |
| 固定种子扩展比较，混合节点、批量、序列组、工时、周末及失败配置 | 120/120 原实现与新实现完整轨迹摘要一致，seed=20261016；补充实验，不计入 pytest 用例数量 |
| 全量后端 `python -m pytest -q -ra tests` | P2 门禁修复前运行：1966 passed / 6 skipped，679.12 秒；0 failed / xfailed / xpassed；测试门禁修复后未重复运行全量后端 |
| 修复两项 P2 后，锁定 Node 24.22.0 / npm 11.19.1 的 `npm run check:architecture` | 通过；日志 `11-review-fixes-architecture.log` |
| 修复两项 P2 后，工具链契约 / 后端架构 / 前端分层 fixture | 21 / 86 / 98 passed |
| API facade | 34 namespaces / 455 unique domain methods，通过 |
| 前端导入环 | 277 files / 587 internal edges，无循环 |
| 前端分层扫描 | 277 files / 586 edges / 0 frozen legacy edges |
| `git diff --check` 及新增文件空白检查 | 通过 |

本批没有前端运行时代码变更，未重复运行前端单元、构建或浏览器 E2E；API facade、前端导入环和分层门禁通过。

6 项跳过均来自既有 `tests/test_release_gate_bootstrap.py`：224、253 行各 1 项 Linux 目录持久化契约，241 行 1 项 Linux 文件系统契约，280 行 1 项 Linux 可执行测试运行器，299 行参数化的 2 项 Linux 发布演练。它们因当前 Windows 平台不具备对应运行条件而跳过，本批没有修改发布工具；这些跳过不记为通过，也不替代生产发布前适用的 Linux 验证。

## 交付边界

正式本地 diff 复审已通过；本次提交准备仅暂存 Task 3 的 12 个文件，并复核暂存区文件清单和空白检查。commit、push 和创建合并到 `master` 的 PR 待单独授权后执行。排程数据库、业务数据、服务状态和生产发布均不属于本次实施操作。`.brooks-lint-history.json`、Task 0 历史报告、`.tmp-*`、临时部署脚本、测试日志和构建产物不进入本批变更。
