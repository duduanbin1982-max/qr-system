# 物料管理修复验收证据

日期：2026-11-02，Asia/Shanghai。基线：`8110dddc9b5ff7b9835bd9561c749cb4d2a136dc`。
工作分支：`codex/materials-audit-fixes`。
范围：物料管理审计 C1–C3、W1–W8 的本地修复，不含生产历史修复、数据库迁移或发布。

业务依据和实施步骤分别见 [设计](../specs/2026-11-02-materials-remediation.md) 与 [计划](../plans/2026-11-02-materials-remediation.md)。

## 发现与对应验证

| 发现 | 修复行为 | 对应回归 |
| --- | --- | --- |
| C1 库存及台账可删除 | 影响查询与事务内删除共用余额、流水、业务引用检查；仅全空白物料可物理删除 | `test_material_inventory_safety.py`；前端删除保护单测 |
| C2 非有限库存 | 共享有限数值策略，验证输入、现存余额及计算结果；拒绝非法类型、非有限值和溢出 | `test_material_value_policy.py`、`test_material_inventory_safety.py`、`test_material_requirement_policy.py` |
| C3 快照选源与通用料 | 不再读取实时 BOM；NULL 通用料首笔获批正常报工按整单扣一次，专用料按报工扣；同料先合并验库存 | `test_order_material_state.py`、`test_material_consumption_repository.py`、真实报工及并发集成 |
| W1 必需领料审计 | 消耗、库存、台账和必需审计同事务；命令构造及存储失败均回滚 | `test_material_inventory_safety.py` |
| W2 旧订单关联 | 搜索文字变更立即取消原选中 ID，允许明确无订单领料 | `material-audit-behavior.spec.js`；`material-audit-regressions.spec.js` |
| W3 弹窗晚响应 | 请求固定实体与表单快照，响应校验弹窗会话及身份 | `material-audit-behavior.spec.js`；真实浏览器晚响应回归 |
| W4 撤销统计 | 近期趋势只统计有效消耗；历史行保留撤销状态、原因和样本范围 | `material-audit-behavior.spec.js`；真实浏览器图表回归 |
| W5 撤销日志关联 | 统一解析人工、自动及订单通用消耗原日志；历史无原日志继续保留兼容 | `test_material_inventory_safety.py`；真实报工撤销集成 |
| W6 选料分页 | 订单及产品共用完整分页加载器；后续页失败不发布部分目录，旧请求不覆盖新结果 | `material-options-pagination.spec.js` |
| W7 非法配方 | 产品和订单共用有效 ID、有限正用量策略；持久化前验证实体，原始快照在计算前再次验证 | `test_material_recipe_safety.py`、`test_material_requirement_policy.py`、仓储及报工集成 |
| W8 空白名称 | 创建和更新均规范化并验证非空，保留局部更新及重复检查契约 | `test_material_inventory_safety.py` |

## 兼容与事务证据

- 新订单在原建单事务保存 `material_order_snapshot_initialized`，包括明确的空快照；已有非空旧配方可使用。零行无来源证据返回 `MATERIAL_SNAPSHOT_UNKNOWN`，已有报工且通用料历史不明返回 `LEGACY_AMBIGUOUS`，不猜测、不回退实时 BOM。
- `material_order_common_basis` 保存整单数量、完整通用配方、digest、触发报工及消耗/原日志 ID；空通用配方也冻结。审计归档后仍读取校验。数量或配方漂移、证据损坏、原始台账不守恒及通用消耗已撤销均显式拒绝。
- 订单级幂等依赖真实调用方的 `BEGIN IMMEDIATE` 串行化。双连接/双线程四种场景覆盖同/跨工序、首事务提交/回滚：第二调用方先得到 `SQLITE_BUSY`，获取写锁后重新读取，成功事实中始终只有一笔订单通用扣料，各专用消耗正确关联报工。
- 真实 `/api/mobile/report` 集成不替换报工或扣料服务。专用质量任务自动创建仅在该测试 fixture 中关闭，避免将本轮材料用例与未执行的首件检验混合；实际质量服务保持原行为。
- 审计故障覆盖 `OperationalError` / `IntegrityError` × 插入前 / 插入后失败四种组合，核对订单、工序、报工、库存、消耗、日志及物料事件整体回滚，重试仅产生一次有效事实。上述物料状态审计写入故障统一返回通用错误，不暴露内部约束信息。
- 细微用量使用相对误差且绝对容差为零；正值浮点下溢、NULL/0 工序混淆及原台账余额不守恒均拒绝。正常浮点舍入仍可通过。

## 验证记录

最终运行平台为 Windows，Python 3.12、项目独立 Node 24.22.0 / npm 11.19.1；未更改全局运行时。

| 范围 | 结果 | 本地原始证据 |
| --- | --- | --- |
| 状态、真实报工、并发最终定向回归 | 68 passed | `test-results/materials-state-report-final.log` |
| 独立库存与数值复验 | 87 passed | 独立复审运行结果 |
| 独立物料策略/状态/报工/仓储复验 | 112 passed（审计故障扩展前）；审批及完工另 15 passed | 独立复审运行结果 |
| 独立并发复验 | 4 passed | 独立复审运行结果 |
| 全量后端 | 2830 passed, 22 skipped | `test-results/materials-full-final-20261102/backend.log` |
| 前端单测 | 542 passed（70 files） | `test-results/materials-full-final-20261102/frontend-unit.log` |
| 架构、toolchain、API facade、import cycles、layers | 98 passed；279 files / 594 edges / 0 frozen legacy edges | `test-results/materials-full-final-20261102/architecture.log` |
| 前端生产构建 | passed | `test-results/materials-full-final-20261102/frontend-build.log` |
| 完整 E2E | passed | `test-results/materials-full-final-20261102/e2e.log` |

统一入口汇总：`test-results/materials-full-final-20261102/summary.json`，五个阶段全部 `passed`。后端 Windows 运行中的 22 个 skip 是平台专属测试；其中 POSIX 权限、目录交换、目录持久化及真实 Linux 发布器/回退用例仍需 Linux CI 或隔离 Linux 环境补验，不能据此声称 Linux 生产演练通过。

早期完整矩阵在发现审计约束错误响应缺口后主动停止，不作为最终通过证据。最终矩阵从后端阶段重新开始；原始失败复现及定向通过日志仅存于忽略的本地测试产物。

最终矩阵对应的 29 个修改或新增源码及测试文件，其 SHA-256 清单保存在 `test-results/materials-full-final-20261102/candidate-source-sha256.txt`，可用 `sha256sum -c` 复核；该清单不包含后续更新的三份交付文档。原始测试产物与清单均留在忽略目录，不进入提交候选。

本机未安装 WSL，亦无可复用的 Docker/Podman 等隔离 Linux runtime。Windows 跳过的 POSIX 权限、目录交换、目录持久化及真实 Linux 发布器/回退用例须在后续 Linux CI 或隔离环境补验；Git Bash 不等于 Linux 验收。本轮未修改发布门禁，未将既有基线的 Linux 通过结果充作当前修改的验收结果。

## 独立复审与交付边界

后端库存与前端分别由非作者交叉复审；状态证据、配方与报工关系另行独立复审。复审发现的微量容差、正数下溢、NULL/0、原日志余额及审计存储错误响应问题均已修复，并补回归；当前无剩余阻断发现。

本轮未执行 commit、push、PR 或生产操作。未修改数据库 schema、迁移文件、正式报工事实及附件；生产旧订单的未知/歧义状态如需确认或修复，须另行审核来源和操作范围。提交候选仅含本轮源码、测试、设计、计划及本证据，不含 `.brooks-lint-history.json`、临时脚本/数据库、依赖目录或其他历史报告。
