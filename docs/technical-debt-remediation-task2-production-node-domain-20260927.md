# Brooks-debt 修复 Task 2：统一生产节点领域模型

**日期：** 2026-09-27
**分支：** `codex/production-node-domain-unification`
**基线：** `github/master@9211b7c30c4d48ed20555706c8fbe25e44842d9d`
**执行范围：** 本地代码、自动测试和一次性生产数据库副本；未修改 `192.168.1.8`。

## 1. 修复结果

Task 2 已把新停机事实的领域主键从 Legacy 产线统一为稳定的 `production_node_id`：

- 正式排程、节点占用、停机影响订单和动态重排继续按 `production_node_id` 计算；
- 无 `legacy_process_line_id` 的活动生产节点可以创建停机事件；
- `schedule_downtime_events.production_node_id` 成为必填事实；
- `process_line_id` 改为可空，只保留历史证据和可选兼容投影；
- 有稳定 Legacy 映射的节点仍保留 `process_line_id` 投影，但该投影不再是新写入前提；
- `/api/production-lines` 仅保留 GET 只读兼容查询；POST、PUT、DELETE 固定返回 `LEGACY_PROCESS_LINE_WRITE_BLOCKED`；
- 前端 API facade 已删除 Legacy 产线创建、修改和删除方法。

## 2. V095 数据库迁移

新增 V095：`Make downtime facts production-node native`。

迁移步骤：

1. 检查历史停机记录的 Legacy→节点映射；
2. 对缺少 `production_node_id` 的历史记录只允许使用唯一稳定映射回填；
3. 无映射、重复映射、孤立的非空节点 ID，或现有节点与 Legacy 投影矛盾时阻断迁移并报告事件 ID；
4. 事务内重建 `schedule_downtime_events`；
5. 完整保留 ID、Legacy ID、时间、状态、来源、操作人和审计时间；
6. 保留 `schedule_downtime_events` 的 AUTOINCREMENT 高水位，防止已分配的审计 ID 在表重建后被重用；
7. 重建节点时间、Legacy 时间和来源索引；
8. 保留 `process_line_id` 外键，不删除、不改写历史 Legacy 证据。

## 3. 自动验证

- 后端全量：`1631 passed`；
- 本轮审核修复定向回归：`38 passed`；
- 生产节点、动态重排、迁移和兼容定向回归：`266 passed`；
- 前端单元测试：`301 passed`；
- 前端 E2E：`20 passed`；
- API facade：通过，`34 namespaces / 441 unique domain methods`；
- 前端导入环：通过，`210 files / 512 internal edges`；
- 前端生产构建：通过；
- `git diff --check`：通过。

最终验收脚本的 `--expected-version` 在未显式指定时跟随
`LATEST_VERSION`，避免迁移到当前最新版本后仍按历史 V094 默认值误报失败。

## 4. V094 生产快照副本验收

使用 Task 0 从 `192.168.1.8` 获取的 V094 一致性只读快照创建一次性副本，并执行 V095 及完整生产排程验收。

- 数据库版本：V094 → V095；
- `quick_check=ok`；
- 外键违规：0；
- 活动订单：94；
- 试排成功：94/94；
- 工序数：661；
- 内部计划工序：384；
- 数量不守恒：0；
- 序列件跨节点拆分违规：0；
- 节点内部冲突：0；
- 与既有排程冲突：0；
- 外协/非排程工序：5，道数全部不占内部容量；
- 历史订单回放：20/20 成功；
- 历史回放数量违规：0；
- 历史回放冲突：0；
- 最新兼容审计差异：0；
- 正式执行和报工事实指纹：前后一致；
- 源 V094 快照文件：前后摘要一致，未修改。

一次性验收报告位于未跟踪目录：

`./.tmp-production-node-domain-task2-20260927/v095-final-acceptance-report.json`

## 5. 当前边界

- 尚未 commit、push 或创建 PR；
- 尚未部署生产；
- 尚未执行生产 V095 迁移、停服、重启或功能开关切换；
- `.brooks-lint-history.json`、Task 0 报告和已有 `.tmp-production-scheduling-*` 目录均不属于 Task 2 提交范围。

下一步应先审核 Task 2 本地 diff；审核通过后再单独授权 `commit、push 和创建 PR`。
