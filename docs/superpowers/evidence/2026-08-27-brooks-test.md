# Brooks-Lint Review

**Mode:** Test Quality Review  
**Scope:** 当前工作树 `codex/task-2-evidence-protocol` @ `53d97c2ade38a86687151083b280e509227488a8` 的全部后端、前端单测和 E2E 测试；并复核 API facade、前端 import graph、生产构建门禁。生产已部署提交 `879913879e606e8d849ac5fa7a4ff0f613a9c966` 的既有门禁结果仅作为部署证据，不对生产数据库执行写操作。  
**Health Score:** 94/100  
**Trend:** 93 → 94 (+1) over last 2 runs

整体结论：测试套件能够稳定保护主要业务路径，本轮全部测试通过；全量 pytest 覆盖率报告为 81%，其中生产源码 `modules/` 为 78%，部署脚本与 `server.py` 为 47%。主要质量债务集中在前端单测对 API mock 和调用断言的依赖，另有少量测试直接绑定私有实现。

---

## Test Suite Map

```text
Backend unit tests:        10 files, 97 tests
Backend integration tests: 111 files, 1010 tests
Backend contract tests:    13 files, 102 tests
Frontend unit tests:       35 files, 149 tests
E2E tests:                  6 spec files, 19 tests

Combined unit tests:        246 tests (19.3%)
Combined integration tests: 1010 tests (79.2%)
E2E tests:                   19 tests (1.5%)
Ratio:                       19.3% : 79.2% : 1.5% (contract markers may overlap)

Backend full run:           1204 passed in 275.36s (0:04:35)
Backend pytest coverage:     81% (54,389 statements; 10,198 missed, includes test modules)
Production source coverage:  `modules/` 78%; `scripts/` + `server.py` 47%; combined 74%
Frontend unit run:          149 passed in 13.93s
E2E run:                    19 passed in 1.5m
Production build:           258 modules transformed
API facade check:           34 namespaces, 408 unique domain methods
Import graph check:         196 files, 487 internal edges, no cycles

Coverage areas:             versioned master data, routes/processes, payroll,
                            performance, quality, inventory, shipments, orders,
                            reports, permissions, authentication, and frontend
                            administrative/mobile workflows all have dedicated tests.
```

## Findings

### 🟡 Warning

**T4 Mock Abuse — 前端单测主要验证 API wiring**
Symptom: 35 个前端单测文件中大量通过 `vi.mock` 替换 API、权限和 store；单测源码共有 86 处 `toHaveBeenCalledWith`。例如 `PerformancePage.spec.js` 在全局 mock 中注册 25 个绩效 API 及 2 个用户/岗位 API 方法（`frontend/tests/unit/PerformancePage.spec.js:7-80`），并在每个用例前统一设置多组 resolved response（`frontend/tests/unit/PerformancePage.spec.js:159-182`）；冲突流程的关键断言仍以 mock 调用参数和次数为主（`frontend/tests/unit/PerformancePage.spec.js:235-253`）。`ProcessList.spec.js` 也注册多个版本化 API mock（`frontend/tests/unit/ProcessList.spec.js:7-45`），并集中断言调用参数（`frontend/tests/unit/ProcessList.spec.js:250-257`、`322-335`）。
Source: The Art of Unit Testing — Mock usage guidelines；xUnit Test Patterns — Behavior Verification
Consequence: API facade 的真实响应形状、序列化、错误状态和服务端状态转换可能已回归，但前端单测仍会因 mock 与组件 wiring 正常而通过；调用断言越多，测试越容易把实现细节误当成用户行为。
Remedy: 对高风险工作流增加基于测试服务器或 MSW 的请求/响应契约测试，覆盖真实 HTTP 状态码、错误 payload 和响应字段；把 `toHaveBeenCalledWith` 限定为确实属于外部命令契约的字段（如幂等键、row version），其余用渲染状态、用户可见结果和持久化事实断言；拆分全局 mock setup，按场景只注入必要依赖。

### 🟢 Suggestion

**T2 Test Brittleness — 少量测试直接依赖私有方法**
Symptom: 3 个业务测试直接调用私有实现：`PerformanceLedgerService._score_revision_changed`（`tests/test_position_fact_bindings.py:409-421`）、`ProcessQualityEvaluationService._evaluate_dimensions`（`tests/test_process_quality_evaluation.py:675-697`）和 `RouteVersionService._content_digest`（`tests/test_route_version_workflow.py:303-310`）。Task 2 的 evidence protocol 测试还集中调用 `_canonical`/`_digest` 私有 wrapper（`tests/test_evidence_protocol.py:49-83`、`tests/test_evidence_protocol_characterization.py:56-82`），这些属于有意保留的兼容性契约，但仍会绑定委托实现。
Source: The Art of Unit Testing — Test isolation principle；The Pragmatic Programmer — Orthogonality
Consequence: 在不改变外部行为的情况下重命名、提取或合并私有方法会触发测试失败，增加版本化领域服务的重构成本；私有 wrapper 契约若扩散，会让实现边界难以调整。
Remedy: 将业务规则通过稳定的公开 policy/service 行为验证，改为断言持久化修订、评分结果、摘要或 API 响应；保留少量 evidence protocol characterization 测试作为架构契约，并明确集中在单一文件，避免新增同类私有调用。

## Summary

本轮后端 1204 项、前端单测 149 项和 E2E 19 项全部通过，全量 pytest 覆盖率 81%（生产源码合计 74%），全套反馈时间约 4 分 35 秒，未发现阻断发布的测试错误、慢测试或明显的覆盖率幻觉。优先治理前端 mock 契约和少量私有方法耦合；集成测试占比虽高，但数据库隔离明确且执行时间健康，当前不单独判定为架构问题。部署脚本覆盖率较低，现有 CLI 成功/失败契约测试提供了基本保护，后续可补充不触碰真实生产资源的 dry-run 分支测试。近期前端单测日志曾出现 Vue `onMounted` 在无活动组件实例中调用的警告（`inventory-composable.spec.js`、`useRoleManage.spec.js`、`useRoleGroups.spec.js`），不影响通过结果，建议后续把这些 composable 测试统一放入组件 setup harness 以消除噪声。

本轮仅执行只读代码审计、测试、构建和静态门禁；未修改生产代码、数据库或生产配置，也未推送、合并、部署或重启服务。

---

## 修复复验（2026-08-27）

本轮按“行为保持、分阶段修复”执行了测试质量整改，原始审计内容和历史分数保留不变。

已完成：

- `PerformancePage.spec.js`、`ProcessList.spec.js`：保留幂等键和 `row_version` 等外部命令契约，移除刷新次数、调用时序等实现细节断言，增加批次状态、草稿状态、按钮状态和用户可见结果断言。
- `inventory-composable.spec.js`、`useRoleManage.spec.js`、`useRoleGroups.spec.js`：统一使用 Vue `setup` harness 挂载 composable，消除组件实例外调用 `onMounted` 的测试警告。
- `tests/test_position_fact_bindings.py`、`tests/test_process_quality_evaluation.py`、`tests/test_route_version_workflow.py`：将业务场景从私有方法调用改为公开服务/API 行为验证；保留动态权重和可选维度的完整行为覆盖。
- 新增 `frontend/tests/unit/api-transport-contract.spec.js`：直接验证真实 API facade、HTTP 方法、查询序列化、JSON 请求体和 409 错误契约。
- Evidence Protocol 私有 wrapper 断言集中保留在 characterization 测试中，并增加边界注释，禁止业务测试继续扩散私有调用。

复验结果：

```text
Backend:              1203 passed in 282.91s
Backend coverage:     modules/* 78%
Frontend unit:        151 passed, 36 files
E2E:                  19 passed
Architecture checks:  34 namespaces / 408 methods; 196 files / 487 edges; no cycles
Build:                258 modules transformed
Diff check:           passed
```

复验结论：T2 中 3 个业务私有方法调用已清除，Evidence Protocol 的少量私有 wrapper 仍作为集中式架构 characterization 契约保留。T4 的全局 mock 依赖尚未全部消除，但高风险绩效/工序流程已增加真实 facade 传输契约，且关键断言已转为行为和状态断言；后续可继续扩展真实 HTTP 契约覆盖。全程未连接或修改 `192.168.1.8`，未触碰生产数据库、配置、服务或附件。
