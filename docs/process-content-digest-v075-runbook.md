# V075 工序/路线摘要修复运行手册

## 现象

V074 精确工价创建要求 `expected_process_content_digest` 和
`expected_route_content_digest` 非空。V060 历史基线生成的部分版本摘要为空，导致待发布路线建立工价时出现“参数校验失败”。

## 修复范围

V075 只修复缺失的 `process_versions.content_digest`、
`process_route_versions.content_digest` 及 V074 工价快照字段：

- 摘要按版本服务现有 canonical payload 重新计算 SHA-256；
- 仅更新空字段，不覆盖已有摘要或快照；
- 不改变工序、路线节点、工价金额、状态、订单和工资事实；
- 为每条修复记录追加不可变审计事件，使用确定性幂等键；
- 保持 `ROUTE_PRICE_PENDING_WRITE_ENABLED` 原值，迁移不自动开启工价写入。

## 预检与发布

1. 在生产副本运行 `python scripts/pending_route_price_v074_operations.py validate-replica`，确认目标数据库版本为 `75`、完整性和外键检查通过，历史工价汇总不变。
2. 维护窗口内停服，创建最终数据库备份并校验 SHA-256。
3. 执行 V074、V075 迁移，确认所有版本摘要长度为 64，路线 77 的 6 个工序引用均返回非空摘要。
4. 重启服务，验收健康接口、兼容审计 `mismatch=0` 和功能开关原值。
5. 先由工价制单人创建精确草稿，再由独立审批人通过成组发布批准；不得单独批准待发布路线工价。

## 回退

若迁移或健康验收失败，停止服务，恢复迁移前数据库备份并重启。保留 V075 审计证据，不删除原有版本事件或历史工价记录。
