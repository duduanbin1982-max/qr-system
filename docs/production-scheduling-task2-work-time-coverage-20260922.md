# 生产排程 Task 2：精确工时覆盖审计

**执行日期：** 2026-09-22（Asia/Shanghai）
**范围：** 本地分支的只读副本审计逻辑、工时命中分层和回归测试
**生产安全边界：** 未连接、未写入、未迁移、未停服、未重启 `192.168.1.8`

## 1. 审计规则

审计复用排程服务的标准工时匹配结果，不重新实现另一套匹配规则。每道工序按以下结果分类：

### 有效工时命中

- `route_version:product`：产品 + 路线版本 + 工序版本精确命中；
- `route_version:generic`：路线版本 + 工序版本通用标准；
- `route:product`、`route:generic`：路线范围回退；
- `process:product`、`process:generic`：工序范围回退。

### 有意不占用内部产能

- `execution_policy`；
- `outsourced`；
- `non_scheduled`。

这类工序不计入内部工时缺失，但会单独计数并保留路线版本、工序版本和执行策略证据。

### 必须阻断

- `MISSING_WORK_TIME_STANDARD`：未找到有效标准工时；
- `NO_COMPATIBLE_NODE`：没有满足能力要求的生产节点；
- `NODE_CALENDAR_UNAVAILABLE`：节点没有可用工作日历时间；
- `UPSTREAM_BLOCKED`：前序工序已阻断；
- 其他未分类阻断。

阻断工序不会被伪造为已排程，也不会生成虚假的占用分钟。

## 2. 新增输出

`scripts/preflight_schedule_precision.py` 现在输出：

- `work_time_coverage.operation_count`；
- `evaluable_internal_operation_count`；
- `matched_operation_count`；
- `version_bound_match_count`：产品/路线版本/工序版本精确绑定的命中数；
- `missing_standard_operation_count`；
- `blocked_operation_count`；
- `completed_fact_count`；
- `non_scheduled_count`；
- `coverage_percent`；
- `version_bound_coverage_percent`；
- `tier_counts`；
- `missing_standard_details`；
- `blocked_details`；
- `fallback_details`；
- `work_time_audit_rows`。

每一行审计事实都保留订单、产品、路线版本、工序版本、标准版本、单件工时、准备工时、难度系数、命中范围和阻断原因。

## 3. 测试结果

新增覆盖：

- 精确产品版本工时命中；
- 工序通用标准回退；
- 外协/非排程工序不计入缺失；
- 缺失工时明确归类为 `missing_standard`；
- 原数据库文件保持不变。

排程相关回归结果：

```text
104 passed
```

## 4. 下一步

在获得生产只读副本后，运行 Task 2 审计并生成业务清单：

1. 全部活动订单；
2. 全部订单工序；
3. 精确命中与回退命中分布；
4. 外协/非排程工序清单；
5. 缺失工时阻断清单；
6. 节点或日历阻断清单。

只有内部可排程工序覆盖率达标、缺失项均有业务结论后，才进入 Task 3 的多节点拆分和跨天排程验收。
