# Task 3：排程服务热点拆分与验证

日期：2026-10-13。

工作树：`.worktrees/architecture-task3-schedule-hotspot`。
分支：`codex/architecture-task3-schedule-hotspot`。
Git 基线：`970b99817897fdf395999ffe3f6c0167e919123f`。

## 实现边界

生成排程和动态重排现在共用 `SchedulePurePlanner`。数据库事实读取与规划决策分离：
`SchedulePlanningFactsLoader` 读取原始工时候选、节点、日历、例外和停机事实；
纯领域策略完成产品与版本工时匹配、能力筛选、分配、锁定恢复、阻断和冲突、交期风险计算。
纯规划器不访问数据库、不读取功能开关、不初始化 Flask。

输入与输出包含递归冻结的 `PlanningFactsSnapshot`、`PlanningOperationFacts`、
`PlanningResourceFacts`、`PlanningOperationResult`、`PlanningDecision`、
`PlanningAssessmentFacts`、`PlanningManifest` 和 `PlanningEvidence`。
内部工作副本允许局部更新占用；不会修改调用方快照。

| 原职责 | 实际归属 |
| --- | --- |
| 精确工时匹配 | `modules/domain/schedule_standard_matching.py` |
| 工序规划、能力选择、容量、锁定恢复 | `modules/domain/schedule_pure_planner.py` |
| 冲突与交期风险 | `modules/domain/schedule_planning_assessment.py` |
| 事实读取 | `modules/services/schedule_planning_facts.py` |
| 版本评估的事实加载与持久化 | `modules/services/schedule_assessment_service.py` |
| 列表、详情与看板查询 | `modules/services/schedule_query_service.py` |
| 事务所有权 | `modules/services/schedule_unit_of_work.py` |

实际 Git 基线中的容量服务为 2406 行，本轮降到 1301 行。
规划循环保留为短编排方法；共享纯规划器的主循环限制在 60 行以内，单方法限制在 120 行以内，
相应测试阻止再次堆积复杂度。历史公开入口和少量旧私有方法仅作兼容委托。
`SchedulePlanningStrategy` 已去掉 provider、动态容量服务导入和私有跨服务调用。
原有版本工作流通过现有公开 Strategy 直接获得新实现，无需修改审批接口。

## 必须保持的行为

- 工作日、班次、跨天、周末、停机、加班槽位合并与分配顺序保持兼容。
- 节点日历缺失必须阻断；Legacy 产线保留原有默认日历回退。
- 产品专用工时优先，其次通用工时；范围、版本、有效期和 id 排序保持原口径。
- 多节点分配数量守恒，序列件约束保留；外协/非排程工序不占内部容量。
- 只读快照计算、写入前 digest 复核、短写事务和 STALE_INPUT 行为保留。
- SAVEPOINT 内版本、项目、冲突、风险、证据共同保存；失败回滚后仍记录失败运行。
- 已发布旧版本保持不可变，证据保存失败不能产生半完成排程。
- `schedule_runs.result_json` 仍为历史列表格式，manifest 与摘要保存到独立证据。
- 容量槽位采用惰性迭代，避免为每次候选分配预生成十年容量列表。

## 验证证据

P1 修复后最终全量后端：1789 passed，耗时 398.66 秒。
JUnit XML 结果保留为忽略的本地证据：`data/task3-p1-backend.junit.log`。
修复前全量后端为 1777 passed，日志保留在 `data/task3-backend-final.log`。

已经通过的定向验证：
- 生成、动态重排、版本发布、行为摘要和仓储职责定向回归：90 passed。
- 补充纯规划、能力不匹配、跨天、周末、停机、外协、快照不变、方法规模及日历回退测试。
- 惰性分配修正后的行为摘要与动态重排定向回归：17 passed。
- P1 修复后共享纯规划、生成、动态重排、短写事务、仓储及批量节点回归：58 passed。
- 架构检查：29 passed；API facade：34 namespaces / 455 domain methods。
- 前端导入环：219 files / 532 edges；无新增依赖环。
- `git diff --check` 通过。

原行为摘要文件 `tests/schedule_capacity_behavior_v1.json` 未修改。
比较测试沿用冻结基线，不通过重写预期掩盖行为变化。
完整日志保存在本地忽略的 `data/task3-*.log`。

## P1 修复与再次审核

首次本地 diff 审核复现了节点日历前置条件回归：节点日历缺失或无启用班次时，
加班时段仍可能使共享纯规划器返回 `planned`，而 Git 基线会拒绝分配。

已将日历和班次校验恢复到 `SchedulePurePlanner._allocate_resource()`：
节点必须具备有效日历和班次，才能进入正常槽位与加班槽位计算。
单节点兼容入口委托该领域校验，避免重复规则。Legacy 产线回退逻辑保持原样。

新增 12 个参数化行为用例：
- 生成和重排模式中，缺失日历或空班次即使有加班也必须阻断。
- 有效日历继续支持周末加班产能。
- 无效日历节点不能抢占日历有效的其他候选节点。
- 两个正式服务入口保存 `NODE_CALENDAR_UNAVAILABLE` 阻断结果，
  `schedule_runs.result_json` 仍为列表，旧版本项目保持不变。

新增纯规划用例在修复前为 6 failed / 2 passed，修复后全部通过。
最终全量后端、架构门禁、API facade、导入环和 diff 格式检查通过。
再次审核为 PR Review，范围为 Task 3 本地 15 个文件并重点复查 P1 路径；
未发现新的阻断问题，Health Score 为 100/100。

## 交付与后续

本阶段仅修改独立本地工作树，未提交、推送、创建 PR 或修改生产环境。
本地验证不替代最新生产副本的业务验收，也未宣称已对当前真实活动订单重新试排。
本地 diff 再次审核通过，下一步进入 Task 3 提交准备，授权后独立提交和创建 PR。
提交范围不得包含 `.brooks-lint-history.json`、历史 Task 0 报告、`.tmp-*` 或临时部署脚本。
