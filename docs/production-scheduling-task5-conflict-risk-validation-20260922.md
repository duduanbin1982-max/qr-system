# 生产排程 Task 5：冲突检测与交期风险预警验收报告

日期：2026-09-22
范围：本地分支与生产数据库只读副本
生产环境：未修改 `192.168.1.8`

## 一、完成内容

1. 新增 V093 数据库迁移：
   - `schedule_effective_capacity_intervals` 统一有效容量视图；
   - `schedule_revision_conflict_checks` 不可变冲突检查批次；
   - `schedule_revision_conflicts` 不可变冲突事实；
   - `schedule_revision_risk_assessments` 不可变交期风险证据。
2. 有效容量口径统一为：
   - 排程分段优先；
   - 无分段时才回退工序排程区间；
   - 优先使用稳定 `production_node_id`；
   - 仅无节点标识时使用 Legacy `process_line_id`；
   - 排除阻断、软删除、外协及非排程工序；
   - 仅正式发布投影及已锁定候选任务占用容量。
3. 新增纯领域冲突检测器，覆盖：
   - 独占节点时间重叠；
   - 停机或不可用时段重叠；
   - 锁定任务冲突；
   - 工序前后顺序倒置；
   - 序列件重复分配；
   - 外协/非排程工序错误占用内部容量；
   - 无效容量区间。
4. 候选修订版风险直接依据本次不可变条目计算，不再读取旧正式投影。
5. 提交、批准和发布前执行冲突门禁；存在阻断冲突时返回
   `SCHEDULE_CONFLICT_GATE_FAILED`，禁止继续流转。
6. 甘特图及工序工作台新增：
   - 风险/冲突/阻断筛选；
   - 生产节点冲突数量与区间摘要；
   - 工序冲突徽标；
   - 缓冲分钟、主要风险来源和建议动作提示。

## 二、生产只读副本结果

副本来源：Task 4 的 V092 生产只读副本。
输出副本：`.tmp-production-scheduling-task5-20260922/production-current-v093-conflict-risk.db`

- 迁移版本：V092 → V093；
- 有效容量区间：98；
- 分段区间：98；
- schedule 回退区间：0；
- 外协/非排程占用内部容量：0；
- 分段与 schedule 重复计入：0；
- 正式生产节点冲突：0；
- 交期风险订单：6；
  - 已逾期：4；
  - 高风险：2；
- 最大预计延期：42,785 分钟；
- 人工注入停机冲突后，发布门禁正确阻断：
  - 错误码：`SCHEDULE_CONFLICT_GATE_FAILED`；
  - 冲突类型：`downtime_overlap`；
  - 验证后已回滚临时停机事实；
- `PRAGMA quick_check = ok`；
- 外键违规：0。

副本证据：

- `.tmp-production-scheduling-task5-20260922/v093-conflict-risk-report.json`
- `.tmp-production-scheduling-task5-20260922/production-current-v093-conflict-risk.db`

## 三、自动化验收

- 后端全量：`1579 passed`；
- 前端全量：`290 passed`；
- API facade：通过，34 个命名空间、443 个唯一方法；
- 前端导入环：通过，203 个文件、499 条内部依赖边；
- 前端生产构建：通过；
- `git diff --check`：通过。

## 四、结论

Task 5 的冲突检测、不可变证据、候选版本风险快照、审批发布门禁和前端预警工作台已经完成。本阶段仅在本地和生产数据库只读副本上验证，没有修改生产环境，也没有提交、推送或创建 PR。

下一阶段可进入 Task 6：实际报工、停机、返工和节点占用驱动的动态重排深化；在进入 Task 6 前，也可以先单独授权提交当前累计分支并创建 PR。
