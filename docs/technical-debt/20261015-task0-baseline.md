# Brooks-debt Task 0：行为基线与修复台账

## 冻结范围

- 核实日期：2026-10-15，Asia/Shanghai。通过 `git fetch github master` 和 `git ls-remote github refs/heads/master` 核实 GitHub；12:58、13:05 再核实，远端提交未变化。
- 基线提交：`d62a4eb95ccbf4273d1adfc3277b27fb00259abc`；提交时间 `2026-10-15T11:44:19+08:00`。
- 基线 tree：`33aa6018a833c59a7e4f75b84ad07086e64219b9`。
- 独立分支：`codex/brooks-debt-task0-baseline`，从上述提交创建，初始工作树干净。
- 关联审计：`BROOKS_DEBT_20261015.md`，SHA-256 `dabc2808e8ba1572cde54cb6bfb1d44d48216db5e95908f2a267c3fb25955f11`。沿用 D01–D07 编号，本阶段不重新评分，也不把建立台账视为债务已修复。
- 本阶段只增加文档、依赖清单及保护测试；业务实现、迁移、运行时前端、现有架构白名单和 golden fixture 不变。

本地隔离工作树为 `C:/Users/dubin/Documents/生产管理系统升级版/.worktrees/brooks-debt-task0-baseline`。原审计工作树的 `.brooks-lint-history.json` 及其他任务文件未纳入本阶段。

## 本次实际工具链

| 项目 | 实测 | 工程声明/说明 |
|---|---|---|
| 系统 | Windows 11，10.0.26200，AMD64；Git Bash | 本次所有 shell 命令经 Git Bash |
| Git | 2.55.0.windows.2 | 只向 GitHub 读取 master |
| Python / pytest / SQLite | 3.12.10 / 9.0.3 / 3.49.1 | 使用本地 Python 3.12；临时测试数据库 |
| Node / npm | 25.2.1 / 11.6.2 | `package.json` 声明 Node `>=20.19 <21`、npm `10.8.2`；差异登记为 D07 |
| Vite / Vitest / Playwright / Vue | 8.2.0 / 4.1.10 / 1.62.1 / 3.5.38 | 由当前锁文件 `npm ci` 安装 |

`npm ci --no-audit --no-fund` 成功，安装 186 个包。安装输出包含 `EBADENGINE` 及 `glob@10.5.0` 弃用提示；本阶段记录提示，不更改工具链或依赖。当前前端证据属于实测 Node 25 环境，不能替代 Task 1 在最终选定的受支持工具链下的复验。

| 冻结输入 | SHA-256 |
|---|---|
| `package.json` | `45cd67e51e96d059aa1f1366c3ab11ebcdb0abde69d5ffd842533dd24a833efe` |
| `package-lock.json` | `5beba390ded111f3e331b25a41c5de09dd65c10d26db84778f08c3adf75fe183` |
| `requirements.txt` | `f5c36b17c1b251727837aaf08b968cd4117fa0d8a8f9d8c570d3ed66b8b3522c` |
| `tests/schedule_capacity_behavior_v1.json` | `e7cbab5f52611d6dbca933ae80294cf61567392ffd585729f5d30596a6f21bd2` |
| `frontend/scripts/frontend-layer-baseline.json`（文件原字节） | `b50285a2f086067687be024599a6963e6d2abc3459d29c4fa44d77c9c51423b9` |

## 实际运行结果

下表区分未改动 master 的全量基线与 Task 0 新增保护测试。历史报告中的 `1900 passed` 不作为此次结果。每次命令、已捕获的时间、退出码、失败/跳过/预期失败及证据 SHA-256 登记在 [verification.json](20261015-task0/verification.json)；未捕获的安装起止时间明确记为 null，不根据文件时间推断。

| 检查 | 本次结果 | 范围 |
|---|---|---|
| 全量后端 `python -m pytest -q -ra tests` | 1894 passed、6 skipped；0 failed / errors / xfailed / xpassed；749.90 秒 | 收集 1900 项；在新增测试前已完成收集，用于原始 master 行为基线 |
| 全量前端 `npm run test:unit` | 55 个文件，339 passed；0 failed / skipped / todo | JSON 明细已保留 |
| E2E `E2E_PORT=4187 npm run test:e2e` | 25 passed；0 failed / skipped；未启用重试 | 本地服务、隔离数据库及独立静态构建目录 |
| `npm run build` | 通过；Vite 构建 1.52 秒 | 同时执行 API、导入环和前端层级门禁 |
| `npm run check:architecture` | 后端 32 passed；前端层级 fixture 34 passed | API facade 34 namespaces / 455 methods；前端 219 文件 / 532 导入边，无环；层级 531 边 / 127 条冻结历史边 |
| 两组补充保护测试 | 27 passed；0 failed / skipped / xfailed | `test_user_service_extended.py` + `test_production_node_legacy_write_guard.py`，其中新增 10 个参数化测试实例 |

全量后端命令运行时间为 `2026-10-15T12:52:46+08:00`–`13:05:25+08:00`。补充测试中的 17 项与原始全量基线重叠，不能把 27 直接累加为新的全量通过总数；未宣称在最终测试文件上重新执行过第二次全量后端。

六项跳过均来自 `tests/test_release_gate_bootstrap.py`，本次 Windows 环境不满足既有 Linux 条件，没有为本阶段新增 skip 或 xfail：

| 测试名称 | pytest 跳过原因 |
|---|---|
| `test_bootstrap_receipt_is_exclusive_and_preserves_approval` | Linux production durability contract |
| `test_bootstrap_rejects_symlinked_production_control` | Linux production filesystem contract |
| `test_receipt_persistence_failure_prevents_release_and_preserves_production` | Linux production durability contract |
| `test_locked_test_dependencies_are_only_linked_into_temporary_test_checkout` | Linux executable test runner |
| `test_real_launcher_preserves_facts_and_evidence_on_acceptance_and_rollback[accepted]` | Linux release rehearsal |
| `test_real_launcher_preserves_facts_and_evidence_on_acceptance_and_rollback[rollback]` | Linux release rehearsal |

发布工具维护角色应在 Task 9 的 Linux 隔离环境补跑这六项并保留证据；本次只取得 Windows 的实际基线，不表示 Linux 持久化、实际发布或失败回退演练已经通过。后端日志未出现 warnings summary。

原始日志、JUnit XML、Vitest JSON 保存在 `C:/Users/dubin/Documents/生产管理系统升级版/.architecture-audits/20261015-task0-baseline/`；Playwright HTML 保存在本工作树的 `playwright-report/`。这些运行产物不进入业务提交。测试只写本地临时数据库、测试附件和忽略的构建目录，没有访问生产数据库。

非失败输出也予以保留：前端单元日志出现 98 条 Vue warn，来自使用模拟 `useGantt` 状态的 `GanttChartProductionNodes.spec.js`，内容为未定义渲染属性及缺失 `form` prop；另有一次 jsdom `Window.open()` 未实现提示。分别交由 Task 2B 和 2A 在迁移前核对测试替身与行为断言，不通过屏蔽日志消除。E2E 还出现 `NO_COLOR` 被 `FORCE_COLOR` 覆盖的环境提示。这些提示不计作失败、跳过或已证明的生产故障。

## 行为保护样本

测试 node ID 均以仓库根目录为起点。下列既有样本保持原值；只有用户导入错误及旧产线拦截矩阵补充了断言。

| 领域 | 固定保护样本/测试 | 必须保持的行为 |
|---|---|---|
| 生成排程摘要 | `tests/test_schedule_capacity_characterization.py::test_generation_baseline_captures_multi_node_cross_day_risk_and_replay`；`tests/test_schedule_pure_planning.py::test_generation_summary_is_replay_stable` | 跨节点、跨天、数量守恒、风险、幂等；manifest/摘要一致；`schedule_runs.result_json` 仍为列表 |
| 缺工时阻断 | `tests/test_schedule_capacity_characterization.py::test_blocking_baseline_captures_missing_work_time_without_fabrication` | 不伪造工时或排程；阻断码及摘要不变 |
| 动态重排摘要 | `tests/test_schedule_capacity_characterization.py::test_dynamic_replan_baseline_captures_report_rework_lock_and_replay`；`tests/test_schedule_pure_planning.py::test_dynamic_replan_summary_is_replay_stable` | 正常报工、未结返工、锁定、剩余数量及旧版本不变 |
| 事务/证据失败 | `tests/test_schedule_replan_use_case.py::test_evidence_failure_keeps_failed_ledger_and_old_projection`；characterization 的 `test_failure_and_publication_baseline_preserves_auditable_state` | 失败审计、SAVEPOINT、旧正式投影及不可变版本；保存版本和证据必须原子完成 |
| 绩效来源与 manifest | `tests/test_performance_history_migration.py::test_history_manifest_matches_exact_pre_refactor_characterization`、`test_historical_scrap_rework_and_inspection_sources_are_controlled`、`test_unattributed_historical_quality_never_auto_maps_similar_candidates` | 来源计数、覆盖/缺失、跨月归属、歧义人员不自动归属、旧修订不变 |
| 绩效快照与短事务 | `tests/test_performance_history_planning.py::test_month_planner_uses_snapshots_without_database_access`；migration 的 `test_apply_rejects_source_snapshot_drift_before_writing`、`test_apply_generates_only_reviewable_v2_and_is_idempotent` | 递归不可变、快照漂移拦截、按月写入、幂等，不因后续拆分退化 |
| 用户权限 | `tests/test_user_service_extended.py::test_admin_accounts_require_actual_admin_for_every_mutation`、`test_role_changes_require_admin_and_batch_is_atomic`、`test_privileged_import_requires_admin_and_rolls_back_file` | 真管理员约束；批量越权整个回滚，不残留已导入行 |
| 用户导入错误（新增） | 同文件 `test_user_import_preserves_mixed_row_errors_and_successes`、`test_user_import_bounds_error_details_without_losing_total` | 有效行继续导入；重复账号、空行、未知角色/岗位保持行号与顺序；错误明细最多 20 条、摘要最多 5 条，累计数不截断；岗位来源与审计计数不变 |
| 文档校验及回滚 | 同文件 `test_employee_document_rejects_invalid_content_and_size`、`test_employee_document_upload_rolls_back_file_when_audit_fails`、`test_employee_document_delete_restores_file_when_audit_fails` | 内容/扩展名、大小校验；审计失败时磁盘与数据库一起回滚 |
| 旧产线写入 | `tests/test_production_node_legacy_write_guard.py`；新增 `test_order_and_schedule_guard_have_identical_cutover_contract` | 开关开/关 × 字段省略/显式 null/显式值；订单和排程同一 409/code/action/details；不修改传入数据，原 API 与节点原生入口保护保留 |

排程 golden 样本内部摘要冻结为：

| 样本键 | SHA-256 |
|---|---|
| `multi_node_cross_day` | `bd30c8260e092031e383fc83544d56e1b06bc1863ee9dcb4490adbf1ff352c1c` |
| `missing_work_time` | `6db1c794bed787b8796e49bec91c7959dd21359f342397760cb8adcf2ce62b44` |
| `dynamic_replan` | `0b0aaf4b167c762ec3e4380e0776f7a9a26d9f4e55dc08e54df2a6bee839cbdf` |
| `failure_and_publication` | `eaceb12628ac84c56bd594834196bd7daa77fdf64bdd4a48dd854e012a7ddbb1` |

绩效固定样本整体 manifest 为 `6fb94bfc55e9345954315654ba388f8cbac83fbd822179dba5e4e9e42c8dff1d`，月份 manifest 为 `7d8b1f4df72b1c120e958987d3b935b50bec67941291d8ecde9c89bb2c73d69d`。未来若有意改变业务规则，必须单独说明输入与预期差异并审核，不能通过重录 golden 让重构测试变绿。

## 七项债务台账

所有事项当前状态为 **open / 已冻结、待实施**。负责角色是后续任务的交付职责，不表示已经指定某位员工或取得审批。每批由对应维护角色实施、测试角色提供证据、独立代码审核角色批准；生产操作人与生产批准人属于另行授权流程。

| ID | 审计级别 / 优先分 | 完成批次 | 实施负责角色 | 关闭所需验收证据 |
|---|---|---|---|---|
| D01 纯排程策略热点 | Warning / 4 | Task 3 容量分配；Task 4 冲突检测 | 后端排程维护角色 | 每次只抽取一类策略；不可变上下文/结果；分配顺序、舍入、跨班次/周末、停机、外协、数量守恒、零节点冲突及生成/重排摘要一致；既有事务和版本保护通过 |
| D02 绩效质量来源规划/落库热点 | Warning / 4 | Task 6，在 Task 5 之后 | 后端绩效维护角色；业务核验角色确认来源归属 | 按评价/报废/返修/检验来源纯阶段规划；来源/计数/覆盖/缺失及 manifest 等值；继续保持不可变快照、digest 校验、按月短事务、幂等和旧修订不可变 |
| D03 UserService 多职责 | Warning / 4 | Task 7 | 账号与权限后端维护角色 | 账号角色、导入及文档适配分离，公共入口兼容；管理员约束、混合导入错误、审计/岗位来源、文件校验与磁盘回滚样本通过 |
| D04 绩效持久化规则重复 | Warning / 4 | Task 5 | 绩效仓储维护角色 | 版本分配、异常插入分别只有一个规则所有者；其余公共委托使用同一 db；默认字段、返回值、异常及调用方事务不变，仓储不得新增 commit |
| D05 前端历史依赖 | Warning / 6 | Task 2A–2F | 各批次前端维护角色，见下表与逐边清单 | 每批迁移到 Composable，删除相应基线项；保留 API facade、权限、请求协调及展示语义；剩余边数单调减少，最终 127 条归零 |
| D06 旧产线写入策略重复 | Suggestion / 2 | Task 8 | 订单/排程后端维护角色 | 共享纯准入策略显式接收开关，保留兼容公共入口；开关矩阵与 409/code/action/details、旧入口只读和节点原生路径测试通过 |
| D07 工具链不一致 | Suggestion / 2 | Task 1，前端迁移之前 | 工具链/CI 维护角色 | 明确受支持版本并固定验证入口；锁文件安装、全量前端、E2E 和构建在该版本下通过；单独评估版本升级，不能仅扩大 engines 范围消除提示 |

里程碑依次为 Task 1 → Task 2A–2F → Task 3 → Task 4 → Task 5 → Task 6 → Task 7 → Task 8 → Task 9 全量验收。Task 5 是 Task 6 的前置条件。具体日期和人员待排期，完成批次及负责角色已经明确；未编造截止日期或个人认领。

每个事项后续需在本表登记状态、证据路径、PR、合并 SHA 及关闭结论。Task 0 不将任何 D01–D07 标为 resolved。

## 前端逐条迁移清单

[frontend-dependency-inventory.json](20261015-task0/frontend-dependency-inventory.json) 为本次 127 条边的不可变原始盘点，包含唯一编号 `D05-001`–`D05-127`、消费文件、目标、原引用摘要、批次、负责角色、完成里程碑和状态。每个消费文件只属于一个批次；完整覆盖 60 个文件，没有未分配项。

| 批次 | 业务范围 | 边数 | 消费文件 | 负责角色 |
|---|---|---:|---:|---|
| 2A | 库存 | 1 | 1 | 库存前端维护角色 |
| 2B | 排程、甘特图 | 4 | 2 | 排程前端维护角色 |
| 2C | 报表、统计、首页概览 | 41 | 22 | 报表前端维护角色 |
| 2D | 绩效工资、工时、质量 | 48 | 21 | 绩效质量前端维护角色 |
| 2E | 主数据、设置 | 19 | 9 | 主数据前端维护角色 |
| 2F | 登录、导航、审批、扫码、追溯 | 14 | 5 | 应用上下文前端维护角色 |
| 合计 | | 127 | 60 | |

目标分类：API facade 49 条、store 44 条、auth 24 条、router 7 条、permissions 1 条、report-utils 2 条。它们是被精确冻结的历史依赖，不是绕过 facade 的直接 HTTP 访问。

后续保留原始清单中的每条记录，只更新迁移状态及证据，不删除历史追踪项；迁移成功后删除运行门禁中的对应历史边。某个文件可拆成同批次的多个 PR，每个 PR 必须列明已偿还的 D05 编号。剩余批次不得补回已经删除的边，也不得增加例外。

## 现有架构例外与约束

| 项目 | 冻结值 / 边界 |
|---|---|
| Service → 数据库事务抽象 | 仅 `approval_policy_service.py`、`department_service.py` → `modules.db_unit_of_work`；不是业务 SQL 许可 |
| 层级扫描文件例外 | Repository：`modules/repositories/context.py`；Service：`modules/services/__init__.py`；Route：空 |
| Middleware SQL | 文件基线为空，SQL 指纹基线为空；禁止增加 |
| 普通模块扇出 | 阈值 30；组合根仅 `modules/migration_catalog.py`、`modules/schemas/__init__.py`，仍禁止反向 Service 依赖和循环 |
| 排程门面复杂度上限 | `SCHEDULE_CAPACITY_SERVICE_DECISION_POINT_BUDGET = 353`，后续只能收敛 |
| 前端纯展示工具 | 仅 `lib/productionTime.js`；不得借此添加 IO、状态或 API 依赖 |
| 前端历史边 | 127 条，canonical manifest SHA-256 `46bf396e2d964aa537fdb15db3d6a2fe4395767efd2897269f1ab9f99f7e03d9`；既有基线扩展/变更负向 fixture 继续通过 |
| 运维稳定入口 | 仅 `OperationsFacade` 和 `operations_dto` 中 `MigrationStep`、`PrecisionPreflightRequest`、`ScheduleOperationError`；递归 Python、嵌入 Python 和根目录 Shell 扫描保留 |
| 生成文件排除 | `*.generated.py`、`*_generated.py`、`*_pb2.py`、`*_pb2_grpc.py`；目录 `__generated__`、`_generated`、`generated`；业务文件不得移入这些目录绕过检查 |

排除的非源码目录为 `.git`、`.pytest_cache`、`.venv`、`__pycache__`、`backups`、`data`、`dist`、`logs`、`node_modules`、`ssl_backup`、`uploads`。本阶段不改上述扫描规则、白名单、摘要或发布门禁。

## 后续批次放行条件

1. 每批独立实施、diff 审核、定向验证、相关全量验证、commit、push、PR、独立审核和合并；登记合并 SHA。
2. 行为摘要、来源 manifest、权限、错误响应或事务出现差异时，先解释并修复，不以放宽门禁、更新 golden 或忽略失败结案。
3. D07 仍 open，本次通过只证明当前实际环境；Task 1 完成后在选定工具链下复验。
4. Task 9 重新运行全部后端、前端、E2E、构建、API/导入环/架构/运维契约及行为对比；明确失败、跳过和 xfail 的原因。
5. 生产发布单独核实当前 SHA、回退 SHA、维护窗口、最大停机、幂等键、操作人/批准人及备份；数据库、附件和前端迁移必须明确授权。本次 Task 0 没有执行生产写入。
